"""Portable lifecycle contracts and tooling for Agent Skills packages."""

from skills_sdk.distribution import prepare_private_registry_candidate
from skills_sdk.evaluation import evaluate_scenario_set, evaluate_scenario_set_v2
from skills_sdk.lifecycle import plan_runtime_install
from skills_sdk.models import (
    ActivationObservation,
    DiscoveryObservation,
    EvaluationReceipt,
    EvaluationReceiptV2,
    InstallationResult,
    InstallPlan,
    MantraAssessment,
    MantraStatus,
    MutationRaceEvidence,
    PackageInventory,
    PackageInventoryRecord,
    PackageInventoryRecordV2,
    PackageInventoryV2,
    PackageSafetyBlocker,
    PackageSafetyEvidenceReceipt,
    PackageSafetyEvidenceReference,
    PackageSafetyFinding,
    PackageSafetyReviewer,
    ProviderCallPublicResult,
    ProviderCostObservation,
    ProviderExecutionBlocker,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderIdentity,
    ProviderIdentityV2,
    ProviderUsageMetadata,
    PrSweepDirtyState,
    PrSweepFinding,
    PrSweepValidationResult,
    RecommendedMechanism,
    RegistryIdentity,
    RegistryPreparationBlocker,
    RegistryPreparationReceipt,
    RegistryPreparationRequest,
    RegistryPreparationWarning,
    RiskClassification,
    RollbackJournal,
    RollbackJournalEntry,
    RollbackOutcome,
    RuntimeAdapterIdentity,
    RuntimeEvidenceBlocker,
    RuntimeFile,
    RuntimeLock,
    RuntimeLockEntry,
    RuntimeOutcomeReceipt,
    RuntimeTarget,
    ScenarioCaseResult,
    ScenarioCaseResultV2,
    ScenarioCaseV2,
    ScenarioObservation,
    ScenarioObservationV2,
    ScenarioQualityAppliedPolicy,
    ScenarioQualityAppliedPolicyV2,
    ScenarioQualityFinding,
    ScenarioQualityReceipt,
    ScenarioQualityReceiptV2,
    ScenarioSet,
    ScenarioSetV2,
    ScorerCalibrationAppliedPolicy,
    ScorerCalibrationMetrics,
    ScorerCalibrationRates,
    ScorerCalibrationReceipt,
    ScorerJudgeParameters,
    ScorerProfile,
    ScorerQualityReceipt,
    SecurityScreeningResult,
    SelectedCaseJudgeEvidence,
    TextProviderAdapterDescriptor,
    ValueDecision,
    ValueDecisionV2,
)
from skills_sdk.providers import execute_provider_call

__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    """Load optional public evaluation exports only when requested."""
    if name in {"validate_pr_sweep_dirty_closeout", "validate_recurring_findings"}:
        from skills_sdk.validation.pr_sweep import validate_pr_sweep_dirty_closeout, validate_recurring_findings

        return {
            "validate_pr_sweep_dirty_closeout": validate_pr_sweep_dirty_closeout,
            "validate_recurring_findings": validate_recurring_findings,
        }[name]
    if name in {"ScenarioQualityPolicy", "assess_scenario_quality"}:
        from skills_sdk.evaluation.quality import ScenarioQualityPolicy, assess_scenario_quality

        return {
            "ScenarioQualityPolicy": ScenarioQualityPolicy,
            "assess_scenario_quality": assess_scenario_quality,
        }[name]
    if name in {"assess_scorer_quality", "assess_scorer_calibration"}:
        from skills_sdk.evaluation import assess_scorer_calibration, assess_scorer_quality

        return {
            "assess_scorer_quality": assess_scorer_quality,
            "assess_scorer_calibration": assess_scorer_calibration,
        }[name]
    if name in {
        "SelectedCaseJudgeAdapter",
        "SelectedCaseJudgeInput",
        "execute_selected_case_with_judge",
    }:
        from skills_sdk.evaluation.live_selected_case import (
            SelectedCaseJudgeAdapter,
            SelectedCaseJudgeInput,
            execute_selected_case_with_judge,
        )

        return {
            "SelectedCaseJudgeAdapter": SelectedCaseJudgeAdapter,
            "SelectedCaseJudgeInput": SelectedCaseJudgeInput,
            "execute_selected_case_with_judge": execute_selected_case_with_judge,
        }[name]
    if name in {
        "SelectedCaseDefinition",
        "SuppliedTextProviderAdapter",
        "execute_selected_case",
        "load_selected_case",
    }:
        from skills_sdk.evaluation.selected_case import (
            SelectedCaseDefinition,
            SuppliedTextProviderAdapter,
            execute_selected_case,
            load_selected_case,
        )

        return {
            "SelectedCaseDefinition": SelectedCaseDefinition,
            "SuppliedTextProviderAdapter": SuppliedTextProviderAdapter,
            "execute_selected_case": execute_selected_case,
            "load_selected_case": load_selected_case,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActivationObservation",
    "DiscoveryObservation",
    "EvaluationReceipt",
    "EvaluationReceiptV2",
    "InstallPlan",
    "InstallationResult",
    "MantraAssessment",
    "MantraStatus",
    "MutationRaceEvidence",
    "PackageInventory",
    "PackageInventoryRecord",
    "PackageInventoryRecordV2",
    "PackageInventoryV2",
    "PackageSafetyBlocker",
    "PackageSafetyEvidenceReceipt",
    "PackageSafetyEvidenceReference",
    "PackageSafetyFinding",
    "PackageSafetyReviewer",
    "PrSweepDirtyState",
    "PrSweepFinding",
    "PrSweepValidationResult",
    "ProviderCallPublicResult",
    "ProviderCostObservation",
    "ProviderExecutionBlocker",
    "ProviderExecutionError",
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "ProviderIdentity",
    "ProviderIdentityV2",
    "ProviderUsageMetadata",
    "RecommendedMechanism",
    "RegistryIdentity",
    "RegistryPreparationBlocker",
    "RegistryPreparationReceipt",
    "RegistryPreparationRequest",
    "RegistryPreparationWarning",
    "RiskClassification",
    "RollbackJournal",
    "RollbackJournalEntry",
    "RollbackOutcome",
    "RuntimeAdapterIdentity",
    "RuntimeEvidenceBlocker",
    "RuntimeFile",
    "RuntimeLock",
    "RuntimeLockEntry",
    "RuntimeOutcomeReceipt",
    "RuntimeTarget",
    "ScenarioCaseResult",
    "ScenarioCaseResultV2",
    "ScenarioCaseV2",
    "ScenarioObservation",
    "ScenarioObservationV2",
    "ScenarioQualityAppliedPolicy",
    "ScenarioQualityAppliedPolicyV2",
    "ScenarioQualityFinding",
    "ScenarioQualityPolicy",
    "ScenarioQualityReceipt",
    "ScenarioQualityReceiptV2",
    "ScenarioSet",
    "ScenarioSetV2",
    "ScorerCalibrationAppliedPolicy",
    "ScorerCalibrationMetrics",
    "ScorerCalibrationRates",
    "ScorerCalibrationReceipt",
    "ScorerJudgeParameters",
    "ScorerProfile",
    "ScorerQualityReceipt",
    "SecurityScreeningResult",
    "SelectedCaseDefinition",
    "SelectedCaseJudgeAdapter",
    "SelectedCaseJudgeEvidence",
    "SelectedCaseJudgeInput",
    "SuppliedTextProviderAdapter",
    "TextProviderAdapterDescriptor",
    "ValueDecision",
    "ValueDecisionV2",
    "__version__",
    "assess_scenario_quality",
    "assess_scorer_calibration",
    "assess_scorer_quality",
    "evaluate_scenario_set",
    "evaluate_scenario_set_v2",
    "execute_provider_call",
    "execute_selected_case",
    "execute_selected_case_with_judge",
    "load_selected_case",
    "plan_runtime_install",
    "prepare_private_registry_candidate",
    "validate_pr_sweep_dirty_closeout",
    "validate_recurring_findings",
]
