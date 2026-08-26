from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models import PackageInventoryRecord, PackageInventoryRecordV2

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/inventory"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_accepted_inventory_fixture_validates_against_model_and_schema() -> None:
    payload = _load("accepted.json")
    record = PackageInventoryRecord.model_validate(payload)
    SchemaRegistry().validate("package-inventory.v1", record.model_dump(mode="json"))
    assert record.mantra.overall.value == "pass"


def test_rejected_inventory_fixture_is_not_silently_coerced() -> None:
    with pytest.raises(ValidationError, match="plugin_bundle"):
        PackageInventoryRecord.model_validate(_load("rejected.json"))


def test_boundary_inventory_fixture_preserves_typed_blockers() -> None:
    record = PackageInventoryRecord.model_validate(_load("boundary.json"))
    assert record.source is None
    assert record.intended_disposition.value == "needs_owner_decision"
    assert set(record.blocker_codes) == {"canonical_source_unknown", "runtime_copy_not_source"}
    assert record.mantra.overall.value == "revise"


def test_v2_pending_value_fixture_preserves_typed_blocker() -> None:
    payload = _load("pending-value-review-v2.json")
    record = PackageInventoryRecordV2.model_validate(payload)
    SchemaRegistry().validate("package-inventory.v2", record.model_dump(mode="json"))
    assert record.value_decision.value == "needs_review"
    assert record.blocker_codes == ("value_review_required",)


def test_v1_model_rejects_the_v2_pending_value_fixture() -> None:
    with pytest.raises(ValidationError):
        PackageInventoryRecord.model_validate(_load("pending-value-review-v2.json"))


@pytest.mark.parametrize(
    "changes",
    [
        {"blocker_codes": []},
        {"intended_disposition": "admit_to_foundry"},
    ],
)
def test_v2_schema_rejects_unblocked_pending_value_review(changes: dict[str, object]) -> None:
    payload = _load("pending-value-review-v2.json")
    payload.update(changes)
    with pytest.raises(ContractError, match=r"package-inventory\.v2 rejected"):
        SchemaRegistry().validate("package-inventory.v2", payload)


def test_generated_inventory_schemas_have_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_schemas.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
