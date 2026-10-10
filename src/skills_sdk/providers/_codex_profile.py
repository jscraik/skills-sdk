"""Parse explicit Codex profile bytes without loading host resources or secrets.

This private input boundary is not execution evidence. Catalogue resolution,
effective execution settings and matched-candidate binding belong to admission.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from skills_sdk.core.errors import ContractError

_MAX_PROFILE_BYTES = 65_536
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*(?:/[A-Za-z0-9][A-Za-z0-9._+-]*)*(?::[A-Za-z0-9][A-Za-z0-9._+-]*)?")
_PROVIDER = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_SECRET = re.compile(r"(?:^|[^a-z0-9])(?:bearer\s|sk-|ghp_|github_pat_|xoxb-|xoxp-|AKIA)", re.IGNORECASE)
_STRINGS = {
    "model",
    "model_provider",
    "model_catalog_json",
    "default_permissions",
    "approval_policy",
    "approvals_reviewer",
    "model_reasoning_summary",
    "model_reasoning_effort",
    "web_search",
}
_BOOLEANS = {"hide_agent_reasoning"}
_TABLES = {"features", "mcp_servers", "model_providers"}
_FEATURES = {"plugins", "skill_mcp_dependency_install", "apps", "code_mode", "code_mode_only"}
_MCP_FIELDS = {"enabled", "required", "url", "command", "args"}
_PROVIDER_FIELDS = {"name", "base_url", "wire_api", "env_key"}
_SETTING_FIELDS = _STRINGS - {"model", "model_provider", "model_catalog_json"} | _BOOLEANS
_CLOSED_SETTINGS = {
    "approval_policy": {"untrusted", "on-request", "never"},
    "approvals_reviewer": {"user", "auto_review", "guardian_subagent"},
    "model_reasoning_summary": {"auto", "concise", "detailed", "none"},
    "web_search": {"disabled", "cached", "indexed", "live"},
}


@dataclass(frozen=True, slots=True)
class _ParsedCodexProfile:
    """Secret-free selection metadata, explicitly short of effective settings."""

    lane: Literal["local", "cloud"]
    profile_sha256: str
    model: str
    provider: str
    requires_catalogue: bool
    declares_provider: bool


def _invalid() -> ContractError:
    return ContractError("invalid_model_profile", "profile requires supported, explicit, secret-free TOML inputs")


def _parse_codex_defaults(payload: bytes | None) -> dict[str, object]:
    """Read caller-supplied defaults without falling back to runtime settings."""
    if payload is None:
        return {}
    if type(payload) is not bytes or not 0 < len(payload) <= _MAX_PROFILE_BYTES:
        raise _invalid()
    try:
        data = tomllib.loads(payload.decode("utf-8"))
        if set(data) - _SETTING_FIELDS:
            raise _invalid()
        _validate_settings(data)
        return data
    except (ValueError, TypeError, RecursionError):
        raise _invalid() from None


def _text(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 4096
        and value == value.strip()
        and not any(ord(character) < 32 for character in value)
        and not _SECRET.search(value)
    )


def _validate_settings(data: dict[str, object]) -> None:
    """Check the bounded adapter's supported options without resolving host policy."""
    if any(not _text(data[key]) for key in (_SETTING_FIELDS - _BOOLEANS) & data.keys()):
        raise _invalid()
    if any(type(data[key]) is not bool for key in _BOOLEANS & data.keys()):
        raise _invalid()
    if any(data[key] not in choices for key, choices in _CLOSED_SETTINGS.items() if key in data):
        raise _invalid()


def _disabled_mcp(value: object) -> None:
    if type(value) is not dict or len(value) > 64:
        raise _invalid()
    for name, entry in value.items():
        if not _text(name) or type(entry) is not dict or set(entry) - _MCP_FIELDS:
            raise _invalid()
        if entry.get("enabled") is not False or entry.get("required", False) is not False:
            raise _invalid()
        if any(not _text(entry[key]) for key in ("url", "command") if key in entry):
            raise _invalid()
        args = entry.get("args", [])
        if type(args) is not list or len(args) > 32 or any(not _text(arg) for arg in args):
            raise _invalid()


def _providers(value: object, selected: str) -> bool:
    if type(value) is not dict or len(value) > 16:
        raise _invalid()
    for name, entry in value.items():
        if not _text(name) or not _PROVIDER.fullmatch(name) or type(entry) is not dict:
            raise _invalid()
        if set(entry) - _PROVIDER_FIELDS or any(not _text(item) for item in entry.values()):
            raise _invalid()
        if entry.get("wire_api") not in {"responses", "chat"} or not entry.get("base_url"):
            raise _invalid()
        endpoint = urlsplit(entry["base_url"])
        # Accessing .port rejects non-numeric ports and values above 65535.
        port = endpoint.port
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or port == 0
        ):
            raise _invalid()
        if "env_key" in entry and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", entry["env_key"]):
            raise _invalid()
    return selected in value


def _validate_profile(data: dict[str, object]) -> None:
    if set(data) - (_STRINGS | _BOOLEANS | _TABLES):
        raise _invalid()
    if any(not _text(data[key]) for key in _STRINGS & data.keys()):
        raise _invalid()
    _validate_settings(data)
    model, provider = data.get("model"), data.get("model_provider")
    if not _text(model) or not _MODEL.fullmatch(model) or len(model) > 128:
        raise _invalid()
    if not _text(provider) or not _PROVIDER.fullmatch(provider) or len(provider) > 64:
        raise _invalid()
    features = data.get("features", {})
    if type(features) is not dict or set(features) - _FEATURES or any(item is not False for item in features.values()):
        raise _invalid()
    _disabled_mcp(data.get("mcp_servers", {}))


def _parse_codex_profile(payload: bytes, lane: Literal["local", "cloud"]) -> _ParsedCodexProfile:
    """Capture selection from supplied bytes; never resolve paths or environment.

    Unknown executable settings, enabled integrations and inline credentials are
    rejected. A declared catalogue or inherited provider remains a dependency,
    not a silently accepted effective model configuration.
    """
    if (
        type(payload) is not bytes
        or not 0 < len(payload) <= _MAX_PROFILE_BYTES
        or type(lane) is not str
        or lane not in {"local", "cloud"}
    ):
        raise _invalid()
    try:
        data = tomllib.loads(payload.decode("utf-8"))
        _validate_profile(data)
        declared = _providers(data.get("model_providers", {}), data["model_provider"])
        return _ParsedCodexProfile(
            lane,
            hashlib.sha256(payload).hexdigest(),
            data["model"],
            data["model_provider"],
            "model_catalog_json" in data,
            declared,
        )
    except (ValueError, TypeError, RecursionError, KeyError):
        raise _invalid() from None
