# Repository standards

`CODESTYLE.md` is the policy front door. This document describes the executable
SDK implementation of that policy.

## Validation entrypoints

Install `uv` and Vale from `.mise.toml` with
`MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise install python uv ruff vale`, then create
the project environment with `mise exec -- uv sync --frozen`. The validation
wrappers apply the same checkout-scoped trust binding and invoke `uv` through
`mise`, so an ambient tool release or persistent global trust record cannot
silently change the proof path.

Run `bash scripts/validate-codestyle.sh` while editing. It checks Ruff formatting
and lint, semantic typing for the standards tooling, and the repository-wide
structural standards program. Run
`bash scripts/validate-repository.sh` before a commit or pull request; it adds
schema drift, the full test suite, package builds, and diff hygiene.

The standards program scans all Python source and tests for public annotations,
module and function bounds, broad exception handling, global declarations,
dependency-direction violations, suppressions, and machine-specific paths. It
also parses repository TOML, JSON, and workflow YAML; checks exact tool pins,
required ignored output, and local Markdown link targets; and fails with typed,
path-bound findings.

The narrower semantic MyPy lane is intentional: versioned frozen Pydantic
models retain their public v2-subclasses-v1 compatibility, while the structural
gate prevents untyped public interfaces and suppression comments across the
whole repository.

Generated schemas under `src/skills_sdk/schemas/` remain committed projections.
Change their Pydantic source and run the generator; do not edit projections by
hand. Caches, virtual environments, builds, local receipts, and machine state
are not source artifacts.

## Portable inheritance boundary

The adapted rules cover Python 3.12, Pydantic contracts, deterministic core
logic, explicit errors, portable paths, documentation and configuration drift,
signed Conventional Commits, and exact SDK tool pins. They do not import
Agent-Skills scripts, infrastructure, Codex configuration, skill graphs, local
memory, runtime installation, Tessl workflows, or non-Python toolchains.

Vale is pinned by `.mise.toml` and runs from `scripts/validate-codestyle.sh`
against the repository's tracked prose files only.
The destination-owned `SkillsSDK` package rejects absolute, evidence-free
readiness and security claims while allowing truthful negated or scoped claims,
and enforces the project name in reader-facing prose. The rules
lint Markdown, MDX, AsciiDoc, and reStructuredText while leaving code spans and
blocks to their language-specific tools. The current repository is the clean
baseline: there are no exclusions, inline suppressions, or imported Foundry and
Agent-Skills vocabularies.

## Pull-request contract inheritance

Agent-Skills `origin/main` at
`b3478dc42363b0fb0f3551cc271dd845a6c636ff` supplies the comparison evidence.
The SDK owns the destination contract and applies only portable controls:

| Source control | SDK disposition | SDK mechanism |
| --- | --- | --- |
| `.github/PULL_REQUEST_TEMPLATE.md` | adapted for this repository | Preserve SDK contract, schema, provider, runtime, distribution, and compatibility boundaries; add exact readiness and guarded-refresh evidence fields. |
| PR-body contract validator and focused tests | portable and required | Validate exact section/field/checklist order, non-empty required values, replayable command outcomes, explicit pending checklist states, and stale-template rejection. |
| Create/update readiness receipts | already equivalent external control | Use the projected receipt gate bound to branch, head, base, scope digest, hosted checks, reviews, and threads; do not duplicate that state machine in SDK core. |
| Guarded PR-body refresh | already equivalent external control | Use the projected body-only helper after update readiness; raw broader PR editing is outside the SDK workflow. |
| Hosted template gate | adapted for this repository | The existing `validate` check loads the validator and template from the trusted base. The first validator PR has one explicit candidate bootstrap because its base cannot contain the new validator. |
| Agent-Skills release modes, Linear fields, Node/harness gates, and package commands | inapplicable | These are Agent-Skills repository policy or non-Python toolchains and are not portable SDK contract requirements. |

The aggregate repository gate executes the focused validator regressions through
the full pytest suite and statically requires the trusted-base hosted wiring.
Hosted body validation remains separate from local source proof and fails closed
when a body omits, reorders, duplicates, or leaves required template content
unclassified.

## Evidence boundary

These checks prove repository source consistency for the exact candidate. They
do not prove hosted checks or reviews, provider execution, registry state,
publication, installation, discovery, activation, runtime behavior, or rights.
