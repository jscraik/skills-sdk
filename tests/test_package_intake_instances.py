from __future__ import annotations

import pytest
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
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
