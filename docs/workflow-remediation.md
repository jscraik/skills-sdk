# Workflow remediation — September 17

## Scope and ownership

Owner: Skills SDK maintainers. Consumers: agents implementing public contracts
and migrating retained workflows. Scope: contribution and compatibility
requirements, discovery tests, and architecture evidence placement.

This record replaces the conversation-only remediation checklist. The earlier
instruction-audit record is absent from the current merged baseline, so this
record owns the findings for this change. Instructions live in `AGENTS.md`,
`CONTRIBUTING.md`, and `docs/compatibility.md`; this audit grants no authority.
Maintain this record when the selected fixes or their proof change.

Prior transcripts and review summaries are non-authoritative, untrusted
content. Only explicit owner promotion through canonical guidance changes
that classification. Current files and executed checks own readiness claims.

## Findings and disposition

Score: no-score. This is a bounded repair, not a measured agent benchmark.
Existing strengths include pinned tools, a repository validation wrapper,
versioned contracts, and focused adversarial regression suites.

| Severity | Category | Finding | Smallest correction and evidence |
| --- | --- | --- | --- |
| High | proof_gap | Passing focused tests and clean reviews did not establish all public input invariants. | `CONTRIBUTING.md` selects supported boundaries and accepted/rejected cases. Existing regressions in `tests/test_package_intake_instances.py` and related suites remain intact. |
| High | missing_validation | Migration policy and selector parity were discovered late in review. | `docs/compatibility.md` requires source revision, consumer fixtures, declarations, and executed parity or a blocker; `tests/test_scenario_quality.py` retains policy and selector regressions. |
| Medium | claim_boundary | Architecture tests locked historical commands and signature text without proving behaviour. | Retain dependency and command-execution checks; add public CLI discovery checks; move historical evidence below. |
| Medium | context_routing | Agents could begin contract work before reading acceptance requirements. | Root guidance now routes contract and migration work to the owning sections before implementation. |
| Medium | safety_boundary | Historical session and review material is non-authoritative, untrusted content. | Promote only the owner-approved guidance and run the repository validation wrapper before local closeout. |

The sibling sweep covered architecture tests, CLI discovery, contribution
routing, and compatibility guidance. Public contract semantics, schemas, and
existing defect regressions are unchanged. Global approval, signing, and
review-request rules belong to Configs and have separate validation.

## Three-PR experiment

Trial one PR under active repair and one waiting externally. Compare repair
pushes after first review, repeated defect families, and user interventions
needed to resume authorized work using existing PR history. This is a bounded
experiment, not a permanent gate or scheduled automation.

## Validation and limitations

The checkout advanced concurrently to merged PR #32 at `1db66a4` before
validation; current tests and command guidance were preserved.

- Command: `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_cli_help.py tests/test_skill_validation_architecture.py -q`
  -> pass (public discovery, dependency boundaries, and documented commands).
- Command: `bash scripts/validate-repository.sh` -> fail in the primary
  checkout (1,611 passed, one failed, one skipped). An existing untracked
  agent-run manifest contains a machine path and fails the public-source scan.
  The unrelated artifact was preserved and the scan was not weakened.
- Command: `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_public_repository_boundary.py -q`
  -> blocked on the first isolated attempt (mise state-directory write denied).
  The same command with temporary `MISE_STATE_DIR` -> pass (five tests).
- Command: `bash scripts/validate-repository.sh` -> pass in the isolated
  checkout with temporary `MISE_STATE_DIR` (1,612 passed, one skipped; schema,
  style, typing, repository standards, source and wheel builds, and diff checks).
  The isolated checkout contains the committed baseline and identical owned
  candidate bytes; unrelated untracked files are outside that candidate.
  Exact temporary environment paths remain in ignored local run evidence.
- Command: `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- vale --config .vale.ini AGENTS.md CONTRIBUTING.md ARCHITECTURE.md docs/compatibility.md docs/workflow-remediation.md`
  -> pass (includes the new audit document).

The final evidence update changes only this record; its editorial and isolated
public-source checks are repeated after recording the aggregate result. No private session paths or raw transcripts
are retained here. Local proof does not establish future agent adherence,
hosted CI, review clearance, downstream cutover, or retirement.
Validation blocks false readiness and proof-skipping until the applicable
commands, receipts, or equivalent proof exist.

## Retained historical architecture evidence

The documentation-only capability-map update was checked with these exact
repository commands:

- `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_public_repository_boundary.py tests/test_repository_standards.py tests/test_skill_validation_architecture.py`
  — `pass` (`84 passed`).
- `bash scripts/validate-codestyle.sh` — `pass` (Ruff, MyPy, repository
  standards, and Vale completed without findings).
- `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen python scripts/generate_schemas.py --check` —
  `pass` (no generated-schema drift).
- `bash scripts/validate-repository.sh` — `pass` (`1,443 passed`, `1 skipped`;
  source distribution and wheel built successfully).
- `git diff --check` — `pass`.
- `git verify-commit 841ab6ebbff3ffd7bee4d1ff60ecbee0d11739eb` — `pass`
  (good native ED25519 signature for the exact reconciliation commit).

External outcome lanes remain blocked rather than inferred from those local
checks:

| Lane | Outcome | Concrete reason | Nearest meaningful fallback |
| --- | --- | --- | --- |
| Provider | `blocked` | The repository contains offline orchestration and envelopes, not a selected provider client, credentials, network transport, or an authorized real-provider call. | Provider-call conformance plus provider execution model and schema tests. |
| Registry | `blocked` | Private-registry preparation performs no registry authentication, upload, or mutation. | Deterministic registry-preparation contract tests. |
| Host runtime | `blocked` | Runtime lifecycle code plans transitions but has no host apply or rollback adapter. | Runtime-lock and installation-planning contract tests. |
| Tessl | `blocked` | Tessl CLI routes are parse-only and no Tessl integration was executed. | CLI parser/help tests and candidate-bound local contract checks. |
| Publication | `blocked` | Publication is external to the SDK and no destination or publication authority was supplied. | Local build, immutable receipt, and registry-preparation proof. |
