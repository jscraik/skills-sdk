"""Explicit standalone-skill to complete-plugin candidate preparation."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import normalize_standalone_skill_package
from skills_sdk.models import PluginNormalizationMetadata, PluginPackageValidation, PluginValidationPolicy
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
from skills_sdk.models.package import IntakeChecks, PackageOwner, PackageSourceKind

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "synthetic-skill"


def _context(*, rights: bool = True) -> SkillPackageIntakeContext:
    owner = PackageOwner.model_validate(
        {
            "owner": "sdk-tests",
            "maintainer": "sdk-tests",
            "ownership_state": "canonical",
            "rights": {"basis": "authored", "license": "Apache-2.0", "evidence_ref": "source/SKILL.md"},
        }
    )
    return SkillPackageIntakeContext(
        source_repository="jscraik/skills-sdk",
        source_revision="1" * 40,
        source_path="synthetic-skill",
        source_kind=PackageSourceKind.GIT,
        owner=owner,
        checks=IntakeChecks(identity=True, provenance=True, rights=rights, owner_unchanged=True),
    )


def _normalize(source: Path, destination: Path, *, rights: bool = True):
    return normalize_standalone_skill_package(
        source,
        destination,
        _context(rights=rights),
        PluginNormalizationMetadata(
            name="synthetic-plugin",
            version="1.0.0",
            description="Synthetic one-skill plugin fixture.",
        ),
    )


def test_normalization_creates_bound_complete_plugin_without_changing_source(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    (source / "references").mkdir()
    (source / "references" / "guide.md").write_text("Reference material.\n", encoding="utf-8")
    (source / "evals").mkdir()
    (source / "evals" / "scenarios.json").write_text('{"cases": []}\n', encoding="utf-8")
    original = {
        path.relative_to(source): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in source.rglob("*")
        if path.is_file()
    }

    receipt = _normalize(source, tmp_path / "plugin")

    assert receipt.status == "prepared" and receipt.candidate_created
    assert (
        receipt.source_mutated is receipt.network_used is receipt.execution_performed is receipt.release_ready is False
    )
    assert receipt.plugin_validation is not None and receipt.plugin_validation.status == "pass"
    assert receipt.normalized_package is not None
    assert receipt.normalized_package.identity.name == "synthetic-plugin"
    assert len(receipt.plugin_validation.skills) == 1
    assert receipt.plugin_validation.skills[0].validation.candidate == receipt.source_intake.candidate
    manifest = json.loads((tmp_path / "plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "synthetic-plugin"
    assert (tmp_path / "plugin" / "skills" / "synthetic-skill" / "SKILL.md").read_bytes() == original[Path("SKILL.md")][
        0
    ]
    assert (tmp_path / "plugin" / "skills" / "synthetic-skill" / "references" / "guide.md").read_text(
        encoding="utf-8"
    ) == "Reference material.\n"
    assert (tmp_path / "plugin" / "skills" / "synthetic-skill" / "evals" / "scenarios.json").read_text(
        encoding="utf-8"
    ) == '{"cases": []}\n'
    assert (
        stat.S_IMODE((tmp_path / "plugin" / "skills" / "synthetic-skill" / "SKILL.md").stat().st_mode)
        == original[Path("SKILL.md")][1]
    )
    assert {
        path.relative_to(source): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in source.rglob("*")
        if path.is_file()
    } == original
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))


def test_normalization_blocks_unapproved_rights_without_creating_candidate(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    destination = tmp_path / "plugin"

    receipt = _normalize(source, destination, rights=False)

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "rights_unconfirmed"
    assert not destination.exists()
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))


def test_normalize_plugin_cli_emits_bound_receipt_and_preserves_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    source_skill = (source / "SKILL.md").read_bytes()
    context_path = tmp_path / "intake-context.json"
    context_path.write_text(_context().model_dump_json(), encoding="utf-8")

    result = main(
        [
            "normalize-plugin",
            str(source),
            str(tmp_path / "plugin"),
            "--context",
            str(context_path),
            "--plugin-name",
            "synthetic-plugin",
            "--plugin-version",
            "1.0.0",
            "--plugin-description",
            "Synthetic one-skill plugin fixture.",
            "--json",
            "--robot",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    payload = json.loads(output)
    assert payload["schema_version"] == "plugin-normalization/v1"
    assert payload["status"] == "prepared" and payload["release_ready"] is False
    assert payload["plugin_validation"]["skills"][0]["validation"]["candidate"] == payload["source_intake"]["candidate"]
    assert (source / "SKILL.md").read_bytes() == source_skill


def test_normalization_retains_standalone_validation_findings(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    (source / "SKILL.md").write_text("---\nname: other-skill\ndescription: Fixture.\n---\n", encoding="utf-8")

    receipt = _normalize(source, tmp_path / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "name_mismatch"
    assert not (tmp_path / "plugin").exists()


def test_normalization_does_not_overwrite_an_existing_destination(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    destination = tmp_path / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    receipt = _normalize(source, destination)

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "candidate_destination_exists"
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert tuple(path.name for path in destination.iterdir()) == ("keep.txt",)


def test_normalization_rejects_a_symlinked_destination_parent(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    real_parent = tmp_path / "real"
    linked_parent = tmp_path / "linked"
    shutil.copytree(FIXTURE_ROOT, source)
    real_parent.mkdir()
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    receipt = _normalize(source, linked_parent / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "candidate_normalization_failed"
    assert not (real_parent / "plugin").exists()


def test_normalization_rejects_output_inside_source_and_recovers(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    nested = _normalize(source, source / "plugin")

    assert nested.status == "blocked" and not nested.candidate_created
    assert nested.blocker is not None and nested.blocker.code == "candidate_normalization_failed"
    assert not (source / "plugin").exists()
    recovered = _normalize(source, tmp_path / "recovered-plugin")
    assert recovered.status == "prepared" and recovered.candidate_created


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "bad/name", "version": "1.0.0", "description": "Fixture."},
        {"name": "bad_name", "version": "1.0.0", "description": "Fixture."},
        {"name": "bad..name", "version": "1.0.0", "description": "Fixture."},
        {"name": "name", "version": " ", "description": "Fixture."},
        {"name": "name", "version": "1.0.0", "description": " padded "},
        {"name": "n" * 65, "version": "1.0.0", "description": "Fixture."},
    ],
)
def test_normalization_metadata_rejects_noncanonical_values(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        PluginNormalizationMetadata.model_validate(payload)


def test_normalization_metadata_uses_registered_schema() -> None:
    payload = PluginNormalizationMetadata(name="plugin", version="1.0.0", description="Fixture.").model_dump(
        mode="json"
    )

    SchemaRegistry().validate("plugin-normalization-metadata.v1", payload)


def test_normalization_metadata_schema_rejects_manifest_name_that_identity_cannot_accept() -> None:
    payload = {
        "schema_version": "plugin-normalization-metadata/v1",
        "name": "bad_name",
        "version": "1.0.0",
        "description": "Fixture.",
    }

    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization-metadata.v1", payload)


def test_normalization_rejects_unsafe_source_and_detects_change_after_intake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (source / "external.md").symlink_to(outside)
    unsafe = _normalize(source, tmp_path / "unsafe-plugin")
    assert unsafe.status == "blocked" and not unsafe.candidate_created
    assert not (tmp_path / "unsafe-plugin").exists()
    (source / "external.md").unlink()

    original = (source / "SKILL.md").read_bytes()
    actual_intake = normalization.intake_skill_package

    def changed_after_intake(root: Path, context: SkillPackageIntakeContext) -> SkillPackageIntakeReceipt:
        receipt = actual_intake(root, context)
        (root / "SKILL.md").write_bytes(original + b"\n# changed\n")
        return receipt

    monkeypatch.setattr(normalization, "intake_skill_package", changed_after_intake)
    changed = _normalize(source, tmp_path / "changed-plugin")
    assert changed.status == "blocked" and not changed.candidate_created
    assert changed.blocker is not None and changed.blocker.code == "source_changed"
    assert not (tmp_path / "changed-plugin").exists()
    (source / "SKILL.md").write_bytes(original)


def test_normalization_reports_capture_value_error_as_source_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    outside = tmp_path / "outside.md"
    shutil.copytree(FIXTURE_ROOT, source)
    outside.write_text("outside source", encoding="utf-8")
    actual_intake = normalization.intake_skill_package

    def mutate_after_intake(root: Path, context: SkillPackageIntakeContext) -> SkillPackageIntakeReceipt:
        receipt = actual_intake(root, context)
        (root / "external.md").symlink_to(outside)
        return receipt

    monkeypatch.setattr(normalization, "intake_skill_package", mutate_after_intake)

    receipt = _normalize(source, tmp_path / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "source_changed"
    assert not (tmp_path / "plugin").exists()


def test_normalization_receipt_rejects_forged_plugin_or_child_identity(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    receipt = _normalize(source, tmp_path / "plugin")
    assert receipt.status == "prepared"
    payload = receipt.model_dump(mode="json")
    payload["normalized_package"]["identity"]["package_id"] = "different-plugin"

    with pytest.raises(ValidationError):
        type(receipt).model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization.v1", payload)


def test_normalization_receipt_requires_normalized_lifecycle(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    receipt = _normalize(source, tmp_path / "plugin")
    assert receipt.status == "prepared"
    payload = receipt.model_dump(mode="json")
    payload["normalized_package"]["lifecycle"] = "admitted"

    with pytest.raises(ValidationError):
        type(receipt).model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization.v1", payload)


def test_normalization_receipt_requires_description_policy_and_metadata(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    receipt = _normalize(source, tmp_path / "plugin")
    assert receipt.status == "prepared"
    payload = receipt.model_dump(mode="json")
    payload["plugin_validation"]["policy"]["require_description"] = False
    payload["plugin_validation"]["manifest"]["description"] = None

    with pytest.raises(ValidationError):
        type(receipt).model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization.v1", payload)


def test_blocked_normalization_cannot_retain_validation_without_created_candidate(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    prepared = _normalize(source, tmp_path / "prepared")
    blocked = _normalize(source, tmp_path / "blocked", rights=False)
    assert prepared.status == "prepared" and blocked.blocker is not None
    payload = prepared.model_dump(mode="json")
    payload.update(
        status="blocked",
        normalized_package=None,
        blocker=blocked.blocker.model_dump(mode="json"),
        candidate_created=False,
    )

    with pytest.raises(ValidationError):
        type(prepared).model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization.v1", payload)


def test_normalization_rejects_destination_replacement_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    destination = tmp_path / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    validate = normalization.validate_plugin_package

    def validate_replaced_directory(
        root: Path,
        *,
        source_revision: str,
        policy: PluginValidationPolicy | None = None,
    ) -> PluginPackageValidation:
        manifest_path = root / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(name="attacker-plugin", version="9.9.9", description="Replacement.")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return validate(root, source_revision=source_revision, policy=policy)

    monkeypatch.setattr(normalization, "validate_plugin_package", validate_replaced_directory)
    receipt = _normalize(source, destination)

    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "normalized_candidate_changed"
    assert receipt.plugin_validation is not None and receipt.plugin_validation.status == "pass"
    assert receipt.normalized_package is None
