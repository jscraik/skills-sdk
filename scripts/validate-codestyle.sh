#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"

mise exec -- uv run --frozen ruff format --check .
mise exec -- uv run --frozen ruff check .
mise exec -- uv run --frozen mypy
mise exec -- uv run --frozen python scripts/check_repository_standards.py
mise exec -- vale --config .vale.ini .
