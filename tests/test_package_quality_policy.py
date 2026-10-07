"""Applicable-file and textual-reference policy through public boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package

REVISION = "1" * 40


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "quality-fixture"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: quality-fixture\ndescription: Inspect examples.\n---\n# Example\n")
    (root / "references").mkdir()
    return root


def test_required_file_rejection_and_corrected_input(tmp_path: Path) -> None:
    root = _package(tmp_path)
    policy = SkillValidationPolicy(required_files=("references/README.md",))
    original = (root / "SKILL.md").read_bytes()
    assert validate_skill_package(root, source_revision=REVISION).status == "pass"
    blocked = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert blocked.status == "blocked"
    assert blocked.findings[0].code == "required_file_missing"
    assert blocked.findings[0].evidence_refs == ("references/README.md",)
    (root / "references/README.md").write_text("# Reference routing\n")
    accepted = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert accepted.status == "pass"
    assert accepted.candidate != blocked.candidate
    assert (root / "SKILL.md").read_bytes() == original
    for result in (blocked, accepted):
        SchemaRegistry().validate("skill-package-validation.v1", result.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("name", "payload", "code", "corrected"),
    [
        ("guide.md", b" \n", "empty_reference", b"# Guide\n"),
        ("guide.markdown", b" \n", "empty_reference", b"# Guide\n"),
        ("guide.markdown", b"\xff", "invalid_reference_utf8", b"# Guide\n"),
        ("guide.md", b"\xef\xbb\xbf \n", "empty_reference", b"\xef\xbb\xbf# Guide\n"),
        ("guide.txt", b"\xef\xbb\xbf", "empty_reference", b"\xef\xbb\xbfUse the example.\n"),
        ("guide.txt", b"\xff", "invalid_reference_utf8", b"Use the supplied fixture.\n"),
        ("data.json", b"{", "invalid_reference_format", b'{"example": true}'),
        ("data.json", b"NaN", "invalid_reference_format", b"null"),
        ("data.json", b"Infinity", "invalid_reference_format", b"1"),
        ("data.json", b"-Infinity", "invalid_reference_format", b"-1"),
        ("data.json", b'{"score": NaN}', "invalid_reference_format", b'{"score": 0}'),
        ("data.json", b"[" + b"9" * 4301 + b",]", "invalid_reference_format", b"[" + b"9" * 4301 + b"]"),
        ("data.json", b"--" + b"9" * 4301, "invalid_reference_format", b"-" + b"9" * 4301),
        ("data.yaml", b"example: [", "invalid_reference_format", b"example: true\n"),
    ],
)
def test_reference_rejection_default_compatibility_and_recovery(
    tmp_path: Path, name: str, payload: bytes, code: str, corrected: bytes
) -> None:
    root = _package(tmp_path)
    reference = root / "references" / name
    reference.write_bytes(payload)
    policy = SkillValidationPolicy(check_reference_content=True)
    assert validate_skill_package(root, source_revision=REVISION).status == "pass"
    result = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert result.status == "blocked"
    assert code in {finding.code for finding in result.findings}
    assert reference.read_bytes() == payload
    reference.write_bytes(corrected)
    assert validate_skill_package(root, source_revision=REVISION, policy=policy).status == "pass"


@pytest.mark.parametrize("payload", ["resource: !Ref Example\n", "---\nfirst: true\n---\nsecond: false\n"])
def test_yaml_syntax_accepts_tags_and_multiple_documents(tmp_path: Path, payload: str) -> None:
    root = _package(tmp_path)
    reference = root / "references/example.yaml"
    reference.write_text(payload)
    result = validate_skill_package(
        root, source_revision=REVISION, policy=SkillValidationPolicy(check_reference_content=True)
    )
    assert result.status == "pass"
    assert reference.read_text() == payload


@pytest.mark.parametrize("depth", [129, 10_000])
def test_yaml_nesting_budget_blocks_cli_and_recovers(tmp_path: Path, depth: int) -> None:
    root = _package(tmp_path)
    reference = root / "references/example.yaml"
    payload = "[" * depth + "0" + "]" * depth
    reference.write_text(payload)
    arguments = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        "validate",
        str(root),
        "--source-revision",
        REVISION,
        "--check-reference-content",
        "--json",
    ]
    rejected = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=5)
    assert rejected.returncode == 2, rejected.stderr
    result = json.loads(rejected.stdout)
    assert "reference_content_limit" in {item["code"] for item in result["findings"]}
    assert reference.read_text() == payload
    reference.write_text("[" * 128 + "0" + "]" * 128)
    accepted = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=5)
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["candidate"] != result["candidate"]


@pytest.mark.parametrize("count", [100_000, 100_001])
def test_yaml_event_budget_stops_and_closes_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    from collections.abc import Iterator

    root = _package(tmp_path)
    (root / "references/example.yaml").write_text("example: true\n")
    consumed = 0
    closed = False

    def bounded_events(*args: object, **kwargs: object) -> Iterator[yaml.events.Event]:
        nonlocal consumed, closed
        try:
            for _ in range(count):
                consumed += 1
                yield yaml.events.ScalarEvent(None, None, (True, False), "value")
            if count > 100_000:
                raise AssertionError("parser must not resume after the work budget")
        finally:
            closed = True

    with monkeypatch.context() as guarded:
        guarded.setattr("skills_sdk.validation.skill_package.yaml.parse", bounded_events)
        result = validate_skill_package(
            root, source_revision=REVISION, policy=SkillValidationPolicy(check_reference_content=True)
        )
    assert result.status == ("pass" if count == 100_000 else "blocked")
    assert consumed == count
    assert closed
    assert (
        validate_skill_package(
            root, source_revision=REVISION, policy=SkillValidationPolicy(check_reference_content=True)
        ).status
        == "pass"
    )


def test_reference_text_budget_blocks_then_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _package(tmp_path)
    reference = root / "references/example.json"
    limit = 8_388_608
    oversized = b'"' + b"a" * (limit - 1) + b'"'
    reference.write_bytes(oversized)
    policy = SkillValidationPolicy(check_reference_content=True)

    def unexpected_parse(*args: object, **kwargs: object) -> object:
        raise AssertionError("oversized reference must block before JSON parsing")

    with monkeypatch.context() as guarded:
        guarded.setattr("skills_sdk.validation.skill_package.json.loads", unexpected_parse)
        rejected = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert rejected.status == "blocked"
    assert "reference_content_limit" in {item.code for item in rejected.findings}
    assert reference.read_bytes() == oversized
    reference.write_bytes(b'"' + b"a" * (limit - 2) + b'"')
    accepted = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert accepted.status == "pass"
    assert accepted.candidate != rejected.candidate


@pytest.mark.parametrize("suffix", [".MD", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdwn", ".mdtxt", ".mdtext"])
def test_markdown_suffix_neighbours_block_and_recover(tmp_path: Path, suffix: str) -> None:
    root = _package(tmp_path)
    reference = root / "references" / ("example" + suffix)
    reference.write_bytes(b" \n")
    policy = SkillValidationPolicy(check_reference_content=True)
    assert validate_skill_package(root, source_revision=REVISION, policy=policy).status == "blocked"
    reference.write_bytes(b"\xef\xbb\xbf# Example\n")
    assert validate_skill_package(root, source_revision=REVISION, policy=policy).status == "pass"


def test_binary_references_and_nested_resources_are_not_text_requirements(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (root / "references/image.png").write_bytes(b"\xff\x00")
    (root / "references/nested").mkdir()
    (root / "references/nested/example.json").write_text("[1, 2]\n")
    assert (
        validate_skill_package(
            root, source_revision=REVISION, policy=SkillValidationPolicy(check_reference_content=True)
        ).status
        == "pass"
    )


@pytest.mark.parametrize(
    "required", [("../secret",), ("/secret",), ("references/a", "references/a"), (3,), ["README.md"]]
)
def test_invalid_required_file_policy_is_a_typed_blocker(tmp_path: Path, required: object) -> None:
    root = _package(tmp_path)
    policy = SkillValidationPolicy()
    object.__setattr__(policy, "required_files", required)
    result = validate_skill_package(root, source_revision=REVISION, policy=policy)
    assert result.status == "blocked"
    assert result.candidate is None
    assert result.findings[0].code == "invalid_validation_policy"


def test_forged_boolean_policy_is_revalidated(tmp_path: Path) -> None:
    policy = SkillValidationPolicy()
    object.__setattr__(policy, "check_reference_content", "false")
    result = validate_skill_package(_package(tmp_path), source_revision=REVISION, policy=policy)
    assert result.status == "blocked"
    assert result.findings[0].code == "invalid_validation_policy"


def test_intake_reuses_applicable_package_policy(tmp_path: Path) -> None:
    root = _package(tmp_path)
    context = SkillPackageIntakeContext.model_validate(
        {
            "source_repository": "jscraik/fixture",
            "source_revision": REVISION,
            "source_path": "quality-fixture",
            "source_kind": "git",
            "owner": {
                "owner": "fixture",
                "maintainer": "fixture",
                "ownership_state": "canonical",
                "rights": {"basis": "authored", "license": "MIT", "evidence_ref": "SKILL.md"},
            },
            "checks": {"identity": True, "provenance": True, "rights": True, "owner_unchanged": True},
        }
    )
    policy = SkillValidationPolicy(required_files=("references/README.md",))
    blocked = intake_skill_package(root, context, policy=policy)
    assert blocked.status == "blocked"
    (root / "references/README.md").write_text("# Reference routing\n")
    accepted = intake_skill_package(root, context, policy=policy)
    assert accepted.status == "normalized"
    assert accepted.validation.status == "pass"


def test_required_symlink_does_not_satisfy_policy(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (tmp_path / "outside.md").write_text("# Outside\n")
    (root / "references/README.md").symlink_to(tmp_path / "outside.md")
    result = validate_skill_package(
        root, source_revision=REVISION, policy=SkillValidationPolicy(required_files=("references/README.md",))
    )
    assert result.status == "blocked"
    assert "required_file_missing" in {finding.code for finding in result.findings}


@pytest.mark.parametrize("command", ["validate", "build"])
def test_public_cli_policy_rejection_and_recovery(tmp_path: Path, command: str) -> None:
    root = _package(tmp_path)
    arguments = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        command,
        str(root),
        "--source-revision",
        REVISION,
        "--require-file",
        "references/README.md",
        "--check-reference-content",
        "--json",
    ]
    blocked = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert blocked.returncode == 2, blocked.stderr
    assert json.loads(blocked.stdout)["status"] == "blocked"
    (root / "references/README.md").write_text("# Reference routing\n")
    accepted = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["status"] == ("built" if command == "build" else "pass")
