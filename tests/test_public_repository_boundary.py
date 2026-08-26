from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BANNED_PATH_PARTS = {".agents", ".codex", ".harness", "packages"}
BANNED_TEXT = (
    "/" + "Users" + "/",
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "PRIVATE KEY",
    "tessl" + "_api_key",
)

PUBLIC_SURFACES = (
    "CHANGELOG.md",
    "SUPPORT.md",
    "docs/api.md",
    "docs/cli.md",
    "docs/compatibility.md",
    "docs/agent-entrypoint.md",
    "examples/inventory_contract.py",
)


def _source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / value for value in result.stdout.splitlines() if value]


def test_seed_has_no_private_package_or_runtime_roots() -> None:
    offending = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _source_files()
        if BANNED_PATH_PARTS.intersection(path.relative_to(REPO_ROOT).parts)
    ]
    assert offending == []


def test_public_repository_surfaces_are_present_and_linked() -> None:
    missing = [path for path in PUBLIC_SURFACES if not (REPO_ROOT / path).is_file()]
    assert missing == []

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for path in PUBLIC_SURFACES:
        assert f"{path}]" in readme or f"{path})" in readme


def test_public_docs_preserve_portable_and_no_waiver_boundaries() -> None:
    docs = "\n".join((REPO_ROOT / path).read_text(encoding="utf-8") for path in PUBLIC_SURFACES)
    assert "portable" in docs.casefold()
    assert "waiver" in docs.casefold()
    assert "provider" in docs.casefold()


def test_public_docs_distinguish_wire_shapes_from_semantic_registry_checks() -> None:
    api = (REPO_ROOT / "docs/api.md").read_text(encoding="utf-8")
    compatibility = (REPO_ROOT / "docs/compatibility.md").read_text(encoding="utf-8")
    assert 'exclude={"schema_version"}' in api
    assert "model-level semantic invariants" in api
    assert "model_validate(payload)" in api
    assert "not registered with `SchemaRegistry`" in api
    assert "bare wire shape" in compatibility
    assert "`receipt-base.v1` requires `schema_version`" in compatibility


def test_seed_has_no_machine_paths_keys_or_provider_secrets() -> None:
    offending: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker.casefold() in text.casefold() for marker in BANNED_TEXT):
            offending.append(path.relative_to(REPO_ROOT).as_posix())
    assert offending == []
