"""Bound matched inputs before coercion, using canonical SDK model members."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar, Literal, Self, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ModelWrapValidatorHandler, model_validator
from pydantic_core import TzInfo

from skills_sdk.models.inventory import _ContractModel
from skills_sdk.models.packaging import PackageFileRole
from skills_sdk.models.validation import ValidationSeverity


def _canonical_models() -> tuple[type[BaseModel], ...]:
    """Resolve the fixed graph after model imports, without caller registration."""
    from skills_sdk.models.coverage import ClaimCoverage, CoverageClaim, CoverageGap, ScenarioCoveragePlan
    from skills_sdk.models.evaluation import ScorerProfile
    from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2, ScenarioCaseResultV2, ScenarioCaseV2, ScenarioSetV2
    from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt
    from skills_sdk.models.matched_comparison import (
        MatchedCaseBinding,
        MatchedComparisonPlan,
        MatchedComparisonRubric,
        MatchedDimensionJudgment,
        MatchedLaneSpec,
        MatchedPairAssessment,
        MatchedRubricDimension,
        MatchedVariantJudgment,
    )
    from skills_sdk.models.matched_execution import MatchedExecutedPair, MatchedExecutionReceipt
    from skills_sdk.models.matched_feedback import (
        MatchedCloudRegressionReceipt,
        MatchedRegressionAssignment,
        MatchedRegressionReceipt,
    )
    from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt, MatchedCloudHandoff
    from skills_sdk.models.matched_plugin_calibration import (
        MatchedCalibrationTarget,
        MatchedVariantCalibrationBundle,
    )
    from skills_sdk.models.matched_plugin_scope import MatchedPluginCaseScope, MatchedPluginScope
    from skills_sdk.models.matched_policy import (
        MatchedCaseSummary,
        MatchedLaneSummary,
        MatchedRunBudget,
        MatchedSelectionPolicy,
    )
    from skills_sdk.models.observed_calibration import (
        CalibrationJudgeVerdict,
        HeldOutCalibrationProbe,
        ObservedCalibrationPlan,
        ObservedCalibrationProbeResult,
        ObservedCalibrationReceipt,
    )
    from skills_sdk.models.package import PackageCandidateIdentity, SkillIdentity
    from skills_sdk.models.packaging import PackageManifestFile, PackageReceiptBlocker
    from skills_sdk.models.plugin import (
        PluginCapturedFile,
        PluginPackageValidation,
        PluginSkillBinding,
        PluginValidationPolicy,
        PortablePluginManifest,
    )
    from skills_sdk.models.provider import ProviderIdentityV2
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
    from skills_sdk.models.provider_execution import ProviderExecutionBlocker, ProviderExecutionRequest
    from skills_sdk.models.safety import PackageSafetyBlocker
    from skills_sdk.models.scorer_quality import ScorerCalibrationAppliedPolicy, ScorerJudgeParameters
    from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
    from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation

    return (
        ScorerProfile,
        ClaimCoverage,
        CoverageClaim,
        CoverageGap,
        ScenarioCoveragePlan,
        EvaluationReceiptV2,
        ScenarioCaseResultV2,
        ScenarioCaseV2,
        ScenarioSetV2,
        MatchedCalibrationReceipt,
        MatchedCaseBinding,
        MatchedComparisonPlan,
        MatchedComparisonRubric,
        MatchedDimensionJudgment,
        MatchedLaneSpec,
        MatchedPairAssessment,
        MatchedRubricDimension,
        MatchedVariantJudgment,
        MatchedExecutedPair,
        MatchedExecutionReceipt,
        MatchedCloudRegressionReceipt,
        MatchedRegressionAssignment,
        MatchedRegressionReceipt,
        MatchedCloudExecutionReceipt,
        MatchedCloudHandoff,
        MatchedCalibrationTarget,
        MatchedVariantCalibrationBundle,
        MatchedPluginCaseScope,
        MatchedPluginScope,
        MatchedCaseSummary,
        MatchedLaneSummary,
        MatchedRunBudget,
        MatchedSelectionPolicy,
        CalibrationJudgeVerdict,
        HeldOutCalibrationProbe,
        ObservedCalibrationPlan,
        ObservedCalibrationProbeResult,
        ObservedCalibrationReceipt,
        PackageCandidateIdentity,
        PluginCapturedFile,
        PluginPackageValidation,
        PluginSkillBinding,
        PluginValidationPolicy,
        PortablePluginManifest,
        SkillIdentity,
        PackageManifestFile,
        PackageReceiptBlocker,
        ProviderIdentityV2,
        TextProviderAdapterDescriptor,
        ProviderExecutionBlocker,
        ProviderExecutionRequest,
        PackageSafetyBlocker,
        ScorerCalibrationAppliedPolicy,
        ScorerJudgeParameters,
        SelectedCaseJudgeEvidence,
        SkillPackageFinding,
        SkillPackageValidation,
    )


def _canonical_matched_input(value: object, *, work_limit: int = 4096) -> object:
    """Copy only bounded canonical members; never invoke a caller serializer."""
    allowed = _canonical_models()
    boolean_fields = {
        name
        for model in allowed
        for name, field in model.model_fields.items()
        if field.annotation is bool
        or (get_origin(field.annotation) is Literal and all(type(item) is bool for item in get_args(field.annotation)))
    }
    active: set[int] = set()
    remaining = work_limit

    def visit(item: object, depth: int) -> object:
        nonlocal remaining
        kind = type(item)
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("matched input exceeds its nesting or work boundary")
        if item is None or any(kind is scalar for scalar in (str, bool, int, float)):
            return item
        if type(item) is datetime:
            if type(item.tzinfo) not in (type(None), timezone, TzInfo):
                raise ValueError("matched timestamp requires a canonical fixed timezone")
            return datetime.isoformat(item)
        if kind is PackageFileRole or kind is ValidationSeverity:
            return item.value
        if not any(kind is canonical for canonical in (*allowed, dict, list, tuple)):
            raise ValueError("matched input requires canonical dictionary mappings, SDK models, containers and scalars")
        identity = id(item)
        if identity in active:
            raise ValueError("matched input contains a cycle")
        active.add(identity)
        try:
            if any(kind is model for model in allowed):
                fields, extras = item.__dict__, item.__pydantic_extra__
                if type(fields) is not dict or (extras is not None and type(extras) is not dict):
                    raise ValueError("matched model storage requires canonical dictionaries")
                if len(fields) > remaining or any(type(key) is not str for key in fields):
                    raise ValueError("matched model storage requires bounded string dictionary keys")
                if any(key not in type(item).model_fields for key in fields) or extras:
                    raise ValueError("copied matched models contain unknown fields")
                return visit(fields, depth + 1)
            if len(item) > remaining:
                raise ValueError("matched input exceeds its work boundary")
            if kind is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError("matched input requires string dictionary keys")
                if any(key in boolean_fields and type(member) is not bool for key, member in item.items()):
                    raise ValueError("matched Boolean fields require exact Boolean values")
                for key in ("package_id", "source_revision", "content_sha256", "code"):
                    if key in item and (type(item[key]) is not str or item[key] != item[key].strip()):
                        raise ValueError("matched identity and finding codes require canonical unpadded strings")
                return {key: visit(member, depth + 1) for key, member in item.items()}
            return [visit(member, depth + 1) for member in item]
        finally:
            active.remove(identity)

    return visit(value, 0)


class _MatchedContractModel(_ContractModel):
    """Revalidate matched inputs without changing observed-calibration contracts."""

    model_config = ConfigDict(revalidate_instances="always")
    _ingress_work_limit: ClassVar[int] = 4096

    @model_validator(mode="wrap")
    @classmethod
    def canonical_members(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        """Retain raw scalar types and reject custom models before Pydantic."""
        return handler(_canonical_matched_input(value, work_limit=cls._ingress_work_limit))
