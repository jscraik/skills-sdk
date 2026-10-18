"""Whole-plugin binding for the existing local skill-quality workflow."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from skills_sdk.models.inventory import Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import PluginPackageValidation, PluginSkillBinding
from skills_sdk.models.plugin_presentation import PluginPresentationCheck
from skills_sdk.models.quality_workflow import LocalCheckRequestV2, LocalCheckResultV2

PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES = 32 * 1_048_576
"""Aggregate supplied-assessment budget: four maximum-sized content-review assessments."""

_BLOCKER_CODES = frozenset(
    {
        "plugin_quality_input_invalid",
        "plugin_quality_request_invalid",
        "plugin_quality_root_mismatch",
        "plugin_quality_assessments_invalid",
        "plugin_quality_child_blocked",
        "plugin_quality_presentation_missing",
        "plugin_quality_presentation_blocked",
        "plugin_quality_source_changed",
    }
)
_SUCCESS_EVIDENCE = ("request", "initial_capture", "children", "presentation", "final_capture")
_RESULT_SCHEMA_EXTRA: dict[str, Any] = {
    "if": {"properties": {"status": {"const": "local_checks_passed"}}, "required": ["status"]},
    "then": {
        "required": [*_SUCCESS_EVIDENCE],
        "properties": {
            "request": {"type": "object"},
            "initial_capture": {"type": "object"},
            "final_capture": {"type": "object"},
            "presentation": {"type": "object"},
            "children": {"minItems": 1},
            "blocker": {"type": "null"},
        },
    },
    "else": {"required": ["blocker"], "properties": {"blocker": {"type": "object"}}},
}


class PluginQualityChild(_ContractModel):
    """One explicit skill request in root-capture order."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    path: str
    request: LocalCheckRequestV2

    @model_validator(mode="after")
    def supported_child(self) -> Self:
        """Keep this first composition create/external-check only."""
        PluginSkillBinding.direct_skill(self.path)
        if self.request.intent == "update" or self.request.content_review_mode != "supplied":
            raise ValueError("plugin quality requires create/external-check and supplied review")
        return self


class PluginQualityRequest(_ContractModel):
    """Expected complete content, modes and exact child requests."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["plugin-quality-request/v1"] = "plugin-quality-request/v1"
    candidate: PackageCandidateIdentity
    mode_manifest_sha256: Sha256
    children: tuple[PluginQualityChild, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def canonical_inputs(cls, value: object) -> object:
        """Reuse bounded revalidation of nested local-quality evidence."""
        return LocalCheckRequestV2.inputs_are_revalidated(value)

    @model_validator(mode="after")
    def child_order(self) -> Self:
        """Reject duplicate, unordered or foreign-revision requests."""
        paths = tuple(child.path for child in self.children)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("plugin quality children must be sorted and unique")
        if any(child.request.candidate.source_revision != self.candidate.source_revision for child in self.children):
            raise ValueError("plugin quality children must share the root revision")
        return self


def supported_quality_root(request: PluginQualityRequest, capture: PluginPackageValidation) -> bool:
    """Join the skill-only supported profile to exact root and child identities."""
    return (
        capture.status == "pass"
        and capture.policy.require_version
        and capture.policy.require_description
        and capture.candidate == request.candidate
        and capture.mode_manifest_sha256 == request.mode_manifest_sha256
        and tuple((child.path, child.validation.candidate) for child in capture.skills)
        == tuple((child.path, child.request.candidate) for child in request.children)
        and not any(item.path == "mcp.json" for item in capture.files)
    )


class PluginQualityResult(_ContractModel):
    """Local composition evidence; never an independent approval or release."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", json_schema_extra=_RESULT_SCHEMA_EXTRA
    )
    schema_version: Literal["plugin-quality/v1"] = "plugin-quality/v1"
    status: Literal["local_checks_passed", "blocked"]
    request: PluginQualityRequest | None = None
    initial_capture: PluginPackageValidation | None = None
    children: tuple[LocalCheckResultV2, ...] = Field(default=(), max_length=128)
    presentation: PluginPresentationCheck | None = None
    final_capture: PluginPackageValidation | None = None
    blocker: PackageReceiptBlocker | None = None
    mutation_performed: Literal[False] = False
    evaluation_executed: Literal[False] = False
    execution_authorized: Literal[False] = False
    release_ready: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def canonical_inputs(cls, value: object) -> object:
        """Revalidate typed envelopes rather than trusting copied instances."""
        normalized = LocalCheckRequestV2.inputs_are_revalidated(value)
        flags = ("mutation_performed", "evaluation_executed", "execution_authorized", "release_ready")
        if isinstance(normalized, dict) and any(normalized.get(flag, False) is not False for flag in flags):
            raise ValueError("plugin quality authority flags must be literal false")
        return normalized

    @model_validator(mode="after")
    def binds_complete_plugin(self) -> Self:
        """Require complete root and child evidence for any successful result."""
        if (self.status == "blocked") != (self.blocker is not None):
            raise ValueError("plugin quality status requires its blocker")
        if self.children:
            if self.request is None or self.initial_capture is None:
                raise ValueError("child results require request and capture")
            self._bind_children()
        if self.status == "local_checks_passed":
            self._require_success()
        else:
            self._require_blocker_stage()
        return self

    def _children_complete(self) -> bool:
        """Report whether every requested child was retained and passed."""
        return (
            self.request is not None
            and len(self.children) == len(self.request.children)
            and all(child.status == "local_checks_passed" for child in self.children)
        )

    def _presentation_bound(self) -> bool:
        """Report whether a retained presentation passed for the requested root."""
        presentation, request = self.presentation, self.request
        return (
            presentation is not None
            and request is not None
            and presentation.status == "pass"
            and presentation.candidate == request.candidate
            and presentation.mode_manifest_sha256 == request.mode_manifest_sha256
        )

    def _require_blocker_stage(self) -> None:
        """Bind each typed first-stop code to the evidence that stage actually retains."""
        assert self.blocker is not None
        code = self.blocker.code
        if code not in _BLOCKER_CODES:
            raise ValueError("plugin quality blocker code is not part of this contract")
        retained = {name for name in _SUCCESS_EVIDENCE if getattr(self, name)}
        early = {"plugin_quality_input_invalid", "plugin_quality_request_invalid"}
        if code in early:
            valid = not retained
        elif self.request is None or self.initial_capture is None:
            valid = False
        elif code == "plugin_quality_root_mismatch":
            valid = retained == {"request", "initial_capture"} and not supported_quality_root(
                self.request, self.initial_capture
            )
        elif not supported_quality_root(self.request, self.initial_capture):
            valid = False
        elif code == "plugin_quality_assessments_invalid":
            valid = retained == {"request", "initial_capture"}
        elif code == "plugin_quality_child_blocked":
            valid = retained == {"request", "initial_capture", "children"} and self.children[-1].status == "blocked"
        elif not self._children_complete():
            valid = False
        elif code == "plugin_quality_presentation_missing":
            valid = retained == {"request", "initial_capture", "children"}
        elif code == "plugin_quality_presentation_blocked":
            valid = retained == {"request", "initial_capture", "children", "presentation"} and (
                not self._presentation_bound()
            )
        else:
            valid = (
                self._presentation_bound()
                and self.final_capture is not None
                and self.final_capture != self.initial_capture
            )
        if not valid:
            raise ValueError("plugin quality blocker code must match its retained stage evidence")

    def _bind_children(self) -> None:
        """Bind every retained local result to its actual root subtree."""
        assert self.request is not None and self.initial_capture is not None
        capture = self.initial_capture
        expected = self.request.children
        if (
            capture.candidate != self.request.candidate
            or capture.mode_manifest_sha256 != self.request.mode_manifest_sha256
        ):
            raise ValueError("child quality requires matching root content and modes")
        if tuple(child.path for child in capture.skills) != tuple(child.path for child in expected):
            raise ValueError("quality requests must cover every root skill")
        if len(self.children) > len(expected):
            raise ValueError("unexpected child result")
        for index, result in enumerate(self.children):
            if result.request != expected[index].request:
                raise ValueError("child quality must retain the selected request")
            if expected[index].request.candidate != capture.skills[index].validation.candidate:
                raise ValueError("child quality must bind its captured subtree")
            if index < len(self.children) - 1 and result.status != "local_checks_passed":
                raise ValueError("plugin quality must stop at the first child blocker")

    def _require_success(self) -> None:
        """Successful composition needs all checks and a fresh unchanged capture."""
        if self.request is None or self.initial_capture is None or self.final_capture is None:
            raise ValueError("passing plugin quality requires initial and final captures")
        if self.initial_capture.status != "pass" or self.final_capture != self.initial_capture:
            raise ValueError("passing plugin quality requires unchanged content, modes and settings")
        if not supported_quality_root(self.request, self.initial_capture):
            raise ValueError("passing plugin quality requires the supported skill-only root profile")
        if len(self.children) != len(self.request.children) or any(
            child.status != "local_checks_passed" for child in self.children
        ):
            raise ValueError("passing plugin quality requires every child")
        if self.presentation is None or self.presentation.status != "pass":
            raise ValueError("passing plugin quality requires presentation assessment")
        if (
            self.presentation.candidate != self.request.candidate
            or self.presentation.mode_manifest_sha256 != self.request.mode_manifest_sha256
        ):
            raise ValueError("presentation must bind root content and modes")
        manifest = self.initial_capture.manifest
        assert manifest is not None
        if (
            self.presentation.openai_settings_source != manifest.openai_settings_source
            or self.presentation.openai_settings_sha256 != manifest.openai_settings_sha256
        ):
            raise ValueError("presentation must bind the captured settings")
        files = {item.path: (item.sha256, item.size_bytes) for item in self.initial_capture.files}
        if any(files.get(image.path) != (image.sha256, image.size_bytes) for image in self.presentation.images):
            raise ValueError("presentation must bind the captured image bytes")


__all__ = [
    "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES",
    "PluginQualityChild",
    "PluginQualityRequest",
    "PluginQualityResult",
]
