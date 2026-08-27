from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.packaging import (
    PackageFileRole,
    PackageHardeningPolicy,
    PackageHardeningReceipt,
    PackageManifestFile,
)
from skills_sdk.packaging import build_skill_package, harden_skill_package

REVISION = "1" * 40


def _clock() -> datetime:
    return datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _skill(root: Path, *, readme: bool = True) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {root.name}\ndescription: Hardening fixture.\nmetadata:\n  version: 1.0.0\n---\n\n# Fixture\n",
        encoding="utf-8",
    )
    if readme:
        (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    return root


def test_hardening_passes_and_binds_exact_build_candidate(tmp_path: Path) -> None:
    package_receipt = build_skill_package(_skill(tmp_path / "fixture"), source_revision=REVISION, clock=_clock)

    receipt = harden_skill_package(package_receipt)

    assert receipt.status == "pass"
    assert receipt.candidate == package_receipt.candidate
    assert receipt.package_digest == package_receipt.package_digest
    assert receipt.blockers == ()
    assert receipt.mutation_performed is False
    SchemaRegistry().validate("package-hardening.v1", receipt.model_dump(mode="json"))


def test_hardening_blocks_missing_required_readme(tmp_path: Path) -> None:
    package_receipt = build_skill_package(
        _skill(tmp_path / "fixture", readme=False), source_revision=REVISION, clock=_clock
    )

    receipt = harden_skill_package(package_receipt)

    assert receipt.status == "blocked"
    assert receipt.package_digest is None
    assert {item.id for item in receipt.blockers} == {"required_package_roles"}


def test_hardening_policy_can_explicitly_make_readme_optional(tmp_path: Path) -> None:
    package_receipt = build_skill_package(
        _skill(tmp_path / "fixture", readme=False), source_revision=REVISION, clock=_clock
    )

    receipt = harden_skill_package(package_receipt, policy=PackageHardeningPolicy(require_readme=False))

    assert receipt.status == "pass"


def test_hardening_exposes_budget_warning_without_hiding_it(tmp_path: Path) -> None:
    package_receipt = build_skill_package(_skill(tmp_path / "fixture"), source_revision=REVISION, clock=_clock)

    receipt = harden_skill_package(package_receipt, policy=PackageHardeningPolicy(max_file_count=1))

    assert receipt.status == "pass"
    assert [item.id for item in receipt.warnings] == ["package_size_budget"]
    assert receipt.warnings[0] in receipt.hardening_checks


def test_hardening_blocks_forbidden_manifest_paths_without_mutation(tmp_path: Path) -> None:
    package_receipt = build_skill_package(_skill(tmp_path / "fixture"), source_revision=REVISION, clock=_clock)
    assert package_receipt.manifest is not None
    unsafe_file = PackageManifestFile(
        path="references/.env.production",
        sha256="0" * 64,
        size_bytes=0,
        role=PackageFileRole.REFERENCE,
    )
    manifest = package_receipt.manifest.model_copy(
        update={"files": (*package_receipt.manifest.files, unsafe_file)}
    )
    unsafe_receipt = package_receipt.model_copy(
        update={
            "manifest": manifest,
            "included_files": (*package_receipt.included_files, unsafe_file.path),
        }
    )

    receipt = harden_skill_package(unsafe_receipt)

    assert receipt.status == "blocked"
    assert {item.id for item in receipt.blockers} == {"forbidden_package_paths"}
    assert receipt.mutation_performed is False


def test_hardening_propagates_blocked_build_without_claiming_digest(tmp_path: Path) -> None:
    root = _skill(tmp_path / "fixture")
    (root / "SKILL.md").write_text(
        "---\nname: other\ndescription: Invalid identity.\n---\n", encoding="utf-8"
    )
    package_receipt = build_skill_package(root, source_revision=REVISION, clock=_clock)

    receipt = harden_skill_package(package_receipt)

    assert receipt.status == "blocked"
    assert receipt.package_digest is None
    assert "package_receipt_built" in {item.id for item in receipt.blockers}


def test_hardening_receipt_rejects_warning_projection_drift(tmp_path: Path) -> None:
    package_receipt = build_skill_package(_skill(tmp_path / "fixture"), source_revision=REVISION, clock=_clock)
    payload = harden_skill_package(package_receipt).model_dump(mode="json")
    payload["warnings"] = [payload["hardening_checks"][0]]

    with pytest.raises(ValidationError, match="projections"):
        PackageHardeningReceipt.model_validate(payload)
