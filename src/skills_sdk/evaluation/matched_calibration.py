"""Execute dimensional held-out calibration through existing guarded callbacks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput
from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution, execute_scorer_calibration
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt, _dimension_digest, _dimension_score
from skills_sdk.models.matched_comparison import MatchedComparisonRubric, MatchedVariantJudgment
from skills_sdk.models.observed_calibration import CalibrationJudgeVerdict, ObservedCalibrationPlan
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.models.scorer_quality import ScorerJudgeParameters


@dataclass(frozen=True, slots=True)
class DimensionalJudgeInput:
    """Actual provider output plus frozen rubric; held-out labels are never passed."""

    selected: SelectedCaseJudgeInput
    rubric: MatchedComparisonRubric


class DimensionalJudgeAdapter(Protocol):
    identity: ProviderIdentityV2
    parameters: ScorerJudgeParameters

    async def judge(self, inputs: DimensionalJudgeInput) -> object: ...

    async def cleanup(self) -> None: ...


class _DimensionalCalibrationJudge:
    def __init__(self, delegate: DimensionalJudgeAdapter, rubric: MatchedComparisonRubric) -> None:
        self.delegate = delegate
        self.rubric = rubric
        self.judgments: list[MatchedVariantJudgment] = []
        self.invocations = 0

    @property
    def identity(self) -> ProviderIdentityV2:
        return self.delegate.identity

    @property
    def parameters(self) -> ScorerJudgeParameters:
        return self.delegate.parameters

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        rubric = MatchedComparisonRubric.model_validate(self.rubric)
        callback = self.delegate.judge
        if not callable(callback):
            raise ValueError("dimensional judge callback is unavailable")
        self.invocations += 1
        raw = await callback(DimensionalJudgeInput(inputs, rubric))
        judgment = MatchedVariantJudgment.model_validate(raw)
        if MatchedComparisonRubric.model_validate(self.rubric) != rubric:
            raise ValueError("dimensional calibration rubric changed during invocation")
        score = _dimension_score(rubric, judgment)
        digest = _dimension_digest(rubric, judgment)
        references = tuple(
            reference for reference in judgment.evidence.evidence_refs if not reference.startswith("judge-results/")
        )
        judgment = MatchedVariantJudgment.model_validate(
            judgment.model_copy(
                update={
                    "evidence": judgment.evidence.model_copy(
                        update={
                            "judge_result_sha256": digest,
                            "evidence_refs": (*references, f"judge-results/{digest}"),
                        }
                    )
                }
            )
        )
        self.judgments.append(judgment)
        return CalibrationJudgeVerdict(evidence=judgment.evidence, score=score)

    async def cleanup(self) -> None:
        await self.delegate.cleanup()


async def execute_matched_calibration(
    plan: object, rubric: object, executions: tuple[CalibrationProbeExecution, ...]
) -> MatchedCalibrationReceipt:
    """Observe dimensional callbacks and retain recomputable calibration evidence."""
    try:
        parsed = ObservedCalibrationPlan.model_validate(plan)
        scoring = MatchedComparisonRubric.model_validate(rubric)
        if type(executions) is not tuple or any(type(item) is not CalibrationProbeExecution for item in executions):
            raise ValueError("dimensional calibration requires a bounded explicit batch")
        wrappers = tuple(_DimensionalCalibrationJudge(item.judge, scoring) for item in executions)
        batch = tuple(replace(item, judge=wrapper) for item, wrapper in zip(executions, wrappers, strict=True))
    except (TypeError, ValueError):
        return MatchedCalibrationReceipt(
            status="blocked",
            blocker=PackageSafetyBlocker(
                code="invalid_matched_calibration", message="Matched calibration requires bound dimensional inputs."
            ),
        )
    observed = await execute_scorer_calibration(parsed, batch)
    retained = tuple(judgment for wrapper in wrappers for judgment in wrapper.judgments)[: len(observed.results)]
    return MatchedCalibrationReceipt(
        rubric=scoring, calibration=observed, judgments=retained, status=observed.status, blocker=observed.blocker
    )
