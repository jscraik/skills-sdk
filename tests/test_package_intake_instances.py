from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt, build_intake_decision
from skills_sdk.models.package import IntakeChecks, IntakeDecision, IntakeDecisionStatus, PackageCandidateIdentity
from tests.test_package_intake import FIXTURE_ROOT, _context


def test_top_level_typed_intake_instances_are_revalidated() -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    assert SkillPackageIntakeReceipt.model_validate(receipt) == receipt
    assert SkillPackageIntakeContext.model_validate(receipt.context) == receipt.context
    context = receipt.context.model_copy(
        update={"source_repository": "https://example-user:FAKE_TOKEN@example.invalid/repo"}
    )
    source = receipt.source.model_copy(
        update={
            "provenance": receipt.source.provenance.model_copy(update={"repository": context.source_repository}),
        }
    )
    forged = receipt.model_copy(
        update={
            "context": context,
            "source": source,
            "normalized_package": receipt.normalized_package.model_copy(update={"source": source}),
        }
    )
    with pytest.raises(ValidationError, match="owner/repository slug"):
        SkillPackageIntakeReceipt.model_validate(forged)
    with pytest.raises(ValidationError, match="owner/repository slug"):
        SkillPackageIntakeContext.model_validate(context)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("skill-package-intake.v1", forged.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="owner/repository slug"):
        intake_skill_package(FIXTURE_ROOT, context)


@pytest.mark.parametrize("field", ["mutation_performed", "network_used", "execution_performed"])
def test_top_level_typed_receipt_revalidates_evidence_flags(field: str) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceipt.model_validate(receipt.model_copy(update={field: True}))


@pytest.mark.parametrize("family", ["context", "receipt"])
@pytest.mark.parametrize(
    "locator", ["https://user:FAKE_TOKEN@example.invalid/repo", "/example/checkout", "owner/repo\n"]
)
def test_direct_intake_schemas_reject_sensitive_locators(family: str, locator: str) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    payload = (receipt.context if family == "context" else receipt).model_dump(mode="json")
    context = payload if family == "context" else payload["context"]
    context["source_repository"] = locator
    schema = "skill-package-intake-context.v1" if family == "context" else "skill-package-intake.v1"
    validator = Draft202012Validator(SchemaRegistry().load(schema))
    assert not validator.is_valid(payload)
    context["source_repository"] = "Example-Team/repo.name_2"
    assert validator.is_valid(payload)


@pytest.mark.parametrize("field", ["identity", "provenance", "rights", "owner_unchanged"])
@pytest.mark.parametrize("value", ["yes", 1, None])
@pytest.mark.parametrize("construction", ["copy", "construct"])
def test_decision_helper_revalidates_typed_checks(field: str, value: object, construction: str) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    original = receipt.context.checks
    checks = (
        original.model_copy(update={field: value})
        if construction == "copy"
        else IntakeChecks.model_construct(**{**dict(original), field: value})
    )
    with pytest.raises(ValidationError):
        build_intake_decision(receipt.candidate, checks)


@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
@pytest.mark.parametrize("construction", ["copy", "construct"])
def test_decision_helper_revalidates_typed_candidate(field: str, construction: str) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    original = receipt.candidate
    candidate = (
        original.model_copy(update={field: "INVALID"})
        if construction == "copy"
        else PackageCandidateIdentity.model_construct(**{**dict(original), field: "INVALID"})
    )
    with pytest.raises(ValidationError):
        build_intake_decision(candidate, receipt.context.checks)


@pytest.mark.parametrize("owner_unchanged", [True, False])
def test_decision_helper_preserves_valid_typed_neighbors(owner_unchanged: bool) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    checks = receipt.context.checks.model_copy(update={"owner_unchanged": owner_unchanged})
    decision = build_intake_decision(receipt.candidate, checks)
    assert decision.decision is (
        IntakeDecisionStatus.ADMIT if owner_unchanged else IntakeDecisionStatus.NEEDS_OWNER_DECISION
    )
    assert IntakeDecision.model_validate(decision.model_dump(mode="json")) == decision
