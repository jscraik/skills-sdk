"""Prove portable plugin intake from an isolated installed wheel."""

from __future__ import annotations

import hashlib
import json
import os
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
    print("installed portable plugin API and CLI: accepted/rejected/recovery pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
