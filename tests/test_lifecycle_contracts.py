from __future__ import annotations

import re
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from scripts.package_safety_schema import MACHINE_PATH_SCHEMA_PATTERN, PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN
from skills_sdk.core.digests import candidate_content_sha256, canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.lifecycle import (
    InstallPlan,
    RuntimeFile,
    RuntimeLock,
    RuntimeLockEntry,
    RuntimeTarget,
    lifecycle_text_is_public_safe,
)
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.registry import RegistryIdentity, RegistryPreparationBlocker


def _entry() -> RuntimeLockEntry:
    files = (RuntimeFile(path="SKILL.md", sha256="c" * 64),)
    return RuntimeLockEntry(
        package_name="synthetic-skill",
        version="0.1.0",
        candidate=PackageCandidateIdentity(
            package_id="synthetic-skill",
            source_revision="1" * 40,
            content_sha256=candidate_content_sha256(files),
        ),
        package_digest="b" * 64,
        registry=RegistryIdentity(registry_id="private-registry", namespace="team"),
        package_receipt_id="package-receipt-1234",
        registry_preparation_receipt_id="registry-preparation-1234",
        target=RuntimeTarget(scope="project", target_id="project-runtime"),
        files=files,
    )


def _planned_payload() -> dict[str, object]:
    entry = _entry()
    payload: dict[str, object] = {
        "schema_version": "install-plan/v1",
        "candidate": entry.candidate.model_dump(mode="json"),
        "package_name": entry.package_name,
        "version": entry.version,
        "package_digest": entry.package_digest,
        "package_receipt_id": entry.package_receipt_id,
        "status": "planned",
        "operation": "install",
        "target": entry.target.model_dump(mode="json"),
        "registry": entry.registry.model_dump(mode="json"),
        "registry_preparation_receipt_id": entry.registry_preparation_receipt_id,
        "registry_input_receipt_id": entry.package_receipt_id,
        "current_lock_sha256": "d" * 64,
        "rollback_lock_sha256": "d" * 64,
        "proposed_lock_sha256": "e" * 64,
        "proposed_entry": entry.model_dump(mode="json"),
        "evidence": ("evidence/install-plan.json",),
        "mutation_performed": False,
    }
    _bind_plan_id(payload)
    return payload


def _bind_plan_id(payload: dict[str, object]) -> None:
    identity = {
        key: value for key, value in payload.items() if key not in {"plan_id", "schema_version", "mutation_performed"}
    }
    if payload["status"] == "blocked":
        for field in ("operation", "proposed_lock_sha256", "proposed_entry"):
            identity.pop(field, None)
    payload["plan_id"] = f"install-plan-{canonical_json_sha256(identity)[:24]}"


def test_runtime_contracts_are_exported_and_registered() -> None:
    lock = RuntimeLock(entries=(_entry(),))
    assert lock.schema_version == "runtime-lock/v1"
    SchemaRegistry().validate("runtime-lock.v1", lock.model_dump(mode="json"))
    SchemaRegistry().validate("install-plan.v1", _planned_payload())


@pytest.mark.parametrize(
    "removed", ["candidate", "package_digest", "operation", "proposed_lock_sha256", "proposed_entry"]
)
def test_direct_draft_requires_planned_state_fields(removed: str) -> None:
    payload = _planned_payload()
    del payload[removed]
    errors = list(Draft202012Validator(SchemaRegistry().load("install-plan.v1")).iter_errors(payload))
    assert errors


def test_schema_registry_applies_cross_field_plan_invariants() -> None:
    payload = _planned_payload()
    payload["registry_input_receipt_id"] = "package-receipt-unrelated"
    with pytest.raises(ValidationError, match="registry input must match"):
        InstallPlan.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("install-plan.v1", payload)


def test_no_change_operation_requires_identical_lock_digests() -> None:
    payload = _planned_payload()
    payload["operation"] = "no_change"
    _bind_plan_id(payload)

    with pytest.raises(ValidationError, match="identical current and proposed"):
        InstallPlan.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("install-plan.v1", payload)


def test_install_operation_requires_distinct_lock_digests() -> None:
    payload = _planned_payload()
    payload["proposed_lock_sha256"] = payload["current_lock_sha256"]
    _bind_plan_id(payload)

    with pytest.raises(ValidationError, match="distinct current and proposed"):
        InstallPlan.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("install-plan.v1", payload)


@pytest.mark.parametrize(
    ("model_name", "field", "unsafe_value"),
    [
        ("runtime-lock", "package_receipt_id", "sk-live-secret"),
        ("runtime-lock", "registry_preparation_receipt_id", "ghp_leaked-token"),
        ("install-plan", "package_receipt_id", "sk-live-secret"),
        ("install-plan", "registry_preparation_receipt_id", "ghp_leaked-token"),
        ("install-plan", "registry_input_receipt_id", "sk-live-secret"),
    ],
)
def test_receipt_ids_reject_credential_shapes_across_boundaries(
    model_name: str,
    field: str,
    unsafe_value: str,
) -> None:
    if model_name == "runtime-lock":
        entry = _entry().model_dump(mode="json")
        entry[field] = unsafe_value
        payload = {"schema_version": "runtime-lock/v1", "entries": [entry]}
        with pytest.raises(ValidationError, match="receipt identity"):
            RuntimeLock.model_validate(payload)
        schema_name = "runtime-lock.v1"
    else:
        payload = _planned_payload()
        payload[field] = unsafe_value
        _bind_plan_id(payload)
        with pytest.raises(ValidationError, match="receipt identity"):
            InstallPlan.model_validate(payload)
        schema_name = "install-plan.v1"

    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate(schema_name, payload)
    assert list(Draft202012Validator(SchemaRegistry().load(schema_name)).iter_errors(payload))


def test_runtime_lock_rejects_duplicate_entries_and_files_across_boundaries() -> None:
    lock_payload = RuntimeLock(entries=(_entry(),)).model_dump(mode="json")
    lock_payload["entries"].append(deepcopy(lock_payload["entries"][0]))
    with pytest.raises(ValidationError, match="entries must be unique"):
        RuntimeLock.model_validate(lock_payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("runtime-lock.v1", lock_payload)
    assert list(Draft202012Validator(SchemaRegistry().load("runtime-lock.v1")).iter_errors(lock_payload))

    entry_payload = _entry().model_dump(mode="json")
    entry_payload["files"].append(deepcopy(entry_payload["files"][0]))
    with pytest.raises(ValidationError, match="file paths must be unique"):
        RuntimeLockEntry.model_validate(entry_payload)

    plan_payload = _planned_payload()
    proposed_entry = plan_payload["proposed_entry"]
    assert isinstance(proposed_entry, dict)
    proposed_files = proposed_entry["files"]
    assert isinstance(proposed_files, list)
    proposed_files.append(deepcopy(proposed_files[0]))
    _bind_plan_id(plan_payload)
    with pytest.raises(ValidationError, match="file paths must be unique"):
        InstallPlan.model_validate(plan_payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("install-plan.v1", plan_payload)
    assert list(Draft202012Validator(SchemaRegistry().load("install-plan.v1")).iter_errors(plan_payload))


def test_runtime_lock_rejects_forged_file_inventory_across_model_and_registry() -> None:
    payload = RuntimeLock(entries=(_entry(),)).model_dump(mode="json")
    payload["entries"][0]["files"][0]["sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="candidate digest must match runtime files"):
        RuntimeLock.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("runtime-lock.v1", payload)

    plan_payload = _planned_payload()
    plan_payload["proposed_entry"]["files"][0]["sha256"] = "f" * 64
    _bind_plan_id(plan_payload)
    with pytest.raises(ValidationError, match="candidate digest must match runtime files"):
        InstallPlan.model_validate(plan_payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("install-plan.v1", plan_payload)


@pytest.mark.parametrize(
    "value",
    [
        "runtime-package-v1",
        "evidence/review.json",
        "sk-live-secret",
        "token=plainvalue",
        "/" + "Users/alice/runtime.json",
        "C" + ":\\Users\\alice\\runtime.json",
    ],
)
def test_model_and_schema_public_text_patterns_remain_in_parity(value: str) -> None:
    schema_safe = (
        re.search(PUBLIC_TEXT_CREDENTIAL_SCHEMA_PATTERN, value) is None
        and re.search(MACHINE_PATH_SCHEMA_PATTERN, value) is None
    )
    assert lifecycle_text_is_public_safe(value) is schema_safe


@pytest.mark.parametrize(
    "observed_at",
    [
        "2026-13-01T09:00:00Z",
        "2026-08-32T09:00:00Z",
        "2026-08-29T24:00:00Z",
        "2026-08-29T09:60:00Z",
        "2026-08-29T09:00:60Z",
        "2026-08-29T09:00:00+24:00",
    ],
)
def test_direct_draft_rejects_out_of_range_rfc3339_components(observed_at: str) -> None:
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    observed_at_schema = schema["properties"]["observed_at"]
    assert list(Draft202012Validator(observed_at_schema).iter_errors(observed_at))


@pytest.mark.parametrize(
    "observed_at",
    [
        "2026-02-30T09:00:00Z",
        "2025-02-29T09:00:00Z",
    ],
)
def test_direct_draft_format_checker_rejects_impossible_calendar_dates(observed_at: str) -> None:
    schema = SchemaRegistry().load("package-safety-evidence.v1")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    payload = {
        "schema_version": "package-safety-evidence/v1",
        "observed_at": observed_at,
    }
    errors = list(validator.iter_errors(payload))
    assert any(error.validator == "format" and list(error.path) == ["observed_at"] for error in errors)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "evidence/" + "/" + "Us" + "ers/alice/runtime.json",
        "evidence/work" + "space/cache.json",
        "evidence/to" + "ken=plainvalue.json",
        "evidence/hf_" + "secret.json",
        "C" + ":\\Users\\alice\\runtime.json",
    ],
)
def test_runtime_public_paths_reject_credential_and_machine_shapes(unsafe_value: str) -> None:
    with pytest.raises(ValidationError):
        RuntimeFile(path=unsafe_value, sha256="c" * 64)
    entry = _entry().model_dump(mode="json")
    entry["files"][0]["path"] = unsafe_value
    payload = {"schema_version": "runtime-lock/v1", "entries": [entry]}
    with pytest.raises(ContractError):
        SchemaRegistry().validate("runtime-lock.v1", payload)
    assert list(Draft202012Validator(SchemaRegistry().load("runtime-lock.v1")).iter_errors(payload))


def test_blocked_plan_cannot_claim_transition_and_keeps_portable_blocker() -> None:
    payload = _planned_payload()
    blocker = RegistryPreparationBlocker(code="registry_blocked", message="Blocked by policy")
    payload.update(
        status="blocked",
        candidate=None,
        package_digest=None,
        operation=None,
        proposed_lock_sha256=None,
        proposed_entry=None,
        blocker=blocker.model_dump(mode="json"),
    )
    _bind_plan_id(payload)
    plan = InstallPlan.model_validate(payload)
    assert plan.mutation_performed is False
    SchemaRegistry().validate("install-plan.v1", payload)


@pytest.mark.parametrize(
    "unsafe_code",
    [
        "/" + "Users/alice/runtime.json",
        "to" + "ken=plainvalue",
        "C" + ":/root/install.json",
    ],
)
def test_blocked_plan_rejects_unsafe_blocker_codes_across_boundaries(unsafe_code: str) -> None:
    payload = _planned_payload()
    blocker = RegistryPreparationBlocker(code=unsafe_code, message="Blocked by policy")
    payload.update(
        status="blocked",
        candidate=None,
        package_digest=None,
        operation=None,
        proposed_lock_sha256=None,
        proposed_entry=None,
        blocker=blocker.model_dump(mode="json"),
    )
    _bind_plan_id(payload)
    with pytest.raises(ValidationError, match="blocker must not contain"):
        InstallPlan.model_validate(payload)
    with pytest.raises(ContractError, match="contract_validation_failed"):
        SchemaRegistry().validate("install-plan.v1", payload)
    assert list(Draft202012Validator(SchemaRegistry().load("install-plan.v1")).iter_errors(payload))
