"""Compile explicit profile configuration for a driver without ambient defaults."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from typing import Literal

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.models.matched_comparison import MatchedComparisonPlan
from skills_sdk.providers._codex_profile import _SETTING_FIELDS, _parse_codex_defaults, _validate_settings
from skills_sdk.providers._codex_profile_binding import _bind_codex_profile, _CodexProfileBinding, _CodexProfileSource
from skills_sdk.providers._codex_profile_resolution import _reasoning_levels


@dataclass(frozen=True, slots=True)
class _CodexProfileInvocation:
    """Immutable private driver input; compiling it does not execute a provider."""

    binding: _CodexProfileBinding
    configuration_sha256: str
    configuration_json: str = field(repr=False)


def _configuration_options(source: _CodexProfileSource, data: dict[str, object], model: dict[str, object]) -> dict:
    options = _parse_codex_defaults(source.defaults_bytes)
    for target, key in (
        ("model_reasoning_effort", "default_reasoning_level"),
        ("model_reasoning_summary", "default_reasoning_summary"),
    ):
        if model.get(key) is not None:
            options[target] = model[key]
    options.update({key: value for key, value in data.items() if key in _SETTING_FIELDS})
    if set(options) != _SETTING_FIELDS:
        raise ContractError(
            "model_profile_settings_missing", "supply explicit defaults for every unresolved profile setting"
        )
    _validate_settings(options)
    if "supported_reasoning_levels" in model and options["model_reasoning_effort"] not in _reasoning_levels(
        model["supported_reasoning_levels"]
    ):
        raise ContractError(
            "model_profile_reasoning_mismatch", "select a reasoning effort advertised by the supplied model"
        )
    return options


def _compile_codex_profile(
    plan: object, source: _CodexProfileSource, role: Literal["generator", "judge"] = "generator"
) -> _CodexProfileInvocation:
    """Apply profile > selected catalogue > explicit defaults precedence.

    Only supplied bytes are read. Disabled MCP launch commands and catalogue file
    paths are not forwarded; selected catalogue contents and transport are explicit
    private driver inputs. Temperature/trial count come from the frozen matched lane.
    The driver must separately prove it consumed this configuration.
    """
    binding = _bind_codex_profile(plan, source, role)
    current = MatchedComparisonPlan.model_validate(plan)
    lane = current.lanes[0 if source.name == "oss-local.config.toml" else 1]
    data = tomllib.loads(source.profile_bytes.decode("utf-8"))
    providers = data.get("model_providers", {})
    if source.provider_bytes is not None:
        providers = tomllib.loads(source.provider_bytes.decode("utf-8"))["model_providers"]
    model = {}
    if source.catalogue_bytes is not None:
        model = next(
            item for item in json.loads(source.catalogue_bytes)["models"] if item["slug"] == binding.native_model
        )
    parameters = lane.generator_parameters if role == "generator" else lane.judge_parameters
    configuration = {
        "model": binding.native_model,
        "model_provider": data["model_provider"],
        "transport": providers[data["model_provider"]],
        "options": _configuration_options(source, data, model),
        "features": dict.fromkeys(
            ("plugins", "apps", "code_mode", "code_mode_only", "skill_mcp_dependency_install"), False
        ),
        "mcp_servers": {},
        "catalogue_model": model or None,
        "temperature": parameters.temperature,
        "trial_count": parameters.trial_count,
    }
    return _CodexProfileInvocation(
        binding, canonical_json_sha256(configuration), json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    )
