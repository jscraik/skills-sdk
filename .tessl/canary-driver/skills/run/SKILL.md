---
name: run
description: Execute the single pre-approved Tessl worker control canary and report its actual result.
---

Run only the already approved worker canary. This skill grants no authority.
Require the setup hook's private owned receipt and the approved policy digest.
If setup failed, stop and report failure; do not repair or rerun it.

From the unchanged clone root, invoke:

```bash
python3 -I -B .tessl/platform_driver.py --phase canary --policy .tessl/canary-policy.json --policy-sha256 "$SDK_CANARY_POLICY_SHA256" --receipt "$HOME/.sdk-tessl-canary-setup.json"
```

The driver creates a child network namespace, enables loopback there, drops
privileges, verifies isolation and executes the existing hash-bound canary.
Missing sudo, namespace capability, policy, receipt, tool or authority is a
terminal blocker. Never use a networked fallback, --yolo, another agent,
Factory loop, reviewer, product command, push, metadata write or account key.
Do not print environment values or private helpers. Do not change the branch.

Report the driver's exit/status and public evidence root. Success requires
canary_pass plus the saved inner result's pass statuses for installation,
native hooks, signing and key cleanup. A zero log-stream exit or setup pass
alone is insufficient. Preserve failures. Do not retry or resume; stop after
this one invocation. The controller owns platform cancellation and teardown.
