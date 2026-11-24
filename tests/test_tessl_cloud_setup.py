"""Exercise worker preparation without downloads or caller-owned state changes."""

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".tessl/cloud-launch-setup.sh"


def _executable(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def worker(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    checkout, home, tools = (tmp_path / name for name in ("checkout", "home", "tools"))
    for directory in (checkout / "scripts", home, tools):
        directory.mkdir(parents=True)
    (checkout / ".mise.toml").write_text('[tools]\npython = "3.12"\n', encoding="utf-8")
    (checkout / "uv.lock").write_text("synthetic lock\n", encoding="utf-8")
    (checkout / "scripts/circleci-mise-bootstrap.sh").write_text(
        'printf "bootstrap\\n" >> "$PROOF_LOG"\nexit "${BOOTSTRAP_EXIT:-0}"\n', encoding="utf-8"
    )
    # Keep every process and scratch path in the fixture; cloud tools are stand-ins.
    for name in ("bash", "mkdir", "install", "rm", "mktemp", "cat", "chmod"):
        target = shutil.which(name)
        assert target is not None
        (tools / name).symlink_to(target)
    (tools / "mktemp").unlink()
    _executable(tools, "uname", 'case "$1" in -s) echo "${FIXTURE_OS:-Linux}";; -m) echo x86_64;; esac\n')
    _executable(tools, "mktemp", f'exec "{shutil.which("mktemp")}" -d "$FIXTURE_TMP/scratch.XXXXXXXX"\n')
    _executable(
        tools,
        "tar",
        """printf 'extract\n' >> "$PROOF_LOG"
while [[ "$1" != -C ]]; do shift; done
shift
mkdir -p "$1/mise/bin"
cat > "$1/mise/bin/mise" <<'MISE'
#!/bin/bash
set -eu
[[ -z "${GH_TOKEN+x}" && -z "${GITHUB_TOKEN+x}" && -z "${GITHUB_PERSONAL_ACCESS_TOKEN+x}" ]]
[[ "$MISE_TRUSTED_CONFIG_PATHS" == "$PWD/.mise.toml" ]]
[[ "$MISE_CEILING_PATHS" == "$PWD/.." ]]
printf '%s\n' "$*" >> "$PROOF_LOG"
[[ "${FAIL_SYNC:-0}" != 1 || "$*" != 'exec -- uv sync --frozen --extra images' ]]
MISE
chmod 755 "$1/mise/bin/mise"
""",
    )
    environment = {
        "HOME": str(home),
        "PATH": str(tools),
        "FIXTURE_TMP": str(tmp_path),
        "PROOF_LOG": str(tmp_path / "commands"),
        "GH_TOKEN": "synthetic-sentinel",
        "GITHUB_TOKEN": "synthetic-sentinel",
        "GITHUB_PERSONAL_ACCESS_TOKEN": "synthetic-sentinel",
    }
    return checkout, home, environment


def _run(worker: tuple[Path, Path, dict[str, str]]) -> subprocess.CompletedProcess[str]:
    checkout, _, environment = worker
    return subprocess.run(
        ["/bin/bash", str(HOOK)], cwd=checkout, env=environment, capture_output=True, text=True, check=False
    )


def test_repeated_setup_preserves_inputs_and_scopes_environment(worker: tuple[Path, Path, dict[str, str]]) -> None:
    checkout, home, environment = worker
    original_environment = environment.copy()
    sentinel = home / "existing-setting"
    sentinel.write_bytes(b"preserve existing settings")
    lock_before = (checkout / "uv.lock").read_bytes()
    for _ in range(2):
        result = _run(worker)
        assert result.returncode == 0, result.stderr
        assert "validation has not run" in result.stdout
    assert environment == original_environment
    assert sentinel.read_bytes() == b"preserve existing settings"
    assert (checkout / "uv.lock").read_bytes() == lock_before
    assert (home / ".local/bin/mise").is_file()
    assert not (home / ".config").exists()
    commands = Path(environment["PROOF_LOG"]).read_text(encoding="utf-8").splitlines()
    assert (
        commands
        == [
            "bootstrap",
            "extract",
            "install python uv ruff vale",
            "exec -- uv sync --frozen --extra images",
            "exec -- python --version",
            "exec -- uv --version",
        ]
        * 2
    )
    assert not list(Path(environment["FIXTURE_TMP"]).glob("scratch.*"))


def test_unsupported_platform_stops_before_bootstrap(worker: tuple[Path, Path, dict[str, str]]) -> None:
    worker[2]["FIXTURE_OS"] = "Darwin"
    result = _run(worker)
    assert result.returncode != 0
    assert "requires Linux x86_64" in result.stderr
    assert not Path(worker[2]["PROOF_LOG"]).exists()


@pytest.mark.parametrize("missing", [".mise.toml", "uv.lock", "scripts/circleci-mise-bootstrap.sh"])
def test_missing_input_stops_before_bootstrap(worker: tuple[Path, Path, dict[str, str]], missing: str) -> None:
    (worker[0] / missing).unlink()
    assert _run(worker).returncode != 0
    assert not Path(worker[2]["PROOF_LOG"]).exists()


def test_failed_bootstrap_stops_before_install(worker: tuple[Path, Path, dict[str, str]]) -> None:
    worker[2]["BOOTSTRAP_EXIT"] = "7"
    assert _run(worker).returncode == 7
    assert Path(worker[2]["PROOF_LOG"]).read_text(encoding="utf-8") == "bootstrap\n"
    assert not (worker[1] / ".local").exists()


def test_failed_sync_stops_and_cleans_scratch(worker: tuple[Path, Path, dict[str, str]]) -> None:
    worker[2]["FAIL_SYNC"] = "1"
    result = _run(worker)
    assert result.returncode != 0
    assert "completed" not in result.stdout
    commands = Path(worker[2]["PROOF_LOG"]).read_text(encoding="utf-8")
    assert "exec -- python --version" not in commands
    assert not list(Path(worker[2]["FIXTURE_TMP"]).glob("scratch.*"))
