---
schema_version: 1
---

# Skills SDK agent guidance

Skills SDK is the public, portable implementation of package authoring,
validation, security, evaluation, receipt, and handoff contracts for Agent
Skills. It is not a package Foundry, runtime installation, or distribution
registry.

## Boundaries

- Keep the core independent of Agent-Skills, Tessl, Codex, and local runtime
  filesystem layouts. Integrations implement explicit provider interfaces.
- Never commit private skill source, credentials, opaque secret values,
  machine-specific paths, generated receipts, or provider run histories.
- Keep source, validation, runtime, provider, distribution, and publication
  evidence separate.
- Preserve stable receipt fields and schema versions. Test compatibility before
  changing a public contract.
- Never waive or suppress a failed contract. Repair the implementation or emit
  a typed blocker.

## Validation

Run `bash scripts/validate-repository.sh` before a commit or pull request.
