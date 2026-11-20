#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
export MISE_CEILING_PATHS="$repo_root/.."

# Keep timing output off stdout so wheel-version remains safe to capture.
run_timed() {
  local label="$1" started="$SECONDS" result=0
  shift
  printf 'installed-smoke: start %s\n' "$label" >&2
  "$@" || result=$?
  printf 'installed-smoke: finish %s status=%s elapsed_seconds=%s\n' \
    "$label" "$result" "$((SECONDS - started))" >&2
  return "$result"
}

smoke_venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/sdk-pr-sweep-smoke.XXXXXXXX")"
trap 'rm -rf -- "$smoke_venv_dir"' EXIT
sdk_wheel_version="$(run_timed wheel-version mise exec -- uv version --short)"
sdk_built_wheels=(dist/skills_sdk-"$sdk_wheel_version"-*.whl)
if [[ ${#sdk_built_wheels[@]} -ne 1 || ! -f "${sdk_built_wheels[0]}" ]]; then
  echo "expected exactly one wheel for the current SDK version" >&2
  exit 1
fi
run_timed create-venv mise exec -- uv venv --python 3.12 "$smoke_venv_dir"
run_timed install-base-wheel mise exec -- uv pip install --python "$smoke_venv_dir/bin/python" "${sdk_built_wheels[0]}"
run_timed pr-sweep "$smoke_venv_dir/bin/python" tests/installed_pr_sweep_smoke.py
run_timed codex-judge "$smoke_venv_dir/bin/python" tests/installed_codex_judge_smoke.py
run_timed fm-advisory "$smoke_venv_dir/bin/python" tests/installed_fm_advisory_smoke.py
run_timed package-quality "$smoke_venv_dir/bin/python" tests/installed_package_quality_smoke.py
run_timed plugin-intake "$smoke_venv_dir/bin/python" tests/installed_plugin_intake_smoke.py
run_timed plugin-presentation-without-images "$smoke_venv_dir/bin/python" tests/installed_plugin_presentation_smoke.py --without-images
run_timed scenario-coverage "$smoke_venv_dir/bin/python" tests/installed_scenario_coverage_smoke.py
run_timed content-review "$smoke_venv_dir/bin/python" tests/installed_content_review_smoke.py
run_timed quality-workflow-prepare mise exec -- uv run --frozen python tests/installed_quality_workflow_smoke.py --prepare "$smoke_venv_dir/quality-inputs"
run_timed quality-workflow-check "$smoke_venv_dir/bin/python" tests/installed_quality_workflow_smoke.py --check "$smoke_venv_dir/quality-inputs"
run_timed pre-execution-prepare mise exec -- uv run --frozen python tests/installed_pre_execution_smoke.py --prepare "$smoke_venv_dir/safety-inputs"
run_timed pre-execution-check "$smoke_venv_dir/bin/python" tests/installed_pre_execution_smoke.py --check "$smoke_venv_dir/safety-inputs"
run_timed observed-calibration-prepare mise exec -- uv run --frozen python tests/installed_observed_calibration_smoke.py --prepare "$smoke_venv_dir/calibration-inputs"
run_timed observed-calibration-check "$smoke_venv_dir/bin/python" tests/installed_observed_calibration_smoke.py --check "$smoke_venv_dir/calibration-inputs"
run_timed native-calibration-prepare mise exec -- uv run --frozen python tests/installed_native_calibration_smoke.py --prepare "$smoke_venv_dir/native-calibration-inputs"
run_timed native-calibration-check "$smoke_venv_dir/bin/python" tests/installed_native_calibration_smoke.py --check "$smoke_venv_dir/native-calibration-inputs"
run_timed native-matched-prepare mise exec -- uv run --frozen python tests/installed_native_matched_smoke.py --prepare "$smoke_venv_dir/native-matched-inputs"
run_timed native-matched-check "$smoke_venv_dir/bin/python" tests/installed_native_matched_smoke.py --check "$smoke_venv_dir/native-matched-inputs"
run_timed matched-prepare mise exec -- uv run --frozen python tests/installed_matched_smoke.py --prepare "$smoke_venv_dir/matched-inputs"
run_timed matched-check "$smoke_venv_dir/bin/python" tests/installed_matched_smoke.py --check "$smoke_venv_dir/matched-inputs"
run_timed install-images-extra mise exec -- uv pip install --python "$smoke_venv_dir/bin/python" "${sdk_built_wheels[0]}[images]"
run_timed plugin-presentation-with-images "$smoke_venv_dir/bin/python" tests/installed_plugin_presentation_smoke.py --with-images
run_timed plugin-quality-prepare mise exec -- uv run --frozen --extra images python tests/installed_plugin_quality_smoke.py --prepare "$smoke_venv_dir/plugin-quality-inputs"
run_timed plugin-quality-check "$smoke_venv_dir/bin/python" tests/installed_plugin_quality_smoke.py --check "$smoke_venv_dir/plugin-quality-inputs"
