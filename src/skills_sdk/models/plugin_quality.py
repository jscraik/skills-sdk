"""Whole-plugin binding for the existing local skill-quality workflow."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skills_sdk.models.inventory import PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import ArchiveSourceSnapshot, PackageCandidateIdentity, SavedReleaseSnapshot
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import PluginPackageValidation, PluginSkillBinding
from skills_sdk.models.plugin_presentation import PluginPresentationCheck
from skills_sdk.models.quality_workflow import (
    LocalCheckRequestV2,
    LocalCheckRequestV3,
    LocalCheckRequestV4,
    LocalCheckResultV2,
    LocalCheckResultV3,
    LocalCheckResultV4,
)
from skills_sdk.models.safety import _public_text_is_redaction_safe

PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES = 32 * 1_048_576
"""Aggregate supplied-assessment budget: four maximum-sized content-review assessments."""

PLUGIN_QUALITY_REQUEST_MAX_BYTES = 1_048_576
PLUGIN_QUALITY_RESULT_MAX_BYTES = 64 * 1_048_576

_IDENTITY_KEYS = frozenset(
    {"package_id", "source_revision", "content_sha256", "mode_manifest_sha256", "sha256", "code"}
)
_BLOCKER_CODES = frozenset(
    {
        "plugin_quality_input_invalid",
        "plugin_quality_request_invalid",
        "plugin_quality_capacity_exceeded",
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


def bounded_json_size(value: object, limit: int) -> int:
    """Measure compact UTF-8 JSON without allocating an aggregate encoded copy.

    Raises `ValueError` once `limit` bytes are exceeded, for non-JSON values, or
    for nesting beyond 64 levels, so oversized evidence is never fully walked.
    """
    remaining = [limit]

    def consume(size: int) -> None:
        remaining[0] -= size
        if remaining[0] < 0:
            raise ValueError("supplied assessments exceed the aggregate evidence budget")

    def visit(item: object, depth: int) -> None:
        if depth > 64:
            raise ValueError("assessment nesting exceeds its bound")
        if isinstance(item, Enum):
            visit(item.value, depth + 1)
        elif type(item) is dict:
            consume(2 + max(0, len(item) - 1) + len(item))
            for key, member in item.items():
                if type(key) is not str:
                    raise ValueError("assessment evidence requires string keys")
                visit(key, depth + 1)
                visit(member, depth + 1)
        elif type(item) in (list, tuple):
            consume(2 + max(0, len(item) - 1))
            for member in item:
                visit(member, depth + 1)
        elif type(item) is str:
            consume(2)
            for start in range(0, len(item), 4096):
                consume(len(json.dumps(item[start : start + 4096], ensure_ascii=False).encode("utf-8")) - 2)
        elif item is None or type(item) in (int, float, bool):
            consume(len(json.dumps(item, allow_nan=False)))
        elif isinstance(item, BaseModel) and type(item).__module__.startswith("skills_sdk."):
            visit(item.__dict__, depth + 1)
        else:
            raise ValueError("assessment evidence requires canonical JSON values")

    visit(value, 0)
    return limit - remaining[0]


def _public_envelope_is_safe(value: object) -> bool:
    """Screen every retained JSON key and string, including nested receipt families.

    Charge the bounded envelope before walking text; SDK models are inspected
    without allocating a serialized copy. Standalone receipt contracts are unchanged.
    """

    def safe(item: object) -> bool:
        if isinstance(item, str):
            return _public_text_is_redaction_safe(item)
        if isinstance(item, Enum):
            return safe(item.value)
        if isinstance(item, BaseModel):
            return safe(item.__dict__)
        if type(item) is dict:
            return all(safe(key) and safe(member) for key, member in item.items())
        if type(item) in (tuple, list):
            return all(safe(member) for member in item)
        return True

    try:
        bounded_json_size(value, PLUGIN_QUALITY_RESULT_MAX_BYTES)
        return safe(value)
    except (ValueError, TypeError, RecursionError):
        return False


def _reject_padded_identity(value: object) -> None:
    """Reject whitespace-padded identity and digest strings before Pydantic strips them.

    Walks only already-normalized, depth-bounded and cycle-checked containers.
    Identity, digest and blocker-code members are inspected before normalization.
    Assessment byte budgets remain enforced without an unrelated scalar limit.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, member in item.items():
                if (
                    isinstance(key, str)
                    and (key in _IDENTITY_KEYS or key.endswith("_sha256"))
                    and isinstance(member, str)
                    and member != member.strip()
                ):
                    raise ValueError("plugin quality identities, digests and codes must not be padded")
                if isinstance(member, (dict, list, tuple)):
                    pending.append(member)
        elif isinstance(item, (list, tuple)):
            pending.extend(member for member in item if isinstance(member, (dict, list, tuple)))


class PluginQualityChild(_ContractModel):
    """One explicit skill request in root-capture order."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    path: PortablePath = Field(json_schema_extra={"allOf": [{"pattern": "^skills/[^/]+$"}]})
    request: LocalCheckRequestV2

    @model_validator(mode="after")
    def supported_child(self) -> Self:
        """Keep this first composition create/external-check only."""
        PluginSkillBinding.direct_skill(self.path)
        if self.request.intent == "update" or self.request.content_review_mode != "supplied":
            raise ValueError("plugin quality requires create/external-check and supplied review")
        if not _public_envelope_is_safe(self):
            raise ValueError("plugin quality child request text must be redaction-safe")
        return self


def _reject_excess_children(value: object) -> None:
    """Read only container size before recursive request or result materialisation."""
    data = value.__dict__ if isinstance(value, BaseModel) else value
    if isinstance(data, Mapping):
        children = data.get("children")
        if isinstance(children, (list, tuple)) and len(children) > 128:
            raise ValueError("plugin quality child count exceeds 128")


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
        _reject_excess_children(value)
        bounded_json_size(value, PLUGIN_QUALITY_REQUEST_MAX_BYTES)
        if not _public_envelope_is_safe(value):
            raise ValueError("plugin quality request text must be redaction-safe")
        normalized = LocalCheckRequestV2.inputs_are_revalidated(value)
        _reject_padded_identity(normalized)
        return normalized

    @model_validator(mode="after")
    def child_order(self) -> Self:
        """Reject duplicate, unordered or foreign-revision requests."""
        bounded_json_size(self, PLUGIN_QUALITY_REQUEST_MAX_BYTES)
        paths = tuple(child.path for child in self.children)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("plugin quality children must be sorted and unique")
        if any(child.request.candidate.source_revision != self.candidate.source_revision for child in self.children):
            raise ValueError("plugin quality children must share the root revision")
        return self


def _capture_metadata_is_safe(capture: PluginPackageValidation) -> bool:
    """Keep retained free-form manifest fields within the public-text boundary."""
    return _public_envelope_is_safe(capture)


def _child_metadata_is_safe(child: LocalCheckResultV2) -> bool:
    """Cover initial stage, intake and final child captures in the retained result."""
    return _public_envelope_is_safe(child)


def _presentation_metadata_is_safe(presentation: PluginPresentationCheck) -> bool:
    """Screen both image and copy approval reference text before composition retention."""
    return _public_envelope_is_safe(presentation)


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
        and (
            not isinstance(request, PluginQualityRequestV2)
            or (capture.manifest is not None and capture.manifest.version == request.source_snapshot.version)
        )
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
        _reject_excess_children(value)
        data = value.__dict__ if isinstance(value, BaseModel) else value
        if isinstance(data, Mapping):
            _reject_excess_children(data.get("request"))
        if not _public_envelope_is_safe(value):
            raise ValueError("plugin quality retained text or envelope budget is unsafe")
        normalized = LocalCheckRequestV2.inputs_are_revalidated(value)
        _reject_padded_identity(normalized)
        flags = ("mutation_performed", "evaluation_executed", "execution_authorized", "release_ready")
        if isinstance(normalized, dict) and any(normalized.get(flag, False) is not False for flag in flags):
            raise ValueError("plugin quality authority flags must be literal false")
        return normalized

    @model_validator(mode="after")
    def binds_complete_plugin(self) -> Self:
        """Require complete root and child evidence for any successful result."""
        bounded_json_size(self, PLUGIN_QUALITY_RESULT_MAX_BYTES)
        if any(not _child_metadata_is_safe(child) for child in self.children) or (
            self.presentation is not None and not _presentation_metadata_is_safe(self.presentation)
        ):
            raise ValueError("plugin quality retained child and presentation metadata must be redaction-safe")
        if any(
            capture is not None and not _capture_metadata_is_safe(capture)
            for capture in (self.initial_capture, self.final_capture)
        ):
            raise ValueError("plugin quality captured metadata must be redaction-safe")
        if (self.status == "blocked") != (self.blocker is not None):
            raise ValueError("plugin quality status requires its blocker")
        if (
            self.request is not None
            and self.presentation is not None
            and self.presentation.candidate is not None
            and self.presentation.candidate.source_revision != self.request.candidate.source_revision
        ):
            raise ValueError("plugin presentation must retain the selected source revision")
        if self.children:
            if self.request is None or self.initial_capture is None:
                raise ValueError("child results require request and capture")
            self._bind_children()
            self._bound_assessments()
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
        early = {"plugin_quality_input_invalid", "plugin_quality_request_invalid", "plugin_quality_capacity_exceeded"}
        if code in early:
            valid = not retained
        elif self.request is None or self.initial_capture is None:
            valid = False
        elif code == "plugin_quality_root_mismatch":
            capture = self.initial_capture
            valid = (
                retained == {"request", "initial_capture"}
                and capture.policy.require_version
                and capture.policy.require_description
                and (
                    capture.candidate is None
                    or capture.candidate.source_revision == self.request.candidate.source_revision
                )
                and not supported_quality_root(self.request, capture)
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
            final = self.final_capture
            valid = (
                self._presentation_bound()
                and final is not None
                and final.policy == self.initial_capture.policy
                and final != self.initial_capture
                and (
                    final.candidate is None
                    or (
                        final.candidate.package_id == self.request.candidate.package_id
                        and final.candidate.source_revision == self.request.candidate.source_revision
                    )
                )
            )
        if not valid:
            raise ValueError("plugin quality blocker code must match its retained stage evidence")
        if code == "plugin_quality_source_changed":
            self._bind_presentation_capture()

    def _bound_assessments(self) -> None:
        """Reapply the aggregate budget to the normalized assessments this envelope retains."""
        assert self.request is not None
        retained: dict[str, object] = {}
        for expected, result in zip(self.request.children, self.children, strict=False):
            for stage in result.stages:
                assessment = getattr(stage.receipt, "assessment", None)
                if stage.name == "content-review" and assessment is not None:
                    retained[expected.path] = assessment.model_dump(mode="json")
        try:
            bounded_json_size(retained, PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES)
        except (ValueError, RecursionError) as error:
            raise ValueError("retained assessments exceed the aggregate evidence budget") from error

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
            if any(
                stage.receipt.candidate is not None
                and stage.receipt.candidate.source_revision != expected[index].request.candidate.source_revision
                for stage in result.stages
            ):
                raise ValueError("child stages must retain the selected source revision")
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
        self._bind_presentation_capture()

    def _bind_presentation_capture(self) -> None:
        """Bind passed presentation assertions to the initial capture, including after drift."""
        assert self.initial_capture is not None and self.presentation is not None
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


class PluginQualityChildV2(PluginQualityChild):
    """Explicit saved-release child quality request."""

    request: LocalCheckRequestV3


class PluginQualityRequestV2(PluginQualityRequest):
    """Whole-plugin saved snapshot and children bound before any child checks."""

    schema_version: Literal["plugin-quality-request/v2"] = "plugin-quality-request/v2"
    source_snapshot: SavedReleaseSnapshot
    children: tuple[PluginQualityChildV2, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def snapshot_matches_children(self) -> Self:
        """Reject mixed releases, root identities, modes and selected child paths."""
        if (
            self.source_snapshot.root_candidate != self.candidate
            or self.source_snapshot.root_mode_manifest_sha256 != self.mode_manifest_sha256
            or any(
                child.request.intake.source.snapshot != self.source_snapshot
                or child.request.intake.source.path != child.path
                for child in self.children
            )
        ):
            raise ValueError("saved-release quality must bind one whole snapshot and its child paths")
        return self


class PluginQualityResultV2(PluginQualityResult):
    """Retain saved-release provenance throughout the existing quality sequence."""

    schema_version: Literal["plugin-quality/v2"] = "plugin-quality/v2"
    request: PluginQualityRequestV2 | None = None
    children: tuple[LocalCheckResultV3, ...] = Field(default=(), max_length=128)


class PluginQualityChildV3(PluginQualityChildV2):
    """An archive-backed child selected from the containing plugin."""

    request: LocalCheckRequestV4


class PluginQualityRequestV3(PluginQualityRequestV2):
    """Whole archive snapshot checked through the existing quality caller."""

    schema_version: Literal["plugin-quality-request/v3"] = "plugin-quality-request/v3"
    source_snapshot: ArchiveSourceSnapshot
    children: tuple[PluginQualityChildV3, ...] = Field(min_length=1, max_length=128)


class PluginQualityResultV3(PluginQualityResultV2):
    """Archive provenance retained without upstream release claims."""

    schema_version: Literal["plugin-quality/v3"] = "plugin-quality/v3"
    request: PluginQualityRequestV3 | None = None
    children: tuple[LocalCheckResultV4, ...] = Field(default=(), max_length=128)


__all__ = [
    "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES",
    "PluginQualityChild",
    "PluginQualityChildV2",
    "PluginQualityChildV3",
    "PluginQualityRequest",
    "PluginQualityRequestV2",
    "PluginQualityRequestV3",
    "PluginQualityResult",
    "PluginQualityResultV2",
    "PluginQualityResultV3",
    "bounded_json_size",
]
