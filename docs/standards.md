# Repository standards

`CODESTYLE.md` is the policy front door. This document describes the executable
SDK implementation of that policy.

## Validation entrypoints

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

Vale is pinned by `.mise.toml` and runs from `scripts/validate-codestyle.sh`.
The destination-owned `SkillsSDK` package rejects absolute, evidence-free
readiness and security claims while allowing truthful negated or scoped claims,
and enforces the project name in reader-facing prose. The rules
lint Markdown, MDX, AsciiDoc, and reStructuredText while leaving code spans and
blocks to their language-specific tools. The current repository is the clean
baseline: there are no exclusions, inline suppressions, or imported Foundry and
Agent-Skills vocabularies.

## Evidence boundary

These checks prove repository source consistency for the exact candidate. They
do not prove hosted checks or reviews, provider execution, registry state,
publication, installation, discovery, activation, runtime behavior, or rights.
