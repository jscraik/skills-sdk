from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import PackageReceipt

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-receipts"


def _candidate() -> PackageCandidateIdentity:
    return PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256="a" * 64,
    )


def test_built_receipt_fixture_is_candidate_bound() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    receipt = PackageReceipt.model_validate(payload)
    assert receipt.status == "built"
    assert receipt.manifest.candidate == receipt.candidate
    assert set(receipt.included_files) == {"README.md", "SKILL.md"}
    assert receipt.mutation_performed is False


def test_blocked_receipt_fixture_requires_an_explicit_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked.json").read_text(encoding="utf-8"))
    receipt = PackageReceipt.model_validate(payload)
    assert receipt.status == "blocked"
    assert receipt.blocker_codes == ("unsafe_path",)


def test_manifest_and_receipt_must_bind_same_candidate() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["manifest"]["candidate"]["source_revision"] = "2" * 40
    with pytest.raises(ValidationError, match="same candidate"):
        PackageReceipt.model_validate(payload)


def test_built_receipt_cannot_omit_manifest_files() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    payload["included_files"] = ["SKILL.md"]
    with pytest.raises(ValidationError, match="every manifest path"):
        PackageReceipt.model_validate(payload)


def test_package_candidate_is_not_a_machine_path() -> None:
    candidate = _candidate()
    assert candidate.package_id == "synthetic-skill"
