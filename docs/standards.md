# Repository standards

`CODESTYLE.md` is the policy front door. This document describes the executable
SDK implementation of that policy.

## Validation entrypoints

Install `uv` and Vale from `.mise.toml` with
`MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise install python uv ruff vale`, then create
the project environment with
`MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen`.
The validation
wrappers apply the same checkout-scoped trust binding and invoke `uv` through
`mise`, so an ambient tool release or persistent global trust record cannot
silently change the proof path.

Run `bash scripts/validate-codestyle.sh` while editing. It checks Ruff formatting
and lint, semantic typing for the standards tooling, and the repository-wide
structural standards program. Run
`bash scripts/validate-repository.sh` before a commit or pull request; it adds
schema drift, the full test suite, package builds, and diff hygiene.

## Validation scope and phases

The default aggregate runs every phase and stops at the first failure. Each
phase prints its start, exit status and elapsed seconds. The hosted `validate`
job exposes quality, tests, build, installed-entrypoint proof and diff hygiene
as separate steps; its successful result still requires every applicable step.
The same wrapper accepts `quality`, `docs-tests`, `tests`, `build`, `installed` or `diff`
for those steps. Running one phase does not establish aggregate completion.

The test phase uses pinned pytest-xdist with two independent worker processes,
retains all collected tests, and prints the 25 slowest cases. Temporary fixture
paths and environment changes remain worker-local. Package builds and installed
smokes remain sequential after tests. Runtime source recapture, calibration,
drift, failure and recovery checks are not cached or removed for speed.

Matched-lane execution may reuse closed YAML parsing within its own operation.
The cache holds at most 32 entries and 2 MiB of accounted retained data; inputs
over 64 KiB bypass it. Exact current text identifies entries, callers receive
independent values, and malformed input is never cached. Source capture, digest
verification and safety decisions still run. Cache data is cleared on return,
failure or cancellation; child tasks and threads cannot use a parent's cache.

Both test routes write JUnit results under `.tmp/test-results/`. CircleCI uploads
these results to expose per-test timings and failures in its Tests tab. The XML
includes test file names for timing-based splitting. Test uploads do not enable
test selection, automatic retries or additional parallel containers.

The documentation-only route is
`bash scripts/validate-docs.sh --base <accepted-base> --head <current-head>`.
It runs schema drift, all codestyle/structural/link/prose checks, documentation-dependent
contract tests and diff hygiene
only after an exact-change classifier accepts ordinary prose. The allowlist is
`docs/` prose with Markdown, MDX, AsciiDoc or reStructuredText suffixes, plus
root `README.md`, `ARCHITECTURE.md`, `UBIQUITOUS.md`, `CHANGELOG.md` and
`SUPPORT.md`. Instructions, validation policy, templates, executable examples,
source, fixtures, configuration and dependencies are outside that exception.
Any nested `AGENTS.md` and this validation-policy document are excluded.
Symlink and executable-mode changes, empty comparisons, stale or unknown heads
and non-prose dirty paths cannot select documentation-only proof.
The base must be an ancestor of the locally fetched `origin/main`; refresh that
ref before selecting an accepted baseline. The current accepted ref must also
be an ancestor of the exact head. A historical caller-supplied base cannot hide
accepted changes missing from a stale branch; that case selects full validation.
An unmerged candidate cannot serve
as its own accepted base to hide earlier executable changes. Index and working
tree modes are checked separately. Classifier queries force file-mode detection
even when checkout configuration ignores it, without changing that configuration.
Tracked non-executable files are also checked for group- or other-execute bits
that Git's file-mode tracking does not report.
Optional Git index refreshes are disabled for those read-only queries.
Assume-unchanged, skip-worktree and other
non-ordinary index flags select full validation, even when tracked bytes appear
unchanged. The classifier does not clear these flags or modify the index.
Inherited Git directory, worktree, index and configuration selectors are removed
from classifier subprocesses. If accepted main advanced after a branch was
created, the non-ancestor comparison selects full validation instead of blocking
the otherwise valid PR.

Hosted PR scope comes from the trusted base classifier, never from an unreviewed
candidate classifier. A base without that classifier uses full validation.
CircleCI fetches GitHub's synthetic PR merge result and verifies its two parents
against the live base and head before checkout, so tests, builds and installed
proof include the base changes. Classification alone runs in a
temporary detached worktree at the exact PR head; it does not move or rewrite
the validation checkout. An advanced base requires full merge-tree proof, not
head-only tests. Invalid head identity blocks classification; corrected inputs
recover. The temporary head worktree is removed after successful classification.
The `docs-tests` phase runs `test_public_repository_boundary.py` and
`test_skill_validation_architecture.py`, retaining their repository-document,
portable-boundary and documented-command checks. Keep this bounded set aligned
with tests that read allowed prose. Those tests also run once within the full
suite; the full aggregate does not repeat the separate documentation phase.
All accepted-main push runs remain full. Documentation proof does not establish
full behavioural regression, build or installed-entrypoint proof, and must be reported
as documentation-only rather than as a full aggregate result.

The standards program scans all Python source and tests for public annotations,
module and function bounds, broad exception handling, global declarations,
dependency-direction violations, suppressions, and machine-specific paths. It
also parses repository TOML, JSON, and workflow YAML; checks exact tool pins,
immutable full-commit references for third-party actions and reusable
workflows, required ignored output, and local Markdown link targets; and fails
with typed, path-bound findings. Local actions and digest-bound container
actions retain their native reference forms.

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
baseline: there are no exclusions, inline suppressions, imported Foundry or
Agent-Skills rule packages, or active code dependencies on those repositories.
Intentional migration and historical provenance terms remain reader-facing SDK
documentation.

## Pull-request contract provenance

The initial comparison used Agent-Skills `origin/main` at
`b3478dc42363b0fb0f3551cc271dd845a6c636ff` as historical extraction evidence.
That revision is not an upstream dependency or continuing inheritance source.
The SDK owns the destination contract and its portable controls:

| Source control | SDK disposition | SDK mechanism |
| --- | --- | --- |
| `.github/PULL_REQUEST_TEMPLATE.md` | adapted for this repository | Preserve SDK contract, schema, provider, runtime, distribution, and compatibility boundaries; add exact readiness and guarded-refresh evidence fields. |
| PR-body contract validator and focused tests | portable and required | Validate exact section/field/checklist order, non-empty required values, replayable command outcomes, explicit pending checklist states, and stale-template rejection. |
| Create/update readiness receipts | already equivalent external control | Use the projected receipt gate bound to branch, head, base, scope digest, hosted checks, reviews, and threads; do not duplicate that state machine in SDK core. |
| Guarded PR-body refresh | already equivalent external control | Normally use the projected body-only helper after update readiness. When invalid metadata prevents that receipt, use its bounded `--repair --dry-run` preflight and apply only the verified body through the same helper. Raw broader PR editing is outside the SDK workflow. |
| Hosted template gate | adapted for this repository | The existing `validate` check loads the validator and template from the trusted base. The first validator PR has one explicit candidate bootstrap because its base cannot contain the new validator. |
| Agent-Skills release modes, Linear fields, Node/harness gates, and package commands | not migrated by this PR-control extraction | Move lifecycle behavior that belongs to the canonical workflow into SDK-owned contracts and entrypoints; retire repository-specific policy instead of importing it as a dependency. |

The aggregate repository gate executes the focused validator regressions through
the full pytest suite and statically requires the trusted-base hosted wiring.
Hosted body validation remains separate from local source proof and fails closed
when a body omits, reorders, duplicates, or leaves required template content
unclassified.

## Evidence boundary

These checks prove repository source consistency for the exact candidate. They
do not prove hosted checks or reviews, provider execution, registry state,
publication, installation, discovery, activation, runtime behavior, or rights.
