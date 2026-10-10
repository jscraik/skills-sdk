"""Bind supplied profile bytes to real matched models without invoking providers."""

from dataclasses import replace

import pytest
from test_codex_profile_dependencies import _CATALOGUE, _PROVIDER
from test_codex_profile_input import _CLOUD, _LOCAL
from test_matched_comparison import _plan

from skills_sdk.core.errors import ContractError
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers._codex_profile_binding import (
    _bind_codex_profile,
    _capture_codex_profile,
    _check_codex_profile_binding,
    _CodexProfileSource,
)


def _profile_plan(source: _CodexProfileSource | None = None) -> MatchedComparisonPlan:
    data = _plan().model_dump(mode="json")
    for lane, tag in zip(data["lanes"], ("small", "cloud"), strict=True):
        provider = f"example-{lane['lane']}"
        model = f"{provider}/example-model:{tag}"
        selected = (
            (source or _SOURCE) if lane["lane"] == "local" else _CodexProfileSource("oss-cloud.config.toml", _CLOUD)
        )
        _, digest = _capture_codex_profile(selected)
        for role in ("generator", "judge"):
            lane[role]["provider_id"] = provider
            lane[role]["model_id"] = model
            lane[role]["adapter_id"] = "codex-profile-offline-v1"
            lane[role]["adapter_version_or_digest"] = digest
            lane[f"{role}_parameters"]["model"] = model
    return MatchedComparisonPlan.model_validate(data)


_SOURCE = _CodexProfileSource("oss-local.config.toml", _LOCAL, _PROVIDER, _CATALOGUE)


@pytest.mark.parametrize("role", ["generator", "judge"])
def test_named_profiles_bind_both_lanes_without_changing_active_cases(role: str) -> None:
    plan = _profile_plan()
    cloud = _CodexProfileSource("oss-cloud.config.toml", _CLOUD)
    for source in (_SOURCE, cloud):
        binding = _bind_codex_profile(plan, source, role)
        assert binding.plan_sha256 == plan.digest
        assert binding.native_model.startswith("example-model:")
        assert binding.portable_model.endswith("/" + binding.native_model)
        _check_codex_profile_binding(binding, plan, source)
        assert "/unavailable" not in repr(binding)
        assert "EXAMPLE_API_KEY" not in repr(binding)
    assert len(plan.case_bindings) == 10


@pytest.mark.parametrize("name", ["oss-cloud.config.toml", "other.toml", "/home/oss-local.config.toml", ""])
def test_wrong_lane_or_nonlogical_selection_blocks_then_recovers(name: str) -> None:
    plan = _profile_plan()
    with pytest.raises(ContractError):
        _bind_codex_profile(plan, replace(_SOURCE, name=name))
    assert _bind_codex_profile(plan, _SOURCE).plan_sha256 == plan.digest


@pytest.mark.parametrize("field", ["profile_bytes", "provider_bytes", "catalogue_bytes"])
def test_changed_inputs_require_new_binding(field: str) -> None:
    plan = _profile_plan()
    binding = _bind_codex_profile(plan, _SOURCE)
    changed = replace(_SOURCE, **{field: getattr(_SOURCE, field) + b"\n"})
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        _check_codex_profile_binding(binding, plan, changed)
    with pytest.raises(ContractError, match="model_profile_plan_mismatch"):
        _bind_codex_profile(plan, changed)
    rebound_plan = _profile_plan(changed)
    assert rebound_plan.digest != plan.digest
    rebound = _bind_codex_profile(rebound_plan, changed)
    assert rebound.inputs_sha256 != binding.inputs_sha256
    _check_codex_profile_binding(rebound, rebound_plan, changed)


def test_plan_settings_change_invalidates_binding_and_forged_plan_is_rejected() -> None:
    plan = _profile_plan()
    binding = _bind_codex_profile(plan, _SOURCE)
    data = plan.model_dump(mode="json")
    data["lanes"][0]["generator_parameters"]["temperature"] = 0.5
    changed = MatchedComparisonPlan.model_validate(data)
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        _check_codex_profile_binding(binding, changed, _SOURCE)
    assert _bind_codex_profile(changed, _SOURCE).plan_sha256 != binding.plan_sha256
    forged = plan.model_copy(update={"case_bindings": ()})
    with pytest.raises(ContractError):
        _bind_codex_profile(forged, _SOURCE)


def test_source_repr_does_not_disclose_supplied_bytes() -> None:
    assert "unavailable" not in repr(_SOURCE)
    assert "Controlled" not in repr(_SOURCE)


def test_public_profile_identity_binds_provenance_without_changing_frozen_schema() -> None:
    from skills_sdk.providers.codex_profiles import CodexProfileSource, describe_codex_profile

    source = CodexProfileSource("oss-local.config.toml", _LOCAL, _PROVIDER, _CATALOGUE)
    identity = describe_codex_profile(source, model_revision="v1")
    assert identity == _profile_plan().lanes[0].generator
    changed = describe_codex_profile(replace(source, profile_bytes=_LOCAL + b"\n"), model_revision="v1")
    assert changed.adapter_version_or_digest != identity.adapter_version_or_digest
    assert identity.schema_version == "provider-identity/v2"
    assert "unavailable" not in identity.model_dump_json()
