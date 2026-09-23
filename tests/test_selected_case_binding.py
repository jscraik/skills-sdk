"""Loaded-case integrity and judge schema parity regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _adapter, _case, _evidence, _prepared_request, _skill

from skills_sdk.core.digests import canonical_json_sha256
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


def test_loader_rejects_private_composed_scenario_set_id(tmp_path: Path) -> None:
    package = _skill(tmp_path / "client")
    skill_file = package / "SKILL.md"
    skill_file.write_text(skill_file.read_text(encoding="utf-8").replace("simplify", "client"), encoding="utf-8")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["skill_name"] = "client"
    payload["cases"] = [_case("secret", ["release"])]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="secret", mode="release")


def test_nested_string_subclass_cannot_spoof_selected_prompt(tmp_path: Path) -> None:
    class DeceptiveText(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    request = request.model_copy(update={"input_sha256": canonical_json_sha256({"prompt": "different"})})

    receipt = asyncio.run(
        execute_selected_case(definition, request, {"prompt": DeceptiveText("different")}, None, None)
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


@pytest.mark.parametrize("prompt_size,accepted", [(100_000, True), (270_000, False)])
def test_selected_case_prompt_obeys_provider_input_limit(tmp_path: Path, prompt_size: int, accepted: bool) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["prompt"] = "x" * prompt_size
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    if accepted:
        assert load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    else:
        with pytest.raises(ContractError, match="invalid_selected_case"):
            load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_adapter_string_subclass_cannot_spoof_deterministic_signal(tmp_path: Path) -> None:
    class DeceptiveOutput(str):
        def casefold(self) -> str:
            return "reviewed needle"

    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"].append({"type": "contains", "value": "needle"})
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = DeceptiveOutput("reviewed")

    receipt = asyncio.run(
        execute_selected_case(
            definition, request, input_payload, _adapter(request, output), _evidence(definition, request, output)
        )
    )

    assert receipt.status == "fail"


def test_loaded_definition_rechecks_package_source_at_execution(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"] = payload["cases"][0]["acceptance"][1:]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(execute_selected_case(definition, request, input_payload, None, None))


def test_mode_string_subclass_cannot_select_release_only_case_as_smoke(tmp_path: Path) -> None:
    class DeceptiveMode(str):
        def __eq__(self, other: object) -> bool:
            return other == "release" or str.__eq__(self, other)

        __hash__ = str.__hash__

    package = _skill(tmp_path / "simplify")
    with pytest.raises(ContractError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode=DeceptiveMode("smoke"))

    selected = load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="release")
    assert selected._mode == "release"


def test_case_id_string_subclass_is_frozen_before_selection(tmp_path: Path) -> None:
    class DeceptiveCaseId(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    package = _skill(tmp_path / "simplify")
    selected = load_selected_case(
        package, source_revision=REVISION, case_id=DeceptiveCaseId("happy-diff"), mode="release"
    )
    assert selected.scenario_set.cases[0].case_id == "happy-diff"
    assert type(selected.scenario_set.cases[0].case_id) is str


def test_raw_judge_mapping_is_validated_at_execution(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed"
    artifact = _evidence(definition, request, output).model_dump(mode="json")

    receipt = asyncio.run(
        execute_selected_case(definition, request, input_payload, _adapter(request, output), artifact)
    )

    assert receipt.status == "pass"


@pytest.mark.parametrize("invalid", [123, {"schema_version": "selected-case-judge-evidence/v1"}])
def test_malformed_judge_artifacts_return_typed_blocker(tmp_path: Path, invalid: object) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(definition, request, input_payload, _adapter(request, "reviewed"), invalid)
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_judge_evidence"
