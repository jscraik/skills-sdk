"""Retain child-specific calibration without relabelling it as plugin proof."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.inventory import PortablePath, Sha256
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedComparisonRubric, MatchedLaneSpec
from skills_sdk.models.matched_ingress import _MatchedContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.plugin import PluginPackageValidation
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.safety import _public_text_is_redaction_safe
from skills_sdk.models.scorer_quality import ScorerJudgeParameters


class MatchedCalibrationTarget(_MatchedContractModel):
    """One observed child/assertion/scorer target, not unspecified sibling cover."""

    skill_path: PortablePath
    child_candidate: PackageCandidateIdentity
    assertion_contract_sha256: Sha256
    scorer: ScorerProfile
    receipt: MatchedCalibrationReceipt

    _ingress_work_limit: ClassVar[int] = 131072

    @field_validator("skill_path", mode="before")
    @classmethod
    def path_is_canonical(cls, value: object) -> str:
        if type(value) is not str or value != value.strip():
            raise ValueError("calibration target requires an exact unpadded child path")
        require_portable_relative_path(value)
        if not _public_text_is_redaction_safe(value):
            raise ValueError("calibration target requires a public child path")
        return value

    @model_validator(mode="after")
    def observed_target_is_exact(self) -> MatchedCalibrationTarget:
        observed = self.receipt.calibration
        if self.receipt.status != "pass" or observed is None or observed.plan is None:
            raise ValueError("calibration target requires completed observed calibration")
        plan = observed.plan
        if (
            not observed.judge_execution_performed
            or len(plan.probes) < 6
            or plan.candidate != self.child_candidate
            or self.scorer.candidate != self.child_candidate
            or plan.scorer != self.scorer
            or plan.assertion_contract_sha256 != self.assertion_contract_sha256
        ):
            raise ValueError("calibration target must retain its exact child, scorer, assertions and held-out coverage")
        return self


class MatchedVariantCalibrationBundle(_MatchedContractModel):
    """A shared judge configuration with explicit child-specific observations."""

    schema_version: Literal["matched-variant-calibration/v1"] = "matched-variant-calibration/v1"
    plugin_candidate: PackageCandidateIdentity
    mode_manifest_sha256: Sha256
    judge: ProviderIdentityV2
    judge_parameters: ScorerJudgeParameters
    rubric: MatchedComparisonRubric
    targets: tuple[MatchedCalibrationTarget, ...] = Field(min_length=1, max_length=10)
    external_authenticity_verified: Literal[False] = False
    promotion_authorized: Literal[False] = False

    _ingress_work_limit: ClassVar[int] = 1048576

    @field_validator("external_authenticity_verified", "promotion_authorized", mode="before")
    @classmethod
    def false_only(cls, value: object) -> object:
        if value is not False:
            raise ValueError("calibration bundles cannot authenticate callbacks or authorise promotion")
        return value

    @model_validator(mode="after")
    def targets_share_only_the_declared_configuration(self) -> MatchedVariantCalibrationBundle:
        keys = tuple((item.skill_path, item.assertion_contract_sha256) for item in self.targets)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("calibration targets require unique sorted child/assertion keys")
        if self.judge_parameters.model != self.judge.model_id:
            raise ValueError("calibration bundle parameters must bind the declared judge")
        for target in self.targets:
            observed = target.receipt.calibration.plan
            if (
                target.receipt.rubric != self.rubric
                or observed.judge != self.judge
                or observed.parameters != self.judge_parameters
            ):
                raise ValueError("each calibration target must retain the shared judge, settings and rubric")
        return self


def _require_plugin_calibration_bundle(
    raw: object,
    plugin: PluginPackageValidation,
    rubric: MatchedComparisonRubric,
    lane_binding: tuple[MatchedLaneSpec, str],
    targets: tuple[tuple[str, str, ScorerProfile], ...],
) -> MatchedVariantCalibrationBundle:
    """Join the complete required target set to a frozen plugin and lane digest."""
    bundle = MatchedVariantCalibrationBundle.model_validate(raw)
    lane, digest = lane_binding
    if (
        plugin.status != "pass"
        or plugin.candidate != bundle.plugin_candidate
        or plugin.mode_manifest_sha256 != bundle.mode_manifest_sha256
        or rubric != bundle.rubric
        or lane.judge != bundle.judge
        or lane.judge_parameters != bundle.judge_parameters
        or canonical_json_sha256(bundle.model_dump(mode="json")) != digest
    ):
        raise ValueError("calibration bundle differs from the frozen plugin, modes, judge or commitment")
    children = {item.path: item.validation.candidate for item in plugin.skills}
    required: dict[tuple[str, str], ScorerProfile] = {}
    for path, assertions, scorer in targets:
        key = (path, assertions)
        if path not in children or children[path] != scorer.candidate:
            raise ValueError("calibration target must bind a captured child")
        if key in required and required[key] != scorer:
            raise ValueError("one child/assertion target cannot substitute another scorer")
        required[key] = scorer
    retained = {(item.skill_path, item.assertion_contract_sha256): item for item in bundle.targets}
    if required.keys() != retained.keys() or any(retained[key].scorer != scorer for key, scorer in required.items()):
        raise ValueError("calibration bundle must cover the exact required child/assertion/scorer targets")
    return bundle


def _require_variant_calibration(
    plan: MatchedComparisonPlan, lane: MatchedLaneSpec, variant: str, raw: object
) -> MatchedVariantCalibrationBundle:
    """Require all case-driver assertion targets before accessing any host adapter."""
    if variant not in {"baseline", "candidate"}:
        raise ValueError("matched calibration variant is undeclared")
    capture = getattr(plan.plugin_scope, variant)
    targets = tuple(
        (scope.driver_skill_path, binding.assertion_contract_sha256, getattr(scope, variant + "_scorer"))
        for scope, binding in zip(plan.plugin_scope.cases, plan.case_bindings, strict=True)
    )
    return _require_plugin_calibration_bundle(
        raw, capture, plan.rubric, (lane, getattr(lane, variant + "_calibration_sha256")), targets
    )
