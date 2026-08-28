#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

uv run python scripts/generate_schemas.py --check
bash scripts/validate-codestyle.sh
uv run pytest
uv build
git diff --check
