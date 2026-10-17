# Agentic review pilot and product rollout

Status: proposed implementation plan. This document authorizes no external
installation, PR messaging, paid execution, publication, or merge.

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
and remaining advisory docstring warning. Configs repairs are signed and pushed
in [Configs PR 366](https://github.com/jscraik/configs/pull/366); that PR's hosted
validation and review remain separate from SDK PR 63 clearance.
PR 63 merged at 22:49 UTC on 16 October 2026 as
[`e480d429`](https://github.com/jscraik/skills-sdk/commit/e480d429adaf400f3ae0ab78c4a4bacb0fbeae60)
after fresh readiness and exact-head local review. The reports are published in
[SDK PR 64](https://github.com/jscraik/skills-sdk/pull/64); the Configs repair and
report PRs remain separate open deliveries with their own CI and review gates.

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
