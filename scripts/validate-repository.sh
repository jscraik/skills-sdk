#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."

phase="${1:-all}"
if [[ $# -gt 1 || ! "$phase" =~ ^(all|quality|docs-tests|tests|build|installed|diff)$ ]]; then
  echo "usage: bash scripts/validate-repository.sh [all|quality|docs-tests|tests|build|installed|diff]" >&2
  exit 2
fi

# Run the labeled command, report elapsed seconds, and return its exit status.
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
if [[ "$phase" == docs-tests ]]; then
  run_timed docs-tests mise exec -- uv run --frozen pytest \
    tests/test_public_repository_boundary.py tests/test_skill_validation_architecture.py --durations=10 \
    --junitxml=.tmp/test-results/docs.xml -o junit_family=xunit1
fi
if [[ "$phase" == all || "$phase" == tests ]]; then
  run_timed tests mise exec -- uv run --frozen --extra images pytest -n 2 --dist load --durations=25 \
    --durations-min=0.1 --junitxml=.tmp/test-results/full.xml -o junit_family=xunit1
fi
if [[ "$phase" == all || "$phase" == build ]]; then
  run_timed build mise exec -- uv build
fi
if [[ "$phase" == all || "$phase" == installed ]]; then
  run_timed installed bash scripts/validate-installed.sh
fi
if [[ "$phase" == all || "$phase" == diff ]]; then
  # Main checks the entire tree so multi-commit pushes cannot hide earlier damage.
  if [[ -n "${SDK_CI_BASE_SHA:-}" ]]; then
    diff_base="$SDK_CI_BASE_SHA"
    git rev-parse --verify "$diff_base^{commit}" >/dev/null
  elif [[ "${CIRCLE_BRANCH:-}" != main ]] && git rev-parse --verify HEAD^ >/dev/null 2>&1; then
    diff_base=HEAD^
  else
    diff_base="$(git hash-object -t tree /dev/null)"
  fi
  run_timed committed-diff git diff --check "$diff_base" HEAD
  run_timed staged-diff git diff --cached --check
  run_timed diff git diff --check
fi
