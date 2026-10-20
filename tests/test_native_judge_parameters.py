"""Additive native controls retain strict schemas without changing legacy families."""

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models import CodexNativeJudgeParameters, PluginQualityRequest, PluginQualityResult
from skills_sdk.providers.codex_judge import CodexJudgeSettings


@pytest.mark.parametrize("names", [("a" * 65,), tuple(f"server_{index}" for index in range(65))])
def test_mcp_override_limits_reject_before_argument_construction(names: tuple[str, ...]) -> None:
    """Raw, typed and structural settings cannot admit oversized overrides."""
    payload = CodexJudgeSettings("fixture-model", "0.153.4", ()).public_settings()
    payload["disabled_mcp_servers"] = names
    with pytest.raises(ValueError):
        CodexJudgeSettings("fixture-model", "0.153.4", names)
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(payload)
    schema = CodexNativeJudgeParameters.model_json_schema()
    assert list(Draft202012Validator(schema).iter_errors({**payload, "disabled_mcp_servers": list(names)}))


def test_native_schema_is_not_a_portable_core_contract() -> None:
    """Provider-specific settings are accepted by their integration model only."""
    with pytest.raises(ContractError) as raised:
        SchemaRegistry().load("codex-native-judge-parameters.v1")
    assert raised.value.code == "unknown_schema"


def test_mcp_override_limits_preserve_boundary_keys_and_reject_typed_forgery() -> None:
    """Maximum supported overrides round-trip, while forged instances revalidate."""
    names = tuple(f"server{index:02d}" + "x" * 56 for index in range(64))
    settings = CodexJudgeSettings("fixture-model", "0.153.4", names)
    parameters = settings.calibration_parameters()
    assert parameters.disabled_mcp_servers == names
    schema = CodexNativeJudgeParameters.model_json_schema()
    Draft202012Validator(schema).validate(json.loads(parameters.model_dump_json()))
    forged = CodexNativeJudgeParameters.model_construct(
        **{**settings.public_settings(), "disabled_mcp_servers": (*names, "extra")}
    )
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(forged)


def test_native_requested_settings_round_trip_and_existing_exports() -> None:
    """The packaged provider schema and integration model share a generated contract."""
    parameters = CodexJudgeSettings("fixture-model", "0.153.4", ("docs",)).calibration_parameters()
    payload = json.loads(parameters.model_dump_json())
    schema = json.loads(
        files("skills_sdk.schemas").joinpath("codex-native-judge-parameters.v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    assert CodexNativeJudgeParameters.model_validate(payload) == parameters
    assert len(parameters.settings_sha256()) == 64
    assert PluginQualityRequest is not None and PluginQualityResult is not None


def test_public_native_tags_remain_valid_and_forged_paths_fail_revalidation() -> None:
    """Path rejection must preserve public provider/model names and distrust typed forgery."""
    payload = CodexJudgeSettings("fixture-model", "0.153.4", ()).public_settings()
    payload["model"] = "provider/public-model"
    assert CodexNativeJudgeParameters.model_validate(payload).model == "provider/public-model"
    forged = CodexNativeJudgeParameters.model_construct(**{**payload, "model": "/absolute/local-model"})
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(forged)


def test_mcp_names_preserve_raw_binding_and_reject_forged_whitespace() -> None:
    """Accepted names bind unchanged; typed forgery must not hide normalization."""
    payload = CodexJudgeSettings("fixture-model", "0.153.4", ("docs", "search_api-v2")).public_settings()
    parameters = CodexNativeJudgeParameters.model_validate(payload)
    assert parameters.disabled_mcp_servers == ("docs", "search_api-v2")
    assert (
        parameters.settings_sha256()
        == CodexJudgeSettings("fixture-model", "0.153.4", parameters.disabled_mcp_servers)
        .calibration_parameters()
        .settings_sha256()
    )
    forged = CodexNativeJudgeParameters.model_construct(**{**payload, "disabled_mcp_servers": (" docs ",)})
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(forged)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", 0),
        ("trial_count", True),
        ("trial_count", 2),
        ("shell_tool", 0),
        ("apps", True),
        ("plugins", True),
        ("ephemeral", 1),
        ("timeout_seconds", True),
        ("timeout_seconds", 301),
        ("sandbox", "workspace-write"),
        ("disabled_mcp_servers", ["docs", "docs"]),
        ("disabled_mcp_servers", ["docs.enabled=true"]),
        ("disabled_mcp_servers", ["café"]),
        ("disabled_mcp_servers", ["文档"]),
        ("disabled_mcp_servers", [" docs "]),
        ("disabled_mcp_servers", ["\tdocs"]),
        ("disabled_mcp_servers", ["docs\n"]),
        ("model", "/absolute/local-model"),
        ("cli_version", "/absolute/version"),
        ("model", "C:\\local\\model"),
        ("model", "~/local-model"),
        ("model", "café"),
        ("model", "m" * 129),
        ("model", " model "),
        ("cli_version", " version "),
        ("cli_version", "v" * 129),
        ("schema_version", "codex-native-judge-parameters/v2"),
    ],
)
def test_invalid_native_settings_rejected_by_integration_model(field: str, value: object) -> None:
    """Semantic MCP/identity checks complement the structural packaged schema."""
    payload = CodexJudgeSettings("fixture-model", "0.153.4", ()).public_settings()
    payload[field] = value
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(payload)
