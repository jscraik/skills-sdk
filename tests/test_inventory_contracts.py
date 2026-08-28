from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from skills_sdk.models import (
    MantraStatus,
    PackageDisposition,
    PackageInventory,
    PackageInventoryRecord,
    PackageInventoryRecordV2,
    PackageInventoryV2,
    PackageType,
    RecommendedMechanism,
    ValueDecision,
    ValueDecisionV2,
)


def _mantra(status: str = "pass") -> dict[str, object]:
    principle = {"status": status, "evidence": ["tests/test_inventory_contracts.py"]}
    return {
        "source_revision": "1" * 40,
        "content_sha256": "a" * 64,
        "taste": principle,
        "thin_surfaces": principle,
        "strong_guardrails": principle,
        "simplicity": principle,
        "progressive_disclosure": principle,
        "durable_memory": principle,
        "valuemaxxing": principle,
        "self_improvement": principle,
        "professional_output": principle,
        "overall": status,
    }


def _record(package_id: str = "synthetic-skill") -> PackageInventoryRecord:
    return PackageInventoryRecord.model_validate(
        {
            "package_id": package_id,
            "package_type": PackageType.SKILL,
            "current_path": "skills/synthetic-skill",
            "declared_version": "0.1.0",
            "owner": "synthetic-owner",
            "user_outcome": "make a source-bound package admission decision",
            "distinctive_value": "keeps package identity and rights evidence together",
            "maintenance_cost": "one catalog record and one SDK contract",
            "context_cost": "loaded only during inventory or admission review",
            "overlap_with_existing": (),
            "recommended_mechanism": RecommendedMechanism.STANDALONE_SKILL,
            "value_decision": ValueDecision.RETAIN,
            "mantra": _mantra(),
            "source": {
                "repository": "https://example.invalid/source.git",
                "revision": "1" * 40,
                "path": "skills/synthetic-skill",
                "content_sha256": "a" * 64,
            },
            "rights": {
                "basis": "authored",
                "license": "Apache-2.0",
                "evidence_ref": "evidence/rights.json",
            },
            "direct_consumers": ("tests/fixtures/synthetic-skill/SKILL.md",),
            "runtime_visibility": (),
            "intended_disposition": PackageDisposition.ADMIT_TO_FOUNDRY,
        },
    )


def test_inventory_record_is_frozen_and_versioned() -> None:
    record = _record()
    assert record.schema_version == "package-inventory/v1"
    assert record.mantra.overall is MantraStatus.PASS
    with pytest.raises(ValidationError):
        field_name = "current_path"
        setattr(record, field_name, "other/path")


def test_inventory_rejects_absolute_or_escaping_paths() -> None:
    with pytest.raises(ValidationError, match="invalid_portable_path"):
        PackageInventoryRecord.model_validate(
            _record().model_dump() | {"current_path": "/" + "tmp/skills/synthetic-skill"}
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
        mantra=_mantra("revise"),
        intended_disposition=PackageDisposition.NEEDS_OWNER_DECISION,
    )
    record = PackageInventoryRecord.model_validate(payload)
    assert record.blocker_codes == ("provenance_unknown",)


def test_mantra_status_rollup_and_candidate_binding_are_enforced() -> None:
    invalid_overall = _mantra()
    invalid_overall["overall"] = "revise"
    with pytest.raises(ValidationError, match="mantra overall must be pass"):
        PackageInventoryRecord.model_validate(_record().model_dump() | {"mantra": invalid_overall})

    mismatched: dict[str, Any] = _record().model_dump()
    mismatched["mantra"] = _mantra()
    mismatched["mantra"]["content_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="exact source revision and content digest"):
        PackageInventoryRecord.model_validate(mismatched)


def test_merge_value_decision_requires_overlap_evidence() -> None:
    payload = _record().model_dump()
    payload.update(value_decision=ValueDecision.MERGE, recommended_mechanism=RecommendedMechanism.STANDALONE_SKILL)
    with pytest.raises(ValidationError, match="overlap_with_existing"):
        PackageInventoryRecord.model_validate(payload)


def test_pending_value_review_is_a_typed_blocker() -> None:
    payload = _record().model_dump()
    payload.update(
        schema_version="package-inventory/v2",
        value_decision=ValueDecisionV2.NEEDS_REVIEW,
        blocker_codes=("value_review_required",),
        mantra=_mantra("revise"),
        intended_disposition=PackageDisposition.NEEDS_OWNER_DECISION,
    )
    record = PackageInventoryRecordV2.model_validate(payload)
    assert record.value_decision is ValueDecisionV2.NEEDS_REVIEW


def test_v2_inventory_record_preserves_v1_python_inheritance() -> None:
    assert issubclass(PackageInventoryRecordV2, PackageInventoryRecord)


@pytest.mark.parametrize(
    ("disposition", "blocker_codes"),
    [
        (PackageDisposition.ADMIT_TO_FOUNDRY, ("value_review_required",)),
        (PackageDisposition.NEEDS_OWNER_DECISION, ()),
    ],
)
def test_pending_value_review_rejects_unblocked_or_admitted_candidates(
    disposition: PackageDisposition,
    blocker_codes: tuple[str, ...],
) -> None:
    payload = _record().model_dump()
    payload.update(
        schema_version="package-inventory/v2",
        value_decision=ValueDecisionV2.NEEDS_REVIEW,
        blocker_codes=blocker_codes,
        mantra=_mantra("pass" if disposition == PackageDisposition.ADMIT_TO_FOUNDRY else "revise"),
        intended_disposition=disposition,
    )
    with pytest.raises(ValidationError, match="needs_review value decision"):
        PackageInventoryRecordV2.model_validate(payload)


def test_v1_inventory_rejects_the_v2_pending_review_value() -> None:
    payload = _record().model_dump()
    payload["value_decision"] = "needs_review"
    with pytest.raises(ValidationError, match=r"retain.*merge.*replace.*retire"):
        PackageInventoryRecord.model_validate(payload)


def test_v2_inventory_set_requires_v2_records() -> None:
    record = PackageInventoryRecordV2.model_validate(
        _record().model_dump()
        | {
            "schema_version": "package-inventory/v2",
            "value_decision": "needs_review",
            "blocker_codes": ("value_review_required",),
            "mantra": _mantra("revise"),
            "intended_disposition": "needs_owner_decision",
        }
    )
    inventory = PackageInventoryV2(source_revision="1" * 40, records=(record,))
    assert inventory.schema_version == "package-inventory-set/v2"


def test_v1_inventory_set_rejects_a_constructed_v2_record() -> None:
    record = PackageInventoryRecordV2.model_validate(
        _record().model_dump()
        | {
            "schema_version": "package-inventory/v2",
            "value_decision": "needs_review",
            "blocker_codes": ("value_review_required",),
            "mantra": _mantra("revise"),
            "intended_disposition": "needs_owner_decision",
        }
    )
    with pytest.raises(ValidationError, match=r"set/v1 requires package-inventory/v1"):
        PackageInventory.model_validate({"source_revision": "1" * 40, "records": (record,)})


def test_inventory_rejects_duplicate_package_ids() -> None:
    with pytest.raises(ValidationError, match="package_id values must be unique"):
        PackageInventory(source_revision="1" * 40, records=(_record(), _record()))


def test_v1_inventory_set_accepts_raw_v1_record_mapping() -> None:
    inventory = PackageInventory.model_validate(
        {"source_revision": "1" * 40, "records": (_record().model_dump(mode="json"),)}
    )

    assert inventory.records[0].schema_version == "package-inventory/v1"
