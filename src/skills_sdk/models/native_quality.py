"""Additive native calibration joins for read-only local quality."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from skills_sdk.models.inventory import NonEmptyText
from skills_sdk.models.native_judge import CodexNativeJudgeParameters
from skills_sdk.models.observed_calibration import (
    NativeCalibrationPlan,
    NativeCalibrationReceipt,
    _audit_copied_members,
)
from skills_sdk.models.quality_workflow import (
    _QUALITY_TYPES,
    LocalCheckRequestV2,
    LocalCheckResultV2,
    LocalQualityStage,
    QualityStageReceipt,
)
from skills_sdk.models.scorer_quality import ScorerCalibrationMetrics, ScorerCalibrationReceipt, ScorerQualityReceipt


def _native_quality_input(value: object) -> object:
    """Reject native subclasses before shared quality normalization loses their class."""
    canonical = (
        CodexNativeJudgeParameters,
        NativeCalibrationPlan,
        NativeCalibrationReceipt,
        NativeScorerQualityReceipt,
        NativeScorerCalibrationReceipt,
        NativeLocalCheckRequest,
        NativeLocalQualityStage,
        NativeLocalCheckResult,
    )
    pending, seen = [value], set()
    while pending:
        if len(seen) > 131072:
            raise ValueError("native quality input exceeds its work boundary")
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, canonical) and type(item) not in canonical:
            raise ValueError("native quality requires canonical SDK native models")
        if isinstance(item, (NativeCalibrationPlan, NativeCalibrationReceipt)):
            _audit_copied_members(item)
        if isinstance(item, BaseModel):
            pending.append(item.__dict__)
        elif isinstance(item, Mapping):
            for name in (
                "mutation_performed",
                "network_used",
                "execution_performed",
                "release_ready",
                "execution_authorized",
                "evaluation_executed",
                "promotion_authorized",
                "external_authenticity_verified",
            ):
                if name in item and item[name] is not False:
                    raise ValueError("native quality proof flags require literal false")
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return LocalCheckRequestV2.inputs_are_revalidated(value)


def native_calibration_matrix(observation: NativeCalibrationReceipt) -> ScorerCalibrationMetrics:
    """Recompute counts from retained ordered native outcomes."""
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    keys = {("pass", "pass"): "tp", ("fail", "fail"): "tn", ("fail", "pass"): "fp", ("pass", "fail"): "fn"}
    for result in observation.results:
        counts[keys[(result.expected_label, result.predicted_label)]] += 1
    return ScorerCalibrationMetrics(**counts)


class NativeScorerQualityReceipt(ScorerQualityReceipt):
    """Native declaration assessment; no numeric temperature is invented."""

    schema_version: Literal["native-scorer-quality/v1"] = "native-scorer-quality/v1"
    model_config = ConfigDict(revalidate_instances="always")
    parameters: CodexNativeJudgeParameters | None = None
    calibration_probe_ids: tuple[NonEmptyText, ...] = ()
    calibration_expected_labels: tuple[Literal["pass", "fail"], ...] = ()
    scorer_type: Literal["deterministic", "llm_judge", "hybrid", "external"] | None = None

    @model_validator(mode="before")
    @classmethod
    def revalidate_native_members(cls, value: object) -> object:
        return _native_quality_input(value)

    @model_validator(mode="after")
    def native_declaration_is_complete(self) -> Self:
        if self.status == "pass" and (
            self.parameters is None
            or self.scorer_type is None
            or len(self.calibration_probe_ids) != self.calibration_probe_count
            or len(set(self.calibration_probe_ids)) != self.calibration_probe_count
            or len(self.calibration_expected_labels) != self.calibration_probe_count
        ):
            raise ValueError("native scorer declaration requires exact unique probe IDs and native settings")
        return self


def require_native_declaration(plan: NativeCalibrationPlan, declaration: ScorerQualityReceipt) -> None:
    """Require the candidate's declared scorer, settings and ordered held-out IDs."""
    if (
        not isinstance(declaration, NativeScorerQualityReceipt)
        or declaration.status != "pass"
        or declaration.candidate != plan.candidate
        or declaration.parameters != plan.parameters
        or declaration.scorer_id != plan.scorer.scorer_id
        or declaration.scorer_version_or_digest != plan.scorer.version_or_digest
        or declaration.pass_threshold != plan.policy.threshold
        or declaration.calibration_probe_ids != plan.scorer.calibration_probe_ids
        or tuple(probe.expected_label for probe in plan.probes) != declaration.calibration_expected_labels
        or declaration.scorer_type != plan.scorer.scorer_type
        or not plan.scorer.deterministic_checks_first
        or len(plan.probes) < 6
    ):
        raise ValueError("native observation differs from declared scorer or coverage")


class NativeScorerCalibrationReceipt(ScorerCalibrationReceipt):
    """Retain a supplied native observation alongside its recomputed summary."""

    schema_version: Literal["native-scorer-calibration/v1"] = "native-scorer-calibration/v1"
    model_config = ConfigDict(revalidate_instances="always")
    parameters: CodexNativeJudgeParameters | None = None
    observation: NativeCalibrationReceipt | None = None

    @model_validator(mode="before")
    @classmethod
    def revalidate_native_members(cls, value: object) -> object:
        return _native_quality_input(value)

    @model_validator(mode="after")
    def summary_binds_observation(self) -> Self:
        if self.status != "pass":
            return self
        observed = self.observation
        if observed is None or observed.status != "pass" or observed.plan is None or len(observed.plan.probes) < 6:
            raise ValueError("native quality requires a complete native observation")
        plan = observed.plan
        if (
            self.candidate != plan.candidate
            or self.parameters != plan.parameters
            or self.scorer_id != plan.scorer.scorer_id
            or self.scorer_version_or_digest != plan.scorer.version_or_digest
            or self.prompt_version != plan.assertion_contract_sha256
            or self.effective_policy != plan.policy
            or self.example_count != len(observed.results)
            or self.confusion_matrix != native_calibration_matrix(observed)
        ):
            raise ValueError("native summary must retain exact observation bindings")
        return self


class NativeLocalCheckRequest(LocalCheckRequestV2):
    """Freeze the complete expected calibration before accepting supplied evidence."""

    schema_version: Literal["native-local-check-request/v1"]
    calibration_plan: NativeCalibrationPlan
    calibration: NativeCalibrationReceipt | None = None

    @model_validator(mode="before")
    @classmethod
    def native_members_are_canonical(cls, value: object) -> object:
        return _native_quality_input(value)

    @model_validator(mode="after")
    def calibration_binds_candidate(self) -> Self:
        if self.calibration_plan.candidate != self.candidate:
            raise ValueError("native calibration plan must bind the selected child")
        return self


_NATIVE_TYPES = {
    **_QUALITY_TYPES,
    "scorer-quality": (NativeScorerQualityReceipt,),
    "scorer-calibration": (NativeScorerCalibrationReceipt,),
}


class NativeLocalQualityStage(LocalQualityStage):
    """Use native receipt families only at their explicit quality stages."""

    receipt: QualityStageReceipt | NativeScorerQualityReceipt | NativeScorerCalibrationReceipt
    _stage_types: ClassVar[dict] = _NATIVE_TYPES

    @model_validator(mode="before")
    @classmethod
    def stage_evidence_is_revalidated(cls, value: object) -> object:
        return _native_quality_input(value)


class NativeLocalCheckResult(LocalCheckResultV2):
    """Native local quality is supplied evidence, never live authentication."""

    schema_version: Literal["native-local-check/v1"] = "native-local-check/v1"
    request: NativeLocalCheckRequest | None
    stages: tuple[NativeLocalQualityStage, ...] = ()
    _stage_types: ClassVar[dict] = _NATIVE_TYPES

    @model_validator(mode="before")
    @classmethod
    def evidence_is_revalidated(cls, value: object) -> object:
        return super().evidence_is_revalidated(_native_quality_input(value))

    @model_validator(mode="after")
    def calibration_matches_frozen_plan(self) -> Self:
        if self.request is not None:
            for stage in self.stages:
                if isinstance(stage.receipt, NativeScorerCalibrationReceipt):
                    observed = stage.receipt.observation
                    if observed != self.request.calibration:
                        raise ValueError("native quality requires its exact selected calibration observation")
                    if stage.passed():
                        if observed is None or observed.plan != self.request.calibration_plan:
                            raise ValueError("native quality requires its exact frozen calibration plan")
                        declared = next(item.receipt for item in self.stages if item.name == "scorer-quality")
                        require_native_declaration(self.request.calibration_plan, declared)
        return self
