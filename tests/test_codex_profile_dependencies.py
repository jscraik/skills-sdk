"""Retain explicit dependency gaps rather than reading the caller's runtime."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_codex_profile_input import _CLOUD, _LOCAL

from skills_sdk.core.errors import ContractError
from skills_sdk.providers._codex_profile import _parse_codex_profile
from skills_sdk.providers._codex_profile_resolution import _resolve_profile_dependencies

_PROVIDER = b"""[model_providers.example-local]
name = "Controlled local transport"
base_url = "http://localhost:9999/v1"
wire_api = "responses"
"""
_CATALOGUE = json.dumps(
    {
        "client_version": "fixture-v1",
        "models": [{"slug": "example-model:small", "base_instructions": "Controlled fixture instructions."}],
    }
).encode()


def test_explicit_dependencies_are_digest_bound_without_paths_or_transport_execution() -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    resolved = _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE)
    assert resolved.catalogue_sha256 and resolved.selected_model_sha256 and resolved.provider_sha256
    assert "localhost" not in repr(resolved)
    assert "Controlled fixture instructions" not in repr(resolved)
    changed = _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE.replace(b"Controlled", b"Changed"))
    assert changed.catalogue_sha256 != resolved.catalogue_sha256
    assert changed.selected_model_sha256 != resolved.selected_model_sha256


@pytest.mark.parametrize(
    "provider,catalogue,code",
    [
        (None, _CATALOGUE, "model_profile_dependency_missing"),
        (_PROVIDER, None, "model_profile_dependency_missing"),
        (_PROVIDER.replace(b"example-local", b"other"), _CATALOGUE, "model_profile_provider_mismatch"),
        (_PROVIDER, _CATALOGUE.replace(b"example-model:small", b"other"), "model_profile_catalogue_mismatch"),
        (_PROVIDER, b'{"models": [], "client_version": "v1"}', "model_profile_dependency_invalid"),
        (_PROVIDER, b'{"models": [], "models": [], "client_version": "v1"}', "model_profile_dependency_invalid"),
        (_PROVIDER, b'{"models": [NaN], "client_version": "v1"}', "model_profile_dependency_invalid"),
        (_PROVIDER, b"x" * 1_048_577, "model_profile_dependency_invalid"),
        (_PROVIDER + b'api_key = "synthetic-private-value"', _CATALOGUE, "invalid_model_profile"),
    ],
)
def test_missing_mismatched_malformed_dependencies_block_then_recover(
    provider: bytes | None, catalogue: bytes | None, code: str
) -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    with pytest.raises(ContractError) as error:
        _resolve_profile_dependencies(parsed, _LOCAL, provider, catalogue)
    assert error.value.code == code
    assert "synthetic-private-value" not in str(error.value)
    assert _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE).catalogue_sha256


def test_inline_cloud_transport_needs_no_ambient_provider() -> None:
    parsed = _parse_codex_profile(_CLOUD, "cloud")
    resolved = _resolve_profile_dependencies(parsed, _CLOUD, None, None)
    assert resolved.provider_sha256 and resolved.catalogue_sha256 is None
    for provider, catalogue in ((_PROVIDER, None), (None, _CATALOGUE)):
        with pytest.raises(ContractError, match="model_profile_dependency_ambiguous"):
            _resolve_profile_dependencies(parsed, _CLOUD, provider, catalogue)


@pytest.mark.parametrize("port", ["not-a-port", "99999", "0", "-1"])
def test_inherited_provider_ports_reject_and_recover(port: str) -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    invalid = _PROVIDER.replace(b"localhost:9999", f"localhost:{port}".encode())
    with pytest.raises(ContractError):
        _resolve_profile_dependencies(parsed, _LOCAL, invalid, _CATALOGUE)
    assert _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE).provider_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_sha256", "0" * 64),
        ("model", "other-model"),
        ("provider", "other-provider"),
        ("requires_catalogue", False),
        ("declares_provider", True),
    ],
)
def test_dependency_resolution_revalidates_selection_metadata(field: str, value: object) -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    forged = replace(parsed, **{field: value})
    with pytest.raises(ContractError, match="model_profile_input_changed"):
        _resolve_profile_dependencies(forged, _LOCAL, _PROVIDER, _CATALOGUE)
    assert _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE).provider_sha256


def test_dependency_resolution_rejects_changed_profile_bytes_then_recaptures() -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    changed = _LOCAL + b"\n# Changed explicit input\n"
    with pytest.raises(ContractError, match="model_profile_input_changed"):
        _resolve_profile_dependencies(parsed, changed, _PROVIDER, _CATALOGUE)
    recaptured = _parse_codex_profile(changed, "local")
    assert _resolve_profile_dependencies(recaptured, changed, _PROVIDER, _CATALOGUE).provider_sha256


def test_transport_binds_exact_source_separately_from_effective_declaration() -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    original = _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE)
    changed = _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER + b"\n# Changed input\n", _CATALOGUE)
    assert original.provider_sha256 == changed.provider_sha256
    assert original.provider_source_sha256 != changed.provider_source_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("supports_reasoning_summaries", 1),
        ("context_window", True),
        ("max_context_window", -1),
        ("priority", 0.5),
        ("base_instructions", {}),
        ("default_reasoning_level", []),
        ("supported_reasoning_levels", "high"),
        ("model_messages", []),
        ("truncation_policy", False),
        ("upgrade", "unbound-upgrade"),
        ("service_tiers", [None] * 257),
        ("base_instructions", "\ud800"),
    ],
)
def test_catalogue_field_shapes_block_malformed_values_then_recover(field: str, value: object) -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    data = json.loads(_CATALOGUE)
    data["models"][0][field] = value
    with pytest.raises(ContractError, match="model_profile_dependency_invalid"):
        _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, json.dumps(data).encode())
    assert _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, _CATALOGUE).selected_model_sha256


@pytest.mark.parametrize(
    "payload",
    [
        b'{"client_version":"v1","models":[{"slug":"example-model:small","model_messages":{"x":1e999}}]}',
        b'{"client_version":"v1","models":[{"slug":"example-model:small","model_messages":{"x":'
        + b"[" * 40
        + b"0"
        + b"]" * 40
        + b"}}]}",
    ],
)
def test_nested_catalogue_values_are_finite_and_depth_bounded(payload: bytes) -> None:
    parsed = _parse_codex_profile(_LOCAL, "local")
    with pytest.raises(ContractError, match="model_profile_dependency_invalid"):
        _resolve_profile_dependencies(parsed, _LOCAL, _PROVIDER, payload)
