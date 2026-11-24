#!/usr/bin/env bash
set -euo pipefail

# Tessl runs this from the selected checkout before starting the agent.
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  printf '%s\n' 'SDK cloud setup requires Linux x86_64' >&2
  exit 1
fi
repo_root="$(pwd -P)"
if [[ ! -f "$repo_root/.mise.toml" || ! -f "$repo_root/uv.lock" ||
      ! -f "$repo_root/scripts/circleci-mise-bootstrap.sh" ]]; then
  printf '%s\n' 'SDK cloud setup requires the checkout tool pins, lockfile and CI bootstrap' >&2
  exit 1
fi

# Reuse CI's pinned download and SHA-256 verification. No credential is needed
# to download tools or public dependencies.
unset GH_TOKEN GITHUB_TOKEN GITHUB_PERSONAL_ACCESS_TOKEN
bash scripts/circleci-mise-bootstrap.sh
scratch="$(mktemp -d /var/tmp/sdk-cloud-setup.XXXXXXXX)"
trap 'rm -rf -- "$scratch"' EXIT
tar -xzf /tmp/mise.tar.gz -C "$scratch"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$scratch/mise/bin/mise" "$HOME/.local/bin/mise"

# Child-process PATH changes do not reach the agent. Tessl already exposes
# ~/.local/bin; put mise there and resolve SDK commands through mise exec.
export PATH="$HOME/.local/bin:$PATH"
export MISE_CEILING_PATHS="$(cd "$repo_root/.." && pwd -P)"
export MISE_TRUSTED_CONFIG_PATHS="$repo_root/.mise.toml"
# Trusted paths grant trust, not config isolation. Exclude worker-owned configs.
export MISE_CONFIG_DIR="$scratch/config"
export MISE_SYSTEM_CONFIG_DIR="$scratch/system-config"
export MISE_GLOBAL_CONFIG_FILE="$scratch/global.toml"
export MISE_SYSTEM_CONFIG_FILE="$scratch/system.toml"
: > "$MISE_GLOBAL_CONFIG_FILE"
: > "$MISE_SYSTEM_CONFIG_FILE"
# mise install may persist trust; discard preparation state on every exit.
export MISE_STATE_DIR="$scratch/mise-state"
mise install python uv ruff vale
mise exec -- uv sync --frozen --extra images
mise exec -- python --version
mise exec -- uv --version
printf '%s\n' 'SDK dependency preparation completed; validation has not run.'
