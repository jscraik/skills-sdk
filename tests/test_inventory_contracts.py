from __future__ import annotations

import pytest
from pydantic import ValidationError

from skills_sdk.models import PackageDisposition, PackageInventory, PackageInventoryRecord, PackageType


def _record(package_id: str = "synthetic-skill") -> PackageInventoryRecord:
    return PackageInventoryRecord(
        package_id=package_id,
        package_type=PackageType.SKILL,
        current_path="skills/synthetic-skill",
        declared_version="0.1.0",
        owner="synthetic-owner",
        source={
            "repository": "https://example.invalid/source.git",
            "revision": "1" * 40,
            "path": "skills/synthetic-skill",
            "content_sha256": "a" * 64,
        },
        rights={"basis": "authored", "license": "Apache-2.0", "evidence_ref": "evidence/rights.json"},
        direct_consumers=("tests/fixtures/synthetic-skill/SKILL.md",),
        runtime_visibility=(),
        intended_disposition=PackageDisposition.ADMIT_TO_FOUNDRY,
    )


def test_inventory_record_is_frozen_and_versioned() -> None:
    record = _record()
    assert record.schema_version == "package-inventory/v1"
    with pytest.raises(ValidationError):
        record.current_path = "other/path"  # type: ignore[misc]


def test_inventory_rejects_absolute_or_escaping_paths() -> None:
    with pytest.raises(ValidationError, match="invalid_portable_path"):
        PackageInventoryRecord.model_validate(
            _record().model_dump() | {"current_path": "/tmp/skills/synthetic-skill"}
        )
    with pytest.raises(ValidationError, match="invalid_portable_path"):
        PackageInventoryRecord.model_validate(_record().model_dump() | {"current_path": "../skills/synthetic-skill"})


def test_duplicate_disposition_requires_distinct_target() -> None:
    with pytest.raises(ValidationError, match="duplicate_of"):
        PackageInventoryRecord.model_validate(_record().model_dump() | {"intended_disposition": "reject_duplicate"})


def test_unknown_provenance_is_a_typed_owner_decision() -> None:
    payload = _record().model_dump()
    payload.update(
        source=None,
        rights=None,
        blocker_codes=("provenance_unknown",),
        intended_disposition=PackageDisposition.NEEDS_OWNER_DECISION,
    )
    record = PackageInventoryRecord.model_validate(payload)
    assert record.blocker_codes == ("provenance_unknown",)


def test_inventory_rejects_duplicate_package_ids() -> None:
    with pytest.raises(ValidationError, match="package_id values must be unique"):
        PackageInventory(source_revision="1" * 40, records=(_record(), _record()))
