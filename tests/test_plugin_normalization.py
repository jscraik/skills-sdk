"""Explicit standalone-skill to complete-plugin candidate preparation."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
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
    """Create synthetic ownership evidence with an explicit rights decision."""
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
    """Prepare a synthetic one-skill plugin through the public API."""
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
    """Bind the copied child and manifest while preserving every source file and mode."""
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
    """Reject unconfirmed rights before creating any destination."""
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
    """Return source-bound CLI evidence without altering the standalone input."""
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
    """Preserve the original validation blocker instead of preparing invalid source."""
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    (source / "SKILL.md").write_text("---\nname: other-skill\ndescription: Fixture.\n---\n", encoding="utf-8")

    receipt = _normalize(source, tmp_path / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "name_mismatch"
    assert not (tmp_path / "plugin").exists()


def test_normalization_does_not_overwrite_an_existing_destination(tmp_path: Path) -> None:
    """Reject an occupied destination without replacing its caller-owned contents."""
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
    """Reject destination-parent symlinks before writing through them."""
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
    """Block nested output and permit a corrected separate destination."""
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
    """Reject metadata outside the canonical manifest and identity constraints."""
    with pytest.raises(ValidationError):
        PluginNormalizationMetadata.model_validate(payload)


def test_normalization_metadata_uses_registered_schema() -> None:
    """Accept valid metadata through its registered public schema."""
    payload = PluginNormalizationMetadata(name="plugin", version="1.0.0", description="Fixture.").model_dump(
        mode="json"
    )

    SchemaRegistry().validate("plugin-normalization-metadata.v1", payload)


def test_normalization_metadata_schema_rejects_manifest_name_that_identity_cannot_accept() -> None:
    """Keep schema admission aligned with the service's manifest-name boundary."""
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
    """Reject unsafe resources and bytes that change after admitted intake."""
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
        """Change the captured entrypoint after returning genuine intake evidence."""
        receipt = actual_intake(root, context)
        (root / "SKILL.md").write_bytes(original + b"\n# changed\n")
        return receipt

    monkeypatch.setattr(normalization, "intake_skill_package", changed_after_intake)
    changed = _normalize(source, tmp_path / "changed-plugin")
    assert changed.status == "blocked" and not changed.candidate_created
    assert changed.blocker is not None and changed.blocker.code == "source_changed"
    assert not (tmp_path / "changed-plugin").exists()
    (source / "SKILL.md").write_bytes(original)


def test_normalization_reports_unsafe_capture_without_claiming_observed_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report unsupported capture without claiming that two snapshots were compared."""
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    outside = tmp_path / "outside.md"
    shutil.copytree(FIXTURE_ROOT, source)
    outside.write_text("outside source", encoding="utf-8")
    actual_intake = normalization.intake_skill_package

    def mutate_after_intake(root: Path, context: SkillPackageIntakeContext) -> SkillPackageIntakeReceipt:
        """Introduce an unsafe resource after the source has been admitted."""
        receipt = actual_intake(root, context)
        (root / "external.md").symlink_to(outside)
        return receipt

    monkeypatch.setattr(normalization, "intake_skill_package", mutate_after_intake)

    receipt = _normalize(source, tmp_path / "plugin")

    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "standalone_source_capture_blocked"
    assert not (tmp_path / "plugin").exists()


def test_normalization_receipt_rejects_forged_plugin_or_child_identity(tmp_path: Path) -> None:
    """Reject normalized-package identity that conflicts with retained validation."""
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
    """Reject a prepared receipt claiming a lifecycle the operation did not produce."""
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
    """Reject prepared proof that weakens the service's required-description policy."""
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
    """Require retained validation to acknowledge the destination it inspected."""
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
    """Reject a passing validation of manifest bytes this invocation did not generate."""
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
        """Replace generated metadata before obtaining genuine whole-plugin validation."""
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


@pytest.mark.parametrize("mutation", ["manifest", "skill", "directory", "permissions", "symlink"])
def test_normalization_rechecks_destination_after_validation_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Block changes after a passing validation and permit a fresh corrected candidate."""
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    destination = tmp_path / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    original = (source / "SKILL.md").read_bytes()
    validate = normalization.validate_plugin_package

    def validate_then_change(
        root: Path, *, source_revision: str, policy: PluginValidationPolicy | None = None
    ) -> PluginPackageValidation:
        """Return genuine validation after introducing the selected destination drift."""
        validation = validate(root, source_revision=source_revision, policy=policy)
        child = root / "skills" / "synthetic-skill" / "SKILL.md"
        if mutation == "manifest":
            manifest_path = root / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["description"] = "Changed after validation."
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        elif mutation == "skill":
            child.write_bytes(original + b"\nChanged after validation.\n")
        elif mutation == "directory":
            (root / "unvalidated").mkdir()
        elif mutation == "permissions":
            child.chmod(0o600)
        else:
            child.unlink()
            child.symlink_to(source / "SKILL.md")
        return validation

    with monkeypatch.context() as patch:
        patch.setattr(normalization, "validate_plugin_package", validate_then_change)
        receipt = _normalize(source, destination)

    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None
    expected = "normalized_candidate_recheck_failed" if mutation == "symlink" else "normalized_candidate_changed"
    assert receipt.blocker.code == expected
    assert receipt.plugin_validation is not None and receipt.plugin_validation.status == "pass"
    assert receipt.normalized_package is None
    assert (source / "SKILL.md").read_bytes() == original
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))
    recovered = _normalize(source, tmp_path / "recovered-plugin")
    assert recovered.status == "prepared" and recovered.candidate_created


def test_normalization_rejects_directory_replacement_during_final_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical copied bytes must not conceal replacement of the directory this invocation created."""
    from skills_sdk.intake import plugin_normalization as normalization
    from skills_sdk.models.plugin import PluginCapturedFile

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    destination = tmp_path / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    capture = normalization.capture_plugin_source

    def capture_then_replace(root: Path) -> tuple[tuple[PluginCapturedFile, ...], dict[str, bytes], tuple[str, ...]]:
        """Replace the captured directory with equal bytes but a different inode."""
        observed = capture(root)
        if root == destination:
            retained = tmp_path / "retained-original"
            root.rename(retained)
            shutil.copytree(retained, root)
        return observed

    with monkeypatch.context() as patch:
        patch.setattr(normalization, "capture_plugin_source", capture_then_replace)
        receipt = _normalize(source, destination)

    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "normalized_candidate_changed"
    assert receipt.normalized_package is None
    assert _normalize(source, tmp_path / "recovered-plugin").status == "prepared"


@pytest.mark.parametrize("representation", ["raw", "copy", "construct"])
def test_normalization_receipt_rejects_forged_dependency_metadata(tmp_path: Path, representation: str) -> None:
    """The dependency-free normalization result cannot acquire unverified dependencies."""
    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    receipt = _normalize(source, tmp_path / "plugin")
    assert receipt.status == "prepared"
    assert receipt.normalized_package is not None and receipt.normalized_package.dependencies == ()
    payload = receipt.model_dump(mode="json")
    validator = Draft202012Validator(SchemaRegistry().load("plugin-normalization.v1"))
    validator.validate(payload)
    payload["normalized_package"]["dependencies"] = ["unverified-dependency"]

    with pytest.raises(SchemaValidationError):
        validator.validate(payload)
    normalized = receipt.normalized_package.model_copy(update={"dependencies": ("unverified-dependency",)})
    forged = payload
    if representation == "copy":
        forged = receipt.model_copy(update={"normalized_package": normalized})
    elif representation == "construct":
        forged = type(receipt).model_construct(**{**receipt.__dict__, "normalized_package": normalized})
    with pytest.raises(ValidationError):
        type(receipt).model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-normalization.v1", payload)


@pytest.mark.parametrize("representation", ["raw", "copy", "construct"])
def test_blocked_normalization_rejects_passing_validation_for_another_source(
    tmp_path: Path, representation: str
) -> None:
    """Retained passing proof must bind the original source even when creation was blocked."""
    from skills_sdk.models.packaging import PackageReceiptBlocker

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    foreign = tmp_path / "other-source" / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    shutil.copytree(FIXTURE_ROOT, foreign)
    (foreign / "SKILL.md").write_bytes((foreign / "SKILL.md").read_bytes() + b"\nDifferent captured source.\n")
    prepared = _normalize(source, tmp_path / "plugin")
    other = _normalize(foreign, tmp_path / "other-plugin")
    assert prepared.status == other.status == "prepared" and other.plugin_validation is not None
    payload = prepared.model_dump(mode="json")
    payload.update(
        status="blocked",
        normalized_package=None,
        blocker=PackageReceiptBlocker(code="normalization_test_blocked", message="Fixture stop.").model_dump(
            mode="json"
        ),
    )
    neighbor = type(prepared).model_validate(payload)
    registry = SchemaRegistry()
    registry.validate("plugin-normalization.v1", payload)
    forged_payload = {**payload, "plugin_validation": other.plugin_validation.model_dump(mode="json")}
    # JSON Schema checks structure; the model/registry enforce cross-candidate equality.
    Draft202012Validator(registry.load("plugin-normalization.v1")).validate(forged_payload)
    forged = forged_payload
    if representation == "copy":
        forged = neighbor.model_copy(update={"plugin_validation": other.plugin_validation})
    elif representation == "construct":
        forged = type(neighbor).model_construct(**{**neighbor.__dict__, "plugin_validation": other.plugin_validation})
    with pytest.raises(ValidationError):
        type(prepared).model_validate(forged)
    with pytest.raises(ContractError):
        registry.validate("plugin-normalization.v1", forged_payload)
    registry.validate("plugin-normalization.v1", payload)


def test_normalization_retains_binding_failure_without_foreign_passing_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed destination child retains its blocker, not unrelated passing source proof."""
    from skills_sdk.intake import plugin_normalization as normalization

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    original = (source / "SKILL.md").read_bytes()
    validate = normalization.validate_plugin_package

    def validate_changed_child(
        root: Path, *, source_revision: str, policy: PluginValidationPolicy | None = None
    ) -> PluginPackageValidation:
        """Obtain passing validation for a child that no longer matches the source."""
        child = root / "skills" / "synthetic-skill" / "SKILL.md"
        child.write_bytes(child.read_bytes() + b"\nDifferent captured destination.\n")
        return validate(root, source_revision=source_revision, policy=policy)

    with monkeypatch.context() as patch:
        patch.setattr(normalization, "validate_plugin_package", validate_changed_child)
        receipt = _normalize(source, tmp_path / "changed-plugin")
    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "standalone_candidate_binding_mismatch"
    assert receipt.plugin_validation is None and receipt.normalized_package is None
    assert (source / "SKILL.md").read_bytes() == original
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))
    assert _normalize(source, tmp_path / "corrected-plugin").status == "prepared"


@pytest.mark.parametrize("character", ["a", "é", "💡", '"', "\\", "\x00"])
@pytest.mark.parametrize("field", ["version", "description"])
def test_normalization_metadata_enforces_exact_serialized_byte_budget(character: str, field: str) -> None:
    """Accept exactly one MiB and reject the next encoded byte, including JSON escapes."""
    from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI

    values = {"name": "synthetic-plugin", "version": "v", "description": "d"}
    values[field] = ""
    overhead = len((json.dumps({"$schema": PLUGIN_SCHEMA_URI, **values}, ensure_ascii=False, indent=2) + "\n").encode())
    cost = len(json.dumps(character, ensure_ascii=False).encode()) - 2
    count, remainder = divmod(1_048_576 - overhead, cost)
    values[field] = character * count + "a" * remainder
    accepted = PluginNormalizationMetadata.model_validate(values)
    registry = SchemaRegistry()
    registry.validate("plugin-normalization-metadata.v1", accepted.model_dump(mode="json"))
    invalid = {**values, field: values[field] + "a"}
    # Necessary per-field limits cannot express the aggregate UTF-8/escaping budget.
    Draft202012Validator(registry.load("plugin-normalization-metadata.v1")).validate(invalid)
    for payload in (invalid, accepted.model_copy(update={field: invalid[field]})):
        with pytest.raises(ValidationError):
            PluginNormalizationMetadata.model_validate(payload)
    with pytest.raises(ContractError):
        registry.validate("plugin-normalization-metadata.v1", invalid)
    registry.validate("plugin-normalization-metadata.v1", values)


def test_normalization_metadata_budget_combines_fields_and_rejects_invalid_unicode() -> None:
    """Reject combined oversized fields and unencodable input without coercion."""
    registry = SchemaRegistry()
    for values in (
        {"name": "synthetic-plugin", "version": "v" * 600_000, "description": "d" * 600_000},
        {"name": "synthetic-plugin", "version": "v", "description": "bad\ud800unicode"},
    ):
        with pytest.raises(ValidationError):
            PluginNormalizationMetadata.model_validate(values)
        with pytest.raises(ContractError):
            registry.validate("plugin-normalization-metadata.v1", values)
    registry.validate(
        "plugin-normalization-metadata.v1", {"name": "synthetic-plugin", "version": "v", "description": "d"}
    )


@pytest.mark.parametrize("limit", ["MAX_FILE_BYTES", "MAX_FILES", "MAX_TOTAL_BYTES"])
def test_normalization_stable_capture_limits_block_without_false_drift_and_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    """An admitted unchanged source exceeding plugin bounds needs correction, not a drift retry."""
    from skills_sdk.intake import intake_skill_package
    from skills_sdk.validation import plugin_capture

    tmp_path = tmp_path.resolve(strict=True)
    source = tmp_path / "synthetic-skill"
    shutil.copytree(FIXTURE_ROOT, source)
    original = (source / "SKILL.md").read_bytes()
    admitted = intake_skill_package(source, _context())
    assert admitted.status == "normalized" and admitted.decision.decision.value == "admit"
    with monkeypatch.context() as patch:
        patch.setattr(plugin_capture, limit, 0)
        receipt = _normalize(source, tmp_path / "bounded-plugin")
    assert receipt.status == "blocked" and not receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "standalone_source_capture_blocked"
    assert receipt.source_intake.candidate == admitted.candidate
    assert not (tmp_path / "bounded-plugin").exists() and (source / "SKILL.md").read_bytes() == original
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))
    assert _normalize(source, tmp_path / "corrected-plugin").status == "prepared"


@pytest.mark.parametrize("mutation", ["root-file", "format", "mode", "extra-field", "settings"])
@pytest.mark.parametrize("representation", ["raw", "copy", "construct"])
def test_prepared_normalization_rejects_genuine_validation_outside_created_output(
    tmp_path: Path, mutation: str, representation: str
) -> None:
    """Genuine plugin validation is not proof of the exact output normalization creates."""
    from skills_sdk.validation import validate_plugin_package

    tmp_path = tmp_path.resolve(strict=True)
    source, destination = tmp_path / "synthetic-skill", tmp_path / "plugin"
    shutil.copytree(FIXTURE_ROOT, source)
    prepared = _normalize(source, destination)
    assert prepared.status == "prepared" and prepared.normalized_package is not None
    manifest_path = destination / "plugin.json"
    original = manifest_path.read_bytes()
    if mutation == "root-file":
        (destination / "extra.md").write_text("Not created by normalization.\n", encoding="utf-8")
    elif mutation == "mode":
        manifest_path.chmod(0o600)
    else:
        manifest = json.loads(original)
        if mutation == "extra-field":
            manifest["homepage"] = "https://example.com"
        elif mutation == "settings":
            manifest["extensions"] = {"com.openai": {"display_name": "Other presentation"}}
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    validation = validate_plugin_package(
        destination, source_revision="1" * 40, policy=prepared.plugin_validation.policy
    )
    assert validation.status == "pass" and validation.candidate is not None
    assert validation.skills[0].validation.candidate == prepared.source_intake.candidate
    normalized = prepared.normalized_package.model_dump(mode="json")
    normalized["source"]["provenance"]["content_sha256"] = validation.candidate.content_sha256
    normalized_model = type(prepared.normalized_package).model_validate(normalized)
    payload = prepared.model_dump(mode="json")
    payload.update(plugin_validation=validation.model_dump(mode="json"), normalized_package=normalized)
    registry = SchemaRegistry()
    # Structural JSON Schema does not authenticate hashes or enforce output closure.
    Draft202012Validator(registry.load("plugin-normalization.v1")).validate(payload)
    forged = payload
    updates = {"plugin_validation": validation, "normalized_package": normalized_model}
    if representation == "copy":
        forged = prepared.model_copy(update=updates)
    elif representation == "construct":
        forged = type(prepared).model_construct(**{**prepared.__dict__, **updates})
    with pytest.raises(ValidationError):
        type(prepared).model_validate(forged)
    with pytest.raises(ContractError):
        registry.validate("plugin-normalization.v1", payload)
    # Retaining the same-source validation as blocked diagnostics remains supported.
    payload.update(status="blocked", normalized_package=None, blocker={"code": "fixture_blocked", "message": "Stop."})
    registry.validate("plugin-normalization.v1", payload)
    recovered = _normalize(source, tmp_path / "corrected-plugin")
    assert recovered.status == "prepared"
    registry.validate("plugin-normalization.v1", recovered.model_dump(mode="json"))
