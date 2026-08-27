---
schema_version: 1
---

# Skills SDK agent guidance

Skills SDK is the public, portable implementation of package authoring,
validation, security, evaluation, receipt, and handoff contracts for Agent
Skills. It is a contract library and local tooling surface, not a package
Foundry, runtime installer, provider client, distribution registry, or
publication service.

## Scope and boundaries

- Keep the core independent of Agent-Skills, Tessl, Codex, and local runtime
  filesystem layouts; integrations own explicit provider or host adapters.
- Keep source, validation, runtime, provider, distribution, and publication
  evidence in separate lanes. Local contract proof does not establish hosted,
  installed, or published behavior.
- Treat `PackageCandidateIdentity` (`package_id`, `source_revision`, and
  `content_sha256`) as the binding identity for downstream manifests and
  receipts. Preserve stable receipt fields and schema versions.
- `validate_skill_package` and `build_skill_package` are read-only. Validation
  returns a `skill-package-validation/v1` result; a successful build returns a
  candidate-bound `package-receipt/v1`. A blocked build may have
  `candidate: null` when identity cannot be resolved, and neither path writes
  into the package.
- Validate untrusted data at the boundary. Never commit private skill source,
  credentials, opaque secret values, machine-specific paths, generated
  receipts, provider histories, or local runtime state.
- Never waive or suppress a failed contract. Repair the implementation or emit
  a typed blocker. Public contract changes require schema, behavior, and
  compatibility proof.

## Working language and discovery

- Use [`UBIQUITOUS.md`](UBIQUITOUS.md) as the canonical project vocabulary.
  Map overloaded phrases such as “build”, “publish”, “install”, “candidate”,
  and “receipt” through it before changing code or documentation.
- Use [`ARCHITECTURE.md`](ARCHITECTURE.md) for the bird's-eye code map,
  dependency boundaries, and architectural invariants before changing a
  module or public workflow.
- Read [`CODESTYLE.md`](CODESTYLE.md) before technical edits and
  [`CONTRIBUTING.md`](CONTRIBUTING.md) before commit or pull-request work.
- Use [`docs/agent-entrypoint.md`](docs/agent-entrypoint.md) for the short
  first-run route, [`docs/cli.md`](docs/cli.md) for command behavior,
  [`docs/api.md`](docs/api.md) for contract families, and
  [`docs/compatibility.md`](docs/compatibility.md) for versioning rules.
- Keep this file limited to rules every task needs. Put reader-facing detail
  and examples in the linked documentation surfaces.

## Development and validation

- Use Python `3.12` and the pinned `uv` environment: `uv sync --frozen`.
- Run the narrowest relevant check first. Schema changes require
  `uv run python scripts/generate_schemas.py --check` for the
  generator-managed subset and this canonical focused route for the
  hand-maintained resources:
  `uv run pytest tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py`.
  That route checks the `receipt-base.v1`, `blocker.v1`, and
  `package-identity.v1` resources with Draft 2020-12 through
  `SchemaRegistry.load` and exercises their candidate, receipt, and blocker
  contracts. The repository wrapper's full pytest run includes these tests but
  does not run a separate hand-maintained-schema command. Record `pass` only
  for exit `0` with all tests passing, `fail` for a non-zero schema or contract
  assertion, and `blocked` when the command cannot run or complete; include a
  concrete blocker reason and nearest fallback for `blocked`. Public contract
  changes need focused schema, behavior, and compatibility tests.
- Before a commit or pull request, run
  `bash scripts/validate-repository.sh`. The wrapper runs the generated-schema
  check, Ruff, the full pytest suite, `uv build`, and `git diff --check`.
- Report exact validation commands as `pass`, `fail`, or `blocked`, including
  the blocker when the exact production or provider path cannot run.
