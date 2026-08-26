from __future__ import annotations

import copy
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.packaging import build_skill_package
from skills_sdk.validation import SkillValidationPolicy, validate_skill_package
from skills_sdk.validation import skill_package as skill_package_module

REVISION = "1" * 40


def _write_skill(root: Path, *, name: str | None = None, extra_frontmatter: str = "", body: str = "Do work.\n") -> Path:
    root.mkdir(parents=True)
    package_name = name or root.name
    (root / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {package_name}",
                "description: Deterministic validation fixture.",
                "metadata:",
                "  version: 1.2.3",
                extra_frontmatter.rstrip(),
                "---",
                "",
                "# Fixture",
                "",
                body.rstrip(),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def _clock() -> datetime:
    return datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_validation_builds_portable_identity_and_deterministic_manifest(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    references = root / "references"
    references.mkdir()
    (references / "guide.md").write_text("# Guide\n", encoding="utf-8")

    validation = validate_skill_package(root, source_revision=REVISION)
    first = build_skill_package(root, source_revision=REVISION, clock=_clock)
    second = build_skill_package(root, source_revision=REVISION, clock=_clock)

    assert validation.status == "pass"
    assert validation.identity is not None
    assert validation.identity.name == "fixture-skill"
    assert validation.identity.version == "1.2.3"
    assert [item.path for item in validation.files] == ["README.md", "SKILL.md", "references/guide.md"]
    assert first.status == "built"
    assert first.package_digest == second.package_digest
    assert first.candidate == second.candidate
    assert first.manifest == second.manifest
    SchemaRegistry().validate("skill-package-validation.v1", validation.model_dump(mode="json"))
    SchemaRegistry().validate("package-receipt.v1", first.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("frontmatter", "expected_code"),
    [
        ("name: wrong-name\ndescription: Valid.", "name_mismatch"),
        ("name: fixture-skill", "missing_description"),
        ("name: fixture-skill\ndescription: Valid.\nunknown: value", "unknown_frontmatter"),
    ],
)
def test_frontmatter_failures_are_typed(tmp_path: Path, frontmatter: str, expected_code: str) -> None:
    root = tmp_path / "fixture-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n# Fixture\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert expected_code in {item.code for item in result.findings}


def test_unclosed_frontmatter_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "fixture-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: fixture-skill\n", encoding="utf-8")
    result = validate_skill_package(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert {item.code for item in result.findings} == {"invalid_frontmatter"}


@pytest.mark.parametrize("declared_name", [None, ""])
def test_missing_or_empty_name_is_blocked(tmp_path: Path, declared_name: str | None) -> None:
    root = tmp_path / "fixture-skill"
    root.mkdir()
    name_line = "" if declared_name is None else "name:"
    (root / "SKILL.md").write_text(
        f"---\n{name_line}\ndescription: Valid.\n---\n\n# Fixture\n",
        encoding="utf-8",
    )
    result = validate_skill_package(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert "missing_name" in {item.code for item in result.findings}


def test_top_level_and_nested_versions_are_both_supported(tmp_path: Path) -> None:
    top_level = tmp_path / "top-level"
    nested = tmp_path / "nested"
    for root, version_block in ((top_level, "version: 2.0.0"), (nested, "metadata:\n  version: 3.0.0")):
        root.mkdir()
        (root / "SKILL.md").write_text(
            f"---\nname: {root.name}\ndescription: Valid.\n{version_block}\n---\n\n# Fixture\n",
            encoding="utf-8",
        )
    top_result = validate_skill_package(top_level, source_revision=REVISION)
    nested_result = validate_skill_package(nested, source_revision=REVISION)
    assert top_result.identity is not None and top_result.identity.version == "2.0.0"
    assert nested_result.identity is not None and nested_result.identity.version == "3.0.0"


def test_invalid_package_directory_returns_typed_blocker(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "Bad Name", name="bad-name")
    result = validate_skill_package(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert "invalid_package_root" in {item.code for item in result.findings}
    assert result.candidate.package_id.startswith("invalid-package-")


def test_distinct_invalid_roots_cannot_alias_candidate_identity(tmp_path: Path) -> None:
    first_root = _write_skill(tmp_path / "Bad Name", name="valid-name")
    second_root = _write_skill(tmp_path / "Another Bad Name", name="valid-name")

    first = validate_skill_package(first_root, source_revision=REVISION)
    second = validate_skill_package(second_root, source_revision=REVISION)

    assert first.candidate.package_id != second.candidate.package_id


def test_surrogate_root_name_has_deterministic_fallback_identity() -> None:
    candidate = skill_package_module._candidate(Path("/tmp/bad-\udcff"), REVISION, [])

    assert candidate.package_id.startswith("invalid-package-")


def test_symlink_and_credential_like_files_are_blocked(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    references = root / "references"
    references.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (references / "escape.md").symlink_to(outside)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "private.pem").write_text("not-a-real-key\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert {item.code for item in result.findings} == {"symlink_not_allowed", "unsafe_package_file"}
    assert "scripts/private.pem" not in {item.path for item in result.files}


def test_injected_authoring_budgets_block_without_becoming_core_defaults(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill", body="line one\nline two\nline three")
    nested = root / "references" / "nested"
    nested.mkdir(parents=True)
    (nested / "guide.md").write_text("# Nested\n", encoding="utf-8")

    portable = validate_skill_package(root, source_revision=REVISION)
    governed = validate_skill_package(
        root,
        source_revision=REVISION,
        policy=SkillValidationPolicy(max_entrypoint_lines=5, max_reference_depth=1),
    )

    assert portable.status == "pass"
    assert governed.status == "blocked"
    assert {item.code for item in governed.findings} == {
        "entrypoint_line_budget_exceeded",
        "reference_depth_exceeded",
    }


def test_package_directory_depth_is_hard_limited(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    nested = root
    for index in range(skill_package_module._MAX_PACKAGE_DIRECTORY_DEPTH):
        nested /= f"level-{index}"
        nested.mkdir()
    (nested / "included.txt").write_text("included\n", encoding="utf-8")
    too_deep = nested / "too-deep"
    too_deep.mkdir()
    (too_deep / "excluded.txt").write_text("excluded\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    expected_prefix = "/".join(f"level-{index}" for index in range(skill_package_module._MAX_PACKAGE_DIRECTORY_DEPTH))
    assert result.status == "blocked"
    assert "package_depth_exceeded" in {item.code for item in result.findings}
    assert f"{expected_prefix}/included.txt" in {item.path for item in result.files}
    assert f"{expected_prefix}/too-deep/excluded.txt" not in {item.path for item in result.files}


def test_build_returns_typed_blocked_receipt_without_mutation(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill", name="different-skill")
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    receipt = build_skill_package(root, source_revision=REVISION, clock=_clock)

    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "name_mismatch"
    assert receipt.package_digest is None
    assert receipt.mutation_performed is False
    assert after == before


def test_missing_source_is_blocked_without_touching_filesystem(tmp_path: Path) -> None:
    root = tmp_path / "missing-skill"
    result = validate_skill_package(root, source_revision=REVISION)
    assert result.status == "blocked"
    assert result.findings[0].code == "invalid_package_root"
    assert not root.exists()


@pytest.mark.parametrize("reference", ["/tmp/x", "../x", "a//b", "a/./b"])
def test_finding_evidence_refs_require_portable_paths(reference: str) -> None:
    from pydantic import ValidationError

    from skills_sdk.models.validation import SkillPackageFinding

    with pytest.raises(ValidationError):
        SkillPackageFinding(
            code="invalid_path",
            severity="blocker",
            message="invalid",
            evidence_refs=(reference,),
        )


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: fixture-skill\nname: duplicate\ndescription: Valid.",
        "- name\n- description",
        "name: 'unterminated\ndescription: Valid.",
    ],
)
def test_malformed_yaml_is_a_typed_blocker(tmp_path: Path, frontmatter: str) -> None:
    root = tmp_path / "fixture-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n# Fixture\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "invalid_frontmatter" in {item.code for item in result.findings}


def test_candidate_digest_binds_all_safe_package_files(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    agents = root / "agents"
    agents.mkdir()
    (agents / "openai.yaml").write_text("interface: minimal\n", encoding="utf-8")
    (root / "extra.txt").write_text("first\n", encoding="utf-8")

    first = validate_skill_package(root, source_revision=REVISION)
    (root / "extra.txt").write_text("second\n", encoding="utf-8")
    second = validate_skill_package(root, source_revision=REVISION)

    assert first.status == "pass"
    assert {item.path for item in first.files} == {"SKILL.md", "LICENSE", "agents/openai.yaml", "extra.txt"}
    assert first.candidate.content_sha256 != second.candidate.content_sha256


def test_unrecognised_package_files_use_a_v1_compatible_role(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    license_file = next(item for item in result.files if item.path == "LICENSE")
    assert license_file.role == "asset"


@pytest.mark.parametrize("directory_name", [".venv", "venv", ".pytest_cache", "node_modules"])
def test_generated_environment_directories_are_blocked(tmp_path: Path, directory_name: str) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    generated = root / directory_name
    generated.mkdir()
    (generated / "state.txt").write_text("generated\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert "unsafe_package_directory" in {item.code for item in result.findings}
    assert all(not item.path.startswith(directory_name) for item in result.files)


@pytest.mark.parametrize("filename", ["package-receipt.json", "skill-package-validation.json"])
def test_generated_validation_receipts_are_blocked(tmp_path: Path, filename: str) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    (root / filename).write_text("{}\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert "unsafe_package_file" in {item.code for item in result.findings}
    assert filename not in {item.path for item in result.files}


def test_unsafe_nested_file_and_runtime_directory_are_blocked(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    nested = root / "assets" / "private"
    nested.mkdir(parents=True)
    (nested / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    runtime = root / ".codex"
    runtime.mkdir()
    (runtime / "state.json").write_text("{}\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert {item.code for item in result.findings} == {"unsafe_package_directory", "unsafe_package_file"}
    assert "assets/private/.env" not in {item.path for item in result.files}


def test_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    root = _write_skill(tmp_path / "fixture-skill")
    fifo = root / "assets" / "input.pipe"
    fifo.parent.mkdir()
    fifo.parent.mkdir(exist_ok=True)
    os.mkfifo(fifo)

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "unreadable_package_file" in {item.code for item in result.findings}


def test_nonportable_filename_is_a_typed_blocker(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    (root / "bad\nname").write_text("invalid\n", encoding="utf-8")

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "invalid_package_path" in {item.code for item in result.findings}


def test_undecodable_filename_is_a_typed_blocker(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("surrogateescape filename proof requires POSIX")
    root = _write_skill(tmp_path / "fixture-skill")
    try:
        descriptor = os.open(os.fsencode(root) + b"/bad-\xff", os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        pytest.skip("filesystem rejects undecodable byte names")
    os.close(descriptor)

    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "invalid_package_path" in {item.code for item in result.findings}


def test_unsupported_safe_traversal_returns_dedicated_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_skill(tmp_path / "fixture-skill")

    def unsupported(_path: Path) -> int:
        raise skill_package_module._UnsupportedSafeTraversal

    monkeypatch.setattr(skill_package_module, "_open_directory_tree", unsupported)
    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "unsupported_platform" in {item.code for item in result.findings}


def test_observed_file_change_returns_source_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    original = skill_package_module._read_regular_bytes

    def changed(parent_fd: int, name: str) -> tuple[bytes, bool]:
        payload, _stable = original(parent_fd, name)
        return payload, False

    monkeypatch.setattr(skill_package_module, "_read_regular_bytes", changed)
    result = validate_skill_package(root, source_revision=REVISION)

    assert result.status == "blocked"
    assert "source_changed" in {item.code for item in result.findings}


def test_root_source_change_finding_has_portable_evidence() -> None:
    finding = skill_package_module._source_changed_finding(Path())

    assert finding.code == "source_changed"
    assert finding.evidence_refs == ()


def test_generated_schema_enforces_raw_status_invariants(tmp_path: Path) -> None:
    root = _write_skill(tmp_path / "fixture-skill")
    valid = validate_skill_package(root, source_revision=REVISION).model_dump(mode="json")
    registry = SchemaRegistry()

    invalid_pass = copy.deepcopy(valid)
    invalid_pass["identity"] = None
    with pytest.raises(ContractError):
        registry.validate("skill-package-validation.v1", invalid_pass)

    invalid_blocked = copy.deepcopy(valid)
    invalid_blocked["status"] = "blocked"
    with pytest.raises(ContractError):
        registry.validate("skill-package-validation.v1", invalid_blocked)

    mismatched_identity = copy.deepcopy(valid)
    mismatched_identity["identity"]["package_id"] = "different-skill"
    mismatched_identity["identity"]["name"] = "different-skill"
    with pytest.raises(ContractError):
        registry.validate("skill-package-validation.v1", mismatched_identity)
