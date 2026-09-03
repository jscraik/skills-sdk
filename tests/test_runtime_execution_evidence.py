from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.evaluation import EvaluationReceipt, ScorerProfile
from skills_sdk.models.lifecycle import InstallPlan, RuntimeFile, RuntimeLockEntry, RuntimeTarget
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceiptBlocker
from skills_sdk.models.provider_execution import ProviderExecutionResult
from skills_sdk.models.registry import RegistryIdentity
from skills_sdk.models.runtime_evidence import (
    ActivationObservation,
    DiscoveryObservation,
    InstallationResult,
    MutationRaceEvidence,
    RollbackJournal,
    RollbackJournalEntry,
    RollbackOutcome,
    RuntimeEvidenceBlocker,
    RuntimeOutcomeReceipt,
)

NOW = "2026-09-02T09:00:00Z"


def _plan() -> InstallPlan:
    files = (RuntimeFile(path="SKILL.md", sha256="c" * 64),)
    candidate = PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256=candidate_content_sha256(files),
    )
    target = RuntimeTarget(scope="project", target_id="project-runtime")
    entry = RuntimeLockEntry(
        package_name=candidate.package_id,
        version="0.1.0",
        candidate=candidate,
        package_digest="b" * 64,
        registry=RegistryIdentity(registry_id="private-registry", namespace="team"),
        package_receipt_id="package-receipt-1234",
        registry_preparation_receipt_id="registry-preparation-1234",
        target=target,
        files=files,
    )
    payload: dict[str, object] = {
        "schema_version": "install-plan/v1",
        "candidate": candidate.model_dump(mode="json"),
        "package_name": candidate.package_id,
        "version": "0.1.0",
        "package_digest": "b" * 64,
        "package_receipt_id": "package-receipt-1234",
        "status": "planned",
        "operation": "install",
        "target": target.model_dump(mode="json"),
        "registry": entry.registry.model_dump(mode="json"),
        "registry_preparation_receipt_id": "registry-preparation-1234",
        "registry_input_receipt_id": "package-receipt-1234",
        "current_lock_sha256": "d" * 64,
        "rollback_lock_sha256": "d" * 64,
        "proposed_lock_sha256": "e" * 64,
        "proposed_entry": entry.model_dump(mode="json"),
        "evidence": ["evidence/install-plan.json"],
        "mutation_performed": False,
    }
    identity = {key: value for key, value in payload.items() if key not in {"schema_version", "mutation_performed"}}
    payload["plan_id"] = f"install-plan-{canonical_json_sha256(identity)[:24]}"
    return InstallPlan.model_validate(payload)


def _no_change_plan() -> InstallPlan:
    payload = _plan().model_dump(mode="json")
    payload["operation"] = "no_change"
    payload["proposed_lock_sha256"] = payload["current_lock_sha256"]
    identity = {
        key: payload[key]
        for key in (
            "candidate",
            "package_name",
            "version",
            "package_digest",
            "package_receipt_id",
            "registry",
            "registry_preparation_receipt_id",
            "registry_input_receipt_id",
            "current_lock_sha256",
            "rollback_lock_sha256",
            "target",
            "status",
            "evidence",
            "operation",
            "proposed_lock_sha256",
            "proposed_entry",
        )
    }
    payload["plan_id"] = f"install-plan-{canonical_json_sha256(identity)[:24]}"
    return InstallPlan.model_validate(payload)


def _common(plan: InstallPlan) -> dict[str, object]:
    assert plan.candidate is not None
    assert plan.package_digest is not None
    return {
        "candidate": plan.candidate.model_dump(mode="json"),
        "package_name": plan.package_name,
        "version": plan.version,
        "package_digest": plan.package_digest,
        "plan_id": plan.plan_id,
        "plan_sha256": canonical_json_sha256(plan.model_dump(mode="json")),
        "target": plan.target.model_dump(mode="json"),
        "adapter": {"adapter_id": "codex-host", "adapter_version": "1.0.0"},
        "observed_at": NOW,
        "evidence": ["evidence/runtime-observation.json"],
    }


def _blocker() -> dict[str, object]:
    return {
        "code": "runtime_blocked",
        "category": "runtime",
        "message": "Runtime observation was blocked.",
        "evidence_refs": ["evidence/runtime-blocker.json"],
    }


def _installation(plan: InstallPlan) -> InstallationResult:
    payload = {
        **_common(plan),
        "schema_version": "installation-result/v1",
        "receipt_id": "installation-result-1234",
        "lane": "runtime_installation",
        "operation": plan.operation,
        "current_lock_sha256": plan.current_lock_sha256,
        "proposed_lock_sha256": plan.proposed_lock_sha256,
        "resulting_lock_sha256": plan.proposed_lock_sha256,
        "status": "completed",
        "mutation_performed": plan.operation != "no_change",
        "blocker": None,
        "race": None,
    }
    return InstallationResult.model_validate(payload)


def _discovery(plan: InstallPlan, installation: InstallationResult) -> DiscoveryObservation:
    return DiscoveryObservation(
        **_common(plan),
        receipt_id="discovery-observation-1234",
        lane="runtime_discovery",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        method_id="manifest-scan",
        status="discovered",
    )


def _activation(plan: InstallPlan, discovery: DiscoveryObservation) -> ActivationObservation:
    return ActivationObservation(
        **_common(plan),
        receipt_id="activation-observation-1234",
        lane="runtime_activation",
        discovery_receipt_id=discovery.receipt_id,
        discovery_receipt_sha256=canonical_json_sha256(discovery.model_dump(mode="json")),
        mechanism_id="runtime-selection",
        status="active",
        mutation_performed=False,
    )


def _outcome(plan: InstallPlan, activation: ActivationObservation, **updates: object) -> RuntimeOutcomeReceipt:
    payload: dict[str, object] = {
        **_common(plan),
        "receipt_id": "runtime-outcome-1234",
        "lane": "runtime_outcome",
        "activation_receipt_id": activation.receipt_id,
        "activation_receipt_sha256": canonical_json_sha256(activation.model_dump(mode="json")),
        "invocation_id": "scenario-run-1",
        "input_sha256": "4" * 64,
        "output_sha256": "5" * 64,
        "duration_ms": 42,
        "status": "completed",
    }
    payload.update(updates)
    return RuntimeOutcomeReceipt.model_validate(payload)


def test_runtime_evidence_chain_is_registered_bound_and_parseable() -> None:
    plan = _plan()
    installation = _installation(plan)
    installation.validate_against_install_plan(plan)
    discovery = _discovery(plan, installation)
    discovery.validate_against_installation_result(installation)
    activation = _activation(plan, discovery)
    activation.validate_against_discovery(discovery)
    outcome = RuntimeOutcomeReceipt(
        **_common(plan),
        receipt_id="runtime-outcome-1234",
        lane="runtime_outcome",
        activation_receipt_id=activation.receipt_id,
        activation_receipt_sha256=canonical_json_sha256(activation.model_dump(mode="json")),
        invocation_id="scenario-run-1",
        input_sha256="4" * 64,
        output_sha256="5" * 64,
        duration_ms=42,
        status="completed",
    )
    outcome.validate_against_activation(activation)

    for schema_name, receipt in (
        ("installation-result.v1", installation),
        ("discovery-observation.v1", discovery),
        ("activation-observation.v1", activation),
        ("runtime-outcome.v1", outcome),
    ):
        payload = receipt.model_dump(mode="json")
        SchemaRegistry().validate(schema_name, payload)
        parsed = parse_receipt(payload)
        assert parsed.candidate is not None
        assert parsed.candidate.package_id == "synthetic-skill"
        assert parsed.status == "pass"


def test_rollback_journal_and_outcome_bind_complete_upstream_evidence() -> None:
    plan = _plan()
    installation = _installation(plan)
    journal = RollbackJournal(
        **_common(plan),
        journal_id="rollback-journal-1234",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        rollback_lock_sha256=plan.current_lock_sha256,
        entries=(
            RollbackJournalEntry(
                sequence=0,
                path="SKILL.md",
                action="remove",
                status="applied",
                before_sha256="c" * 64,
                evidence_refs=("evidence/rollback-step.json",),
            ),
        ),
        mutation_performed=True,
    )
    journal.validate_against_installation_result(installation)
    outcome = RollbackOutcome(
        **_common(plan),
        receipt_id="rollback-outcome-1234",
        lane="runtime_rollback",
        journal_id=journal.journal_id,
        journal_sha256=canonical_json_sha256(journal.model_dump(mode="json")),
        rollback_lock_sha256=journal.rollback_lock_sha256,
        resulting_lock_sha256=journal.rollback_lock_sha256,
        status="rolled_back",
        mutation_performed=True,
    )
    outcome.validate_against_journal(journal)
    SchemaRegistry().validate("rollback-journal.v1", journal.model_dump(mode="json"))
    SchemaRegistry().validate("rollback-outcome.v1", outcome.model_dump(mode="json"))
    assert parse_receipt(outcome.model_dump(mode="json")).status == "blocked"


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    [
        (
            "installation-result.v1",
            {"status": "completed", "resulting_lock_sha256": None},
        ),
        (
            "runtime-outcome.v1",
            {"status": "completed", "output_sha256": None},
        ),
    ],
)
def test_direct_draft_rejects_incomplete_success_states(schema_name: str, payload: dict[str, object]) -> None:
    plan = _plan()
    if schema_name == "installation-result.v1":
        complete = _installation(plan).model_dump(mode="json")
    else:
        installation = _installation(plan)
        discovery = _discovery(plan, installation)
        activation = _activation(plan, discovery)
        complete = RuntimeOutcomeReceipt(
            **_common(plan),
            receipt_id="runtime-outcome-1234",
            lane="runtime_outcome",
            activation_receipt_id=activation.receipt_id,
            activation_receipt_sha256=canonical_json_sha256(activation.model_dump(mode="json")),
            invocation_id="scenario-run-1",
            input_sha256="4" * 64,
            output_sha256="5" * 64,
            duration_ms=42,
            status="completed",
        ).model_dump(mode="json")
    complete.update(payload)
    validator = Draft202012Validator(SchemaRegistry().load(schema_name), format_checker=FormatChecker())
    assert list(validator.iter_errors(complete))


def test_model_registry_and_draft_reject_host_paths_and_secrets() -> None:
    plan = _plan()
    payload = _installation(plan).model_dump(mode="json")
    payload["evidence"] = ["/" + "Users/alice/runtime.json"]
    with pytest.raises(ValidationError, match=r"portable|machine-path"):
        InstallationResult.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("installation-result.v1", payload)

    payload = _installation(plan).model_dump(mode="json")
    payload["blocker"] = {**_blocker(), "message": "token=plainvalue"}
    payload["status"] = "failed"
    payload["resulting_lock_sha256"] = None
    with pytest.raises(ValidationError, match="credential-shaped"):
        InstallationResult.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("installation-result.v1", payload)


def test_rejected_fixture_cannot_embed_a_machine_path() -> None:
    fixture = Path(__file__).parent / "fixtures/runtime-evidence/rejected-machine-path.json"
    payload = _installation(_plan()).model_dump(mode="json")
    payload.update(json.loads(fixture.read_text(encoding="utf-8")))
    with pytest.raises(ValidationError, match=r"portable|machine-path"):
        InstallationResult.model_validate(payload)
    assert list(Draft202012Validator(SchemaRegistry().load("installation-result.v1")).iter_errors(payload))


def test_mutation_race_requires_distinct_lock_digests() -> None:
    with pytest.raises(ValidationError, match="distinct expected and observed"):
        MutationRaceEvidence(
            expected_lock_sha256="a" * 64,
            observed_lock_sha256="a" * 64,
            detected_at=NOW,
            evidence_refs=("evidence/race.json",),
        )


def test_installation_revalidates_forged_nested_blocker() -> None:
    fixture = Path(__file__).parent / "fixtures/runtime-evidence/rejected-machine-path.json"
    unsafe_path = json.loads(fixture.read_text(encoding="utf-8"))["evidence"][0]
    payload = _installation(_plan()).model_dump(mode="json")
    blocker = RuntimeEvidenceBlocker.model_construct(
        code="runtime_blocked",
        category="runtime",
        message=f"Blocked at {unsafe_path}",
        evidence_refs=("evidence/runtime-blocker.json",),
    )
    payload.update(status="blocked", mutation_performed=False, resulting_lock_sha256=None, blocker=blocker)

    with pytest.raises(ValidationError, match="machine-path"):
        InstallationResult.model_validate(payload)


def test_runtime_evidence_accepts_native_aware_datetime() -> None:
    payload = _installation(_plan()).model_dump(mode="json")
    payload["observed_at"] = datetime(2026, 9, 2, 9, tzinfo=UTC)
    assert InstallationResult.model_validate(payload).observed_at == payload["observed_at"]


def test_mutation_race_expected_digest_binds_the_upstream_lock() -> None:
    plan = _plan()
    payload = _installation(plan).model_dump(mode="json")
    payload.update(
        status="failed",
        resulting_lock_sha256=None,
        blocker=_blocker(),
        race={
            "expected_lock_sha256": "1" * 64,
            "observed_lock_sha256": "2" * 64,
            "detected_at": NOW,
            "evidence_refs": ["evidence/race.json"],
        },
    )
    result = InstallationResult.model_validate(payload)
    with pytest.raises(ValueError, match="race must bind the plan current lock"):
        result.validate_against_install_plan(plan)


def test_cross_object_binding_fails_closed() -> None:
    plan = _plan()
    installation = _installation(plan).model_copy(update={"plan_sha256": "f" * 64})
    with pytest.raises(ValueError, match="complete install plan"):
        installation.validate_against_install_plan(plan)


def test_completed_no_change_observation_does_not_claim_mutation() -> None:
    plan = _no_change_plan()
    result = _installation(plan)
    result.validate_against_install_plan(plan)
    forged_payload = result.model_dump(mode="json")
    forged_payload["mutation_performed"] = True
    with pytest.raises(ValidationError, match="cannot claim mutation"):
        InstallationResult.model_validate(forged_payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("installation-result.v1", forged_payload)
    with pytest.raises(ContractError):
        parse_receipt(forged_payload)
    assert list(Draft202012Validator(SchemaRegistry().load("installation-result.v1")).iter_errors(forged_payload))

    forged_copy = result.model_copy(update={"mutation_performed": True})
    with pytest.raises(ValidationError, match="cannot claim mutation"):
        InstallationResult.model_validate(forged_copy.model_dump(mode="json"))
    with pytest.raises(ContractError):
        parse_receipt(forged_copy.model_dump(mode="json"))


@pytest.mark.parametrize("status", ["failed", "blocked", "indeterminate"])
def test_no_change_observation_never_claims_mutation(status: str) -> None:
    payload = _installation(_no_change_plan()).model_dump(mode="json")
    payload.update(status=status, mutation_performed=True, resulting_lock_sha256=None, blocker=_blocker())
    with pytest.raises(ValidationError, match="cannot claim mutation"):
        InstallationResult.model_validate(payload)


def test_installation_operation_is_required_and_binds_the_plan() -> None:
    plan = _plan()
    payload = _installation(plan).model_dump(mode="json")
    del payload["operation"]
    with pytest.raises(ValidationError, match=r"operation\s+Field required"):
        InstallationResult.model_validate(payload)

    result = _installation(plan).model_copy(update={"operation": "update"})
    with pytest.raises(ValueError, match="plan operation"):
        result.validate_against_install_plan(plan)


def test_rollback_chain_requires_mutating_upstream_evidence() -> None:
    plan = _plan()
    installation_payload = _installation(plan).model_dump(mode="json")
    installation_payload.update(
        status="blocked", mutation_performed=False, resulting_lock_sha256=None, blocker=_blocker()
    )
    installation = InstallationResult.model_validate(installation_payload)
    journal = RollbackJournal(
        **_common(plan),
        journal_id="rollback-journal-1234",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        rollback_lock_sha256=plan.current_lock_sha256,
        entries=(
            RollbackJournalEntry(
                sequence=0,
                path="SKILL.md",
                action="restore",
                status="applied",
                evidence_refs=("evidence/rollback-step.json",),
            ),
        ),
        mutation_performed=True,
    )
    with pytest.raises(ValueError, match="performed a mutation"):
        journal.validate_against_installation_result(installation)

    no_change_plan = _no_change_plan()
    forged_no_change = _installation(no_change_plan).model_copy(
        update={
            "status": "failed",
            "mutation_performed": True,
            "resulting_lock_sha256": None,
            "blocker": installation.blocker,
        }
    )
    forged_journal = journal.model_copy(
        update={
            "candidate": forged_no_change.candidate,
            "package_name": forged_no_change.package_name,
            "version": forged_no_change.version,
            "package_digest": forged_no_change.package_digest,
            "plan_id": forged_no_change.plan_id,
            "plan_sha256": forged_no_change.plan_sha256,
            "target": forged_no_change.target,
            "installation_result_id": forged_no_change.receipt_id,
            "installation_result_sha256": canonical_json_sha256(forged_no_change.model_dump(mode="json")),
            "rollback_lock_sha256": forged_no_change.current_lock_sha256,
        }
    )
    with pytest.raises(ValidationError, match="cannot claim mutation"):
        forged_journal.validate_against_installation_result(forged_no_change)

    non_mutating_journal = journal.model_copy(
        update={
            "entries": (journal.entries[0].model_copy(update={"status": "planned"}),),
            "mutation_performed": False,
        }
    )
    outcome = RollbackOutcome(
        **_common(plan),
        receipt_id="rollback-outcome-1234",
        lane="runtime_rollback",
        journal_id=non_mutating_journal.journal_id,
        journal_sha256=canonical_json_sha256(non_mutating_journal.model_dump(mode="json")),
        rollback_lock_sha256=non_mutating_journal.rollback_lock_sha256,
        resulting_lock_sha256=non_mutating_journal.rollback_lock_sha256,
        status="rolled_back",
        mutation_performed=True,
    )
    with pytest.raises(ValueError, match="journal with an applied mutation"):
        outcome.validate_against_journal(non_mutating_journal)

    for bound_journal, mutation_performed in (
        (journal, False),
        (non_mutating_journal, True),
    ):
        failed = RollbackOutcome(
            **_common(plan),
            receipt_id="rollback-outcome-failed-1234",
            lane="runtime_rollback",
            journal_id=bound_journal.journal_id,
            journal_sha256=canonical_json_sha256(bound_journal.model_dump(mode="json")),
            rollback_lock_sha256=bound_journal.rollback_lock_sha256,
            status="rollback_failed",
            mutation_performed=mutation_performed,
            blocker=_blocker(),
        )
        with pytest.raises(ValueError, match="mutation state must match"):
            failed.validate_against_journal(bound_journal)


@pytest.mark.parametrize("incomplete_status", ["failed", "planned", "skipped"])
def test_rolled_back_outcome_requires_every_journal_entry_applied(incomplete_status: str) -> None:
    plan = _plan()
    installation = _installation(plan)
    journal = RollbackJournal(
        **_common(plan),
        journal_id="rollback-journal-1234",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        rollback_lock_sha256=plan.current_lock_sha256,
        entries=(
            RollbackJournalEntry(
                sequence=0,
                path="SKILL.md",
                action="restore",
                status="applied",
                evidence_refs=("evidence/rollback-step.json",),
            ),
            RollbackJournalEntry(
                sequence=1,
                path="README.md",
                action="restore",
                status=incomplete_status,
                evidence_refs=("evidence/rollback-incomplete.json",),
            ),
        ),
        mutation_performed=True,
    )
    outcome = RollbackOutcome(
        **_common(plan),
        receipt_id="rollback-outcome-1234",
        lane="runtime_rollback",
        journal_id=journal.journal_id,
        journal_sha256=canonical_json_sha256(journal.model_dump(mode="json")),
        rollback_lock_sha256=journal.rollback_lock_sha256,
        resulting_lock_sha256=journal.rollback_lock_sha256,
        status="rolled_back",
        mutation_performed=True,
    )
    with pytest.raises(ValueError, match="every journal entry"):
        outcome.validate_against_journal(journal)
    assert parse_receipt(outcome.model_dump(mode="json")).status == "blocked"


def test_runtime_receipt_families_require_lane_at_every_public_boundary() -> None:
    plan = _plan()
    installation = _installation(plan)
    discovery = _discovery(plan, installation)
    activation = _activation(plan, discovery)
    journal = RollbackJournal(
        **_common(plan),
        journal_id="rollback-journal-1234",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        rollback_lock_sha256=plan.current_lock_sha256,
        entries=(
            RollbackJournalEntry(
                sequence=0,
                path="SKILL.md",
                action="remove",
                status="applied",
                evidence_refs=("evidence/rollback-step.json",),
            ),
        ),
        mutation_performed=True,
    )
    receipts = (
        ("installation-result.v1", InstallationResult, installation),
        (
            "rollback-outcome.v1",
            RollbackOutcome,
            RollbackOutcome(
                **_common(plan),
                receipt_id="rollback-outcome-1234",
                lane="runtime_rollback",
                journal_id=journal.journal_id,
                journal_sha256=canonical_json_sha256(journal.model_dump(mode="json")),
                rollback_lock_sha256=journal.rollback_lock_sha256,
                resulting_lock_sha256=journal.rollback_lock_sha256,
                status="rolled_back",
                mutation_performed=True,
            ),
        ),
        ("discovery-observation.v1", DiscoveryObservation, discovery),
        ("activation-observation.v1", ActivationObservation, activation),
        (
            "runtime-outcome.v1",
            RuntimeOutcomeReceipt,
            RuntimeOutcomeReceipt(
                **_common(plan),
                receipt_id="runtime-outcome-1234",
                lane="runtime_outcome",
                activation_receipt_id=activation.receipt_id,
                activation_receipt_sha256=canonical_json_sha256(activation.model_dump(mode="json")),
                invocation_id="scenario-run-1",
                input_sha256="4" * 64,
                output_sha256="5" * 64,
                duration_ms=42,
                status="completed",
            ),
        ),
    )
    for schema_name, model, receipt in receipts:
        payload = receipt.model_dump(mode="json")
        del payload["lane"]
        with pytest.raises(ValidationError, match=r"lane\s+Field required"):
            model.model_validate(payload)
        with pytest.raises(ContractError, match="rejected the payload"):
            SchemaRegistry().validate(schema_name, payload)
        with pytest.raises(ContractError, match="rejected the payload"):
            parse_receipt(payload)


def test_runtime_outcome_optional_refs_are_all_or_none() -> None:
    plan = _plan()
    installation = _installation(plan)
    discovery = _discovery(plan, installation)
    activation = _activation(plan, discovery)
    with pytest.raises(ValidationError, match="provider result reference"):
        RuntimeOutcomeReceipt(
            **_common(plan),
            receipt_id="runtime-outcome-1234",
            lane="runtime_outcome",
            activation_receipt_id=activation.receipt_id,
            activation_receipt_sha256=canonical_json_sha256(activation.model_dump(mode="json")),
            invocation_id="scenario-run-1",
            input_sha256="4" * 64,
            output_sha256="5" * 64,
            duration_ms=42,
            status="completed",
            provider_result_id="provider-result-1234",
        )


def test_every_downstream_hop_binds_package_version() -> None:
    plan = _plan()
    installation = _installation(plan)
    discovery = _discovery(plan, installation)
    activation = _activation(plan, discovery)
    journal = RollbackJournal(
        **_common(plan),
        journal_id="rollback-journal-1234",
        installation_result_id=installation.receipt_id,
        installation_result_sha256=canonical_json_sha256(installation.model_dump(mode="json")),
        rollback_lock_sha256=plan.current_lock_sha256,
        entries=(
            RollbackJournalEntry(
                sequence=0,
                path="SKILL.md",
                action="remove",
                status="applied",
                evidence_refs=("evidence/rollback-step.json",),
            ),
        ),
        mutation_performed=True,
    )
    rollback = RollbackOutcome(
        **_common(plan),
        receipt_id="rollback-outcome-1234",
        lane="runtime_rollback",
        journal_id=journal.journal_id,
        journal_sha256=canonical_json_sha256(journal.model_dump(mode="json")),
        rollback_lock_sha256=journal.rollback_lock_sha256,
        resulting_lock_sha256=journal.rollback_lock_sha256,
        status="rolled_back",
        mutation_performed=True,
    )
    outcome = _outcome(plan, activation)

    checks = (
        (journal.model_copy(update={"version": "9.9.9"}).validate_against_installation_result, installation),
        (rollback.model_copy(update={"version": "9.9.9"}).validate_against_journal, journal),
        (discovery.model_copy(update={"version": "9.9.9"}).validate_against_installation_result, installation),
        (activation.model_copy(update={"version": "9.9.9"}).validate_against_discovery, discovery),
        (outcome.model_copy(update={"version": "9.9.9"}).validate_against_activation, activation),
    )
    for validate, upstream in checks:
        with pytest.raises(ValueError, match="version"):
            validate(upstream)


def test_runtime_outcome_optional_receipts_bind_exact_objects() -> None:
    plan = _plan()
    installation = _installation(plan)
    discovery = _discovery(plan, installation)
    activation = _activation(plan, discovery)
    provider_payload = json.loads(
        (Path(__file__).parent / "fixtures/provider-execution/result-accepted.json").read_text(encoding="utf-8")
    )
    provider_payload["candidate"] = plan.candidate.model_dump(mode="json")
    provider_result = ProviderExecutionResult.model_validate(provider_payload)
    assert plan.candidate is not None
    scorer = ScorerProfile(
        candidate=plan.candidate,
        scorer_id="runtime-scorer",
        scorer_type="deterministic",
        version_or_digest="v1",
        pass_threshold=1.0,
        deterministic_checks_first=True,
        calibration_required=False,
    )
    evaluation = EvaluationReceipt(
        receipt_id="evaluation-receipt-1234",
        candidate=plan.candidate,
        scenario_set_id="runtime-scenarios",
        scorer=scorer,
        status="blocked",
        blocker=PackageReceiptBlocker(code="runtime_blocked", message="Runtime evaluation was blocked."),
    )
    outcome = _outcome(
        plan,
        activation,
        provider_result_id=provider_result.result_id,
        provider_result_sha256=canonical_json_sha256(provider_result.model_dump(mode="json")),
        evaluation_receipt_id=evaluation.receipt_id,
        evaluation_receipt_sha256=canonical_json_sha256(evaluation.model_dump(mode="json")),
    )

    outcome.validate_against_provider_result(provider_result)
    outcome.validate_against_evaluation_receipt(evaluation)
    with pytest.raises(ValueError, match="complete provider execution result"):
        invalid_provider = outcome.model_copy(update={"provider_result_sha256": "f" * 64})
        invalid_provider.validate_against_provider_result(provider_result)
    with pytest.raises(ValueError, match="complete evaluation receipt"):
        outcome.model_copy(update={"evaluation_receipt_sha256": "f" * 64}).validate_against_evaluation_receipt(
            evaluation
        )


def test_runtime_evidence_module_has_no_host_execution_dependencies() -> None:
    source = (Path(__file__).parents[1] / "src/skills_sdk/models/runtime_evidence.py").read_text(encoding="utf-8")
    for forbidden in (
        "pathlib",
        "open(",
        "write_text",
        "subprocess",
        "requests",
        "httpx",
        "socket",
        "agent_skills",
        "foundry",
        "tessl",
    ):
        assert forbidden not in source.lower()


def test_generic_parser_rejects_non_receipt_rollback_journal() -> None:
    with pytest.raises(ContractError, match="unsupported_receipt_family"):
        parse_receipt({"schema_version": "rollback-journal/v1"})


def test_generated_schemas_declare_structural_and_semantic_boundaries() -> None:
    for name in (
        "installation-result.v1",
        "rollback-journal.v1",
        "rollback-outcome.v1",
        "discovery-observation.v1",
        "activation-observation.v1",
        "runtime-outcome.v1",
    ):
        schema = SchemaRegistry().load(name)
        assert schema["x-skills-sdk-semantic-validator"]["entrypoint"].endswith("SchemaRegistry.validate")
        assert "standard JSON Schema validates one payload structurally" in schema["$comment"]


def test_unknown_fields_cannot_smuggle_host_or_raw_runtime_data() -> None:
    payload = _installation(_plan()).model_dump(mode="json")
    for field in ("absolute_path", "raw_log", "credentials", "environment"):
        invalid = deepcopy(payload)
        invalid[field] = "forbidden"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            InstallationResult.model_validate(invalid)
