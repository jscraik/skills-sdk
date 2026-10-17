# Agentic review pilot and product rollout

Status: P0 baseline, P1 SDK repair and report delivery completed. The docstring
follow-up is merged. P2's seven supplied-history cases are implemented,
validated and independently checked locally; delivery remains pending.
Later product implementation phases are proposed.
This document authorizes no external installation, PR messaging, paid execution,
publication, or merge.

P0 baseline completed on 16 October 2026: [integration inventory and selected
PR 63](agentic-review-p0-baseline.md). [P1 results](agentic-review-p1-results.md)
record isolated reproduction, local repairs, independent shadow review and
passing full repository validation. Signed repairs are pushed, both original
review threads are provider-resolved, and PR metadata is repaired. Hosted CI
passed all 3,777 tests and installed-wheel proof. Current-head CodeRabbit and
Codex clearance passed the installed update gate at 22:35 UTC on 16 October
2026 after authorized parser and request-helper repairs, genuine reinspection,
and verification of the last metadata correction. The high-risk two-bot quorum
passed with zero unresolved threads. The P1 report records the complete evidence
and the historical advisory docstring warning. Configs validation and review
remain separate from SDK PR 63 clearance.
PR 63 merged at 22:49 UTC on 16 October 2026 as
[`e480d429`](https://github.com/jscraik/skills-sdk/commit/e480d429adaf400f3ae0ab78c4a4bacb0fbeae60)
after fresh readiness and exact-head local review. The reports are published in
[SDK PR 64](https://github.com/jscraik/skills-sdk/pull/64), merged on 17 October
at 02:46 UTC as `8733065a`. The subsequent
[SDK PR 65](https://github.com/jscraik/skills-sdk/pull/65) retained three useful
helper docstrings and deliberately omitted six redundant test descriptions.
It merged at 10:58 UTC as `0d4a39d8`, after both required reviewers and the final
current-head update receipt passed. All five hosted checks passed. Its completed
local full suite recorded 3,915 passed and one skipped. The accepted file tree
matches the tested candidate. The primary checkout was then fast-forwarded to
clean main; the old source and merged delivery branches were removed after
their work was accounted for. This is the P2 starting revision.

Live readback on 17 October also shows
[Configs PR 366](https://github.com/jscraik/configs/pull/366) merged at 03:09 UTC
as `ed9110f9`, while [Configs PR 367](https://github.com/jscraik/configs/pull/367)
remains open at `3b4d6875` with passing reported checks. These are distinct
deliveries. No merge or current-head review clearance is inferred for PR 367,
and its later corrections are not assumed present in the accepted PR 366 tree.
That cross-repository follow-up does not reopen the completed SDK repair.

Start with reviewing changes to Skills SDK itself. Prove the review loop before
adding package assessment features or new product interfaces. Reuse existing
standards, checks, reviewer integrations, and readiness gates.

## Outcome and boundary

The pilot should produce actionable, evidence-backed findings for the exact SDK
PR revision, preserve the author's responses, and turn one confirmed recurring
problem into a tested improvement. It must distinguish a completed review with
no findings from an unavailable, failed, skipped, or incomplete review.

Two workflows remain separate:

- Product code review binds evidence to repository, base SHA, head SHA, changed
  scope, and review-policy revision.
- Package assessment binds evidence to `PackageCandidateIdentity`, including
  source revision and content digest. A PR approval cannot substitute for that
  package's validation, evaluation, rights, publication, or runtime evidence.

Planning decision: `DOCS_ONLY` now. Implementation should improve existing
surfaces, with no new skill, autonomous maintenance service, or parallel
readiness gate. The copied assumption rejected is that a plausible model verdict
or a validated receipt establishes that an independent review actually ran.

## What already exists

This inventory is based on inspected local source and documentation. It is not
a fresh execution of the tests, hosted CI, reviewer integrations, or product UI.

| Capability | Existing evidence | Reuse and remaining work |
| --- | --- | --- |
| SDK standards and ownership | [Agent guidance](../../AGENTS.md), [codestyle](../../CODESTYLE.md), [architecture](../../ARCHITECTURE.md) | Reuse these as the standard; add narrow review instructions only where a real gap exists. |
| Mechanical validation and CI | [Validation wrapper](../../scripts/validate-repository.sh), [CI](../../.github/workflows/validate.yml) | Reuse schema, quality, full tests, build, installed API/CLI proof, and diff checks. Their existence does not establish the current hosted result. |
| PR description contract | [Template](../../.github/PULL_REQUEST_TEMPLATE.md), [validator](../../.github/scripts/validate_pr_template_body.py) | Reuse intent and behavior-proof fields. Review findings need evidence beyond a completed description. |
| Supplied package content review | [Assessment implementation](../../src/skills_sdk/validation/content_review.py), [tests](../../tests/test_content_review.py) | Validates candidate/file binding and coverage. It does not execute or authenticate a reviewer. Do not treat this as a PR-review adapter. |
| Offline package reviewer execution | [Execution implementation](../../src/skills_sdk/evaluation/content_review.py), [regression tests](../../tests/test_content_review_execution.py) | Existing trusted callback execution, deadline and drift handling are useful patterns. They are not a live review transport or security sandbox. |
| Recurring-finding verification | [CLI contract](../cli.md#pr-sweep-verification), [schema](../../src/skills_sdk/schemas/pr-sweep-recurring-findings.v1.schema.json), [tests](../../tests/test_pr_sweep_validation.py) | Reuse normalized invariant fingerprints and the three-occurrence guardrail rule. The command validates supplied records; it does not collect PRs or maintain memory automatically. |
| Local operator readiness controls | Existing workstation current-head receipts, independent review, CI and thread gates | Verify their current invocation contract before integration. Preserve their authority; a new review report cannot replace them. These controls are not portable SDK-core behavior. |
| SkillsBar evidence display | Sibling repository README and `PipelineEvidenceLoaderTests.swift` describe candidate-bound, separate evidence lanes | Extend the existing loader/view after a stable SDK consumer contract exists. Current input still uses legacy agent-skills paths; direct released-SDK consumption needs its own migration proof. |
| Foundry candidate custody | Sibling repository README describes source identity, provenance, rights observations, and blocked-source retention | Preserve temporary filesystem storage. Do not add reviewer orchestration or approval rules to Foundry. |
| Registry | Sibling repository README labels the current foundation/prototype and its fictional data | No operational review service, publication, or installation is established. Do not expand it before SDK acceptance and verified private Tessl publication satisfy the existing start gate. |

## SDK pilot work packages

Owner labels below identify responsibility, not assigned people. Each work
package should be one independently reviewable change where practical.

### P0: Establish the baseline and trusted inputs

Owner: SDK maintainer with the workstation review-integration owner.

- Inspect the active review integrations and their current-head output formats;
  choose one already authorized reviewer path before proposing another service.
- Select one upcoming bounded SDK change, plus five historical SDK PRs for
  read-only comparison. Record the exact reviewed revisions and known findings.
- Put the pilot policy in existing workflow guidance: scope, trusted policy
  revision, lens selection, response rules, and run limits.
- Keep raw PR exports and generated receipts outside the public repository.
  Commit only sanitized fixtures, reusable guidance, and implementation.

Exit: a reproducible baseline packet identifies the source revisions, existing
checks, reviewer availability, reference findings, and unknowns. No claim that
current hosted protections or external services work until read back directly.

### P1: Run focused review in shadow mode

Owner: SDK review-integration maintainer. Depends on P0.

Completed for PR 63 at head `7f1c4b1489b7545c2d162fbf1144533c19486d49`:
both required hosted reviewers qualified and the current-head update gate passed.
The [P1 report](agentic-review-p1-results.md) retains failures, repairs and limits.

Use three narrow perspectives initially:

| Perspective | Main question | SDK-specific examples |
| --- | --- | --- |
| Contract correctness | Does the change preserve promised behavior and identity? | Schema compatibility, wrong candidate digest, incomplete plugin coverage. |
| Security and evidence integrity | Can untrusted input or stale evidence cross a boundary? | Unsafe paths, forged review provenance, stale-head clearance, worker side effects. |
| Architecture and operational failure | Does ownership remain clear, and do failures stay bounded? | Registry code leaking into core, callback deadlines, cancellation, missing-provider behavior. |

Use existing review orchestration where supported. Parallelism is optional;
separate perspectives need not mean new agents or a new service. The author
cannot provide the pilot's independent approval. Code and comments under review
are untrusted input. Review-policy and lens changes require separate scrutiny;
the candidate cannot silently lower the standard used to approve itself.

Start with one run per selected head and one rerun after a repair batch. Stop
after two repair rounds and record unresolved findings for a human decision.
Record elapsed time and actual provider usage where available; set an explicit
spend ceiling before selecting any paid adapter.

Exit: one actual current-head review with evidence and declared scope, or an
honest blocker. Existing review and merge requirements remain unchanged.

### P2: Reconcile findings and revisions

Owner: review-integration maintainer. Depends on P1.

First adapt the existing reviewer output and readiness evidence. Add a new
public SDK contract only if a second named consumer demonstrates that the
current contract cannot represent what it needs. Follow contract acceptance
and compatibility procedures before doing so.

The pilot packet must retain:

- Repository, base/head revisions, reviewed scope, trusted policy revision,
  actual reviewer identity, run outcome, and evidence references.
- Finding identity, lens, location, consequence, confidence, evidence, and
  proposed blocking classification. Severity and confidence are separate.
- Author response: fix, refute, or decline, with reason and supporting evidence.
- Recheck result: still present, verified fixed, refuted, accepted exception,
  reopened, or unverified. A fixed claim needs a checked revision.

Use invariant and location context to reconcile findings across line movement.
Unchanged findings should not create duplicate comments. A new head invalidates
the old current-head clearance; differential review must explicitly establish
coverage of the changed scope. A missing reviewer, timeout, quota failure,
publication failure, or uncovered scope cannot become a clean review.

Exit: fixtures prove unchanged finding deduplication, line movement, verified
repair, recurrence, changed-head invalidation, and failed-review handling.
Human authorization is required to accept an unresolved blocking exception;
an agent's decline alone does not clear it.

#### P2 first slice from accepted main

Consumer: the SDK maintainer reconciling a review and its next revision. Start
from accepted `0d4a39d8`. Adapt the existing review packet and tests before
considering another service or public model. The implementation checkpoint
below adds the missing offline replay proof; PR 63's real repair loop alone
did not establish these transitions.

| Reuse now | Gap to prove in P2 |
| --- | --- |
| PR 63's two confirmed findings, original head, repair head and provider-resolved threads | A sanitized fixture preserves each finding's invariant, source identity, author response and independently checked disposition across revisions. |
| Existing recurring-findings schema and validator | They validate supplied class fingerprints and occurrence records; they do not track line movement or reconcile a finding lifecycle. Keep class identity separate from occurrence identity. |
| Existing workstation head, reviewer, check and thread gate | Keep it authoritative for merge readiness. Replay stale-head and failed-review cases without a second SDK merge gate. |
| PR 65's metadata repair, later summary, reinspection and qualified verdict sequence | Preserve evidence event order. A later concern reopens assessment even on an unchanged source head; an earlier clean verdict cannot erase it. |

Implement the smallest fixture-driven reconciliation slice in this order:

1. Extract sanitized records from PR 63 and PR 65. Retain public evidence links,
   full base/head identities, policy revision and reviewer identity; exclude
   raw transcripts, generated receipts and machine-specific paths.
2. Define expected transitions in the existing pilot record: open to verified
   fixed, refuted with evidence, declined but still blocking, and reopened.
   Keep provider outcome separate from finding disposition. Unknown evidence
   stays unverified.
3. Prove six acceptance cases: unchanged finding produces one identity; line
   movement preserves identity; repair closes only on the checked revision;
   recurrence creates a new linked occurrence; changed head invalidates old
   clearance; failed or unavailable review cannot produce a clean result.
   Add the observed later-concern case as a seventh ordering regression.
4. Put executable fixture behavior in the existing review-integration owner.
   Keep portable recurring-ledger checks in the SDK's existing validator.
   Establish the ownership seam before implementation; do not copy the
   workstation parser or GitHub transport into SDK core.
5. Run focused acceptance cases, the applicable repository validation route,
   and independent review of identity and event-order boundaries. A second
   named consumer is required before proposing a new public SDK contract.

P2 exit is a repeatable reconciliation result with those cases passing and
each disposition tied to its evidence. It does not authorize bot messaging,
exception acceptance, merging, package publication or runtime installation.
PR 63 already provides a useful P3 real-loop example, but it does not replace
repeatable P2 lifecycle regressions or the later P5 usefulness trial.

#### P2 local implementation checkpoint, 17 October 2026

The smallest executable change belongs in Configs, alongside the existing
review disposition loader, rather than in SDK core. The isolated implementation
branch is `codex/jsc-517-p2-finding-reconciliation`, based on accepted Configs
`ed9110f9aa94967357f7b111e922ecbd8ddadc33`. The primary Configs checkout and
its live projected scripts were left untouched. This SDK report branch remains
`codex/update-review-pilot-closeout`, based on `0d4a39d8`.

The review-integration maintainer owns the new internal
`codex/scripts/pr_finding_history.py` helper. Its consumer is the maintainer
comparing supplied review packets across revisions. It replaces manual history
comparison for this pilot; existing source-disposition loading did not model
line movement or recurrence. The seven sanitized reconstructions and their
limits are in `codex/scripts/tests/fixtures/p2-reconciliation.json` and its
companion documentation. The maintained Configs policy test lane includes
`codex/scripts/tests/test_pr_finding_history.py` and a wiring assertion.
No dependency or public SDK contract was added.

| Case | Local acceptance result |
| --- | --- |
| Unchanged finding | One stable identity and occurrence; repeated observations retained. |
| Line movement | Same identity despite a new line and provider alias. |
| Verified repair | A matching author response and independent checked revision close the occurrence. |
| Recurrence | New linked occurrence; original response and repair evidence remain available. |
| Changed head | Current disposition becomes unverified without rewriting historical repair proof. |
| Failed review | Failed, unavailable and incomplete runs cannot produce a clean diagnostic. |
| Later concern | A later finding blocks after an earlier completed empty inventory. |

The key binds repository, PR, normalized invariant and semantic anchor, not line
number or provider prose. Anchors preserve case for case-sensitive symbols.
This is explicit-anchor reconciliation within one PR, not fuzzy
matching. The packet retains full base/head/policy revisions, reviewed scope,
source identity, severity, confidence, consequence, responses and checked
dispositions. Conflicting aliases, ambiguous event order, wrong repository/PR,
unsafe paths and malformed evidence fail validation. Stale, self-reviewed and
uncovered repair claims remain unverified. No unresolved-exception acceptance
route exists.

Independent review found one response-lifetime defect: a later author decline
or refutation could inherit an earlier verified fix. All three superseding
response variants reproduced it before repair. The correction invalidates the
active closure, preserves the previous response and verification history, and
requires a fresh matching independent recheck. A neighboring identity probe
also reproduced accidental merging of `Parser` and `parser` anchors; retaining
anchor case corrected it without changing invariant normalization.
The complete 17-test focused
suite then passed, including all seven cases through the real read-only CLI.
Independent re-review and independent execution returned no findings.

The bounded sibling search covered the existing disposition loader and repair
endorsement module. They validate immutable supplied records or source-bound
endorsements and do not replace an active response during history replay;
neither required this correction. No live readiness or reviewer parser changed.

The fixtures are labeled sanitized reconstructions. Public PR 63/65 references
are retained; actor labels, event times and counterfactual variants are not
claims of additional observed defects. There are no raw provider transcripts,
credentials, runtime receipts or private source in the fixture packet.
Synthetic recurrences do not count toward P4's three-occurrence learning rule.

Output always identifies supplied offline evidence and states
`readiness_claimed: false`. Exit zero means the packet was processed, including
blocked and unverified results. The helper does not authenticate providers,
fetch evidence, write receipts, mutate threads or grant merge authority. The
existing live gate remains mandatory. The Configs baseline and final focused
local proof passed, including the maintained test wiring.
The implementation is committed locally; publication and hosted clearance are
pending. No hosted result is claimed.

Validation commands below ran in their named checkout with
`MISE_CEILING_PATHS="$PWD/.."` and
`MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml"` for mise invocations. Foreign
repository argv is retained as evidence, not as an SDK command recipe.

- Historical Configs argv: `["mise", "exec", "uv@0.11.3", "--", "uv", "run", "--offline", "--no-config", "--no-project", "--python", "3.12", "--with", "pyyaml==6.0.3", "--with", "pydantic==2.13.4", "--with", "markdown-it-py==4.2.0", "python", "-m", "unittest", "codex/scripts/tests/test_pr_finding_history.py"]`
  -> pass, final 17 tests, including all seven CLI cases and the two repaired
  mechanisms. Independent execution passed the same final suite.
- Historical Configs argv: `["mise", "exec", "node@24.13.1", "pnpm@10.33.2", "--", "pnpm", "check"]`
  -> pass, exit zero: lint, typecheck, source tests, 37 duplication regressions,
  duplication baseline, 667 maintained policy tests in 871.315 seconds, and
  maintained test wiring passed. The aggregate ran while the narrow review
  corrections were completed; the final 17-test suite was also run separately
  after both corrections, by the implementer and the independent reviewer.
- Historical Configs argv: `["mise", "exec", "ruff@0.15.11", "--", "ruff", "check", "codex/scripts/pr_finding_history.py", "codex/scripts/tests/test_pr_finding_history.py"]`
  -> pass on the final candidate. Pyright is not installed in this checkout;
  no Python static-typecheck result is claimed.
- Historical Configs argv: `["mise", "exec", "node@24.13.1", "pnpm@10.33.2", "--", "pnpm", "exec", "markdownlint-cli2", "codex/scripts/tests/fixtures/p2-reconciliation.md"]`
  -> pass, zero errors.
- Historical Configs argv: `["mise", "exec", "vale@3.14.1", "--", "vale", "--config", ".vale.ini", "codex/scripts/tests/fixtures/p2-reconciliation.md"]`
  -> pass, zero errors and warnings.
- Historical Configs argv: `["bash", "scripts/validate-codestyle.sh"]` and
  `["bash", "codex/scripts/verify-work.sh", "--fast"]`
  -> blocked by the automatic execution hook's protected indirect-shell rule.
  The direct documented package baseline and pinned unittest route supply the
  meaningful fallback; neither rejected wrapper is reported as passing.
- Command: `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_pr_sweep_validation.py tests/test_public_repository_boundary.py tests/test_skill_validation_architecture.py --durations=10`
  -> pass in the SDK checkout, 49 tests in 16.02 seconds. This verifies the
  unchanged recurring-ledger seam and documentation-dependent contracts.
- Command: `git diff --check` -> pass in both checkouts.

SDK generated schemas, Ruff format/lint, MyPy, repository standards and report
Vale also passed directly. These checks do not stand in for the full SDK
behavioral suite, new hosted CI, provider authentication or merge readiness.

At closeout, unrelated SDK agent-instruction and integration-installation files
appeared in the primary checkout. They were preserved and excluded from this
task's owned report scope. The current combined checkout classifies as full,
so the earlier docs-only classification is not current whole-checkout proof.
The two report files are validated separately against an isolated snapshot of
accepted `0d4a39d8`; no acceptance of those unrelated installation changes is
inferred from the P2 result.

### P3: Complete one real PR loop

Owner: SDK maintainer and independent reviewer. Depends on P2.

Run the selected SDK PR through existing validation, actual review, author
response, repair, and current-head re-review. Confirm hosted check results and
review-thread state through the existing readiness process. A pilot completion
can stop at a reviewable PR; merging requires its own explicit authority.

Acceptance cases must include a real repaired finding, or a historical
reproduction if the selected change has no findings. Use isolated fixtures for
negative tests rather than introduce known defects into a live PR.

Exit: original failure, repair, fresh proof, independent coverage, current-head
status, and any unresolved gaps are recorded separately. No SDK package
publication or runtime-installation claim follows from this result.

### P4: Improve one recurring problem at its source

Owner: SDK maintainer. Depends on P3 and sufficient confirmed recurrence.

Apply the existing three-occurrence rule instead of creating a competing
learning threshold. Group by root cause rather than wording. Choose one of:

- A deterministic regression test when the invariant is mechanically checkable.
- A small change to existing instructions when agents lack relevant context.
- A sharper review criterion when reasoning remains necessary.

Record the evidence, owning surface, validation, and replaced guidance. Run a
bounded sibling search. Verify a positive case and a valid neighboring case so
the check does not reject acceptable behavior. A single severe defect still
deserves repair and an appropriate regression test; it does not automatically
justify a broad policy change. No automatic updates to global memory or rules.

Exit: one independently reviewed improvement passes its actual check and the
existing recurring-findings validator. If recurrence is insufficient, record
that boundary and defer this phase rather than manufacture occurrences.

### P5: Decide whether to expand

Owner: Jamie, using the pilot evidence. Depends on P3; P4 may remain deferred.

Evaluate five historical comparisons and three prospective PRs. This is a
bounded usefulness trial, not a statistical claim of general review accuracy.
Record confirmed findings, false positives, missed reference findings, duplicate
comments, author response effort, review latency, and actual or unknown cost.

Required technical outcomes:

- Every completed run identifies its exact head and review scope.
- No stale, failed, skipped, or incomplete run is accepted as current clearance.
- Every blocking finding has a response and independently checked disposition.
- All lifecycle fixtures from P2 pass, including a previously fixed recurrence.
- No unapproved external writes, policy weakening, or private-source leakage.

Continue only if the reviews add useful findings or materially reduce review
effort. Tune the existing lens or adapter before adding another reviewer.
Persistent disagreement or excessive noise is a reason to retain shadow mode.

## Product rollout after pilot acceptance

| Order | Owner/product | Work to integrate or build | Acceptance |
| --- | --- | --- | --- |
| 1 | SDK package assessment | Reuse candidate binding, supplied assessment and bounded execution; implement the selected trusted live adapter only after its authority and provenance contract are defined. Add package-specific host/behavior and permission lenses where existing review cannot cover them. | Installed public API/CLI consumer proves wrong-digest, missing-coverage, failed-provider and neighboring valid cases. Actual invocation proof remains separate from content review. |
| 2 | SkillsBar | Consume a pinned SDK public result; extend existing evidence loading and views with reviewed revision, required/advisory findings, scope gaps, freshness, and next action. Avoid automatic paid review on menu open. | Tests and native Mac interaction show current, stale, failed, and unavailable states; accessibility and evidence links work; local proof never appears as hosted clearance. |
| 3 | Foundry | Add only the minimum SDK intake/handoff reference needed for existing custody records. No new gate or service. | The same held bytes reach SDK processing; blocked candidates and reasons remain accessible; storage is never labelled admitted. |
| 4 | Registry, deferred | After the existing start/transition gates, workers consume an installed pinned SDK package; service owns isolation, scheduling, storage, authorization, and public/private presentation. | Exact version and evidence binding survive publication/readback; tenant isolation and private-material exclusion pass; no source-checkout dependency or duplicated SDK rules. |
| 5 | Personal website | Publish one sanitized case study after its underlying evidence is verified and public sharing is approved. | Claims distinguish tests, review, runtime, and publication; no private source or provider logs are exposed. |

The first useful cross-product handoff is SDK to SkillsBar. Registry expansion
is not a prerequisite for the pilot, and this plan does not waive its start gate.

## Validation and delivery plan

P0 is read-only discovery. P1/P2 changes use focused contract and lifecycle
regressions first. Existing supplied content-review tests prove only their
package-assessment lane; they are not PR-review execution tests.

For SDK implementation, use the pinned Python 3.12/uv environment and the
repository command contracts. Public model/schema changes require generated
schema checks, focused contract tests, behavior and compatibility proof. Before
a commit or PR, run `bash scripts/validate-repository.sh`. For ordinary prose,
use `bash scripts/validate-docs.sh --base <accepted-base> --head <current-head>`
only when its classifier accepts the exact change.

External setup, review publication, pushes, merges, paid runs, installation and
schedules retain their separate authorization and effective approval boundaries.
This plan changes no runtime, reviewer, branch-protection or product settings.

The initial draft reported source/document inventory, relative-link and diff
checks without preserving their exact commands. Those historical observations
are not reproducible command-level proof. The following current checks verify
the report's repository context and links:

- Command: `git ls-files -- docs/projects/agentic-review-pilot.md docs/projects/agentic-review-p0-baseline.md docs/projects/agentic-review-p1-results.md docs/projects/sdk-workflow/tasks.md`
  -> pass; all four report and task-ledger paths are tracked.
- Command: `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen python scripts/check_repository_standards.py`
  -> pass; includes repository documentation-link checks.
- Command: `git diff --check` -> pass; checks diff hygiene.

These checks do not prove implementation behavior, hosted review, or
cross-product integration. Later P0/P1 evidence is recorded in the linked reports.
