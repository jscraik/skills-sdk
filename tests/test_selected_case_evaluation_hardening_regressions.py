"""Regression coverage for selected-case evidence boundary hardening."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _safety_for, _skill

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import execute_selected_case, load_selected_case
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import ProviderAdapterFailure


def test_forged_selected_case_definition_is_rejected_before_receipt(tmp_path: Path) -> None:
    """Reject a forged selected-case definition before producing a receipt."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged_case = definition.scenario_set.cases[0].model_copy(update={"forbidden_commands": ("bearer=opaque-secret",)})
    forged_set = definition.scenario_set.model_copy(update={"cases": (forged_case,)})

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                replace(definition, scenario_set=forged_set),
                request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                None,
                None,
            )
        )


def test_selected_case_blocks_unsupported_output_contract(tmp_path: Path) -> None:
    """Block output contracts the selected-case route cannot prove."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["output_contract"] = {"required_fields": ["summary"]}
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="unsupported_output_contract"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_forged_deterministic_assertion_type_is_rejected(tmp_path: Path) -> None:
    """Reject a forged deterministic assertion type at execution."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged = replace(
        definition,
        semantic_assertions=definition.semantic_assertions[:-1],
        deterministic_assertions=((definition.semantic_assertions[-1][0], "bogus", "absent"),),
    )

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                forged, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
            )
        )


@pytest.mark.parametrize("operand", ["", "  "])
def test_forged_empty_deterministic_operand_is_rejected(tmp_path: Path, operand: str) -> None:
    """Reject operands that would trivially satisfy a contains assertion."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged = replace(
        definition,
        semantic_assertions=definition.semantic_assertions[:-1],
        deterministic_assertions=((definition.semantic_assertions[-1][0], "contains", operand),),
    )

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                forged, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
            )
        )


@pytest.mark.parametrize("terms", [("",), (" ",), ()])
def test_forged_empty_semantic_terms_are_rejected(tmp_path: Path, terms: tuple[str, ...]) -> None:
    """Recheck semantic operand shape before accepting judge evidence."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    semantic = definition.semantic_assertions[0]
    forged = replace(
        definition, semantic_assertions=((semantic[0], semantic[1], terms, ()), *definition.semantic_assertions[1:])
    )

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                forged, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
            )
        )


def test_private_case_id_is_rejected_by_loader(tmp_path: Path) -> None:
    """Keep case identity screening aligned with public judge evidence."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["id"] = "client-secret"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="client-secret", mode="release")


def test_private_requirement_id_is_rejected_by_loader(tmp_path: Path) -> None:
    """Keep requirement identity screening aligned with judge evidence."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    acceptance = payload["cases"][0]["acceptance"]
    requirement = next(item for item in acceptance if item["type"] == "semantic_requirements")
    requirement["requirements"][0]["id"] = "client-secret"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_acceptance_assertion"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_private_forbidden_command_is_rejected_by_loader(tmp_path: Path) -> None:
    """Reject projected forbidden commands that execution would not publish."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = ["client-secret"]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_request_mismatch_has_no_package_evidence_ref(tmp_path: Path) -> None:
    """A host request mismatch must not blame the package eval source."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": "different"}
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"
    assert receipt.case_results[0].blocker.evidence_refs == ()


def test_deceptive_dict_equality_cannot_bind_different_provider_input(tmp_path: Path) -> None:
    """Canonicalize the payload before comparing it with the selected prompt."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )

    class DeceptiveInput(dict[str, str]):
        def __eq__(self, other: object) -> bool:
            return True

    input_payload = DeceptiveInput(prompt="different", system="override")
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mismatch"


@pytest.mark.parametrize(
    "field", ["provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest"]
)
def test_selected_case_rejects_private_nested_provider_identity(tmp_path: Path, field: str) -> None:
    """Screen ordinary schema-valid provider identities at the selected-case boundary."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    provider = request.provider.model_copy(update={field: "client-secret"})
    forged_request = request.model_copy(update={"provider": provider})

    with pytest.raises(ContractError, match="invalid_provider_request"):
        asyncio.run(
            execute_selected_case(
                definition,
                forged_request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                None,
                None,
            )
        )

    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["judge"][field] = "client-secret"
    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_judge_provider_model_id_machine_path_matches_schema(tmp_path: Path) -> None:
    """Keep judge model and schema aligned on machine-path-shaped identities."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["judge"]["model_id"] = "org/home/user"

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_judge_candidate_mapping_cannot_spoof_public_id(tmp_path: Path) -> None:
    """Screen the validated candidate, not an untrusted mapping's get method."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    actual = {**payload["candidate"], "package_id": "ghp_secret"}

    class SpoofedCandidate(Mapping[str, object]):
        def __iter__(self) -> Iterator[str]:
            return iter(actual)

        def __len__(self) -> int:
            return len(actual)

        def __getitem__(self, key: str) -> object:
            return actual[key]

        def get(self, key: str, default: object = None) -> object:
            return "simplify" if key == "package_id" else actual.get(key, default)

    payload["candidate"] = SpoofedCandidate()

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)


@pytest.mark.parametrize("container", [set, iter])
def test_judge_assertion_id_iterables_cannot_publish_private_values(
    tmp_path: Path, container: Callable[[list[str]], object]
) -> None:
    """Recheck every assertion ID after Pydantic normalizes iterable inputs."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["satisfied_assertion_ids"] = container(["ghp_secret"])

    with pytest.raises(ValueError, match="normalized public strings"):
        SelectedCaseJudgeEvidence.model_validate(payload)


@pytest.mark.parametrize("field", ["source_revision", "content_sha256"])
def test_judge_candidate_newline_digest_fields_match_schema(tmp_path: Path, field: str) -> None:
    """Reject final-newline candidate bindings in both model and schema."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    payload = _evidence(definition, request, "reviewed").model_dump(mode="json")
    payload["candidate"][field] += "\n"

    with pytest.raises(ValueError, match="normalized"):
        SelectedCaseJudgeEvidence.model_validate(payload)
    schema = SchemaRegistry().load("selected-case-judge-evidence.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_forged_scorer_threshold_cannot_turn_failed_case_into_pass(tmp_path: Path) -> None:
    """Prevent a forged scorer threshold from turning failure into success."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed"
    evidence = _evidence(definition, request, output).model_copy(update={"satisfied_assertion_ids": ()})
    adapter = _adapter(request, output)

    valid_receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            adapter,
            evidence,
        )
    )
    assert valid_receipt.status == "fail"

    forged = replace(definition, scorer=definition.scorer.model_copy(update={"pass_threshold": 0.0}))
    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                forged,
                request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                adapter,
                evidence,
            )
        )


def test_private_failure_evidence_ref_returns_redacted_blocker(tmp_path: Path) -> None:
    """Redact private evidence references from provider failure blockers."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)

    class FailingAdapter:
        descriptor = _adapter(request, "reviewed").descriptor

        async def complete(self, request: object, input_payload: object) -> None:
            """Raise a provider failure containing a private evidence reference."""
            raise ProviderAdapterFailure(
                code="rate_limited", category="provider", retryable=True, evidence_refs=("evidence/client_secret.json",)
            )

        async def cleanup(self) -> None:
            """Complete the adapter protocol's no-op cleanup."""
            return None

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            FailingAdapter(),
            _evidence(definition, request, "reviewed"),
        )
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "private_provider_evidence_ref"
    assert receipt.case_results[0].blocker.evidence_refs == ()
    assert "client_secret" not in receipt.model_dump_json()


@pytest.mark.parametrize("field", ["scenario_set_id", "case_id"])
def test_forged_definition_identity_is_rejected_before_receipt(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    if field == "scenario_set_id":
        scenario_set = definition.scenario_set.model_copy(update={field: "ghp_secret"})
    else:
        case = definition.scenario_set.cases[0].model_copy(update={field: "ghp_secret"})
        scenario_set = definition.scenario_set.model_copy(update={"cases": (case,)})

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                replace(definition, scenario_set=scenario_set),
                request,
                SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
                None,
                None,
            )
        )


@pytest.mark.parametrize("field", ["provider", "judge"])
def test_forged_nested_provider_identity_is_rejected(tmp_path: Path, field: str) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    request = _prepared_request(definition, {"prompt": definition.scenario_set.cases[0].prompt})
    evidence = _evidence(definition, request, "reviewed")
    forged_provider = evidence.provider.model_copy(update={"adapter_id": "ghp_secret"})
    payload = evidence.model_dump(mode="json")
    payload[field] = forged_provider

    with pytest.raises(ValueError, match="credential-shaped"):
        SelectedCaseJudgeEvidence.model_validate(payload)


def test_loader_rejects_candidate_incompatible_with_judge_contract(tmp_path: Path) -> None:
    package = _skill(tmp_path / "client-secret")
    skill_file = package / "SKILL.md"
    skill_file.write_text(skill_file.read_text(encoding="utf-8").replace("simplify", "client-secret"), encoding="utf-8")
    evals = package / "references" / "evals.yaml"
    evals.write_text(evals.read_text(encoding="utf-8").replace("simplify", "client-secret"), encoding="utf-8")

    with pytest.raises(ContractError, match="candidate package id must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_private_deterministic_operand_remains_usable_but_unpublished(tmp_path: Path) -> None:
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"].append({"type": "must_not", "value": "password="})
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    definition = load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    output = "reviewed"

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "pass"
    assert "password=" not in receipt.model_dump_json()


def test_forged_duplicate_projected_signal_ids_are_rejected(tmp_path: Path) -> None:
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    duplicate = definition.semantic_assertions[0]
    semantic = (*definition.semantic_assertions, duplicate)
    case = definition.scenario_set.cases[0].model_copy(
        update={"expected_signals": (*definition.scenario_set.cases[0].expected_signals, duplicate[0])}
    )
    scenario_set = definition.scenario_set.model_copy(update={"cases": (case,)})
    forged = replace(definition, scenario_set=scenario_set, semantic_assertions=semantic)

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case(
                forged, request, SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)), None, None
            )
        )
