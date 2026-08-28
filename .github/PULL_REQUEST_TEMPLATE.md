# Pull request

Write for maintainers. Use `n.a.` with a concrete reason when a field does not
apply. Do not include secrets, raw transcripts, bulky telemetry, or local
absolute paths.

## Summary

- Problem:
- Change:
- Intended outcome:
- Out of scope:
- Reviewer focus:
- Risk and rollback:

## Contract and evidence boundaries

- Public API impact:
- Schema impact:
- Provider impact:
- Runtime impact:
- Distribution impact:
- Compatibility impact:

## Behavior proof

- Before:
- After:
- Operator path:
- Evidence:
- Untested paths and limitations:

## Validation

- Regression coverage:
<!-- Add one evidence line for each command:
- Command: `bash scripts/validate-repository.sh` -> pass
- Command: `uv run pytest tests/test_repository_standards.py -q` -> blocked (reason)
-->
- Untested or blocked paths:

## Review and readiness

- Create readiness:
- Update readiness:
- Guarded body refresh:
- CodeRabbit:
- Codex:
- Unresolved findings:

## Checklist

- [ ] The branch is dedicated to this change and is not `main`.
- [ ] Core, provider, runtime, and distribution claims are separated.
- [ ] Public contracts include schema and compatibility proof.
- [ ] Required validation passed without a waiver or suppression.
- [ ] Private package source, generated receipts, and credentials are absent.
- [ ] The PR body was refreshed only through the receipt-bound body helper.
- [ ] The branch will be removed after merge.
