#!/bin/bash
set -eo pipefail
if [[ "${AGENT:-}" != "claude-code" ]]; then
  echo 'Blocked: this canary requires Claude.' >&2
  exit 1
fi
if [[ -z "${SDK_CANARY_POLICY_SHA256:-}" ]]; then
  echo 'Blocked: approved policy digest is required.' >&2
  exit 1
fi
echo 'Preparing the single admitted worker canary.'
python3 -I -B .tessl/platform_driver.py --phase setup \
  --policy .tessl/canary-policy.json --policy-sha256 "$SDK_CANARY_POLICY_SHA256" \
  --parent "$HOME" --receipt "$HOME/.sdk-tessl-canary-setup.json"
