from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk import (
    EvaluationReceiptV2,
    ProviderIdentity,
    ProviderIdentityV2,
    ScenarioCaseV2,
    ScenarioObservationV2,
    ScenarioSetV2,
    evaluate_scenario_set,
    evaluate_scenario_set_v2,
)
from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import CandidateIdentity, parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.evaluation import ScenarioCase, ScenarioObservation, ScenarioSet, ScorerProfile
from skills_sdk.models.package import PackageCandidateIdentity

V1_ARTIFACT_DIGESTS = {
    "provider-identity.v1.schema.json": "74f466710fd3a5bf041ed592383289d876b84d7ee2e6d3dd8610f9ab7d9f5c34",
    "scenario-set.v1.schema.json": "fd0f139a48dcb834c16b9d5ae51aaf693bb3687f6f90403fb6abef04b7d09a52",
    "scenario-observation.v1.schema.json": "2d4f89fbf20b031179f425c2285309e6d408b1ac31820cc35317ae69e93f3b89",
    "scenario-case-result.v1.schema.json": "3c5b1e7ed61ec1cfffc7d66cda777b0140adae027f8bc008669b8b3702ce766e",
    "evaluation-receipt.v1.schema.json": "a018d3e71cfff239038ec4cda4f03821b3fce7848f4b40c65560af74dc16ec70",
}
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"


def _candidate() -> PackageCandidateIdentity:
    return PackageCandidateIdentity(package_id="synthetic-skill", source_revision="1" * 40, content_sha256="a" * 64)


def _provider(*, model_id: str = "synthetic-model") -> ProviderIdentityV2:
    return ProviderIdentityV2(
        provider_id="codex",
        provider_kind="agent",
        model_id=model_id,
        version_or_digest="model-v1",
        adapter_id="codex-exec",
        adapter_version_or_digest="adapter-v1",
    )


def _provider_v1(*, model_id: str = "synthetic-model") -> ProviderIdentity:
    return ProviderIdentity(
        provider_id="codex",
        provider_kind="agent",
        model_id=model_id,
        version_or_digest="model-v1",
        adapter_id="codex-exec",
        adapter_version_or_digest="adapter-v1",
    )


def _scorer() -> ScorerProfile:
    return ScorerProfile(
        candidate=_candidate(),
        scorer_id="deterministic-v1",
        scorer_type="deterministic",
        version_or_digest="v1",
        pass_threshold=1.0,
        deterministic_checks_first=True,
        calibration_required=False,
    )


def _scenario_v2(*, expected_digest: str | None = "b" * 64) -> ScenarioSetV2:
    return ScenarioSetV2(
        candidate=_candidate(),
        scenario_set_id="compatibility-v2",
        release=False,
        cases=(
            ScenarioCaseV2(
                case_id="exact",
                category="boundary",
                prompt="Compare only the externally supplied output digest.",
                expected_signals=("digest supplied",),
                oracle="exact_match",
                expected_output_sha256=expected_digest,
            ),
        ),
    )


def _observations_v2(
    scenario_set: ScenarioSetV2, *, digest: str = "b" * 64, provider: ProviderIdentityV2 | None = None
) -> tuple[ScenarioObservationV2, ...]:
    return (
        ScenarioObservationV2(
            candidate=scenario_set.candidate,
            scenario_set_id=scenario_set.scenario_set_id,
            case_id="exact",
            provider=provider or _provider(),
            status="completed",
            output_sha256=digest,
            runner_id="external-runner",
            runner_version_or_digest="v1",
        ),
    )


def test_v1_generated_schema_bytes_are_unchanged() -> None:
    schema_root = SchemaRegistry().load("scenario-set.v1")["$id"]
    assert schema_root.endswith("scenario-set.v1.schema.json")
    from importlib.resources import files

    for filename, expected in V1_ARTIFACT_DIGESTS.items():
        payload = files("skills_sdk.schemas").joinpath(filename).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected


def test_v1_exact_match_semantics_remain_unsupported() -> None:
    scenario_set = ScenarioSet(
        candidate=_candidate(),
        scenario_set_id="compatibility-v1",
        release=False,
        cases=(
            ScenarioCase(
                case_id="exact",
                category="boundary",
                prompt="Retain v1 semantics.",
                expected_signals=("unchanged",),
                oracle="exact_match",
            ),
        ),
    )
    observation = ScenarioObservation(
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        case_id="exact",
        status="completed",
        output_sha256="b" * 64,
        runner_id="external-runner",
        runner_version_or_digest="v1",
    )

    receipt = evaluate_scenario_set(scenario_set, (observation,), scorer=_scorer())

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "unsupported_oracle"
    generic = parse_receipt(receipt.model_dump(mode="json"))
    assert generic.status == "blocked"
    assert generic.candidate == CandidateIdentity("synthetic-skill", "1" * 40, "a" * 64)


def test_v1_models_do_not_accept_v2_provider_or_digest_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioObservation.model_validate(
            {
                "candidate": _candidate().model_dump(mode="json"),
                "scenario_set_id": "compatibility-v1",
                "case_id": "exact",
                "provider": _provider().model_dump(mode="json"),
                "status": "completed",
                "output_sha256": "b" * 64,
                "runner_id": "runner",
                "runner_version_or_digest": "v1",
            }
        )


def test_v2_exact_match_passes_and_parses_generically() -> None:
    scenario_set = _scenario_v2()
    first = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    repeated = evaluate_scenario_set_v2(scenario_set, reversed(_observations_v2(scenario_set)), scorer=_scorer())

    assert first.status == "pass"
    assert first.case_results[0].expected_output_sha256 == "b" * 64
    assert first.case_results[0].output_digest_mismatch is False
    assert repeated.receipt_id == first.receipt_id
    SchemaRegistry().validate("evaluation-receipt.v2", first.model_dump(mode="json"))
    generic = parse_receipt(first.model_dump(mode="json"))
    assert generic.status == "pass"
    assert generic.lane == "evaluation"


def test_v2_exact_match_fails_on_digest_mismatch_without_raw_output() -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set, digest="c" * 64), scorer=_scorer())

    assert receipt.status == "fail"
    assert receipt.case_results[0].output_digest_mismatch is True
    payload = receipt.model_dump(mode="json")
    assert "raw_output" not in str(payload).lower()
    assert "output_text" not in str(payload).lower()


def test_v2_exact_match_without_expected_digest_blocks_fail_closed() -> None:
    scenario_set = _scenario_v2(expected_digest=None)
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "exact_match_digest_required"


def test_v2_provider_identity_changes_receipt_identity() -> None:
    scenario_set = _scenario_v2()
    first = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    second = evaluate_scenario_set_v2(
        scenario_set,
        _observations_v2(scenario_set, provider=_provider(model_id="replacement-model")),
        scorer=_scorer(),
    )

    assert first.receipt_id != second.receipt_id
    assert first.provider != second.provider


def test_v2_receipt_rejects_provider_result_mismatch() -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    payload = receipt.model_dump(mode="json")
    payload["provider"]["model_id"] = "replacement-model"

    with pytest.raises(ValidationError, match="same provider"):
        EvaluationReceiptV2.model_validate(payload)


def test_v2_receipt_with_results_rejects_missing_provider_in_model_and_draft_schema() -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    payload = receipt.model_dump(mode="json")
    payload.update(
        status="blocked",
        score=None,
        provider=None,
        blocker={"code": "scenario_blocked", "message": "External evaluation was blocked.", "evidence_refs": []},
    )

    with pytest.raises(ValidationError, match="with results must bind one provider"):
        EvaluationReceiptV2.model_validate(payload)
    schema = SchemaRegistry().load("evaluation-receipt.v2")
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_v2_result_model_rejects_duplicate_evidence_refs() -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    payload = receipt.case_results[0].model_dump(mode="json")
    payload["evidence_refs"] = ["evidence/result.json", "evidence/result.json"]

    with pytest.raises(ValidationError, match="evidence refs must be unique"):
        type(receipt.case_results[0]).model_validate(payload)


@pytest.mark.parametrize("model_id", ["urn:provider", "mailto:model", "hf_secretvalue", "AIzaSecretValue"])
def test_provider_v1_preserves_parent_acceptance_semantics(model_id: str) -> None:
    payload = _provider_v1(model_id=model_id).model_dump(mode="json")

    assert ProviderIdentity.model_validate(payload).model_id == model_id
    SchemaRegistry().validate("provider-identity.v1", payload)
    schema = SchemaRegistry().load("provider-identity.v1")
    assert not list(Draft202012Validator(schema).iter_errors(payload))


def test_provider_v1_preserves_parent_rejection_of_slash_model_ids() -> None:
    payload = _provider_v1().model_dump(mode="json")
    payload["model_id"] = "meta-llama/Llama-3.1-8B-Instruct"

    with pytest.raises(ValidationError):
        ProviderIdentity.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-identity.v1", payload)
    schema = SchemaRegistry().load("provider-identity.v1")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    "model_id",
    [
        "meta-llama/Llama-3.1-8B-Instruct",
        "provider/model:revision",
    ],
)
def test_provider_v2_model_and_draft_schema_accept_provider_native_model_id(model_id: str) -> None:
    payload = _provider(model_id=model_id).model_dump(mode="json")

    assert ProviderIdentityV2.model_validate(payload).model_id == payload["model_id"]
    SchemaRegistry().validate("provider-identity.v2", payload)
    schema = SchemaRegistry().load("provider-identity.v2")
    assert not list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    "model_id",
    [
        "urn:provider/model",
        "urn:provider",
        "mailto:model",
        "https://provider.example/model",
        "https:/provider.example/model",
        "file:/provider/model",
        "/model",
        "model/",
        "model//revision",
    ],
)
def test_provider_v2_model_and_draft_schema_reject_url_and_empty_model_segments(model_id: str) -> None:
    payload = _provider().model_dump(mode="json")
    payload["model_id"] = model_id

    with pytest.raises(ValidationError):
        ProviderIdentityV2.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-identity.v2", payload)
    schema = SchemaRegistry().load("provider-identity.v2")
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    ("field", "credential"),
    [
        (field, credential)
        for field in ("provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest")
        for credential in ("hf_secretvalue", "AIzaSecretValue")
    ],
)
def test_provider_v2_model_and_draft_schema_reject_credential_components(field: str, credential: str) -> None:
    payload = _provider().model_dump(mode="json")
    payload[field] = credential

    with pytest.raises(ValidationError, match="credential-shaped"):
        ProviderIdentityV2.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-identity.v2", payload)
    schema = SchemaRegistry().load("provider-identity.v2")
    assert any(error.validator == "not" for error in Draft202012Validator(schema).iter_errors(payload))


def test_provider_v2_fixtures_are_accepted_and_rejected_consistently() -> None:
    accepted = json.loads((FIXTURE_ROOT / "provider-v2-accepted.json").read_text(encoding="utf-8"))
    rejected = json.loads((FIXTURE_ROOT / "provider-v2-rejected.json").read_text(encoding="utf-8"))
    schema = SchemaRegistry().load("provider-identity.v2")

    assert ProviderIdentityV2.model_validate(accepted).model_id == "meta-llama/Llama-3.1-8B-Instruct"
    SchemaRegistry().validate("provider-identity.v2", accepted)
    assert not list(Draft202012Validator(schema).iter_errors(accepted))
    with pytest.raises(ValidationError, match="must not be a URI"):
        ProviderIdentityV2.model_validate(rejected)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("provider-identity.v2", rejected)
    assert list(Draft202012Validator(schema).iter_errors(rejected))


@pytest.mark.parametrize(
    ("schema_name", "model_name"),
    [
        ("scenario-observation.v2", "observation"),
        ("scenario-case-result.v2", "case_result"),
        ("evaluation-receipt.v2", "receipt"),
    ],
)
def test_provider_bearing_v2_contracts_reject_v1_identity(
    schema_name: str,
    model_name: str,
) -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    models = {
        "observation": _observations_v2(scenario_set)[0],
        "case_result": receipt.case_results[0],
        "receipt": receipt,
    }
    model = models[model_name]
    payload = model.model_dump(mode="json")
    payload["provider"]["schema_version"] = "provider-identity/v1"

    with pytest.raises(ValidationError):
        type(model).model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate(schema_name, payload)
    schema = SchemaRegistry().load(schema_name)
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_generic_receipt_parser_rejects_provider_v1_inside_evaluation_v2() -> None:
    scenario_set = _scenario_v2()
    receipt = evaluate_scenario_set_v2(scenario_set, _observations_v2(scenario_set), scorer=_scorer())
    payload = receipt.model_dump(mode="json")
    payload["provider"]["schema_version"] = "provider-identity/v1"

    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


@pytest.mark.parametrize(
    "schema_name",
    [
        "provider-identity.v1",
        "provider-identity.v2",
        "scenario-set.v2",
        "scenario-observation.v2",
        "scenario-case-result.v2",
        "evaluation-receipt.v2",
    ],
)
def test_v2_contract_family_is_registered(schema_name: str) -> None:
    assert SchemaRegistry().load(schema_name)["$schema"].endswith("2020-12/schema")


def test_v2_fixture_is_accepted_without_reinterpreting_rejected_v1_envelope() -> None:
    accepted = json.loads((FIXTURE_ROOT / "scenario-v2-accepted.json").read_text(encoding="utf-8"))
    rejected = json.loads((FIXTURE_ROOT / "scenario-v2-rejected.json").read_text(encoding="utf-8"))

    SchemaRegistry().validate("scenario-set.v2", accepted)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("scenario-set.v2", rejected)
