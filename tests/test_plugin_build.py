"""Real whole-plugin build/hardening, ingress rejection and restored-source recovery."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_plugin_presentation import _fixture, _request

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.core.receipts import parse_receipt
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.plugin_build import PluginBuildReceipt, PluginHardeningPolicy, PluginHardeningReceipt
from skills_sdk.models.plugin_presentation import PluginPresentationRequest
from skills_sdk.packaging import build_plugin_package, build_skill_package, harden_plugin_package
from skills_sdk.packaging import plugin as service

REVISION = "1" * 40


def _plugin(tmp_path: Path) -> Path:
    root, _ = _fixture(tmp_path)
    manifest = json.loads((root / "plugin.json").read_text())
    manifest["version"] = "1.0.0"
    (root / "plugin.json").write_text(json.dumps(manifest))
    (root / "README.md").write_text("# Synthetic plugin\n")
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o644)
    return root


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777) for p in root.rglob("*") if p.is_file()
    }


def _harden(root: Path, build: PluginBuildReceipt) -> PluginHardeningReceipt:
    request = PluginPresentationRequest.model_validate(_request(root))
    return harden_plugin_package(root, build, presentation_request=request)


def test_whole_plugin_read_only_build_hardening_and_schema_roundtrip(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    before = _snapshot(root)
    build = build_plugin_package(root, source_revision=REVISION)
    assert build.status == "built"
    assert {item.path for item in build.validation.files} == set(before)
    assert build.validation.skills[0].path == "skills/fixture-skill"
    hardened = _harden(root, build)
    assert hardened.status == "pass", hardened.blockers
    assert hardened.build.build_digest == build.build_digest
    assert _snapshot(root) == before
    for receipt in (build, hardened):
        payload = receipt.model_dump(mode="json")
        for flag in (
            "mutation_performed",
            "archive_emitted",
            "publication_performed",
            "execution_authorized",
            "release_ready",
        ):
            assert payload[flag] is False
        SchemaRegistry().validate(receipt.schema_version.replace("/", "."), payload)
        parsed = parse_receipt(payload)
        assert parsed.status == "pass"
        assert parsed.candidate.package_id == build.validation.candidate.package_id
        assert type(receipt).model_validate_json(receipt.model_dump_json()) == receipt
    assert build_skill_package(root, source_revision=REVISION).status == "blocked"
    assert build_skill_package(root / "skills/fixture-skill", source_revision=REVISION).status == "built"


@pytest.mark.parametrize("path", ["plugin.json", "skills/fixture-skill/SKILL.md", "assets/icon.png", "README.md"])
def test_changed_source_blocks_then_restored_source_recovers(tmp_path: Path, path: str) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    target = root / path
    original = target.read_bytes()
    target.write_bytes(original + b"\nchanged")
    result = harden_plugin_package(root, build)
    assert result.status == "blocked"
    assert "plugin_source_changed_or_blocked" in result.blockers
    target.write_bytes(original)
    assert _harden(root, build).status == "pass"


def test_mode_only_drift_binds_build_and_recovers(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    target = root / "README.md"
    target.chmod(0o755)
    changed = build_plugin_package(root, source_revision=REVISION)
    assert changed.validation.candidate == build.validation.candidate
    assert changed.build_digest != build.build_digest
    assert _harden(root, build).status == "blocked"
    target.chmod(0o644)
    assert _harden(root, build).status == "pass"


@pytest.mark.parametrize("family", ["build", "hardening"])
@pytest.mark.parametrize("blocked", [False, True])
def test_plugin_receipt_id_survives_immutable_payload_reparse(tmp_path: Path, family: str, blocked: bool) -> None:
    root = _plugin(tmp_path)
    if blocked and family == "build":
        path = root / "plugin.json"
        manifest = json.loads(path.read_text())
        manifest.pop("version")
        path.write_text(json.dumps(manifest))
    build = build_plugin_package(root, source_revision=REVISION)
    receipt = build
    if family == "hardening":
        receipt = harden_plugin_package(root, build) if blocked else _harden(root, build)
    payload = receipt.model_dump(mode="json")
    parsed = parse_receipt(payload)
    assert parsed.receipt_id == "plugin-local-" + canonical_json_sha256(payload)
    for _ in range(2):
        reparsed = parse_receipt(parsed.payload)
        assert reparsed == parsed
        assert reparsed.receipt_id == parsed.receipt_id
        parsed = reparsed


@pytest.mark.parametrize(
    "field,value", [("archive_emitted", True), ("release_ready", 0), ("publication_performed", "false")]
)
def test_authority_flags_reject_raw_and_copied_values(tmp_path: Path, field: str, value: object) -> None:
    build = build_plugin_package(_plugin(tmp_path), source_revision=REVISION)
    payload = build.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        PluginBuildReceipt.model_validate(payload)
    with pytest.raises(ValidationError):
        PluginBuildReceipt.model_validate(build.model_copy(update={field: value}))


def test_forged_nested_capture_and_unknown_copied_member_rejected(tmp_path: Path) -> None:
    build = build_plugin_package(_plugin(tmp_path), source_revision=REVISION)
    invalid = build.validation.model_copy(update={"files": build.validation.files[:-1]})
    with pytest.raises(ValidationError):
        PluginBuildReceipt.model_validate(build.model_copy(update={"validation": invalid}))
    with pytest.raises(ValidationError):
        PluginBuildReceipt.model_validate(build.model_copy(update={"hidden": "discarded by serializers"}))


def test_missing_version_and_private_file_block_and_recover(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    path = root / "plugin.json"
    original = path.read_bytes()
    payload = json.loads(original)
    payload.pop("version")
    path.write_text(json.dumps(payload))
    assert build_plugin_package(root, source_revision=REVISION).status == "blocked"
    parsed = parse_receipt(build_plugin_package(root, source_revision=REVISION).model_dump(mode="json"))
    assert parsed.status == "blocked" and parsed.blocker is not None
    path.write_bytes(original)
    secret = root / ".env"
    secret.write_text("SYNTHETIC_NOT_A_SECRET=fixture\n")
    assert build_plugin_package(root, source_revision=REVISION).status == "blocked"
    secret.unlink()
    assert _harden(root, build_plugin_package(root, source_revision=REVISION)).status == "pass"


def test_policy_and_missing_approvals_cannot_silently_pass(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    result = harden_plugin_package(root, build, policy=PluginHardeningPolicy(max_file_count=1))
    assert {"plugin_size_budget", "plugin_presentation_required"} <= set(result.blockers)
    target = root / "README.md"
    target.chmod(0o666)
    writable = build_plugin_package(root, source_revision=REVISION)
    assert "plugin_writable_by_others" in _harden(root, writable).blockers


def test_schema_registry_rejects_false_digest_and_hidden_hardening_blockers(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    payload = build.model_dump(mode="json")
    payload["build_digest"] = "f" * 64
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-build.v1", payload)
    result = harden_plugin_package(root, build)
    forged = result.model_copy(update={"status": "pass", "blockers": ()})
    with pytest.raises(ValidationError):
        PluginHardeningReceipt.model_validate(forged)


def test_stale_approval_and_wrong_revision_block(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    request = _request(root)
    build = build_plugin_package(root, source_revision="2" * 40)
    result = harden_plugin_package(root, build, presentation_request=PluginPresentationRequest.model_validate(request))
    assert result.status == "blocked"
    wrong = copy.deepcopy(request)
    wrong["image_approvals"][0]["rights_confirmed"] = False
    with pytest.raises(ValidationError):
        PluginPresentationRequest.model_validate(wrong)


def test_transient_source_change_is_not_erased_by_restoration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    (root / "README.md").chmod(0o755)
    changed = build_plugin_package(root, source_revision=REVISION).validation
    (root / "README.md").chmod(0o644)
    observations = iter((changed, build.validation))
    monkeypatch.setattr(service, "validate_plugin_package", lambda *args, **kwargs: next(observations))
    result = harden_plugin_package(root, build)
    assert result.source_stable is False
    assert "plugin_source_changed_or_blocked" in result.blockers


def test_minimal_blocked_receipt_parses_with_unbound_candidate() -> None:
    payload = {
        "schema_version": "plugin-build/v1",
        "status": "blocked",
        "validation": {
            "status": "blocked",
            "findings": [{"code": "fixture_blocked", "message": "Synthetic invalid source", "severity": "blocker"}],
        },
    }
    SchemaRegistry().validate("plugin-build.v1", payload)
    result = parse_receipt(payload)
    assert result.status == "blocked" and result.candidate is None and result.evidence == ()
    assert result.blocker.code == "fixture_blocked"


def test_forged_presentation_image_must_match_captured_file(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    result = _harden(root, build_plugin_package(root, source_revision=REVISION))
    payload = result.model_dump(mode="json")
    image = payload["presentation"]["images"][0]
    image["path"] = "assets/not-captured.png"
    image["approval"]["image_path"] = image["path"]
    with pytest.raises(ValidationError):
        PluginHardeningReceipt.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-hardening.v1", payload)


def test_copied_policy_and_raw_boolean_budgets_reject(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    build = build_plugin_package(root, source_revision=REVISION)
    policy = PluginHardeningPolicy().model_copy(update={"hidden": "not a supported field"})
    with pytest.raises(ValidationError):
        harden_plugin_package(root, build, policy=policy)
    with pytest.raises(ValidationError):
        PluginHardeningPolicy(max_file_count=True)


def test_candidate_environment_imports_this_checkout() -> None:
    import skills_sdk.packaging.plugin

    source = Path(skills_sdk.packaging.plugin.__file__).resolve()
    assert source.is_relative_to(Path(__file__).resolve().parents[1] / "src")
