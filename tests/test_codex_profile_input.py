"""Profile input proof uses synthetic bytes and no home configuration."""

from __future__ import annotations

import hashlib

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.providers._codex_profile import _parse_codex_profile

_LOCAL = b"""model = "example-model:small"
model_provider = "example-local"
model_catalog_json = "/unavailable/catalogue.json"
default_permissions = "readonly-net"
approval_policy = "on-request"
approvals_reviewer = "auto_review"
model_reasoning_summary = "none"
hide_agent_reasoning = true
web_search = "disabled"
[features]
plugins = false
apps = false
[mcp_servers.example]
command = "/unavailable/never-execute"
enabled = false
required = false
args = []
"""

_CLOUD = b"""model = "example-model:cloud"
model_provider = "example-cloud"
[model_providers.example-cloud]
name = "Example Cloud"
base_url = "https://example.invalid/v1"
wire_api = "responses"
env_key = "EXAMPLE_API_KEY"
"""


def test_profile_capture_retains_unresolved_dependencies_without_loading_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile name or digest must not masquerade as effective execution proof."""
    monkeypatch.setenv("EXAMPLE_API_KEY", "synthetic-private-value")
    local = _parse_codex_profile(_LOCAL, "local")
    cloud = _parse_codex_profile(_CLOUD, "cloud")
    assert local.requires_catalogue and not local.declares_provider
    assert cloud.declares_provider and not cloud.requires_catalogue
    assert local.model == "example-model:small"
    assert local.profile_sha256 == hashlib.sha256(_LOCAL).hexdigest()
    assert "unavailable" not in repr(local)
    assert "EXAMPLE_API_KEY" not in repr(cloud)
    assert "synthetic-private-value" not in repr(cloud)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"x" * 65_537,
        b"\xff",
        b'model = "x"\nmodel = "y"',
        b'model = 1\nmodel_provider = "example"',
        b'model = "https://example.invalid/model"\nmodel_provider = "example"',
        b'model = "example"\nmodel_provider = false',
        b'model = "example"\nmodel_provider = "example"\nunknown = true',
        _LOCAL.replace(b"plugins = false", b"plugins = true"),
        _LOCAL.replace(b"enabled = false", b"enabled = true"),
        _LOCAL.replace(b"required = false", b"required = true"),
        _LOCAL.replace(b"args = []", b"args = [1]"),
        _LOCAL.replace(b"hide_agent_reasoning = true", b"hide_agent_reasoning = 1"),
        _CLOUD.replace(b'wire_api = "responses"', b'wire_api = "unknown"'),
        _CLOUD.replace(b"EXAMPLE_API_KEY", b"not a variable"),
        _CLOUD.replace(b"https://example.invalid/v1", b"https://user:private@example.invalid/v1"),
        _CLOUD.replace(b"https://example.invalid/v1", b"https://example.invalid/v1?key=private"),
        _CLOUD.replace(b"https://example.invalid/v1", b"file:///invalid/model"),
        _CLOUD + b'api_key = "synthetic-private-value"\n',
    ],
)
def test_invalid_profiles_block_and_corrected_input_recovers(payload: bytes) -> None:
    with pytest.raises(ContractError) as captured:
        _parse_codex_profile(payload, "local")
    assert captured.value.code == "invalid_model_profile"
    assert captured.value.details == ()
    assert "synthetic-private-value" not in str(captured.value)
    assert _parse_codex_profile(_LOCAL, "local").model == "example-model:small"


def test_changed_settings_change_profile_digest() -> None:
    original = _parse_codex_profile(_LOCAL, "local")
    changed = _parse_codex_profile(_LOCAL.replace(b'"none"', b'"concise"'), "local")
    assert original.profile_sha256 != changed.profile_sha256


@pytest.mark.parametrize("key", ["approval_policy", "approvals_reviewer", "web_search", "model_reasoning_summary"])
def test_closed_option_values_reject_and_recover(key: str) -> None:
    lines = _LOCAL.decode().splitlines()
    invalid = "\n".join(f'{key} = "unsupported-value"' if line.startswith(key + " =") else line for line in lines)
    with pytest.raises(ContractError, match="invalid_model_profile"):
        _parse_codex_profile(invalid.encode(), "local")
    assert _parse_codex_profile(_LOCAL, "local").model == "example-model:small"


@pytest.mark.parametrize("port", ["not-a-port", "99999", "0", "-1"])
def test_inline_provider_ports_reject_and_recover(port: str) -> None:
    invalid = _CLOUD.replace(b"https://example.invalid/v1", f"https://example.invalid:{port}/v1".encode())
    with pytest.raises(ContractError, match="invalid_model_profile"):
        _parse_codex_profile(invalid, "cloud")
    valid = _CLOUD.replace(b"https://example.invalid/v1", b"https://example.invalid:443/v1")
    assert _parse_codex_profile(valid, "cloud").declares_provider


@pytest.mark.parametrize("lane", ["other", None, [], {}])
def test_unsupported_lane_fails_before_parsing(lane: object) -> None:
    with pytest.raises(ContractError):
        _parse_codex_profile(_LOCAL, lane)
