"""Installed-command input boundaries for retained plugin evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from skills_sdk.cli.main import main
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI, PluginValidationPolicy
from skills_sdk.validation import validate_plugin_package

REVISION = "1" * 40


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create a plugin and save passing evidence outside its root, returning both paths and JSON."""
    root = tmp_path.resolve() / "plugin"
    root.mkdir()
    metadata = {
        "$schema": PLUGIN_SCHEMA_URI,
        "name": "example",
        "version": "1.0.0",
        "description": "Example plugin.",
        "extensions": {"com.openai": {"private": "SYNTHETIC-NOT-TO-ECHO"}},
    }
    (root / "plugin.json").write_text(json.dumps(metadata), encoding="utf-8")
    good = validate_plugin_package(root, source_revision=REVISION)
    assert good.status == "pass"
    evidence = root.parent / "evidence.json"
    payload = good.model_dump_json()
    evidence.write_text(payload, encoding="utf-8")
    return root, evidence, payload


def _policy_arguments(policy: PluginValidationPolicy | None) -> list[str]:
    """Translate the fixture policy to the corresponding explicit CLI flags."""
    if policy is None:
        return []
    return [
        *(["--require-version"] if policy.require_version else []),
        *(["--require-description"] if policy.require_description else []),
    ]


def _cli(
    root: Path,
    evidence: Path,
    capsys: pytest.CaptureFixture[str],
    expected: str,
    policy: PluginValidationPolicy | None = None,
) -> dict[str, object]:
    """Invoke evidence verification and check its status, exit code, privacy and authority flags."""
    code = main(
        [
            "validate-plugin",
            str(root),
            "--source-revision",
            REVISION,
            "--verify-evidence",
            str(evidence),
            *_policy_arguments(policy),
            "--json",
            "--robot",
        ]
    )
    assert code == (0 if expected == "pass" else 2)
    output = capsys.readouterr().out
    assert "SYNTHETIC-NOT-TO-ECHO" not in output
    result = json.loads(output)
    assert result["status"] == expected
    assert not any(result[flag] for flag in ("mutation_performed", "execution_authorized", "release_ready"))
    return result


POLICIES = (
    PluginValidationPolicy(require_version=True),
    PluginValidationPolicy(require_description=True),
    PluginValidationPolicy(require_version=True, require_description=True),
)


def test_cli_rejects_forged_digest_and_recovers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reject a forged settings digest through the CLI and accept restored evidence."""
    root, evidence, good = _fixture(tmp_path)
    _cli(root, evidence, capsys, "pass")
    forged = json.loads(good)
    forged["manifest"]["openai_settings_sha256"] = "0" * 64
    evidence.write_text(json.dumps(forged), encoding="utf-8")
    blocked = _cli(root, evidence, capsys, "blocked")
    assert blocked["findings"][0]["code"] == "plugin_evidence_mismatch"
    evidence.write_text(good, encoding="utf-8")
    _cli(root, evidence, capsys, "pass")


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("kind", ["read", "json", "semantic", "mismatch"])
def test_cli_explicit_policy_survives_invalid_mismatch_and_recovery(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    policy: PluginValidationPolicy,
    kind: str,
) -> None:
    """Preserve CLI policy through read, JSON, contract and mismatch rejection."""
    root, evidence, _ = _fixture(tmp_path)
    strict = validate_plugin_package(root, source_revision=REVISION, policy=policy)
    assert strict.status == "pass" and strict.policy == policy
    good = strict.model_dump_json()
    if kind == "read":
        evidence.unlink()
    elif kind == "json":
        evidence.write_text("[", encoding="utf-8")
    elif kind == "semantic":
        evidence.write_text("{}", encoding="utf-8")
    else:
        forged = strict.model_dump(mode="json")
        forged["manifest"]["openai_settings_sha256"] = "0" * 64
        evidence.write_text(json.dumps(forged), encoding="utf-8")
    blocked = _cli(root, evidence, capsys, "blocked", policy)
    assert blocked["findings"][0]["code"] == (
        "plugin_evidence_mismatch" if kind == "mismatch" else "plugin_evidence_invalid"
    )
    assert blocked["policy"] == policy.model_dump(mode="json")
    evidence.write_text(good, encoding="utf-8")
    recovered = _cli(root, evidence, capsys, "pass", policy)
    assert recovered["policy"] == policy.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["missing", "json", "duplicate", "symlink", "directory", "fifo", "oversize"])
def test_cli_evidence_path_and_json_bounds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    """Reject unsafe or invalid evidence inputs and accept a restored ordinary JSON file."""
    root, evidence, good = _fixture(tmp_path)
    if kind in {"missing", "symlink", "directory", "fifo"}:
        evidence.unlink()
    if kind == "json":
        evidence.write_text("[", encoding="utf-8")
    elif kind == "duplicate":
        evidence.write_text('{"status":"pass","status":"blocked"}', encoding="utf-8")
    elif kind == "symlink":
        evidence.symlink_to(root / "plugin.json")
    elif kind == "directory":
        evidence.mkdir()
    elif kind == "fifo":
        os.mkfifo(evidence)
    elif kind == "oversize":
        evidence.write_bytes(b" " * (16 * 1024 * 1024 + 1))
    result = _cli(root, evidence, capsys, "blocked")
    assert result["findings"][0]["code"] == "plugin_evidence_invalid"
    if kind == "directory":
        evidence.rmdir()
    elif kind != "missing":
        evidence.unlink()
    evidence.write_text(good, encoding="utf-8")
    _cli(root, evidence, capsys, "pass")
