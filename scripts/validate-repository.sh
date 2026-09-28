#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."

mise exec -- uv run --frozen python scripts/generate_schemas.py --check
bash scripts/validate-codestyle.sh
mise exec -- uv run --frozen pytest
mise exec -- uv build
smoke_venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/sdk-pr-sweep-smoke.XXXXXXXX")"
trap 'rm -rf -- "$smoke_venv_dir"' EXIT
mise exec -- uv venv --python 3.12 "$smoke_venv_dir"
mise exec -- uv pip install --offline --python "$smoke_venv_dir/bin/python" dist/skills_sdk-0.1.0-py3-none-any.whl
"$smoke_venv_dir/bin/python" tests/installed_pr_sweep_smoke.py
git diff --check
