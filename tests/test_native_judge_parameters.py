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


def test_native_schema_is_not_a_portable_core_contract() -> None:
    """Provider-specific settings are accepted by their integration model only."""
    with pytest.raises(ContractError) as raised:
        SchemaRegistry().load("codex-native-judge-parameters.v1")
    assert raised.value.code == "unknown_schema"


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
        ("model", "/absolute/local-model"),
        ("cli_version", "/absolute/version"),
        ("model", "C:\\local\\model"),
        ("model", "~/local-model"),
        ("schema_version", "codex-native-judge-parameters/v2"),
    ],
)
def test_invalid_native_settings_rejected_by_integration_model(field: str, value: object) -> None:
    """Semantic MCP/identity checks complement the structural packaged schema."""
    payload = CodexJudgeSettings("fixture-model", "0.153.4", ()).public_settings()
    payload[field] = value
    with pytest.raises(ValidationError):
        CodexNativeJudgeParameters.model_validate(payload)
