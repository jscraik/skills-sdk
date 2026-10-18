"""Whole-plugin binding for the existing local skill-quality workflow."""

from __future__ import annotations

import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skills_sdk.models.inventory import Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.plugin import PluginPackageValidation, PluginSkillBinding
from skills_sdk.models.plugin_presentation import PluginPresentationCheck
from skills_sdk.models.quality_workflow import LocalCheckRequestV2, LocalCheckResultV2

PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES = 32 * 1_048_576
"""Aggregate supplied-assessment budget: four maximum-sized content-review assessments."""

_IDENTITY_KEYS = frozenset({"package_id", "source_revision", "content_sha256", "mode_manifest_sha256"})
_PADDING_NODE_LIMIT = 262_144
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
        if type(item) is dict:
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


def _reject_padded_identity(value: object) -> None:
    """Reject whitespace-padded identity and digest strings before Pydantic strips them.

    Walks the already-normalized, cycle-checked containers with a node bound.
    Only `package_id`, `source_revision` and `*_sha256` members are inspected.
    """
    pending, seen = [value], 0
    while pending:
        item = pending.pop()
        seen += 1
        if seen > _PADDING_NODE_LIMIT:
            raise ValueError("plugin quality input exceeds its traversal bound")
        if isinstance(item, dict):
            for key, member in item.items():
                if (
                    isinstance(key, str)
                    and (key in _IDENTITY_KEYS or key.endswith("_sha256"))
                    and isinstance(member, str)
                    and member != member.strip()
                ):
                    raise ValueError("plugin quality identities and digests must not be padded")
                pending.append(member)
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


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
        normalized = LocalCheckRequestV2.inputs_are_revalidated(value)
        _reject_padded_identity(normalized)
        return normalized

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
        _reject_padded_identity(normalized)
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
            final = self.final_capture
            valid = (
                self._presentation_bound()
                and final is not None
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


__all__ = [
    "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES",
    "PluginQualityChild",
    "PluginQualityRequest",
    "PluginQualityResult",
    "bounded_json_size",
]
