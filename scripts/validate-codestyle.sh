#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"

mise exec -- uv run ruff format --check .
mise exec -- uv run ruff check .
mise exec -- uv run mypy
mise exec -- uv run python scripts/check_repository_standards.py
mise exec -- vale --config .vale.ini .
