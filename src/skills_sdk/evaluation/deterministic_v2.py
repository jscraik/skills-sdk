"""Deterministic evaluation for additive v2 provider-bound contracts."""

from __future__ import annotations

from collections.abc import Iterable

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.evaluation_v2 import (
    EvaluationReceiptV2,
    ScenarioCaseResultV2,
    ScenarioCaseV2,
    ScenarioObservationV2,
    ScenarioSetV2,
)
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.provider import ProviderIdentity


def _blocker(code: str, message: str, evidence_refs: tuple[str, ...] = ()) -> PackageReceiptBlocker:
    return PackageReceiptBlocker(code=code, message=message, evidence_refs=evidence_refs)


def _receipt_id(
    scenario_set: ScenarioSetV2,
    scorer: ScorerProfile,
    provider: ProviderIdentity | None,
    case_results: tuple[ScenarioCaseResultV2, ...],
    status: str,
    blocker: PackageReceiptBlocker | None,
    completed_probes: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": "evaluation-receipt/v2",
        "candidate": scenario_set.candidate.model_dump(mode="json"),
        "scenario_set_id": scenario_set.scenario_set_id,
        "provider": provider.model_dump(mode="json") if provider is not None else None,
        "scorer": scorer.model_dump(mode="json"),
        "status": status,
        "case_results": [result.model_dump(mode="json") for result in case_results],
        "blocker": blocker.model_dump(mode="json") if blocker is not None else None,
        "completed_calibration_probe_ids": list(completed_probes),
    }
    return f"eval-v2-{canonical_json_sha256(payload)[:24]}"


def _blocked_receipt(
    scenario_set: ScenarioSetV2,
    scorer: ScorerProfile,
    blocker: PackageReceiptBlocker,
    *,
    provider: ProviderIdentity | None = None,
    case_results: tuple[ScenarioCaseResultV2, ...] = (),
    completed_probes: tuple[str, ...] = (),
) -> EvaluationReceiptV2:
    return EvaluationReceiptV2(
        receipt_id=_receipt_id(scenario_set, scorer, provider, case_results, "blocked", blocker, completed_probes),
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        provider=provider,
        scorer=scorer,
        status="blocked",
        case_results=case_results,
        completed_calibration_probe_ids=completed_probes,
        blocker=blocker,
    )


def _evaluate_case(case: ScenarioCaseV2, observation: ScenarioObservationV2) -> ScenarioCaseResultV2:
    common = {
        "candidate": observation.candidate,
        "scenario_set_id": observation.scenario_set_id,
        "case_id": case.case_id,
        "provider": observation.provider,
        "evidence_refs": observation.evidence_refs,
        "runner_id": observation.runner_id,
        "runner_version_or_digest": observation.runner_version_or_digest,
    }
    if observation.status == "blocked":
        return ScenarioCaseResultV2(status="blocked", blocker=observation.blocker, **common)
    if case.oracle == "structured":
        return ScenarioCaseResultV2(
            status="blocked",
            blocker=_blocker(
                "unsupported_oracle",
                "scenario-set/v2 does not define deterministic structured expectations",
                observation.evidence_refs,
            ),
            **common,
        )
    if case.oracle == "exact_match" and case.expected_output_sha256 is None:
        return ScenarioCaseResultV2(
            status="blocked",
            blocker=_blocker(
                "exact_match_digest_required",
                "exact_match evaluation requires expected_output_sha256",
                observation.evidence_refs,
            ),
            **common,
        )
    if observation.output_sha256 is None:
        raise ValueError("completed observation must contain output_sha256")
    missing = (
        tuple(signal for signal in case.expected_signals if signal not in set(observation.observed_signals))
        if case.oracle == "expected_signal"
        else ()
    )
    forbidden = tuple(command for command in observation.observed_commands if command in set(case.forbidden_commands))
    mismatch = case.oracle == "exact_match" and observation.output_sha256 != case.expected_output_sha256
    return ScenarioCaseResultV2(
        status="fail" if missing or forbidden or mismatch else "pass",
        missing_signals=missing,
        forbidden_commands_observed=forbidden,
        observation_sha256=observation.output_sha256,
        expected_output_sha256=case.expected_output_sha256,
        output_digest_mismatch=mismatch,
        **common,
    )


def evaluate_scenario_set_v2(
    scenario_set: ScenarioSetV2,
    observations: Iterable[ScenarioObservationV2],
    *,
    scorer: ScorerProfile,
    completed_calibration_probe_ids: Iterable[str] = (),
) -> EvaluationReceiptV2:
    """Evaluate v2 observations without executing providers, prompts, or package code."""

    supplied = tuple(completed_calibration_probe_ids)
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
    if any(not isinstance(probe, str) or not probe.strip() for probe in supplied):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("invalid_calibration_probe", "completed calibration probe ids must be non-empty text"),
        )
    if len(supplied) != len(set(supplied)):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("duplicate_calibration_probe", "completed calibration probe ids must be unique"),
        )
    if set(supplied) - set(scorer.calibration_probe_ids):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("unknown_calibration_probe", "completed probes must be declared by the scorer profile"),
        )
    completed = tuple(probe for probe in scorer.calibration_probe_ids if probe in set(supplied))
    if scorer.calibration_required and set(supplied) != set(scorer.calibration_probe_ids):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("calibration_incomplete", "completed calibration probes must match the scorer profile"),
            completed_probes=completed,
        )

    items = tuple(observations)
    ids = tuple(item.case_id for item in items)
    if len(ids) != len(set(ids)):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("duplicate_observation", "scenario observations must have unique case ids"),
            completed_probes=completed,
        )
    if set(ids) != {case.case_id for case in scenario_set.cases}:
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("observation_set_mismatch", "observations must cover exactly the scenario set cases"),
            completed_probes=completed,
        )
    if any(
        item.candidate != scenario_set.candidate or item.scenario_set_id != scenario_set.scenario_set_id
        for item in items
    ):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("observation_identity_mismatch", "observations must bind the same candidate and scenario set"),
            completed_probes=completed,
        )
    providers = {item.provider for item in items}
    if len(providers) != 1:
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("provider_identity_mismatch", "observations must bind exactly one provider"),
            completed_probes=completed,
        )
    provider = next(iter(providers))
    by_id = {item.case_id: item for item in items}
    results = tuple(_evaluate_case(case, by_id[case.case_id]) for case in scenario_set.cases)
    if any(result.status == "blocked" for result in results):
        return _blocked_receipt(
            scenario_set,
            scorer,
            _blocker("scenario_blocked", "one or more scenarios could not be evaluated deterministically"),
            provider=provider,
            case_results=results,
            completed_probes=completed,
        )
    score = sum(result.status == "pass" for result in results) / len(results)
    status = "pass" if score >= scorer.pass_threshold else "fail"
    return EvaluationReceiptV2(
        receipt_id=_receipt_id(scenario_set, scorer, provider, results, status, None, completed),
        candidate=scenario_set.candidate,
        scenario_set_id=scenario_set.scenario_set_id,
        provider=provider,
        scorer=scorer,
        status=status,
        score=score,
        case_results=results,
        completed_calibration_probe_ids=completed,
    )


__all__ = ["evaluate_scenario_set_v2"]
