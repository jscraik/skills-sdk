"""Bind explicit profile inputs to a matched plan, without executing a provider.

This private capture is not an effective-settings or execution receipt. Adapters
must separately establish that the captured settings were applied.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import ValidationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers._codex_profile import _parse_codex_defaults, _parse_codex_profile, _ParsedCodexProfile
from skills_sdk.providers._codex_profile_resolution import _resolve_profile_dependencies


@dataclass(frozen=True, slots=True)
class _CodexProfileSource:
    """Explicit bytes; the logical name is never interpreted as a file path."""

    name: str
    profile_bytes: bytes = field(repr=False)
    provider_bytes: bytes | None = field(default=None, repr=False)
    catalogue_bytes: bytes | None = field(default=None, repr=False)
    defaults_bytes: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _CodexProfileBinding:
    """Capture provenance and plan identity, not clearance to call a provider."""

    profile_name: str
    role: Literal["generator", "judge"]
    plan_sha256: str
    lane_sha256: str
    inputs_sha256: str
    native_model: str
    portable_model: str


def _binding_error(code: str = "model_profile_plan_mismatch") -> ContractError:
    return ContractError(
        code, "select a matching named profile and rebind the current matched plan and explicit inputs"
    )


def _capture_codex_profile(source: _CodexProfileSource) -> tuple[_ParsedCodexProfile, str]:
    """Bind all explicit inputs before the caller freezes an adapter identity."""
    names = {"oss-local.config.toml": "local", "oss-cloud.config.toml": "cloud"}
    if type(source) is not _CodexProfileSource or type(source.name) is not str or source.name not in names:
        raise _binding_error("invalid_model_profile_selection")
    selected = _parse_codex_profile(source.profile_bytes, names[source.name])
    _parse_codex_defaults(source.defaults_bytes)
    dependencies = _resolve_profile_dependencies(
        selected, source.profile_bytes, source.provider_bytes, source.catalogue_bytes
    )
    inputs_sha256 = canonical_json_sha256(
        {
            "binding_contract": "codex-profile-offline/v1",
            "profile_name": source.name,
            "profile_sha256": selected.profile_sha256,
            "dependencies": asdict(dependencies),
            "defaults_sha256": hashlib.sha256(source.defaults_bytes).hexdigest()
            if source.defaults_bytes is not None
            else None,
        }
    )
    return selected, inputs_sha256


def _bind_codex_profile(
    plan: object, source: _CodexProfileSource, role: Literal["generator", "judge"] = "generator"
) -> _CodexProfileBinding:
    """Require input provenance in the plan's existing adapter identity fields."""
    if type(role) is not str or role not in {"generator", "judge"}:
        raise _binding_error("invalid_model_profile_selection")
    try:
        current = MatchedComparisonPlan.model_validate(plan)
        selected, inputs_sha256 = _capture_codex_profile(source)
        lane = next(item for item in current.lanes if item.lane == selected.lane)
        identity = lane.generator if role == "generator" else lane.judge
        portable_model = f"{selected.provider}/{selected.model}"
        if (
            identity.provider_id != selected.provider
            or identity.model_id != portable_model
            or identity.adapter_id != "codex-profile-offline-v1"
            or identity.adapter_version_or_digest != inputs_sha256
        ):
            raise _binding_error()
        return _CodexProfileBinding(
            source.name,
            role,
            current.digest,
            canonical_json_sha256(lane.model_dump(mode="json")),
            inputs_sha256,
            selected.model,
            portable_model,
        )
    except (ValidationError, TypeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise _binding_error() from None


def _check_codex_profile_binding(binding: _CodexProfileBinding, plan: object, source: _CodexProfileSource) -> None:
    """Reject changed input/plan capture; never interpret a binding as approval."""
    if type(binding) is not _CodexProfileBinding:
        raise _binding_error("model_profile_binding_changed")
    try:
        current = _bind_codex_profile(plan, source, binding.role)
    except ContractError:
        raise _binding_error("model_profile_binding_changed") from None
    if current != binding:
        raise _binding_error("model_profile_binding_changed")
