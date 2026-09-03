"""Portable, adapter-supplied runtime execution evidence contracts."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.lifecycle import (
    InstallPlan,
    RuntimeIdentifier,
    RuntimeTarget,
    lifecycle_text_is_public_safe,
)
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import BlockerCode, ReceiptId

RuntimeEvidenceIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"),
]
_RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


def _require_public_text(value: str, field: str) -> str:
    if not lifecycle_text_is_public_safe(value):
        raise ValueError(f"{field} must not contain credential-shaped or machine-path values")
    return value


def _require_public_path(value: str, field: str) -> str:
    require_portable_relative_path(value)
    return _require_public_text(value, field)


def _require_unique_paths(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must be unique")
    return tuple(_require_public_path(value, field) for value in values)


def _require_rfc3339(value: object, field: str) -> object:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be an RFC3339 string")
    return value


def _model_sha256(value: _ContractModel) -> str:
    return canonical_json_sha256(value.model_dump(mode="json"))


class RuntimeAdapterIdentity(_ContractModel):
    """Secret-free identity for an external host-runtime adapter."""

    adapter_id: RuntimeEvidenceIdentifier
    adapter_version: NonEmptyText

    @field_validator("adapter_id", "adapter_version")
    @classmethod
    def identity_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "runtime adapter identity")


class RuntimeEvidenceBlocker(_ContractModel):
    """Typed public blocker without raw logs, credentials, or host paths."""

    code: BlockerCode
    category: Literal["authorization", "policy", "adapter", "filesystem", "race", "runtime", "unknown"]
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = ()

    @field_validator("code", "message")
    @classmethod
    def public_text_must_be_safe(cls, value: str) -> str:
        return _require_public_text(value, "runtime evidence blocker")

    @field_validator("evidence_refs")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_paths(values, "runtime blocker evidence refs")


class MutationRaceEvidence(_ContractModel):
    """Digest-only observation that expected and observed host state diverged."""

    expected_lock_sha256: Sha256
    observed_lock_sha256: Sha256
    detected_at: AwareDatetime
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("detected_at", mode="before")
    @classmethod
    def detected_at_must_be_rfc3339(cls, value: object) -> object:
        return _require_rfc3339(value, "mutation race detected_at")

    @field_validator("evidence_refs")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_paths(values, "mutation race evidence refs")

    @model_validator(mode="after")
    def digests_must_record_a_race(self) -> MutationRaceEvidence:
        if self.expected_lock_sha256 == self.observed_lock_sha256:
            raise ValueError("mutation race must record distinct expected and observed lock digests")
        return self


class _CandidateBoundRuntimeEvidence(_ContractModel):
    candidate: PackageCandidateIdentity
    package_name: RuntimeIdentifier
    version: NonEmptyText
    package_digest: Sha256
    plan_id: ReceiptId
    plan_sha256: Sha256
    target: RuntimeTarget
    adapter: RuntimeAdapterIdentity
    observed_at: AwareDatetime
    evidence: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("package_name", "version", "plan_id")
    @classmethod
    def identity_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "runtime evidence identity")

    @field_validator("observed_at", mode="before")
    @classmethod
    def observed_at_must_be_rfc3339(cls, value: object) -> object:
        return _require_rfc3339(value, "runtime evidence observed_at")

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_paths(values, "runtime evidence paths")

    @model_validator(mode="after")
    def package_identity_must_match_candidate(self) -> _CandidateBoundRuntimeEvidence:
        if self.package_name != self.candidate.package_id:
            raise ValueError("runtime evidence package name must match candidate package_id")
        return self

    def _validate_plan_binding(self, plan: InstallPlan) -> None:
        plan = InstallPlan.model_validate(plan.model_dump(mode="json"))
        if plan.status != "planned" or plan.candidate is None or plan.package_digest is None:
            raise ValueError("runtime execution evidence requires a planned install plan")
        if self.plan_id != plan.plan_id or self.plan_sha256 != _model_sha256(plan):
            raise ValueError("runtime execution evidence must bind the complete install plan")
        if self.candidate != plan.candidate or self.package_digest != plan.package_digest:
            raise ValueError("runtime execution evidence must bind the install plan candidate and digest")
        if self.package_name != plan.package_name or self.version != plan.version or self.target != plan.target:
            raise ValueError("runtime execution evidence must bind the install plan package, version, and target")


class InstallationResult(_CandidateBoundRuntimeEvidence):
    """Adapter-supplied apply observation; the SDK performs no installation."""

    schema_version: Literal["installation-result/v1"] = "installation-result/v1"
    receipt_id: ReceiptId
    lane: Literal["runtime_installation"]
    operation: Literal["install", "update", "no_change"]
    current_lock_sha256: Sha256
    proposed_lock_sha256: Sha256
    resulting_lock_sha256: Sha256 | None = None
    status: Literal["completed", "failed", "blocked", "indeterminate"]
    mutation_performed: bool
    blocker: RuntimeEvidenceBlocker | None = None
    race: MutationRaceEvidence | None = None

    @field_validator("receipt_id")
    @classmethod
    def receipt_id_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "installation result receipt id")

    @model_validator(mode="after")
    def status_must_match_observation(self) -> InstallationResult:
        if self.operation == "no_change":
            if self.current_lock_sha256 != self.proposed_lock_sha256:
                raise ValueError("no-change installation requires identical current and proposed locks")
            if self.mutation_performed:
                raise ValueError("no-change installation cannot claim mutation")
        elif self.current_lock_sha256 == self.proposed_lock_sha256:
            raise ValueError("install or update observation requires distinct current and proposed locks")
        if self.status == "completed":
            if self.resulting_lock_sha256 != self.proposed_lock_sha256:
                raise ValueError("completed installation must report the proposed lock as applied")
            if self.blocker is not None or self.race is not None:
                raise ValueError("completed installation cannot contain a blocker or race")
            if self.operation != "no_change" and not self.mutation_performed:
                raise ValueError("completed installation mutation flag must match the operation")
        elif self.status == "blocked":
            if self.mutation_performed or self.resulting_lock_sha256 is not None or self.blocker is None:
                raise ValueError("blocked installation requires a blocker and cannot claim mutation")
        elif self.blocker is None:
            raise ValueError("failed or indeterminate installation requires a blocker")
        if self.race is not None and self.status not in {"failed", "indeterminate"}:
            raise ValueError("mutation race evidence requires failed or indeterminate installation")
        return self

    def validate_against_install_plan(self, plan: InstallPlan) -> None:
        """Validate this observation against the exact non-mutating plan."""

        self._validate_plan_binding(plan)
        if self.current_lock_sha256 != plan.current_lock_sha256:
            raise ValueError("installation result must bind the plan current lock")
        if self.proposed_lock_sha256 != plan.proposed_lock_sha256:
            raise ValueError("installation result must bind the plan proposed lock")
        if self.operation != plan.operation:
            raise ValueError("installation result must bind the plan operation")
        if self.race is not None and self.race.expected_lock_sha256 != plan.current_lock_sha256:
            raise ValueError("installation race must bind the plan current lock")


class RollbackJournalEntry(_ContractModel):
    """One portable, ordered adapter observation in a rollback journal."""

    sequence: int = Field(ge=0)
    path: PortablePath
    action: Literal["restore", "remove"]
    status: Literal["planned", "applied", "failed", "skipped"]
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def path_must_be_portable(cls, value: str) -> str:
        return _require_public_path(value, "rollback journal path")

    @field_validator("evidence_refs")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_paths(values, "rollback journal evidence refs")


class RollbackJournal(_CandidateBoundRuntimeEvidence):
    """Adapter-supplied immutable rollback journal; the SDK executes no step."""

    schema_version: Literal["rollback-journal/v1"] = "rollback-journal/v1"
    journal_id: ReceiptId
    installation_result_id: ReceiptId
    installation_result_sha256: Sha256
    rollback_lock_sha256: Sha256
    entries: tuple[RollbackJournalEntry, ...] = Field(min_length=1)
    mutation_performed: bool

    @field_validator("journal_id", "installation_result_id")
    @classmethod
    def ids_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "rollback journal identity")

    @model_validator(mode="after")
    def entries_must_be_ordered_and_unique(self) -> RollbackJournal:
        sequences = tuple(entry.sequence for entry in self.entries)
        if sequences != tuple(range(len(self.entries))):
            raise ValueError("rollback journal entries must use contiguous sequence numbers")
        paths = tuple(entry.path for entry in self.entries)
        if len(paths) != len(set(paths)):
            raise ValueError("rollback journal paths must be unique")
        applied = any(entry.status == "applied" for entry in self.entries)
        if self.mutation_performed != applied:
            raise ValueError("rollback journal mutation flag must match applied entries")
        return self

    def validate_against_installation_result(self, result: InstallationResult) -> None:
        result = InstallationResult.model_validate(result.model_dump(mode="json"))
        if not result.mutation_performed:
            raise ValueError("rollback journal requires an installation result that performed a mutation")
        if self.installation_result_id != result.receipt_id or self.installation_result_sha256 != _model_sha256(result):
            raise ValueError("rollback journal must bind the complete installation result")
        if (
            self.candidate != result.candidate
            or self.version != result.version
            or self.package_digest != result.package_digest
        ):
            raise ValueError("rollback journal must bind the installation candidate, version, and digest")
        if self.plan_id != result.plan_id or self.plan_sha256 != result.plan_sha256 or self.target != result.target:
            raise ValueError("rollback journal must bind the installation plan and target")
        if self.rollback_lock_sha256 != result.current_lock_sha256:
            raise ValueError("rollback journal must restore the installation current lock")


class RollbackOutcome(_CandidateBoundRuntimeEvidence):
    """Adapter-supplied rollback outcome; the SDK performs no rollback."""

    schema_version: Literal["rollback-outcome/v1"] = "rollback-outcome/v1"
    receipt_id: ReceiptId
    lane: Literal["runtime_rollback"]
    journal_id: ReceiptId
    journal_sha256: Sha256
    rollback_lock_sha256: Sha256
    resulting_lock_sha256: Sha256 | None = None
    status: Literal["rolled_back", "rollback_failed", "blocked", "indeterminate"]
    mutation_performed: bool
    blocker: RuntimeEvidenceBlocker | None = None
    race: MutationRaceEvidence | None = None

    @field_validator("receipt_id", "journal_id")
    @classmethod
    def ids_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "rollback outcome identity")

    @model_validator(mode="after")
    def status_must_match_observation(self) -> RollbackOutcome:
        if self.status == "rolled_back":
            if not self.mutation_performed or self.resulting_lock_sha256 != self.rollback_lock_sha256:
                raise ValueError("rolled-back outcome must bind the rollback lock")
            if self.blocker is not None or self.race is not None:
                raise ValueError("rolled-back outcome cannot contain blocker or race evidence")
        elif self.status == "blocked":
            if self.mutation_performed or self.resulting_lock_sha256 is not None or self.blocker is None:
                raise ValueError("blocked rollback requires a blocker and cannot claim mutation")
        elif self.blocker is None:
            raise ValueError("failed or indeterminate rollback requires a blocker")
        return self

    def validate_against_journal(self, journal: RollbackJournal) -> None:
        journal = RollbackJournal.model_validate(journal.model_dump(mode="json"))
        if self.status == "rolled_back":
            if not journal.mutation_performed:
                raise ValueError("rolled-back outcome requires a journal with an applied mutation")
            if any(entry.status != "applied" for entry in journal.entries):
                raise ValueError("rolled-back outcome requires every journal entry to be applied")
        if self.mutation_performed != journal.mutation_performed:
            raise ValueError("rollback outcome mutation state must match the journal")
        if self.journal_id != journal.journal_id or self.journal_sha256 != _model_sha256(journal):
            raise ValueError("rollback outcome must bind the complete rollback journal")
        if (
            self.candidate != journal.candidate
            or self.version != journal.version
            or self.package_digest != journal.package_digest
        ):
            raise ValueError("rollback outcome must bind the rollback candidate, version, and digest")
        if self.plan_id != journal.plan_id or self.plan_sha256 != journal.plan_sha256 or self.target != journal.target:
            raise ValueError("rollback outcome must bind the rollback plan and target")
        if self.rollback_lock_sha256 != journal.rollback_lock_sha256:
            raise ValueError("rollback outcome must bind the journal rollback lock")
        if self.race is not None and self.race.expected_lock_sha256 != journal.rollback_lock_sha256:
            raise ValueError("rollback race must bind the journal rollback lock")


class DiscoveryObservation(_CandidateBoundRuntimeEvidence):
    """Observation that an adapter did or did not discover the installed candidate."""

    schema_version: Literal["discovery-observation/v1"] = "discovery-observation/v1"
    receipt_id: ReceiptId
    lane: Literal["runtime_discovery"]
    installation_result_id: ReceiptId
    installation_result_sha256: Sha256
    method_id: RuntimeEvidenceIdentifier
    status: Literal["discovered", "not_discovered", "blocked", "indeterminate"]
    mutation_performed: Literal[False] = False
    blocker: RuntimeEvidenceBlocker | None = None

    @field_validator("receipt_id", "installation_result_id", "method_id")
    @classmethod
    def ids_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "discovery observation identity")

    @model_validator(mode="after")
    def status_must_match_observation(self) -> DiscoveryObservation:
        if self.status == "discovered" and self.blocker is not None:
            raise ValueError("discovered observation cannot contain a blocker")
        if self.status != "discovered" and self.blocker is None:
            raise ValueError("non-discovered observation requires a blocker")
        return self

    def validate_against_installation_result(self, result: InstallationResult) -> None:
        result = InstallationResult.model_validate(result.model_dump(mode="json"))
        if result.status != "completed":
            raise ValueError("discovery observation requires a completed installation result")
        if self.installation_result_id != result.receipt_id or self.installation_result_sha256 != _model_sha256(result):
            raise ValueError("discovery observation must bind the complete installation result")
        if (
            self.candidate != result.candidate
            or self.version != result.version
            or self.package_digest != result.package_digest
        ):
            raise ValueError("discovery observation must bind the installed candidate, version, and digest")
        if self.plan_id != result.plan_id or self.plan_sha256 != result.plan_sha256 or self.target != result.target:
            raise ValueError("discovery observation must bind the installation plan and target")


class ActivationObservation(_CandidateBoundRuntimeEvidence):
    """Observation of activation state; the SDK activates nothing."""

    schema_version: Literal["activation-observation/v1"] = "activation-observation/v1"
    receipt_id: ReceiptId
    lane: Literal["runtime_activation"]
    discovery_receipt_id: ReceiptId
    discovery_receipt_sha256: Sha256
    mechanism_id: RuntimeEvidenceIdentifier
    status: Literal["active", "inactive", "blocked", "indeterminate"]
    mutation_performed: bool
    deactivation_id: RuntimeEvidenceIdentifier | None = None
    blocker: RuntimeEvidenceBlocker | None = None

    @field_validator("receipt_id", "discovery_receipt_id", "mechanism_id", "deactivation_id")
    @classmethod
    def ids_must_be_public_safe(cls, value: str | None) -> str | None:
        return None if value is None else _require_public_text(value, "activation observation identity")

    @model_validator(mode="after")
    def status_must_match_observation(self) -> ActivationObservation:
        if self.status == "active" and self.blocker is not None:
            raise ValueError("active observation cannot contain a blocker")
        if self.status != "active" and self.blocker is None:
            raise ValueError("non-active observation requires a blocker")
        if self.mutation_performed and self.deactivation_id is None:
            raise ValueError("mutating activation observation requires a deactivation identity")
        return self

    def validate_against_discovery(self, discovery: DiscoveryObservation) -> None:
        discovery = DiscoveryObservation.model_validate(discovery.model_dump(mode="json"))
        if discovery.status != "discovered":
            raise ValueError("activation observation requires a discovered candidate")
        if self.discovery_receipt_id != discovery.receipt_id or self.discovery_receipt_sha256 != _model_sha256(
            discovery
        ):
            raise ValueError("activation observation must bind the complete discovery observation")
        if (
            self.candidate != discovery.candidate
            or self.version != discovery.version
            or self.package_digest != discovery.package_digest
        ):
            raise ValueError("activation observation must bind the discovered candidate, version, and digest")
        if (
            self.plan_id != discovery.plan_id
            or self.plan_sha256 != discovery.plan_sha256
            or self.target != discovery.target
        ):
            raise ValueError("activation observation must bind the discovery plan and target")


class RuntimeOutcomeReceipt(_CandidateBoundRuntimeEvidence):
    """Adapter-supplied runtime observation; not an evaluation or usability claim."""

    schema_version: Literal["runtime-outcome/v1"] = "runtime-outcome/v1"
    receipt_id: ReceiptId
    lane: Literal["runtime_outcome"]
    activation_receipt_id: ReceiptId
    activation_receipt_sha256: Sha256
    invocation_id: RuntimeEvidenceIdentifier
    input_sha256: Sha256
    output_sha256: Sha256 | None = None
    duration_ms: int = Field(ge=0)
    status: Literal["completed", "failed", "blocked", "indeterminate"]
    provider_result_id: ReceiptId | None = None
    provider_result_sha256: Sha256 | None = None
    evaluation_receipt_id: ReceiptId | None = None
    evaluation_receipt_sha256: Sha256 | None = None
    mutation_performed: Literal[False] = False
    blocker: RuntimeEvidenceBlocker | None = None

    @field_validator(
        "receipt_id",
        "activation_receipt_id",
        "invocation_id",
        "provider_result_id",
        "evaluation_receipt_id",
    )
    @classmethod
    def ids_must_be_public_safe(cls, value: str | None) -> str | None:
        return None if value is None else _require_public_text(value, "runtime outcome identity")

    @model_validator(mode="after")
    def status_and_optional_refs_must_be_complete(self) -> RuntimeOutcomeReceipt:
        if self.status == "completed":
            if self.output_sha256 is None or self.blocker is not None:
                raise ValueError("completed runtime outcome requires output digest and no blocker")
        elif self.blocker is None:
            raise ValueError("non-completed runtime outcome requires a blocker")
        if (self.provider_result_id is None) != (self.provider_result_sha256 is None):
            raise ValueError("provider result reference id and digest must be supplied together")
        if (self.evaluation_receipt_id is None) != (self.evaluation_receipt_sha256 is None):
            raise ValueError("evaluation receipt reference id and digest must be supplied together")
        return self

    def validate_against_activation(self, activation: ActivationObservation) -> None:
        activation = ActivationObservation.model_validate(activation.model_dump(mode="json"))
        if activation.status != "active":
            raise ValueError("runtime outcome requires an active observation")
        if self.activation_receipt_id != activation.receipt_id or self.activation_receipt_sha256 != _model_sha256(
            activation
        ):
            raise ValueError("runtime outcome must bind the complete activation observation")
        if (
            self.candidate != activation.candidate
            or self.version != activation.version
            or self.package_digest != activation.package_digest
        ):
            raise ValueError("runtime outcome must bind the activated candidate, version, and digest")
        if (
            self.plan_id != activation.plan_id
            or self.plan_sha256 != activation.plan_sha256
            or self.target != activation.target
        ):
            raise ValueError("runtime outcome must bind the activation plan and target")

    def validate_against_provider_result(self, result: object) -> None:
        """Require the optional provider reference to bind one exact result."""

        from skills_sdk.models.provider_execution import ProviderExecutionResult

        if not isinstance(result, ProviderExecutionResult):
            raise ValueError("runtime outcome provider reference requires a provider execution result")
        result = ProviderExecutionResult.model_validate(result.model_dump(mode="json"))
        if self.provider_result_id != result.result_id or self.provider_result_sha256 != _model_sha256(result):
            raise ValueError("runtime outcome must bind the complete provider execution result")
        if self.candidate != result.candidate:
            raise ValueError("runtime outcome provider result must bind the same candidate")

    def validate_against_evaluation_receipt(self, receipt: object) -> None:
        """Require the optional evaluation reference to bind one exact receipt."""

        from skills_sdk.models.evaluation import EvaluationReceipt
        from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2

        if not isinstance(receipt, (EvaluationReceipt, EvaluationReceiptV2)):
            raise ValueError("runtime outcome evaluation reference requires an evaluation receipt")
        validated = type(receipt).model_validate(receipt.model_dump(mode="json"))
        if self.evaluation_receipt_id != validated.receipt_id or self.evaluation_receipt_sha256 != _model_sha256(
            validated
        ):
            raise ValueError("runtime outcome must bind the complete evaluation receipt")
        if self.candidate != validated.candidate:
            raise ValueError("runtime outcome evaluation receipt must bind the same candidate")


__all__ = [
    "ActivationObservation",
    "DiscoveryObservation",
    "InstallationResult",
    "MutationRaceEvidence",
    "RollbackJournal",
    "RollbackJournalEntry",
    "RollbackOutcome",
    "RuntimeAdapterIdentity",
    "RuntimeEvidenceBlocker",
    "RuntimeOutcomeReceipt",
]
