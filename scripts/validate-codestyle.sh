#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python scripts/check_repository_standards.py
mise exec -- vale --config .vale.ini .
