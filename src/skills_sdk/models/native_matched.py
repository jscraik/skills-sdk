"""Additive native dimensional calibration and supplied matched-assessment contracts."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt, _dimension_digest
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedLaneSpec, MatchedPairAssessment
from skills_sdk.models.matched_plugin_calibration import (
    MatchedCalibrationTarget,
    MatchedVariantCalibrationBundle,
    _bind_plugin_calibration_bundle,
)
from skills_sdk.models.native_judge import CodexNativeJudgeParameters
from skills_sdk.models.observed_calibration import NativeCalibrationReceipt
from skills_sdk.models.provider_execution import _identity_is_public


class NativeMatchedCalibrationReceipt(MatchedCalibrationReceipt):
    """Retain actual dimensional judgments behind a native scalar observation."""

    schema_version: Literal["native-matched-calibration/v1"] = "native-matched-calibration/v1"
    calibration: NativeCalibrationReceipt | None = None
    _native_ingress: ClassVar[bool] = True

    @model_validator(mode="after")
    def native_rubric_is_bound(self) -> Self:
        if (
            self.calibration is not None
            and self.calibration.plan is not None
            and (
                self.rubric is None
                or self.calibration.plan.rubric_sha256 != canonical_json_sha256(self.rubric.model_dump(mode="json"))
            )
        ):
            raise ValueError("native dimensional calibration must bind the complete frozen rubric")
        return self


class NativeMatchedCalibrationTarget(MatchedCalibrationTarget):
    """One native child/assertion/scorer target with complete dimensional proof."""

    receipt: NativeMatchedCalibrationReceipt
    _native_ingress: ClassVar[bool] = True


class NativeMatchedVariantCalibrationBundle(MatchedVariantCalibrationBundle):
    """Exact native child targets with one shared judge, rubric and settings."""

    schema_version: Literal["native-matched-variant-calibration/v1"] = "native-matched-variant-calibration/v1"
    judge_parameters: CodexNativeJudgeParameters
    targets: tuple[NativeMatchedCalibrationTarget, ...] = Field(min_length=1, max_length=10)
    _native_ingress: ClassVar[bool] = True


class NativeMatchedLaneSpec(MatchedLaneSpec):
    """Numeric generation settings and native settings for each fresh judge call."""

    judge_parameters: CodexNativeJudgeParameters
    _native_ingress: ClassVar[bool] = True

    @model_validator(mode="after")
    def settings_bind_models(self) -> Self:
        if any(not _identity_is_public(name) for name in self.judge_parameters.disabled_mcp_servers):
            raise ValueError("native matched MCP names must be public identities")
        if (
            self.generator_parameters.model != self.generator.model_id
            or self.judge_parameters.model != self.judge.model_id
        ):
            raise ValueError("native matched settings must bind their actual models")
        # Native trial_count describes one fresh judge capability, not the
        # matched plan's minimum repeated-case coverage or an execution claim.
        return self


class NativeMatchedComparisonPlan(MatchedComparisonPlan):
    """Freeze the same ten-case policy with a separate native judge lane."""

    schema_version: Literal["native-matched-comparison-plan/v1"] = "native-matched-comparison-plan/v1"
    lanes: tuple[NativeMatchedLaneSpec, ...] = Field(min_length=2, max_length=2)
    _native_ingress: ClassVar[bool] = True

    @model_validator(mode="after")
    def native_lane_identity_is_bound(self) -> Self:
        rubric_digest = canonical_json_sha256(self.rubric.model_dump(mode="json"))
        for lane in self.lanes:
            judge, parameters = lane.judge, lane.judge_parameters
            expected = canonical_json_sha256(
                {
                    "settings": parameters.model_dump(mode="json", exclude={"schema_version"}),
                    "rubric_sha256": rubric_digest,
                }
            )
            if (
                judge.provider_id != "codex"
                or judge.provider_kind != "agent"
                or judge.adapter_id != "codex-cli-judge"
                or judge.version_or_digest != parameters.cli_version
                or judge.adapter_version_or_digest != expected
            ):
                raise ValueError("native matched lane requires its complete rubric and settings identity")
        return self


def _require_native_variant_calibration(
    plan: NativeMatchedComparisonPlan, lane: NativeMatchedLaneSpec, variant: str, raw: object
) -> NativeMatchedVariantCalibrationBundle:
    """Join the exact native targets before accepting supplied pair evidence."""
    if variant not in {"baseline", "candidate"}:
        raise ValueError("native matched calibration variant is undeclared")
    bundle = NativeMatchedVariantCalibrationBundle.model_validate(raw)
    targets = tuple(
        (scope.driver_skill_path, binding.assertion_contract_sha256, getattr(scope, variant + "_scorer"))
        for scope, binding in zip(plan.plugin_scope.cases, plan.case_bindings, strict=True)
    )
    _bind_plugin_calibration_bundle(
        bundle,
        getattr(plan.plugin_scope, variant),
        plan.rubric,
        (lane, getattr(lane, variant + "_calibration_sha256")),
        targets,
    )
    return bundle


class NativeMatchedPairAssessment(MatchedPairAssessment):
    """Supplied pair assessment retaining both exact native calibration joins."""

    schema_version: Literal["native-matched-pair-assessment/v1"] = "native-matched-pair-assessment/v1"
    plan: NativeMatchedComparisonPlan | None = None
    calibrations: tuple[NativeMatchedVariantCalibrationBundle, ...] = Field(default=(), max_length=2)

    _ingress_work_limit: ClassVar[int] = 4194304
    _native_ingress: ClassVar[bool] = True

    @model_validator(mode="after")
    def retained_native_joins_are_exact(self) -> Self:
        if self.status == "blocked":
            if self.calibrations:
                raise ValueError("blocked native assessment cannot retain completed calibration joins")
            return self
        if self.plan is None or len(self.calibrations) != 2:
            raise ValueError("native assessment requires both complete calibration bundles")
        lane = next(item for item in self.plan.lanes if item.lane == self.lane)
        for variant, bundle in zip(("baseline", "candidate"), self.calibrations, strict=True):
            _require_native_variant_calibration(self.plan, lane, variant, bundle)
        for judgment in (self.baseline, self.candidate):
            digest = _dimension_digest(self.plan.rubric, judgment)
            references = tuple(ref for ref in judgment.evidence.evidence_refs if ref.startswith("judge-results/"))
            if judgment.evidence.judge_result_sha256 != digest or references != (f"judge-results/{digest}",):
                raise ValueError("native assessment requires complete bound dimensional result evidence")
            if any(ref.startswith("judge-results/") for row in judgment.dimensions for ref in row.evidence_refs):
                raise ValueError("native assessment dimensions require underlying evidence")
        return self
