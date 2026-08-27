from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import evaluate_scenario_set
from skills_sdk.models.evaluation import (
    EvaluationReceipt,
    ScenarioCase,
    ScenarioObservation,
    ScenarioSet,
    ScorerProfile,
)
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker


def _candidate(*, digest: str = "a" * 64) -> PackageCandidateIdentity:
    return PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256=digest,
    )


def _scenario_set(*, oracle: str = "expected_signal") -> ScenarioSet:
    return ScenarioSet(
        candidate=_candidate(),
        scenario_set_id="release-1",
        release=True,
        cases=(
            ScenarioCase(
                case_id="happy",
                category="happy",
                prompt="Exercise the supported path.",
                expected_signals=("selected", "validated"),
                forbidden_commands=("rm -rf",),
                oracle=oracle,
            ),
            ScenarioCase(
                case_id="regression",
                category="regression",
                prompt="Exercise the repaired path.",
                expected_signals=("preserved",),
                oracle="expected_signal",
            ),
        ),
    )


def _scorer(*, candidate: PackageCandidateIdentity | None = None) -> ScorerProfile:
    return ScorerProfile(
        candidate=candidate or _candidate(),
        scorer_id="deterministic-v1",
        scorer_type="deterministic",
        version_or_digest="v1",
        pass_threshold=1.0,
        deterministic_checks_first=True,
        calibration_required=True,
        calibration_probe_ids=("positive", "negative"),
    )


def _observations(scenario_set: ScenarioSet) -> tuple[ScenarioObservation, ...]:
    return (
        ScenarioObservation(
            candidate=scenario_set.candidate,
            scenario_set_id=scenario_set.scenario_set_id,
            case_id="happy",
            status="completed",
            observed_signals=("selected", "validated"),
            evidence_refs=("evidence/happy.json",),
            output_sha256="b" * 64,
            runner_id="local-runner",
            runner_version_or_digest="v1",
        ),
        ScenarioObservation(
            candidate=scenario_set.candidate,
            scenario_set_id=scenario_set.scenario_set_id,
            case_id="regression",
            status="completed",
            observed_signals=("preserved",),
            evidence_refs=("evidence/regression.json",),
            output_sha256="c" * 64,
            runner_id="local-runner",
            runner_version_or_digest="v1",
        ),
    )


def _schema_errors(name: str, payload: object) -> list[object]:
    return list(Draft202012Validator(SchemaRegistry().load(name)).iter_errors(payload))


def test_evaluator_emits_deterministic_candidate_bound_receipt() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    repeated = evaluate_scenario_set(
        scenario_set,
        reversed(_observations(scenario_set)),
        scorer=_scorer(),
        completed_calibration_probe_ids=("negative", "positive"),
    )

    assert receipt.status == "pass"
    assert receipt.score == 1.0
    assert [result.case_id for result in receipt.case_results] == ["happy", "regression"]
    assert repeated.receipt_id == receipt.receipt_id
    SchemaRegistry().validate("evaluation-receipt.v1", receipt.model_dump(mode="json"))


def test_missing_signal_and_forbidden_command_fail_without_mutation() -> None:
    scenario_set = _scenario_set()
    observations = list(_observations(scenario_set))
    observations[0] = observations[0].model_copy(
        update={"observed_signals": ("selected",), "observed_commands": ("rm -rf",)}
    )

    receipt = evaluate_scenario_set(
        scenario_set,
        observations,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert receipt.status == "fail"
    assert receipt.score == 0.5
    assert receipt.mutation_performed is False
    assert receipt.case_results[0].missing_signals == ("validated",)
    assert receipt.case_results[0].forbidden_commands_observed == ("rm -rf",)


@pytest.mark.parametrize(
    ("observations", "probe_ids", "code"),
    [
        (None, ("positive",), "calibration_incomplete"),
        ((), ("positive", "negative"), "observation_set_mismatch"),
    ],
)
def test_incomplete_inputs_emit_typed_blockers(
    observations: tuple[ScenarioObservation, ...] | None,
    probe_ids: tuple[str, ...],
    code: str,
) -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set) if observations is None else observations,
        scorer=_scorer(),
        completed_calibration_probe_ids=probe_ids,
    )

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == code
    assert receipt.score is None


def test_unsupported_oracle_is_blocked_instead_of_guessed() -> None:
    scenario_set = _scenario_set(oracle="structured")
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "unsupported_oracle"


def test_blocked_observation_preserves_external_blocker() -> None:
    scenario_set = _scenario_set()
    observations = list(_observations(scenario_set))
    observations[0] = ScenarioObservation(
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        case_id="happy",
        status="blocked",
        runner_id="local-runner",
        runner_version_or_digest="v1",
        blocker=PackageReceiptBlocker(code="runner_unavailable", message="runner unavailable"),
    )
    receipt = evaluate_scenario_set(
        scenario_set,
        observations,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker == observations[0].blocker


def test_observation_rejects_completed_claims_when_blocked() -> None:
    with pytest.raises(ValidationError, match="cannot claim completed output"):
        ScenarioObservation(
            candidate=_candidate(),
            scenario_set_id="release-1",
            case_id="happy",
            status="blocked",
            observed_signals=("selected",),
            runner_id="local-runner",
            runner_version_or_digest="v1",
            blocker=PackageReceiptBlocker(code="runner_unavailable", message="runner unavailable"),
        )


def test_receipt_rejects_candidate_mismatch() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    payload = receipt.model_dump()
    payload["candidate"] = _candidate(digest="d" * 64)

    with pytest.raises(ValidationError, match="same candidate"):
        EvaluationReceipt.model_validate(payload)


def test_scorer_candidate_mismatch_returns_typed_blocker() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(candidate=_candidate(digest="d" * 64)),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "scorer_candidate_mismatch"


def test_duplicate_completed_calibration_probes_return_typed_blocker() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative", "negative"),
    )

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "duplicate_calibration_probe"


def test_unknown_completed_calibration_probe_returns_typed_blocker() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative", "unknown"),
    )

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "unknown_calibration_probe"


def test_receipt_identity_includes_blocker_and_calibration_evidence() -> None:
    scenario_set = _scenario_set()
    calibration = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive",),
    )
    missing_observation = evaluate_scenario_set(
        scenario_set,
        (),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert calibration.receipt_id != missing_observation.receipt_id


def test_completed_receipt_identity_includes_optional_calibration_evidence() -> None:
    scenario_set = _scenario_set()
    scorer = _scorer().model_copy(update={"calibration_required": False})

    without_probe = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=scorer,
    )
    with_probe = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=scorer,
        completed_calibration_probe_ids=("positive",),
    )

    assert without_probe.status == "pass"
    assert with_probe.status == "pass"
    assert without_probe.receipt_id != with_probe.receipt_id


def test_non_deterministic_scorer_requires_an_adapter() -> None:
    scenario_set = _scenario_set()
    scorer = _scorer().model_copy(update={"scorer_type": "hybrid"})
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=scorer,
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "provider_adapter_required"


def test_observation_digest_is_bound_into_result_and_receipt_identity() -> None:
    scenario_set = _scenario_set()
    original = _observations(scenario_set)
    changed = list(original)
    changed[0] = original[0].model_copy(update={"output_sha256": "d" * 64})

    first = evaluate_scenario_set(
        scenario_set,
        original,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    second = evaluate_scenario_set(
        scenario_set,
        changed,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert first.case_results[0].observation_sha256 == "b" * 64
    assert first.receipt_id != second.receipt_id


def test_runner_identity_is_bound_into_result_and_receipt_identity() -> None:
    scenario_set = _scenario_set()
    original = _observations(scenario_set)
    changed = list(original)
    changed[0] = original[0].model_copy(
        update={"runner_id": "replacement-runner", "runner_version_or_digest": "v2"}
    )

    first = evaluate_scenario_set(
        scenario_set,
        original,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    second = evaluate_scenario_set(
        scenario_set,
        changed,
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert first.case_results[0].runner_id == "local-runner"
    assert first.case_results[0].runner_version_or_digest == "v1"
    assert first.receipt_id != second.receipt_id


def test_receipt_identity_includes_complete_scorer_policy() -> None:
    scenario_set = _scenario_set()
    baseline = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    changed_policy = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer().model_copy(update={"pass_threshold": 0.5}),
        completed_calibration_probe_ids=("positive", "negative"),
    )

    assert baseline.receipt_id != changed_policy.receipt_id


def test_generated_observation_schema_rejects_blocked_completed_claims() -> None:
    payload = _observations(_scenario_set())[0].model_dump(mode="json")
    payload.update(
        {
            "status": "blocked",
            "blocker": {"code": "runner_unavailable", "message": "runner unavailable", "evidence_refs": []},
        }
    )

    assert _schema_errors("scenario-observation.v1", payload)


def test_generated_result_schema_rejects_pass_with_failures() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    payload = receipt.case_results[0].model_dump(mode="json")
    payload["missing_signals"] = ["fabricated"]

    assert _schema_errors("scenario-case-result.v1", payload)


def test_generated_receipt_schema_rejects_completed_receipt_without_score() -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    payload = receipt.model_dump(mode="json")
    payload["score"] = None

    assert _schema_errors("evaluation-receipt.v1", payload)


@pytest.mark.parametrize(
    "probe_ids",
    [
        ("positive", "fabricated"),
        ("negative", "positive"),
        ("positive",),
    ],
)
def test_receipt_rejects_noncanonical_calibration_evidence(probe_ids: tuple[str, ...]) -> None:
    scenario_set = _scenario_set()
    receipt = evaluate_scenario_set(
        scenario_set,
        _observations(scenario_set),
        scorer=_scorer(),
        completed_calibration_probe_ids=("positive", "negative"),
    )
    payload = receipt.model_dump()
    payload["completed_calibration_probe_ids"] = probe_ids

    with pytest.raises(ValidationError, match="completed calibration probes"):
        EvaluationReceipt.model_validate(payload)
