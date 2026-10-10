"""Prove explicit settings reach an offline driver, without provider execution."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_codex_profile_binding import _SOURCE, _profile_plan
from test_provider_call import _provider_request

from skills_sdk.core.errors import ContractError
from skills_sdk.providers import ProviderAdapterComplete, execute_provider_call
from skills_sdk.providers._codex_profile_adapter import _CodexProfiledCompleteAdapter
from skills_sdk.providers._codex_profile_invocation import _compile_codex_profile

_CONFIGURED = replace(_SOURCE, defaults_bytes=b'model_reasoning_effort = "low"')


def test_compile_applies_selected_settings_and_never_forwards_host_paths() -> None:
    invocation = _compile_codex_profile(_profile_plan(_CONFIGURED), _CONFIGURED)
    config = json.loads(invocation.configuration_json)
    assert config["model"] == "example-model:small"
    assert config["options"]["model_reasoning_effort"] == "low"
    assert config["options"]["model_reasoning_summary"] == "none"
    assert config["temperature"] == 0.0 and config["trial_count"] == 2
    assert config["catalogue_model"]["base_instructions"] == "Controlled fixture instructions."
    assert config["mcp_servers"] == {} and not any(config["features"].values())
    assert "/unavailable" not in invocation.configuration_json
    assert "localhost" not in repr(invocation)


def test_missing_defaults_block_and_explicit_correction_recovers() -> None:
    with pytest.raises(ContractError, match="model_profile_settings_missing"):
        _compile_codex_profile(_profile_plan(), _SOURCE)
    assert _compile_codex_profile(_profile_plan(_CONFIGURED), _CONFIGURED).configuration_sha256
    for defaults in (b"unknown = true", b'hide_agent_reasoning = "true"', b"model_reasoning_effort = []"):
        with pytest.raises(ContractError):
            _compile_codex_profile(_profile_plan(), replace(_SOURCE, defaults_bytes=defaults))


def test_profile_overrides_catalogue_and_explicit_defaults_with_all_sources_bound() -> None:
    catalogue = json.loads(_SOURCE.catalogue_bytes)
    catalogue["models"][0]["default_reasoning_level"] = "medium"
    source = replace(_CONFIGURED, catalogue_bytes=json.dumps(catalogue).encode())
    inherited = _compile_codex_profile(_profile_plan(source), source)
    assert json.loads(inherited.configuration_json)["options"]["model_reasoning_effort"] == "medium"
    # Insert before the profile's first table so this is a root option.
    profile = source.profile_bytes.replace(b"[features]", b'model_reasoning_effort = "high"\n[features]')
    changed_source = replace(source, profile_bytes=profile)
    explicit = _compile_codex_profile(_profile_plan(changed_source), changed_source)
    assert json.loads(explicit.configuration_json)["options"]["model_reasoning_effort"] == "high"
    assert explicit.binding.inputs_sha256 != inherited.binding.inputs_sha256


@pytest.mark.parametrize("key", ["approval_policy", "approvals_reviewer", "web_search", "model_reasoning_summary"])
def test_closed_defaults_reject_even_when_profile_would_override_them(key: str) -> None:
    source = replace(_CONFIGURED, defaults_bytes=f'{key} = "unsupported-value"'.encode())
    with pytest.raises(ContractError, match="invalid_model_profile"):
        _compile_codex_profile(_profile_plan(source), source)
    assert _compile_codex_profile(_profile_plan(_CONFIGURED), _CONFIGURED).configuration_sha256


def test_catalogue_summary_cannot_bypass_resolved_option_validation() -> None:
    catalogue = json.loads(_CONFIGURED.catalogue_bytes)
    catalogue["models"][0]["default_reasoning_summary"] = "unsupported-value"
    profile = _CONFIGURED.profile_bytes.replace(b'model_reasoning_summary = "none"\n', b"")
    source = replace(_CONFIGURED, profile_bytes=profile, catalogue_bytes=json.dumps(catalogue).encode())
    with pytest.raises(ContractError, match="invalid_model_profile"):
        _compile_codex_profile(_profile_plan(source), source)
    catalogue["models"][0]["default_reasoning_summary"] = "none"
    corrected = replace(source, catalogue_bytes=json.dumps(catalogue).encode())
    assert _compile_codex_profile(_profile_plan(corrected), corrected).configuration_sha256


def test_resolved_effort_matches_advertised_levels_and_rebinds_after_correction() -> None:
    catalogue = json.loads(_CONFIGURED.catalogue_bytes)
    catalogue["models"][0]["supported_reasoning_levels"] = [
        {"effort": "custom-effort", "description": "Controlled model capability."}
    ]
    source = replace(_CONFIGURED, catalogue_bytes=json.dumps(catalogue).encode())
    with pytest.raises(ContractError, match="model_profile_reasoning_mismatch"):
        _compile_codex_profile(_profile_plan(source), source)
    corrected = replace(source, defaults_bytes=b'model_reasoning_effort = "custom-effort"')
    invocation = _compile_codex_profile(_profile_plan(corrected), corrected)
    assert json.loads(invocation.configuration_json)["options"]["model_reasoning_effort"] == "custom-effort"


@pytest.mark.parametrize(
    "levels",
    [
        [],
        ["low"],
        [None],
        [{"effort": "low"}],
        [{"effort": "low", "description": "Controlled capability.", "unknown": True}],
        [{"effort": "low", "description": "Controlled capability."}] * 2,
    ],
)
def test_malformed_advertised_efforts_block_and_recover(levels: object) -> None:
    catalogue = json.loads(_CONFIGURED.catalogue_bytes)
    catalogue["models"][0]["supported_reasoning_levels"] = levels
    source = replace(_CONFIGURED, catalogue_bytes=json.dumps(catalogue).encode())
    with pytest.raises(ContractError, match="model_profile_dependency_invalid"):
        _compile_codex_profile(_profile_plan(source), source)
    assert _compile_codex_profile(_profile_plan(_CONFIGURED), _CONFIGURED).configuration_sha256


class _Driver:
    def __init__(self) -> None:
        self.calls = []
        self.cleanup_calls = 0
        self.mutate = None

    async def complete(self, invocation: object, request: object, payload: object) -> ProviderAdapterComplete:
        self.calls.append(json.loads(invocation.configuration_json))
        if self.mutate is not None:
            self.mutate()
        return ProviderAdapterComplete("controlled answer", ("evidence/profile-fixture.json",))

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


def _request_for(adapter: _CodexProfiledCompleteAdapter) -> object:
    data = _provider_request().model_dump(mode="json")
    data["provider"] = adapter.descriptor.provider.model_dump(mode="json")
    return type(_provider_request()).model_validate(data)


def test_driver_receives_compiled_settings_and_cleanup_uses_existing_lifecycle() -> None:
    driver = _Driver()
    adapter = _CodexProfiledCompleteAdapter(_profile_plan(_CONFIGURED), _CONFIGURED, driver)
    result = asyncio.run(adapter.complete(_request_for(adapter), None))
    assert result.text == "controlled answer"
    assert len(driver.calls) == 1
    assert driver.calls[0]["options"]["model_reasoning_effort"] == "low"
    asyncio.run(adapter.cleanup())
    assert driver.cleanup_calls == 1


def test_drift_before_callback_blocks_and_during_callback_discards_result() -> None:
    driver = _Driver()
    adapter = _CodexProfiledCompleteAdapter(_profile_plan(_CONFIGURED), _CONFIGURED, driver)
    request = _request_for(adapter)
    changed = replace(_CONFIGURED, defaults_bytes=b'model_reasoning_effort = "high"')
    adapter.source = changed
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        asyncio.run(adapter.complete(request, None))
    assert driver.calls == []
    adapter.source = _CONFIGURED
    driver.mutate = lambda: setattr(adapter, "source", changed)
    with pytest.raises(ContractError, match="model_profile_binding_changed"):
        asyncio.run(adapter.complete(request, None))
    assert len(driver.calls) == 1
    recovered = _CodexProfiledCompleteAdapter(_profile_plan(changed), changed, _Driver())
    assert asyncio.run(recovered.complete(_request_for(recovered), None)).text == "controlled answer"


def test_profile_adapter_composes_with_public_provider_call_and_cleanup() -> None:
    driver = _Driver()
    adapter = _CodexProfiledCompleteAdapter(_profile_plan(_CONFIGURED), _CONFIGURED, driver)
    outcome = asyncio.run(execute_provider_call(_request_for(adapter), None, adapter))
    assert outcome.public_result.status == "completed"
    assert outcome.complete_text == "controlled answer"
    assert driver.cleanup_calls == 1
    assert driver.calls[0]["model"] == "example-model:small"
    assert "localhost" not in outcome.public_result.model_dump_json()
    assert "Controlled fixture instructions" not in outcome.public_result.model_dump_json()
