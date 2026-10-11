"""Small grouped imports for generated schema model families."""

from __future__ import annotations

from typing import Any

from skills_sdk.models.content_review import ContentReviewAssessment, ContentReviewExecutionResult, ContentReviewResult
from skills_sdk.models.coverage import ScenarioCoveragePlan, ScenarioCoverageResult
from skills_sdk.models.evaluation import (
    EvaluationReceipt,
    ScenarioCaseResult,
    ScenarioObservation,
    ScenarioSet,
    ScorerProfile,
)
from skills_sdk.models.evaluation_v2 import (
    EvaluationReceiptV2,
    ScenarioCaseResultV2,
    ScenarioObservationV2,
    ScenarioSetV2,
)
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
from skills_sdk.models.lifecycle import InstallPlan, RuntimeLock
from skills_sdk.models.local_check import LocalCheckResult
from skills_sdk.models.maintenance import EntrypointMaintenanceResult, RuntimeCopyComparison
from skills_sdk.models.matched_calibration import MatchedCalibrationReceipt
from skills_sdk.models.matched_comparison import MatchedComparisonPlan, MatchedPairAssessment
from skills_sdk.models.matched_execution import MatchedExecutionReceipt
from skills_sdk.models.matched_feedback import MatchedCloudRegressionReceipt, MatchedRegressionReceipt
from skills_sdk.models.matched_handoff import MatchedCloudExecutionReceipt, MatchedCloudHandoff
from skills_sdk.models.matched_plugin_calibration import MatchedVariantCalibrationBundle
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan, ObservedCalibrationReceipt
from skills_sdk.models.packaging import (
    PackageArchiveVerificationReceipt,
    PackageHardeningReceipt,
    PackageManifest,
    PackageReceipt,
    PackageReceiptV2,
)
from skills_sdk.models.plugin import PluginPackageValidation
from skills_sdk.models.plugin_safety import PluginPreExecutionSafetyEvidence
from skills_sdk.models.pre_execution_safety import PreExecutionSafetyEvidence
from skills_sdk.models.provider_call import ProviderCallPublicResult, TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderExecutionResult
from skills_sdk.models.quality_workflow import LocalCheckRequestV2, LocalCheckResultV2
from skills_sdk.models.runtime_evidence import (
    ActivationObservation,
    DiscoveryObservation,
    InstallationResult,
    RollbackJournal,
    RollbackOutcome,
    RuntimeOutcomeReceipt,
)
from skills_sdk.models.scenario_quality import ScenarioQualityReceipt, ScenarioQualityReceiptV2
from skills_sdk.models.scorer_quality import ScorerCalibrationReceipt, ScorerQualityReceipt
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


def evaluation_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return stable evaluation schema registrations in generation order."""

    return (
        (ScenarioSet, "scenario-set.v1.schema.json"),
        (ScorerProfile, "scorer-profile.v1.schema.json"),
        (ScenarioObservation, "scenario-observation.v1.schema.json"),
        (ScenarioCaseResult, "scenario-case-result.v1.schema.json"),
        (EvaluationReceipt, "evaluation-receipt.v1.schema.json"),
        (ScenarioSetV2, "scenario-set.v2.schema.json"),
        (ScenarioObservationV2, "scenario-observation.v2.schema.json"),
        (ScenarioCaseResultV2, "scenario-case-result.v2.schema.json"),
        (EvaluationReceiptV2, "evaluation-receipt.v2.schema.json"),
        (SelectedCaseJudgeEvidence, "selected-case-judge-evidence.v1.schema.json"),
        (ScenarioQualityReceipt, "scenario-quality.v1.schema.json"),
        (ScenarioQualityReceiptV2, "scenario-quality.v2.schema.json"),
        (ScorerQualityReceipt, "scorer-quality.v1.schema.json"),
        (ScorerCalibrationReceipt, "scorer-calibration.v1.schema.json"),
        (ObservedCalibrationPlan, "observed-calibration-plan.v1.schema.json"),
        (ObservedCalibrationReceipt, "observed-calibration.v1.schema.json"),
        (MatchedComparisonPlan, "matched-comparison-plan.v1.schema.json"),
        (MatchedPairAssessment, "matched-pair-assessment.v1.schema.json"),
        (MatchedCalibrationReceipt, "matched-calibration.v1.schema.json"),
        (MatchedVariantCalibrationBundle, "matched-variant-calibration.v1.schema.json"),
        (MatchedExecutionReceipt, "matched-execution.v1.schema.json"),
        (MatchedCloudHandoff, "matched-cloud-handoff.v1.schema.json"),
        (MatchedCloudExecutionReceipt, "matched-cloud-execution.v1.schema.json"),
        (MatchedRegressionReceipt, "matched-regression.v1.schema.json"),
        (MatchedCloudRegressionReceipt, "matched-cloud-regression.v1.schema.json"),
        (LocalCheckResult, "local-check.v1.schema.json"),
        (LocalCheckRequestV2, "local-check-request.v2.schema.json"),
        (LocalCheckResultV2, "local-check.v2.schema.json"),
        (ScenarioCoveragePlan, "scenario-coverage-plan.v1.schema.json"),
        (ScenarioCoverageResult, "scenario-coverage.v1.schema.json"),
        (ContentReviewAssessment, "content-review-assessment.v1.schema.json"),
        (ContentReviewResult, "content-review.v1.schema.json"),
        (ContentReviewExecutionResult, "content-review-execution.v1.schema.json"),
    )


def provider_execution_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return provider execution schemas in request-before-result order."""

    return (
        (ProviderExecutionRequest, "provider-execution-request.v1.schema.json"),
        (ProviderExecutionResult, "provider-execution-result.v1.schema.json"),
        (PreExecutionSafetyEvidence, "pre-execution-safety-evidence.v1.schema.json"),
        (PluginPreExecutionSafetyEvidence, "plugin-pre-execution-safety-evidence.v1.schema.json"),
    )


def provider_call_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return additive provider-call schemas in dependency order."""

    return (
        (TextProviderAdapterDescriptor, "provider-call-adapter.v1.schema.json"),
        (ProviderCallPublicResult, "provider-call-result.v1.schema.json"),
    )


def intake_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return executable intake receipt schemas."""

    return (
        (PluginPackageValidation, "plugin-package-validation.v1.schema.json"),
        (SkillPackageIntakeContext, "skill-package-intake-context.v1.schema.json"),
        (SkillPackageIntakeReceipt, "skill-package-intake.v1.schema.json"),
    )


def packaging_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return package manifest and receipt schemas in dependency order."""

    return (
        (PackageManifest, "package-manifest.v1.schema.json"),
        (PackageReceipt, "package-receipt.v1.schema.json"),
        (PackageReceiptV2, "package-receipt.v2.schema.json"),
        (PackageArchiveVerificationReceipt, "package-archive-verification.v1.schema.json"),
        (PackageHardeningReceipt, "package-hardening.v1.schema.json"),
    )


def runtime_lifecycle_schema_models() -> tuple[tuple[type[Any], str], ...]:
    """Return planning and adapter-supplied runtime evidence schemas."""

    return (
        (RuntimeLock, "runtime-lock.v1.schema.json"),
        (InstallPlan, "install-plan.v1.schema.json"),
        (InstallationResult, "installation-result.v1.schema.json"),
        (RollbackJournal, "rollback-journal.v1.schema.json"),
        (RollbackOutcome, "rollback-outcome.v1.schema.json"),
        (DiscoveryObservation, "discovery-observation.v1.schema.json"),
        (ActivationObservation, "activation-observation.v1.schema.json"),
        (RuntimeOutcomeReceipt, "runtime-outcome.v1.schema.json"),
        (RuntimeCopyComparison, "runtime-copy-comparison.v1.schema.json"),
        (EntrypointMaintenanceResult, "entrypoint-maintenance-result.v1.schema.json"),
    )


__all__ = [
    "evaluation_schema_models",
    "intake_schema_models",
    "packaging_schema_models",
    "provider_call_schema_models",
    "provider_execution_schema_models",
    "runtime_lifecycle_schema_models",
]
