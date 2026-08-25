#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

uv run python scripts/generate_schemas.py
uv run ruff check .
uv run pytest
uv build
git diff --check
