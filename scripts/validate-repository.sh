#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."

phase="${1:-all}"
if [[ $# -gt 1 || ! "$phase" =~ ^(all|quality|tests|build|installed|diff)$ ]]; then
  echo "usage: bash scripts/validate-repository.sh [all|quality|tests|build|installed|diff]" >&2
  exit 2
fi

run_timed() {
  local label="$1" started="$SECONDS" result=0
  shift
  echo "validation: start $label"
  "$@" || result=$?
  echo "validation: finish $label status=$result elapsed_seconds=$((SECONDS - started))"
  return "$result"
}

if [[ "$phase" == all || "$phase" == quality ]]; then
  run_timed schemas mise exec -- uv run --frozen python scripts/generate_schemas.py --check
  run_timed codestyle bash scripts/validate-codestyle.sh
fi
if [[ "$phase" == all || "$phase" == tests ]]; then
  run_timed tests mise exec -- uv run --frozen pytest -n 2 --dist load --durations=25 --durations-min=0.1
fi
if [[ "$phase" == all || "$phase" == build ]]; then
  run_timed build mise exec -- uv build
fi
if [[ "$phase" == all || "$phase" == installed ]]; then
  run_timed installed bash scripts/validate-installed.sh
fi
if [[ "$phase" == all || "$phase" == diff ]]; then
  run_timed diff git diff --check
fi
