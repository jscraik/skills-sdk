# Skills SDK

Skills SDK is the public, portable implementation of the professional lifecycle
for Agent Skills packages: source shape, package identity, authoring contracts,
security guardrails, behavioral evaluation, scorer quality, immutable receipts,
provider handoff, and runtime verification boundaries.

> Thin Surfaces. Strong Guardrails. Progressive Disclosure. Durable Memory. Professional Output.

## Current status

This seed establishes only the public repository, packaging, review, and
validation boundary. The CLI exposes help and version information. Package
verification, evaluation, provider execution, handoff, runtime installation,
and distribution are not implemented by this seed.

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
