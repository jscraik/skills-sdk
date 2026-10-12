#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."
scope="$(mise exec -- uv run --frozen python scripts/validation_scope.py "$@")"
if [[ "$scope" != docs ]]; then
  echo "documentation-only validation rejected: run bash scripts/validate-repository.sh" >&2
  exit 2
fi
bash scripts/validate-repository.sh quality
bash scripts/validate-repository.sh docs-tests
bash scripts/validate-repository.sh diff
