#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"

mise exec -- uv run --frozen python scripts/generate_schemas.py --check
bash scripts/validate-codestyle.sh
mise exec -- uv run --frozen pytest
mise exec -- uv build
git diff --check
