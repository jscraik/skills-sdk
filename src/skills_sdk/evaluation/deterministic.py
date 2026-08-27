"""Deterministic evaluation over externally produced scenario observations."""

from __future__ import annotations

from collections.abc import Iterable

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.evaluation import (
    EvaluationReceipt,
    ScenarioCase,
    ScenarioCaseResult,
    ScenarioObservation,
    ScenarioSet,
    ScorerProfile,
)
from skills_sdk.models.packaging import PackageReceiptBlocker


def _receipt_id(
    scenario_set: ScenarioSet,
    scorer: ScorerProfile,
    case_results: tuple[ScenarioCaseResult, ...],
    status: str,
    blocker: PackageReceiptBlocker | None = None,
    completed_calibration_probe_ids: tuple[str, ...] = (),
) -> str:
    payload = {
        "candidate": scenario_set.candidate.model_dump(mode="json"),
        "scenario_set_id": scenario_set.scenario_set_id,
        "scorer": scorer.model_dump(mode="json"),
        "status": status,
        "case_results": [result.model_dump(mode="json") for result in case_results],
        "blocker": blocker.model_dump(mode="json") if blocker is not None else None,
        "completed_calibration_probe_ids": sorted(completed_calibration_probe_ids),
    }
    return f"eval-{canonical_json_sha256(payload)[:24]}"


def _blocker(code: str, message: str, evidence_refs: tuple[str, ...] = ()) -> PackageReceiptBlocker:
    return PackageReceiptBlocker(code=code, message=message, evidence_refs=evidence_refs)


def _blocked_receipt(
    scenario_set: ScenarioSet,
    scorer: ScorerProfile,
    blocker: PackageReceiptBlocker,
    *,
    case_results: tuple[ScenarioCaseResult, ...] = (),
    completed_calibration_probe_ids: tuple[str, ...] = (),
) -> EvaluationReceipt:
    return EvaluationReceipt(
        receipt_id=_receipt_id(
            scenario_set,
            scorer,
            case_results,
            "blocked",
            blocker,
            completed_calibration_probe_ids,
        ),
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        scorer=scorer,
        status="blocked",
        case_results=case_results,
        completed_calibration_probe_ids=completed_calibration_probe_ids,
        blocker=blocker,
    )


def _evaluate_case(case: ScenarioCase, observation: ScenarioObservation) -> ScenarioCaseResult:
    if observation.status == "blocked":
        if observation.blocker is None:
            raise ValueError("blocked observation must contain a blocker")
        return ScenarioCaseResult(
            candidate=observation.candidate,
            scenario_set_id=observation.scenario_set_id,
            case_id=case.case_id,
            status="blocked",
            evidence_refs=observation.evidence_refs,
            runner_id=observation.runner_id,
            runner_version_or_digest=observation.runner_version_or_digest,
            blocker=observation.blocker,
        )
    if case.oracle != "expected_signal":
        return ScenarioCaseResult(
            candidate=observation.candidate,
            scenario_set_id=observation.scenario_set_id,
            case_id=case.case_id,
            status="blocked",
            evidence_refs=observation.evidence_refs,
            runner_id=observation.runner_id,
            runner_version_or_digest=observation.runner_version_or_digest,
            blocker=_blocker(
                "unsupported_oracle",
                f"scenario-set/v1 does not define deterministic {case.oracle} expectations",
                observation.evidence_refs,
            ),
        )
    observed_signals = set(observation.observed_signals)
    missing_signals = tuple(signal for signal in case.expected_signals if signal not in observed_signals)
    forbidden = set(case.forbidden_commands)
    forbidden_observed = tuple(command for command in observation.observed_commands if command in forbidden)
    status = "fail" if missing_signals or forbidden_observed else "pass"
    if observation.output_sha256 is None:
        raise ValueError("completed observation must contain output_sha256")
    return ScenarioCaseResult(
        candidate=observation.candidate,
        scenario_set_id=observation.scenario_set_id,
        case_id=case.case_id,
        status=status,
        missing_signals=missing_signals,
        forbidden_commands_observed=forbidden_observed,
        evidence_refs=observation.evidence_refs,
        observation_sha256=observation.output_sha256,
        runner_id=observation.runner_id,
        runner_version_or_digest=observation.runner_version_or_digest,
    )


def evaluate_scenario_set(
    scenario_set: ScenarioSet,
    observations: Iterable[ScenarioObservation],
    *,
    scorer: ScorerProfile,
    completed_calibration_probe_ids: Iterable[str] = (),
) -> EvaluationReceipt:
    """Evaluate observations without executing prompts, providers, or package code."""

    supplied_probes = tuple(completed_calibration_probe_ids)
    if scorer.candidate != scenario_set.candidate:
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("scorer_candidate_mismatch", "scorer and scenario set must bind the same candidate"),
        )
    if scorer.scorer_type != "deterministic":
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("provider_adapter_required", "the local evaluator accepts deterministic scorers only"),
        )
    if any(not isinstance(probe, str) or not probe.strip() for probe in supplied_probes):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("invalid_calibration_probe", "completed calibration probe ids must be non-empty text"),
        )
    if len(supplied_probes) != len(set(supplied_probes)):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("duplicate_calibration_probe", "completed calibration probe ids must be unique"),
        )
    supplied_probe_set = set(supplied_probes)
    declared_probe_set = set(scorer.calibration_probe_ids)
    if supplied_probe_set - declared_probe_set:
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("unknown_calibration_probe", "completed probes must be declared by the scorer profile"),
        )
    completed_probes = tuple(probe for probe in scorer.calibration_probe_ids if probe in supplied_probe_set)
    if scorer.calibration_required and supplied_probe_set != declared_probe_set:
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("calibration_incomplete", "completed calibration probes must match the scorer profile"),
            completed_calibration_probe_ids=completed_probes,
        )

    observation_list = tuple(observations)
    observation_ids = tuple(item.case_id for item in observation_list)
    if len(observation_ids) != len(set(observation_ids)):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("duplicate_observation", "scenario observations must have unique case ids"),
            completed_calibration_probe_ids=completed_probes,
        )
    expected_ids = tuple(case.case_id for case in scenario_set.cases)
    if set(observation_ids) != set(expected_ids):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("observation_set_mismatch", "observations must cover exactly the scenario set cases"),
            completed_calibration_probe_ids=completed_probes,
        )
    if any(
        item.candidate != scenario_set.candidate or item.scenario_set_id != scenario_set.scenario_set_id
        for item in observation_list
    ):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("observation_identity_mismatch", "observations must bind the same candidate and scenario set"),
            completed_calibration_probe_ids=completed_probes,
        )

    by_case_id = {item.case_id: item for item in observation_list}
    results = tuple(_evaluate_case(case, by_case_id[case.case_id]) for case in scenario_set.cases)
    if any(result.status == "blocked" for result in results):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("scenario_blocked", "one or more scenarios could not be evaluated deterministically"),
            case_results=results,
            completed_calibration_probe_ids=completed_probes,
        )
    passed = sum(result.status == "pass" for result in results)
    score = passed / len(results)
    status = "pass" if score >= scorer.pass_threshold else "fail"
    return EvaluationReceipt(
        receipt_id=_receipt_id(
            scenario_set,
            scorer,
            results,
            status,
            completed_calibration_probe_ids=completed_probes,
        ),
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        scorer=scorer,
        status=status,
        score=score,
        case_results=results,
        completed_calibration_probe_ids=completed_probes,
    )


__all__ = ["evaluate_scenario_set"]
