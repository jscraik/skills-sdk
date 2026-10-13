"""Prove portable plugin intake from an isolated installed wheel."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _cli(
    root: Path, expected: str, evidence: Path | None = None, policy_flags: tuple[str, ...] = ()
) -> dict[str, object]:
    """Run the installed plugin CLI and assert the expected status, exit code and absence of authority."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills_sdk.cli.main",
            "validate-plugin",
            str(root),
            "--source-revision",
            "1" * 40,
            "--json",
            "--robot",
            *(["--verify-evidence", str(evidence)] if evidence is not None else []),
            *policy_flags,
        ],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == (0 if expected == "pass" else 2), completed.stderr + completed.stdout
    value = json.loads(completed.stdout)
    assert value["status"] == expected
    assert not value["execution_authorized"] and not value["release_ready"] and not value["mutation_performed"]
    return value


def _verify(root: Path, payload: dict[str, object]) -> None:
    """Check installed evidence verification, role and digest forgery rejection, and recovery."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import verify_plugin_package_validation

    evidence = root.parent / "validation.json"
    good = json.dumps(payload)
    assert "SYNTHETIC-PRIVATE-SETTING" not in good
    assert verify_plugin_package_validation(root, payload, source_revision="1" * 40).status == "pass"
    evidence.write_text(good, encoding="utf-8")
    _cli(root, "pass", evidence)
    forged_role = json.loads(good)
    forged_role["skills"][0]["validation"]["files"][0]["role"] = "asset"
    try:
        SchemaRegistry().validate("plugin-package-validation.v1", forged_role)
    except ContractError:
        pass
    else:
        raise AssertionError("installed schema path accepted a forged SKILL.md role")
    forged = json.loads(good)
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    assert verify_plugin_package_validation(root, forged, source_revision="1" * 40).status == "blocked"
    evidence.write_text(json.dumps(forged), encoding="utf-8")
    _cli(root, "blocked", evidence)
    evidence.write_text(good, encoding="utf-8")
    _cli(root, "pass", evidence)


def _verify_policy(root: Path) -> None:
    """Preserve strict policy through installed API and CLI rejection and recovery."""
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models import PluginValidationPolicy
    from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

    policy = PluginValidationPolicy(require_version=True, require_description=True)
    manifest = root / "plugin.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata.update(version="1.0.0", description="Synthetic fixture.")
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    original = manifest.read_bytes()
    good = validate_plugin_package(root, source_revision="1" * 40, policy=policy)
    assert good.status == "pass"
    forged = good.model_dump(mode="json")
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    for supplied in ({}, forged):
        rejected = verify_plugin_package_validation(root, supplied, source_revision="1" * 40, policy=policy)
        assert rejected.status == "blocked" and rejected.policy == policy
        SchemaRegistry().validate("plugin-package-validation.v1", rejected.model_dump(mode="json"))
        assert verify_plugin_package_validation(root, good, source_revision="1" * 40, policy=policy) == good
    evidence = root.parent / "strict-validation.json"
    flags = ("--require-version", "--require-description")
    for invalid in ("{", "{}", json.dumps(forged)):
        evidence.write_text(invalid, encoding="utf-8")
        assert _cli(root, "blocked", evidence, flags)["policy"] == policy.model_dump(mode="json")
        evidence.write_text(good.model_dump_json(), encoding="utf-8")
        assert _cli(root, "pass", evidence, flags)["policy"] == policy.model_dump(mode="json")
    assert manifest.read_bytes() == original


def _verify_blocked_child(root: Path) -> None:
    """Reject forged blocked-child IDs through installed contracts and recover."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models import PluginPackageValidation
    from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

    entrypoint = root / "skills" / "fixture-skill" / "SKILL.md"
    original = entrypoint.read_bytes()
    entrypoint.write_text("---\nname: [\n---\n", encoding="utf-8")
    blocked = validate_plugin_package(root, source_revision="1" * 40)
    assert blocked.status == "blocked" and blocked.skills[0].validation.identity is None
    assert PluginPackageValidation.model_validate(blocked) == blocked
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))
    forged = blocked.model_dump(mode="json")
    forged["skills"][0]["validation"]["candidate"]["package_id"] = "other-skill"
    try:
        SchemaRegistry().validate("plugin-package-validation.v1", forged)
    except ContractError:
        pass
    else:
        raise AssertionError("installed schema accepted a forged blocked-child candidate ID")
    rejected = verify_plugin_package_validation(root, forged, source_revision="1" * 40)
    assert rejected.status == "blocked" and rejected.findings[0].code == "plugin_evidence_invalid"
    assert entrypoint.read_text(encoding="utf-8") == "---\nname: [\n---\n"
    entrypoint.write_bytes(original)
    recovered = validate_plugin_package(root, source_revision="1" * 40)
    assert recovered.status == "pass"
    assert verify_plugin_package_validation(root, recovered, source_revision="1" * 40) == recovered


def _verify_special_file(root: Path) -> None:
    """Reject a synthetic FIFO and recover without exercising real devices."""
    from skills_sdk.validation import validate_plugin_package

    special = root / "known-pipe"
    os.mkfifo(special)
    result = validate_plugin_package(root, source_revision="1" * 40)
    assert result.status == "blocked" and result.findings[0].code == "plugin_input_invalid"
    _cli(root, "blocked")
    special.unlink()
    assert validate_plugin_package(root, source_revision="1" * 40).status == "pass"
    _cli(root, "pass")


def _reject_envelope(root: Path, payload: dict[str, object]) -> None:
    """Reject malformed retained evidence through installed schema, service and CLI."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import verify_plugin_package_validation

    try:
        SchemaRegistry().validate("plugin-package-validation.v1", payload)
    except ContractError:
        pass
    else:
        raise AssertionError("installed schema accepted invalid plugin evidence")
    rejected = verify_plugin_package_validation(root, payload, source_revision="1" * 40)
    assert rejected.status == "blocked" and rejected.findings[0].code == "plugin_evidence_invalid"
    evidence = root.parent / "invalid-envelope.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    assert _cli(root, "blocked", evidence)["findings"][0]["code"] == "plugin_evidence_invalid"


def _verify_canonical_sizes(root: Path) -> None:
    """Reject coerced child sizes and recover through the installed public entrypoints."""
    from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

    asset = root / "skills" / "fixture-skill" / "one-byte.txt"
    asset.write_bytes(b"x")
    good = validate_plugin_package(root, source_revision="1" * 40)
    assert good.status == "pass"
    for size in ("1", True):
        payload = good.model_dump(mode="json")
        for item in payload["skills"][0]["validation"]["files"]:
            if item["path"] == asset.name:
                item["size_bytes"] = size
        _reject_envelope(root, payload)
    assert verify_plugin_package_validation(root, good, source_revision="1" * 40) == good
    evidence = root.parent / "canonical-evidence.json"
    evidence.write_text(good.model_dump_json(), encoding="utf-8")
    _cli(root, "pass", evidence)
    evidence.unlink()
    os.mkfifo(evidence)
    _cli(root, "blocked", evidence)
    evidence.unlink()
    evidence.write_text(good.model_dump_json(), encoding="utf-8")
    _cli(root, "pass", evidence)
    assert asset.read_bytes() == b"x"


def _verify_component_kind(root: Path) -> None:
    """Retain a root skills-file blocker and recover without disturbing child fixtures."""
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import validate_plugin_package

    candidate = root.parent / "wrong-kind-plugin"
    candidate.mkdir()
    (candidate / "plugin.json").write_bytes((root / "plugin.json").read_bytes())
    component = candidate / "skills"
    component.write_bytes(b"ordinary file, invalid component")
    blocked = validate_plugin_package(candidate, source_revision="1" * 40)
    assert blocked.status == "blocked" and blocked.candidate is not None
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))
    _cli(candidate, "blocked")
    forged = blocked.model_dump(mode="json")
    forged.update(status="pass", findings=[])
    _reject_envelope(candidate, forged)
    component.unlink()
    component.mkdir()
    recovered = validate_plugin_package(candidate, source_revision="1" * 40)
    assert recovered.status == "pass"
    evidence = root.parent / "corrected-kind.json"
    evidence.write_text(recovered.model_dump_json(), encoding="utf-8")
    _cli(candidate, "pass", evidence)


def _verify_exact_identities(root: Path) -> None:
    """Reject padded root and child identities through installed boundaries and recover."""
    from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

    good = validate_plugin_package(root, source_revision="1" * 40)
    for child in (False, True):
        for field in ("package_id", "source_revision", "content_sha256"):
            payload = good.model_dump(mode="json")
            candidate = payload["skills"][0]["validation"]["candidate"] if child else payload["candidate"]
            candidate[field] = " " + candidate[field] + "\t"
            _reject_envelope(root, payload)
    assert verify_plugin_package_validation(root, good, source_revision="1" * 40) == good
    evidence = root.parent / "exact-identity.json"
    evidence.write_text(good.model_dump_json(), encoding="utf-8")
    _cli(root, "pass", evidence)


def _verify_retained_settings_and_mcp(root: Path) -> None:
    """Require retained settings selection and the explicit unassessed MCP warning."""
    from skills_sdk.validation import validate_plugin_package, verify_plugin_package_validation

    overlay = root / ".codex-plugin" / "plugin.json"
    overlay.parent.mkdir()
    overlay.write_text("invalid but superseded by inline settings", encoding="utf-8")
    (root / "mcp.json").write_bytes(b"unparsed synthetic MCP data")
    good = validate_plugin_package(root, source_revision="1" * 40)
    assert good.status == "pass" and good.manifest.openai_settings_source == "inline"
    forged = good.model_dump(mode="json")
    forged["manifest"].update(openai_settings_source="none", openai_settings_sha256=None)
    _reject_envelope(root, forged)
    forged = good.model_dump(mode="json")
    forged["findings"] = [item for item in forged["findings"] if item["code"] != "plugin_mcp_not_assessed"]
    _reject_envelope(root, forged)
    forged = good.model_dump(mode="json")
    for finding in forged["findings"]:
        finding["code"] = " " + finding["code"] + "\t"
    _reject_envelope(root, forged)
    assert verify_plugin_package_validation(root, good, source_revision="1" * 40) == good
    evidence = root.parent / "retained-settings.json"
    evidence.write_text(good.model_dump_json(), encoding="utf-8")
    _cli(root, "pass", evidence)


def _verify_required_metadata_findings(root: Path) -> None:
    """Reject erased policy reasons without erasing genuine blocked evidence or recovery."""
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models import PluginValidationPolicy
    from skills_sdk.validation import validate_plugin_package

    manifest = root / "plugin.json"
    original = manifest.read_bytes()
    metadata = json.loads(original)
    metadata.pop("version", None)
    metadata.pop("description", None)
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    policy = PluginValidationPolicy(require_version=True, require_description=True)
    blocked = validate_plugin_package(root, source_revision="1" * 40, policy=policy)
    assert blocked.status == "blocked" and blocked.candidate is not None
    SchemaRegistry().validate("plugin-package-validation.v1", blocked.model_dump(mode="json"))
    for field in ("version", "description"):
        forged = blocked.model_dump(mode="json")
        forged["findings"] = [
            item for item in forged["findings"] if item["code"] != "sdk_plugin_" + field + "_required"
        ]
        _reject_envelope(root, forged)
    manifest.write_bytes(original)
    recovered = validate_plugin_package(root, source_revision="1" * 40, policy=policy)
    assert recovered.status == "pass"
    evidence = root.parent / "recovered-policy.json"
    evidence.write_text(recovered.model_dump_json(), encoding="utf-8")
    _cli(root, "pass", evidence, ("--require-version", "--require-description"))


def _reject_normalization_dependencies(payload: dict[str, object]) -> None:
    """Reject added dependencies through the installed schema and recover with the original receipt."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry

    registry = SchemaRegistry()
    forged = json.loads(json.dumps(payload))
    forged["normalized_package"]["dependencies"] = ["unverified-dependency"]
    try:
        registry.validate("plugin-normalization.v1", forged)
    except ContractError:
        pass
    else:
        raise AssertionError("installed normalization schema accepted unverified dependencies")
    registry.validate("plugin-normalization.v1", payload)


def _reject_blocked_normalization_validation(payload: dict[str, object], foreign: dict[str, object]) -> None:
    """Keep matching blocked evidence and reject unrelated passing proof through installed contracts."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models.plugin_normalization import PluginNormalizationReceipt

    registry = SchemaRegistry()
    blocked = json.loads(json.dumps(payload))
    blocked.update(status="blocked", normalized_package=None, blocker={"code": "fixture_blocked", "message": "Stop."})
    PluginNormalizationReceipt.model_validate(blocked)
    registry.validate("plugin-normalization.v1", blocked)
    forged = {**blocked, "plugin_validation": foreign}
    try:
        PluginNormalizationReceipt.model_validate(forged)
    except ValidationError:
        pass
    else:
        raise AssertionError("installed blocked normalization model accepted unrelated passing proof")
    try:
        registry.validate("plugin-normalization.v1", forged)
    except ContractError:
        pass
    else:
        raise AssertionError("installed blocked normalization registry accepted unrelated passing proof")
    registry.validate("plugin-normalization.v1", blocked)


def _verify_normalization_foreign_child(root: Path, source: Path, context_payload: dict[str, object]) -> None:
    """Retain an actual changed-child blocker without claiming unrelated passing source evidence."""
    from unittest.mock import patch

    from skills_sdk.intake import plugin_normalization as normalization
    from skills_sdk.models import PluginPackageValidation, PluginValidationPolicy
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata

    validate = normalization.validate_plugin_package

    def validate_changed_child(
        candidate: Path, *, source_revision: str, policy: PluginValidationPolicy | None = None
    ) -> PluginPackageValidation:
        """Produce genuine installed validation for a deliberately changed child."""
        child = candidate / "skills" / source.name / "SKILL.md"
        child.write_bytes(child.read_bytes() + b"\nDifferent captured child.\n")
        return validate(candidate, source_revision=source_revision, policy=policy)

    context = SkillPackageIntakeContext.model_validate(context_payload)
    metadata = PluginNormalizationMetadata(name="fixture-plugin", version="1.0.0", description="Synthetic plugin.")
    with patch.object(normalization, "validate_plugin_package", validate_changed_child):
        receipt = normalization.normalize_standalone_skill_package(
            source, root / "foreign-child-plugin", context, metadata
        )
    assert receipt.status == "blocked" and receipt.candidate_created
    assert receipt.blocker is not None and receipt.blocker.code == "standalone_candidate_binding_mismatch"
    assert receipt.plugin_validation is None and receipt.normalized_package is None
    assert (
        normalization.normalize_standalone_skill_package(source, root / "fixed-child-plugin", context, metadata).status
        == "prepared"
    )


def _verify_normalization_destination_drift(root: Path, source: Path, context_payload: dict[str, object]) -> None:
    """Prove the installed public API rejects post-validation drift and permits a fresh candidate."""
    from unittest.mock import patch

    from skills_sdk.intake import plugin_normalization as normalization
    from skills_sdk.models import PluginPackageValidation, PluginValidationPolicy
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin import PluginCapturedFile
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata

    validate = normalization.validate_plugin_package

    def validate_then_change(
        candidate: Path, *, source_revision: str, policy: PluginValidationPolicy | None = None
    ) -> PluginPackageValidation:
        """Change the manifest after obtaining genuine installed validation."""
        result = validate(candidate, source_revision=source_revision, policy=policy)
        manifest = candidate / "plugin.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        return result

    context = SkillPackageIntakeContext.model_validate(context_payload)
    metadata = PluginNormalizationMetadata(name="fixture-plugin", version="1.0.0", description="Synthetic plugin.")
    original = (source / "SKILL.md").read_bytes()
    with patch.object(normalization, "validate_plugin_package", validate_then_change):
        blocked = normalization.normalize_standalone_skill_package(source, root / "drifted-plugin", context, metadata)
    assert blocked.status == "blocked" and blocked.candidate_created
    assert blocked.blocker is not None and blocked.blocker.code == "normalized_candidate_changed"
    assert blocked.normalized_package is None
    capture = normalization.capture_plugin_source
    replaced_destination = root / "replaced-plugin"

    def capture_then_replace(
        candidate: Path,
    ) -> tuple[tuple[PluginCapturedFile, ...], dict[str, bytes], tuple[str, ...]]:
        """Replace the captured destination while retaining identical copied bytes."""
        result = capture(candidate)
        if candidate == replaced_destination:
            retained = root / "retained-original-plugin"
            candidate.rename(retained)
            shutil.copytree(retained, candidate)
        return result

    with patch.object(normalization, "capture_plugin_source", capture_then_replace):
        replaced = normalization.normalize_standalone_skill_package(source, replaced_destination, context, metadata)
    assert replaced.status == "blocked" and replaced.candidate_created
    assert replaced.blocker is not None and replaced.blocker.code == "normalized_candidate_changed"
    assert replaced.normalized_package is None
    recovered = normalization.normalize_standalone_skill_package(source, root / "recovered-plugin", context, metadata)
    assert recovered.status == "prepared"
    assert (source / "SKILL.md").read_bytes() == original


def _verify_normalization_metadata_budget(root: Path, source: Path, context_payload: dict[str, object]) -> None:
    """Prove exact-byte metadata acceptance, rejection and recovery through installed public contracts."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.intake import normalize_standalone_skill_package
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata

    values = {"name": "fixture-budget-plugin", "version": "1.0.0", "description": ""}
    overhead = len((json.dumps({"$schema": PLUGIN_SCHEMA_URI, **values}, indent=2) + "\n").encode())
    values["description"] = "d" * (1_048_576 - overhead)
    metadata = PluginNormalizationMetadata.model_validate(values)
    registry = SchemaRegistry()
    registry.validate("plugin-normalization-metadata.v1", values)
    invalid = {**values, "description": values["description"] + "d"}
    try:
        PluginNormalizationMetadata.model_validate(invalid)
    except ValidationError:
        pass
    else:
        raise AssertionError("installed metadata model admitted an oversized canonical manifest")
    try:
        registry.validate("plugin-normalization-metadata.v1", invalid)
    except ContractError:
        pass
    else:
        raise AssertionError("installed metadata registry admitted an oversized canonical manifest")
    context = SkillPackageIntakeContext.model_validate(context_payload)
    rejected = normalize_standalone_skill_package(
        source, root / "invalid-budget-plugin", context, metadata.model_copy(update=invalid)
    )
    assert rejected.status == "blocked" and rejected.blocker.code == "plugin_metadata_invalid"
    assert not rejected.candidate_created and not (root / "invalid-budget-plugin").exists()
    accepted = normalize_standalone_skill_package(source, root / "exact-budget-plugin", context, metadata)
    assert accepted.status == "prepared"
    assert (root / "exact-budget-plugin" / "plugin.json").stat().st_size == 1_048_576
    registry.validate("plugin-normalization.v1", accepted.model_dump(mode="json"))


def _verify_normalization_output_closure(root: Path, source: Path, context_payload: dict[str, object]) -> None:
    """Reject genuine but non-normalization plugin output and recover through the installed API."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.intake import normalize_standalone_skill_package
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata, PluginNormalizationReceipt
    from skills_sdk.validation import validate_plugin_package

    context = SkillPackageIntakeContext.model_validate(context_payload)
    metadata = PluginNormalizationMetadata(
        name="fixture-closure-plugin", version="1.0.0", description="Synthetic plugin."
    )
    destination = root / "closure-plugin"
    prepared = normalize_standalone_skill_package(source, destination, context, metadata)
    assert prepared.status == "prepared"
    (destination / "extra.md").write_text("Not normalization output.\n", encoding="utf-8")
    validation = validate_plugin_package(
        destination, source_revision=context.source_revision, policy=prepared.plugin_validation.policy
    )
    assert validation.status == "pass" and validation.candidate is not None
    payload = prepared.model_dump(mode="json")
    payload["plugin_validation"] = validation.model_dump(mode="json")
    payload["normalized_package"]["source"]["provenance"]["content_sha256"] = validation.candidate.content_sha256
    try:
        PluginNormalizationReceipt.model_validate(payload)
    except ValidationError:
        pass
    else:
        raise AssertionError("installed normalization model accepted extra root files")
    registry = SchemaRegistry()
    try:
        registry.validate("plugin-normalization.v1", payload)
    except ContractError:
        pass
    else:
        raise AssertionError("installed normalization registry accepted extra root files")
    recovered = normalize_standalone_skill_package(source, root / "closure-recovered-plugin", context, metadata)
    assert recovered.status == "prepared"
    registry.validate("plugin-normalization.v1", recovered.model_dump(mode="json"))


def _verify_normalization_capture_limit(command: list[str], source: Path, root: Path) -> None:
    """Retain a real capture-limit CLI blocker, correct its input and prove fresh candidate binding."""
    from skills_sdk.core.schema_registry import SchemaRegistry

    oversized = source / "oversized.md"
    oversized.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    rejected_command = list(command)
    rejected_command[3] = str(root / "capture-blocked-plugin")
    completed = subprocess.run(rejected_command, cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 2, completed.stderr + completed.stdout
    rejected = json.loads(completed.stdout)
    assert rejected["status"] == "blocked" and not rejected["candidate_created"]
    assert rejected["blocker"]["code"] == "standalone_source_capture_blocked"
    assert rejected["source_intake"]["status"] == "normalized" and not (root / "capture-blocked-plugin").exists()
    SchemaRegistry().validate("plugin-normalization.v1", rejected)
    oversized.unlink()
    recovered_command = list(command)
    recovered_command[3] = str(root / "capture-recovered-plugin")
    completed = subprocess.run(recovered_command, cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    recovered = json.loads(completed.stdout)
    assert (
        recovered["status"] == "prepared"
        and recovered["source_intake"]["candidate"] != rejected["source_intake"]["candidate"]
    )
    assert (
        recovered["plugin_validation"]["skills"][0]["validation"]["candidate"]
        == recovered["source_intake"]["candidate"]
    )
    SchemaRegistry().validate("plugin-normalization.v1", recovered)


def _verify_standalone_normalization(root: Path) -> None:
    """Prove installed API and console entrypoint create a separate bound plugin candidate."""
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.intake import normalize_standalone_skill_package
    from skills_sdk.models.intake import SkillPackageIntakeContext
    from skills_sdk.models.plugin_normalization import PluginNormalizationMetadata

    owner = {
        "owner": "sdk-tests",
        "maintainer": "sdk-tests",
        "ownership_state": "canonical",
        "rights": {"basis": "authored", "license": "Apache-2.0", "evidence_ref": "source/SKILL.md"},
    }
    source = root / "fixture-skill"
    source.mkdir()
    skill = b"---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n\n# Fixture\n"
    (source / "SKILL.md").write_bytes(skill)
    context = SkillPackageIntakeContext.model_validate(
        {
            "source_repository": "jscraik/skills-sdk",
            "source_revision": "1" * 40,
            "source_path": "fixture-skill",
            "source_kind": "local",
            "owner": owner,
            "checks": {"identity": True, "provenance": True, "rights": True, "owner_unchanged": True},
        }
    )
    receipt = normalize_standalone_skill_package(
        source,
        root / "api-plugin",
        context,
        PluginNormalizationMetadata(
            name="fixture-plugin",
            version="1.0.0",
            description="Synthetic plugin.",
        ),
    )
    assert receipt.status == "prepared" and receipt.plugin_validation is not None
    assert receipt.plugin_validation.status == "pass" and receipt.release_ready is False
    assert receipt.plugin_validation.skills[0].validation.candidate == receipt.source_intake.candidate
    assert (source / "SKILL.md").read_bytes() == skill
    SchemaRegistry().validate("plugin-normalization.v1", receipt.model_dump(mode="json"))
    _reject_normalization_dependencies(receipt.model_dump(mode="json"))
    _verify_normalization_destination_drift(root, source, context.model_dump(mode="json"))
    _verify_normalization_foreign_child(root, source, context.model_dump(mode="json"))
    other = normalize_standalone_skill_package(
        source,
        root / "other-revision-plugin",
        context.model_copy(update={"source_revision": "2" * 40}),
        PluginNormalizationMetadata(name="fixture-other-plugin", version="1.0.0", description="Synthetic plugin."),
    )
    assert other.status == "prepared" and other.plugin_validation is not None
    foreign_validation = other.plugin_validation.model_dump(mode="json")
    _reject_blocked_normalization_validation(receipt.model_dump(mode="json"), foreign_validation)

    context_path = root / "normalization-context.json"
    context_path.write_text(context.model_dump_json(), encoding="utf-8")
    command = [
        str(Path(sys.executable).with_name("skills-sdk")),
        "normalize-plugin",
        str(source),
        str(root / "cli-plugin"),
        "--context",
        str(context_path),
        "--plugin-name",
        "fixture-cli-plugin",
        "--plugin-version",
        "1.0.0",
        "--plugin-description",
        "Synthetic CLI plugin.",
        "--json",
        "--robot",
    ]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    cli_receipt = json.loads(completed.stdout)
    assert cli_receipt["status"] == "prepared" and cli_receipt["release_ready"] is False
    assert (
        cli_receipt["plugin_validation"]["skills"][0]["validation"]["candidate"]
        == cli_receipt["source_intake"]["candidate"]
    )
    assert (source / "SKILL.md").read_bytes() == skill
    _reject_normalization_dependencies(cli_receipt)
    _reject_blocked_normalization_validation(cli_receipt, foreign_validation)
    _verify_normalization_metadata_budget(root, source, context.model_dump(mode="json"))
    _verify_normalization_output_closure(root, source, context.model_dump(mode="json"))
    _verify_normalization_capture_limit(command, source, root)
    assert (source / "SKILL.md").read_bytes() == skill


def main() -> int:
    """Exercise complete-source acceptance, rejection and recovery without siblings."""
    import skills_sdk
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.validation import validate_plugin_package

    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-portable-plugin-") as directory:
        root = Path(directory).resolve() / "different-checkout-name"
        child = root / "skills" / "fixture-skill"
        child.mkdir(parents=True)
        skill = b"---\nname: fixture-skill\ndescription: Inspect synthetic examples.\n---\n"
        (child / "SKILL.md").write_bytes(skill)
        (root / "assets").mkdir()
        (root / "assets" / "icon.txt").write_text("Synthetic icon", encoding="utf-8")
        metadata = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "fixture-.plugin",
            "extensions": {"com.openai": {"private": "SYNTHETIC-PRIVATE-SETTING"}},
        }
        manifest = root / "plugin.json"
        for content, expected in ((json.dumps(metadata), "pass"), ("{}", "blocked"), (json.dumps(metadata), "pass")):
            manifest.write_text(content, encoding="utf-8")
            result = validate_plugin_package(root, source_revision="1" * 40)
            assert result.status == expected, result.model_dump(mode="json")
            if expected == "pass":
                assert result.candidate is not None
                assert result.candidate.package_id == "plugin-" + hashlib.sha256(b"fixture-.plugin").hexdigest()
                assert "assets/icon.txt" in {item.path for item in result.files}
                assert result.skills[0].validation.status == "pass"
                SchemaRegistry().validate("plugin-package-validation.v1", result.model_dump(mode="json"))
            _cli(root, expected)
            assert (child / "SKILL.md").read_bytes() == skill
        _verify(root, result.model_dump(mode="json"))
        _verify_policy(root)
        _verify_blocked_child(root)
        _verify_special_file(root)
        _verify_canonical_sizes(root)
        _verify_component_kind(root)
        _verify_exact_identities(root)
        _verify_retained_settings_and_mcp(root)
        _verify_required_metadata_findings(root)
        _verify_standalone_normalization(Path(directory).resolve())
    print("installed portable plugin API and CLI: accepted/rejected/recovery pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
