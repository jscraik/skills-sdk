#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"

mise exec -- uv run --frozen ruff format --check .
mise exec -- uv run --frozen ruff check .
mise exec -- uv run --frozen mypy
mise exec -- uv run --frozen python scripts/check_repository_standards.py
prose_files=()
while IFS= read -r prose_file; do
  prose_files+=("$prose_file")
done < <(git ls-files -- '*.md' '*.mdx' '*.adoc' '*.rst')

if [[ ${#prose_files[@]} -eq 0 ]]; then
  echo "codestyle validation requires tracked repository prose" >&2
  exit 1
fi

mise exec -- vale --config .vale.ini "${prose_files[@]}"
