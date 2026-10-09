#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."

mise exec -- uv run --frozen python scripts/generate_schemas.py --check
bash scripts/validate-codestyle.sh
mise exec -- uv run --frozen pytest
mise exec -- uv build
smoke_venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/sdk-pr-sweep-smoke.XXXXXXXX")"
trap 'rm -rf -- "$smoke_venv_dir"' EXIT
sdk_wheel_version="$(mise exec -- uv version --short)"
sdk_built_wheels=(dist/skills_sdk-"$sdk_wheel_version"-*.whl)
if [[ ${#sdk_built_wheels[@]} -ne 1 || ! -f "${sdk_built_wheels[0]}" ]]; then
  echo "expected exactly one wheel for the current SDK version" >&2
  exit 1
fi
mise exec -- uv venv --python 3.12 "$smoke_venv_dir"
mise exec -- uv pip install --python "$smoke_venv_dir/bin/python" "${sdk_built_wheels[0]}"
"$smoke_venv_dir/bin/python" tests/installed_pr_sweep_smoke.py
"$smoke_venv_dir/bin/python" tests/installed_package_quality_smoke.py
"$smoke_venv_dir/bin/python" tests/installed_plugin_intake_smoke.py
"$smoke_venv_dir/bin/python" tests/installed_scenario_coverage_smoke.py
"$smoke_venv_dir/bin/python" tests/installed_content_review_smoke.py
mise exec -- uv run --frozen python tests/installed_quality_workflow_smoke.py --prepare "$smoke_venv_dir/quality-inputs"
"$smoke_venv_dir/bin/python" tests/installed_quality_workflow_smoke.py --check "$smoke_venv_dir/quality-inputs"
mise exec -- uv run --frozen python tests/installed_pre_execution_smoke.py --prepare "$smoke_venv_dir/safety-inputs"
"$smoke_venv_dir/bin/python" tests/installed_pre_execution_smoke.py --check "$smoke_venv_dir/safety-inputs"
mise exec -- uv run --frozen python tests/installed_observed_calibration_smoke.py --prepare "$smoke_venv_dir/calibration-inputs"
"$smoke_venv_dir/bin/python" tests/installed_observed_calibration_smoke.py --check "$smoke_venv_dir/calibration-inputs"
git diff --check
