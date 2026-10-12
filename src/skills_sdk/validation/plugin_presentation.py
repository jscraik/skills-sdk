"""Read-only presentation checks over captured plugin bytes and supplied approvals.

The fixed OpenAI icon profile is not public listing, archive, rights-verification
or observed host-display clearance. Approval truth stays with its producer.
"""

from __future__ import annotations

from pathlib import Path

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.plugin import PluginCapturedFile, PluginPackageValidation
from skills_sdk.models.plugin_presentation import (
    PluginPresentationCheck,
    PluginPresentationCopyApproval,
    PluginPresentationImage,
    PluginPresentationRequest,
)
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_images import inspect_plugin_image
from skills_sdk.validation.plugin_manifest import _object
from skills_sdk.validation.plugin_package import validate_plugin_package

_ICON_FIELDS = ("logo", "composerIcon", "logoDark", "composerIconDark")


def _finding(code: str, message: str) -> SkillPackageFinding:
    return SkillPackageFinding(code=code, message=message, severity=ValidationSeverity.BLOCKER)


def _result(
    validation: PluginPackageValidation | None,
    findings: tuple[SkillPackageFinding, ...],
    images: tuple[PluginPresentationImage, ...] = (),
    copy: PluginPresentationCopyApproval | None = None,
) -> PluginPresentationCheck:
    manifest = validation.manifest if validation else None
    return PluginPresentationCheck(
        status="blocked" if any(item.severity == ValidationSeverity.BLOCKER for item in findings) else "pass",
        candidate=validation.candidate if validation else None,
        mode_manifest_sha256=validation.mode_manifest_sha256 if validation else None,
        openai_settings_source=manifest.openai_settings_source if manifest else "none",
        openai_settings_sha256=manifest.openai_settings_sha256 if manifest else None,
        images=images,
        copy_approval=copy,
        findings=findings,
    )


def _selected_settings(payloads: dict[str, bytes], validation: PluginPackageValidation) -> dict[str, object]:
    manifest = validation.manifest
    if manifest is None or manifest.openai_settings_source == "none":
        raise ValueError("selected OpenAI settings are required")
    if manifest.openai_settings_source == "inline":
        root = _object(payloads["plugin.json"])
        extensions = root.get("extensions")
        selected = extensions.get("com.openai") if type(extensions) is dict else None
    else:
        selected = _object(payloads[".codex-plugin/plugin.json"])
    if type(selected) is not dict or canonical_json_sha256(selected) != manifest.openai_settings_sha256:
        raise ValueError("selected settings must match captured validation")
    return selected


def _reference(value: object, payloads: dict[str, bytes]) -> str:
    if type(value) is not str or not value.startswith("./"):
        raise ValueError("presentation references require explicit plugin-relative paths")
    path = value[2:]
    require_portable_relative_path(path)
    if path not in payloads:
        raise ValueError("presentation reference must name a captured ordinary file")
    return path


def _references(
    settings: dict[str, object], payloads: dict[str, bytes], validation: PluginPackageValidation
) -> dict[str, tuple[str, ...]]:
    interface = settings.get("interface")
    if type(interface) is not dict or any(key not in interface for key in ("logo", "composerIcon")):
        raise ValueError("presentation requires an interface with logo and composerIcon")
    references: dict[str, set[str]] = {}
    for role in _ICON_FIELDS:
        if role in interface:
            path = _reference(interface[role], payloads)
            references.setdefault(path, set()).add(role)
    screenshots = interface.get("screenshots", [])
    if type(screenshots) is not list or len(screenshots) > 20:
        raise ValueError("screenshots require an array with at most twenty references")
    screenshot_paths = [_reference(value, payloads) for value in screenshots]
    if len(set(screenshot_paths)) != len(screenshot_paths):
        raise ValueError("screenshot references must be unique")
    for path in screenshot_paths:
        references.setdefault(path, set()).add("screenshot")
    if "onboardingSkill" in settings:
        path = _reference(settings["onboardingSkill"], payloads)
        valid = {item.path + "/SKILL.md" for item in validation.skills if item.validation.status == "pass"}
        if path not in valid:
            raise ValueError("onboarding must reference a validated direct child skill")
    return {path: tuple(sorted(roles)) for path, roles in sorted(references.items())}


def _inspect_images(
    references: dict[str, tuple[str, ...]],
    payloads: dict[str, bytes],
    validation: PluginPackageValidation,
    request: PluginPresentationRequest,
) -> tuple[PluginPresentationImage, ...]:
    approvals = {item.image_path: item for item in request.image_approvals}
    if set(approvals) != set(references):
        raise ValueError("approvals must cover exactly the declared unique images")
    records = {item.path: item for item in validation.files}
    images: list[PluginPresentationImage] = []
    for path, roles in references.items():
        kind = "icon" if any(role in _ICON_FIELDS for role in roles) else "screenshot"
        approval, record = approvals[path], records[path]
        if approval.kind != kind or approval.image_sha256 != record.sha256:
            raise ValueError("image approval must match its captured bytes and purpose")
        image_format, width, height = inspect_plugin_image(path, payloads[path], kind=kind)
        images.append(
            PluginPresentationImage(
                path=path,
                sha256=record.sha256,
                size_bytes=record.size_bytes,
                format=image_format,
                width=width,
                height=height,
                roles=roles,
                approval=approval,
            )
        )
    return tuple(images)


def _capture_matches(validation: PluginPackageValidation, files: tuple[PluginCapturedFile, ...]) -> bool:
    candidate = validation.candidate
    return (
        candidate is not None
        and files == validation.files
        and candidate_content_sha256(files) == candidate.content_sha256
        and canonical_json_sha256([item.model_dump(mode="json") for item in files]) == validation.mode_manifest_sha256
    )


def check_plugin_presentation(
    plugin_root: Path,
    *,
    source_revision: str,
    request: PluginPresentationRequest | dict[str, object],
) -> PluginPresentationCheck:
    """Check fresh captured assets; supplied visual/copy approval is not independently judged."""
    validation = None
    code, diagnostic = "plugin_presentation_input_invalid", "presentation request requires bounded canonical evidence"
    try:
        active = PluginPresentationRequest.model_validate(request)
        if type(source_revision) is not str or active.candidate.source_revision != source_revision:
            raise ValueError("source revision mismatch")
        validation = validate_plugin_package(plugin_root, source_revision=source_revision)
        if validation.status != "pass":
            return _result(validation, validation.findings)
        code, diagnostic = (
            "plugin_presentation_binding_mismatch",
            "presentation evidence must bind the current candidate",
        )
        if validation.candidate != active.candidate or validation.mode_manifest_sha256 != active.mode_manifest_sha256:
            raise ValueError("candidate or mode mismatch")
        if (
            validation.manifest is None
            or active.copy_approval.openai_settings_sha256 != validation.manifest.openai_settings_sha256
        ):
            raise ValueError("copy approval settings mismatch")
        code, diagnostic = "plugin_source_changed", "plugin source must remain identical during presentation inspection"
        files, payloads, directories = capture_plugin_source(plugin_root)
        if not _capture_matches(validation, files):
            return _result(None, (_finding(code, diagnostic),))
        code, diagnostic = (
            "plugin_presentation_references_invalid",
            "selected presentation references require captured files and supported field types",
        )
        references = _references(_selected_settings(payloads, validation), payloads, validation)
        code, diagnostic = (
            "plugin_presentation_images_invalid",
            "declared images require matching approvals and bounded complete inspection",
        )
        images = _inspect_images(references, payloads, validation, active)
        code, diagnostic = "plugin_source_changed", "plugin source must remain identical during presentation inspection"
        final_files, _payloads, final_directories = capture_plugin_source(plugin_root)
        if files != final_files or directories != final_directories:
            return _result(None, (_finding(code, diagnostic),))
        return _result(validation, validation.findings, images, active.copy_approval)
    except ImportError:
        return _result(
            validation, (_finding("image_decoder_unavailable", "install the SDK images extra for raster inspection"),)
        )
    except (ContractError, OSError, ValueError, TypeError, KeyError, RecursionError):
        if code == "plugin_source_changed":
            validation = None
        return _result(validation, (_finding(code, diagnostic),))


__all__ = ["check_plugin_presentation"]
