"""Loaded-case integrity and judge schema parity regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _evidence, _prepared_request, _skill

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.selected_case import execute_selected_case, load_selected_case
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


@pytest.mark.parametrize("field", ["output_sha256", "assertion_contract_sha256", "judge_result_sha256"])
def test_judge_top_level_newline_digest_fields_match_schema(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[field] += "\n"

    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize("identity", ["provider", "judge"])
@pytest.mark.parametrize(
    "field", ["provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest"]
)
def test_judge_provider_newline_fields_match_schema(tmp_path: Path, identity: str, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload[identity][field] += "\n"

    with pytest.raises(ValueError):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_mutually_consistent_weakened_definition_cannot_replace_loaded_case(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    weakened_semantic = definition.semantic_assertions[1:]
    case = definition.scenario_set.cases[0].model_copy(
        update={
            "expected_signals": (
                *(item[0] for item in weakened_semantic),
                *(item[0] for item in definition.deterministic_assertions),
            )
        }
    )
    forged = replace(
        definition,
        scenario_set=definition.scenario_set.model_copy(update={"cases": (case,)}),
        semantic_assertions=weakened_semantic,
    )

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(execute_selected_case(forged, request, input_payload, None, None))
