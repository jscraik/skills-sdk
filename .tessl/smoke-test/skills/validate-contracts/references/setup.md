# Bounded worker setup

Only inside this experiment's disposable Linux x86_64 worker. No sudo or
system installation is needed. Verify HEAD first. The archive URL/digest below
are copied from this candidate's .circleci/config.yml, not an unpinned latest
installer. If mise already exists, use it; the project still selects its own
Python minor and exact uv version. Missing curl, tar, sha256sum or an unsupported
architecture is a setup blocker; do not improvise another installation route.

If mise is missing, bootstrap into an owned temporary directory under
/var/tmp (Tessl documents /tmp as memory-backed). Run the following in one
Bash invocation so PATH persists; record command output and stop on any error:

```bash
set -eo pipefail
if ! command -v mise >/dev/null 2>&1; then
  sdk_tools_dir="$(mktemp -d /var/tmp/sdk-validation-tools.XXXXXX)"
  curl --fail --location --max-time 120 https://github.com/jdx/mise/releases/download/v2026.8.14/mise-v2026.8.14-linux-x64.tar.gz -o "$sdk_tools_dir/mise.tar.gz"
  printf '%s  %s\n' '64d5f34aeb7a4e0e327dc1c9be66cd8162e14899a47b11901154a100285a3d61' "$sdk_tools_dir/mise.tar.gz" | sha256sum -c -
  tar -xzf "$sdk_tools_dir/mise.tar.gz" -C "$sdk_tools_dir"
  export PATH="$sdk_tools_dir/mise/bin:$PATH"
fi
export MISE_CEILING_PATHS="$PWD/.."
export MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml"
env -u GH_TOKEN -u GITHUB_TOKEN -u GITHUB_PERSONAL_ACCESS_TOKEN mise install python uv
env -u GH_TOKEN -u GITHUB_TOKEN -u GITHUB_PERSONAL_ACCESS_TOKEN mise exec -- uv sync --frozen
mise exec -- python --version
mise exec -- uv --version
```

Keep the same PATH and trust variables for validation (or explicitly pass
the resolved mise path). Assert Python3.12 and uv0.13.5 before the test command;
Python's patch version may differ because .mise.toml selects minor3.12.
Downloads and build caches are expected setup writes, confined to the worker.
Do not edit .mise.toml, uv.lock, pyproject.toml, shell profiles, cloud hooks,
project links, or developer configuration. Do not add retries to setup/test
commands. Record network/permission/dependency failures and stop.

References checked for this preparation:
- https://docs.tessl.io/automations/cloud-setup-hook
- https://docs.tessl.io/reference/cli-commands
