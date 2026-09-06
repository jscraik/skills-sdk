"""Intake-local public-owner boundary; frozen shared owner contracts stay intact."""

from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
from skills_sdk.models.package import PackageOwner
from tests.test_package_intake import FIXTURE_ROOT, _context


def _replace(owner: dict[str, object], field: str, value: object) -> None:
    if field == "license":
        owner["rights"]["license"] = value
    else:
        owner[field] = value


@pytest.mark.parametrize("field", ["owner", "maintainer", "license"])
@pytest.mark.parametrize(
    "value",
    [
        "/fixture/private",
        "token=FIXTURE_NOT_REAL",
        "sk-fixture-not-real",
        "Team (/fixture/example)",
        r"C:\Fixture\private",
        r"\\server\private",
        "~/private",
        "$HOME/private",
        "${HOME}/private",
        "%USERPROFILE%/private",
        "file:///example/private",
        "https://user:FIXTURE_NOT_REAL@example.invalid/license",
        "api_key : FIXTURE_NOT_REAL",
        "Bearer FIXTURE_NOT_REAL",
        "prefix ghp_fixture_not_real",
        "AIza" + "0" * 35,
        "AKIA" + "0" * 16,
    ],
)
def test_sensitive_owner_metadata_rejected_by_every_intake_boundary(field: str, value: str) -> None:
    context = _context()
    raw = context.model_dump(mode="json")
    _replace(raw["owner"], field, value)
    legacy_owner = PackageOwner.model_validate(raw["owner"])
    forged = context.model_copy(update={"owner": legacy_owner})
    with pytest.raises(ValidationError):
        SkillPackageIntakeContext.model_validate(raw)
    with pytest.raises(ValidationError):
        SkillPackageIntakeContext.model_validate(forged)
    with pytest.raises(ValidationError):
        intake_skill_package(FIXTURE_ROOT, forged)
    assert not Draft202012Validator(SchemaRegistry().load("skill-package-intake-context.v1")).is_valid(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("skill-package-intake-context.v1", raw)

    receipt = intake_skill_package(FIXTURE_ROOT, context)
    payload = receipt.model_dump(mode="json")
    payload["context"]["owner"] = deepcopy(raw["owner"])
    payload["normalized_package"]["owner"] = deepcopy(raw["owner"])
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceipt.model_validate(
            receipt.model_copy(
                update={
                    "context": forged,
                    "normalized_package": receipt.normalized_package.model_copy(update={"owner": legacy_owner}),
                }
            )
        )
    assert not Draft202012Validator(SchemaRegistry().load("skill-package-intake.v1")).is_valid(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


@pytest.mark.parametrize("field", ["owner", "maintainer", "license"])
@pytest.mark.parametrize(
    "value",
    [
        "Example Team",
        "Alice/Bob",
        "Aiza Khan",
        "Aizah Khan",
        "Akia Smith",
        "Akian Team",
        "Bearer",
        "MIT OR Apache-2.0",
        "LicenseRef-company-policy",
        "https://example.invalid/license",
    ],
)
def test_public_owner_metadata_neighbors_remain_valid(field: str, value: str) -> None:
    payload = _context().model_dump(mode="json")
    _replace(payload["owner"], field, value)
    context = SkillPackageIntakeContext.model_validate(payload)
    receipt = intake_skill_package(FIXTURE_ROOT, context)
    assert receipt.status == "normalized"
    actual = receipt.normalized_package.owner.model_dump(mode="json")
    assert (actual["rights"]["license"] if field == "license" else actual[field]) == value
    for name, model in [("skill-package-intake-context.v1", context), ("skill-package-intake.v1", receipt)]:
        wire = model.model_dump(mode="json")
        Draft202012Validator(SchemaRegistry().load(name)).validate(wire)
        SchemaRegistry().validate(name, wire)


@pytest.mark.parametrize("field", ["owner", "maintainer", "license"])
def test_serialized_normalized_owner_sibling_is_screened(field: str) -> None:
    payload = intake_skill_package(FIXTURE_ROOT, _context()).model_dump(mode="json")
    _replace(payload["normalized_package"]["owner"], field, "/fixture/private")
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceipt.model_validate(payload)
    assert not Draft202012Validator(SchemaRegistry().load("skill-package-intake.v1")).is_valid(payload)
