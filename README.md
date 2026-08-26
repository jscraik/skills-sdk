# Skills SDK

Skills SDK is the public, portable implementation of the professional lifecycle
for Agent Skills packages: source shape, package identity, authoring contracts,
security guardrails, behavioral evaluation, scorer quality, immutable receipts,
provider handoff, and runtime verification boundaries.

> Thin Surfaces. Strong Guardrails. Progressive Disclosure. Durable Memory. Professional Output.

## Current status

The `0.1.0` release establishes the public repository boundary and the first
portable contracts for inventory, intake, package identity, packaging,
evaluation, risk, security, and candidate-bound receipts. The CLI currently
exposes a deliberately small boundary-only command surface: it parses help,
version, and lifecycle route names without running provider, runtime, or
distribution side effects. Provider execution, handoff, runtime installation,
and publication remain separate implementation and evidence lanes.

## Ownership boundaries

- Skills Foundry owns retained canonical package source and provenance.
- Skills SDK owns portable lifecycle contracts and their implementation.
- Host repositories own their adapters and package-path resolution.
- Runtime installations prove installed behavior separately.
- Tessl and other registries provide distribution and external evidence; they
  are not editable source owners.

## Development

```bash
uv sync --frozen
bash scripts/validate-repository.sh
uv run skills-sdk --help
```

The cold-agent entrypoint and progressive-disclosure contract are documented in
[`docs/agent-entrypoint.md`](docs/agent-entrypoint.md).

## Public documentation

- [`docs/api.md`](docs/api.md) — public Python contract families and schema
  validation.
- [`docs/cli.md`](docs/cli.md) — the boundary-only command surface and its
  current guarantees.
- [`docs/compatibility.md`](docs/compatibility.md) — Python, schema, and
  compatibility policy.
- [`SUPPORT.md`](SUPPORT.md) — support requests and safe reproduction details.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.

The small [`examples/inventory_contract.py`](examples/inventory_contract.py)
example demonstrates a portable candidate identity without requiring a
provider, runtime installation, credential, or generated receipt.
