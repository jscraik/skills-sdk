"""Read-only portable plugin validation and complete captured candidate binding."""

from __future__ import annotations

import re
from pathlib import Path

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageManifestFile, _file_role
from skills_sdk.models.plugin import (
    PluginCapturedFile,
    PluginPackageValidation,
    PluginSkillBinding,
    PluginValidationPolicy,
    _is_skill_entrypoint,
    plugin_candidate_id,
)
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation, ValidationSeverity
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_manifest import parse_plugin_manifest
from skills_sdk.validation.skill_package import (
    SkillValidationPolicy,
    _candidate,
    _captured_skill_identity,
    _finding,
    _package_policy_findings,
)


def _child(
    path: str, files: tuple[PluginCapturedFile, ...], payloads: dict[str, bytes], revision: str
) -> PluginSkillBinding:
    """Validate one direct skill from captured bytes and bind its files to the supplied revision."""
    prefix, policy = path + "/", SkillValidationPolicy()
    captured = {name[len(prefix) :]: data for name, data in payloads.items() if name.startswith(prefix)}
    records = tuple(
        PackageManifestFile(
            path=item.path[len(prefix) :],
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            role=_file_role(item.path[len(prefix) :]),
        )
        for item in files
        if item.path.startswith(prefix)
    )
    root = Path(path)
    identity, findings = _captured_skill_identity(root, captured["SKILL.md"], policy)
    findings.extend(_package_policy_findings(captured, policy))
    if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", root.name):
        findings.append(_finding("invalid_package_root", "skill directory must use a portable package identifier"))
    result = SkillPackageValidation(
        candidate=_candidate(root, revision, list(records)),
        identity=identity,
        files=records,
        status="blocked" if findings else "pass",
        findings=tuple(findings),
    )
    return PluginSkillBinding(path=path, validation=result)


def _component_findings(payloads: dict[str, bytes], directories: tuple[str, ...]) -> list[SkillPackageFinding]:
    """Report invalid component kinds and warn that captured MCP bytes remain unassessed."""
    findings: list[SkillPackageFinding] = []
    if "skills" in payloads or "mcp.json" in directories:
        findings.append(_finding("plugin_component_kind_invalid", "portable component location has the wrong kind"))
    if any(_is_skill_entrypoint(path) for path in directories):
        findings.append(_finding("plugin_component_kind_invalid", "skill entrypoint must be a regular file"))
    if "mcp.json" in payloads:
        findings.append(
            SkillPackageFinding(
                code="plugin_mcp_not_assessed",
                severity=ValidationSeverity.WARNING,
                message="MCP bytes are bound; transport configuration and execution are not assessed",
                evidence_refs=("mcp.json",),
            )
        )
    return findings


def validate_plugin_package(
    plugin_root: Path,
    *,
    source_revision: str,
    policy: PluginValidationPolicy | None = None,
) -> PluginPackageValidation:
    """Capture a root-manifest plugin; pass is neither admission nor release clearance."""
    active = PluginValidationPolicy()
    diagnostic = "plugin policy must contain only supported boolean requirements"
    try:
        active = PluginValidationPolicy.model_validate(policy if policy is not None else {})
        diagnostic = "source revision must be forty lowercase hexadecimal characters"
        if type(source_revision) is not str or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
            raise ValueError("invalid source revision")
        diagnostic = "plugin source requires bounded ordinary files and safe no-follow paths"
        if not isinstance(plugin_root, Path) or ".." in plugin_root.parts:
            raise ValueError("plugin root requires a safe path")
        files, payloads, directories = capture_plugin_source(plugin_root)
        diagnostic = "root plugin.json and selected settings require bounded valid JSON and supported field types"
        manifest, warnings = parse_plugin_manifest(payloads)
        diagnostic = "plugin child discovery and captured skill metadata must satisfy their input bounds"
        paths = sorted(path.rsplit("/", 1)[0] for path in payloads if _is_skill_entrypoint(path))
        if len(paths) > 128:
            raise ValueError("plugin skill count exceeds bound")
        children = tuple(_child(path, files, payloads, source_revision) for path in paths)
        findings = [*warnings, *_component_findings(payloads, directories)]
        if any(item.validation.status == "blocked" for item in children):
            findings.append(_finding("plugin_child_blocked", "SDK standalone validation blocked a discovered skill"))
        if active.require_version and not (manifest.version or "").strip():
            findings.append(
                _finding("sdk_plugin_version_required", "SDK policy requires nonempty version metadata", "plugin.json")
            )
        if active.require_description and not (manifest.description or "").strip():
            findings.append(
                _finding(
                    "sdk_plugin_description_required",
                    "SDK policy requires nonempty description metadata",
                    "plugin.json",
                )
            )
        diagnostic = "plugin source must remain safely readable for the confirming capture"
        second_files, _second_payloads, second_directories = capture_plugin_source(plugin_root)
        if files != second_files or directories != second_directories:
            return PluginPackageValidation(
                status="blocked",
                policy=active,
                findings=(_finding("plugin_source_changed", "plugin source changed during validation"),),
            )
        return PluginPackageValidation(
            status="blocked" if any(item.severity == ValidationSeverity.BLOCKER for item in findings) else "pass",
            candidate=PackageCandidateIdentity(
                package_id=plugin_candidate_id(manifest.name),
                source_revision=source_revision,
                content_sha256=candidate_content_sha256(files),
            ),
            manifest=manifest,
            policy=active,
            files=files,
            mode_manifest_sha256=canonical_json_sha256([item.model_dump(mode="json") for item in files]),
            skills=children,
            findings=tuple(findings),
        )
    except (ContractError, OSError, ValueError, TypeError, KeyError, RecursionError):
        return PluginPackageValidation(
            status="blocked",
            policy=active,
            findings=(
                _finding(
                    "plugin_input_invalid",
                    diagnostic,
                ),
            ),
        )


__all__ = ["validate_plugin_package"]
