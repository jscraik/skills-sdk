# Agentic review pilot and product rollout

Status: P0 baseline, P1 SDK repair and report delivery completed. SDK PR 65's
docstring follow-up is merged. P2's seven supplied-history cases are implemented,
validated and independently checked locally. The implementation and reports
merged. The separate docstring follow-up also merged before its final readiness
receipt; the request-helper follow-up remains open and is recorded separately.
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

Earlier live readback on 17 October recorded
[Configs PR 366](https://github.com/jscraik/configs/pull/366) merged at 03:09 UTC
as `ed9110f9`, while [Configs PR 367](https://github.com/jscraik/configs/pull/367)
was open at `3b4d6875` with passing reported checks. These were distinct
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
`ed9110f9aa94967357f7b111e922ecbd8ddadc33`. The final tested implementation is
[`e9587e329bbc980abe52ba54dbbd32a953949fd0`](https://github.com/jscraik/configs/commit/e9587e329bbc980abe52ba54dbbd32a953949fd0),
published in [Configs PR 368](https://github.com/jscraik/configs/pull/368).
Its tree includes both corrections described below. The primary Configs checkout and
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
The complete 17-test focused suite then passed against the tree committed as
`e9587e329bbc980abe52ba54dbbd32a953949fd0`, including all seven cases through
the real read-only CLI.
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
The implementation and these reports are published in separate
[Configs PR 368](https://github.com/jscraik/configs/pull/368) and
[SDK PR 67](https://github.com/jscraik/skills-sdk/pull/67). Hosted CI and review
clearance retain their own current-head evidence; the local results above do
not grant either PR clearance.

On 17 October, GitHub confirmed Configs PR 368 merged at 12:26:37 UTC as
`3002f3a92c8164fd3475b91fda188fd0917236fd`, and SDK PR 67 merged at
13:14:05 UTC as `3e3ae014ac38622522c99d428636a3b3cd61af69` from
`857b3e3da085a179c34a868fae08125ce58a8221`. These observed merges do not
retroactively clear the recorded CodeRabbit evidence gaps. All 21 Configs and
five SDK check contexts passed on their published candidates.

The separate [Configs PR 369](https://github.com/jscraik/configs/pull/369)
adds 29 docstring lines at `2d13d2daaf7949b81f928ad092ab6a471f646fe7`.
All 21 hosted checks passed, hosted Codex returned no findings, and an
independent exact-base native review repeated 17 passing tests without a
regression. Fresh CodeRabbit chat inspection reported no findings, but its
[later clarification](https://github.com/jscraik/configs/pull/369#issuecomment-6234505029)
explicitly declared the persisted inspection inconclusive. The readiness gate
correctly refused clearance; the standalone provider marker was not stripped
to override that concern.

Jamie approved a bounded shared-helper repair. Separating the documented
full-review command into its own paragraph produced an authenticated
[actual command acknowledgment](https://github.com/jscraik/configs/pull/369#issuecomment-6234586853).
The service then stopped at its included allowance. This proves command
delivery, not completed review. Sixteen focused tests and independent review
passed; exact historical request recognition and the live creation-time guard
were retained. Later delivery and completed-review evidence follow below.

The routing repair is signed as `34e835492796a6bcdccf4cdc31403dab42f21e96`
in separate [Configs PR 370](https://github.com/jscraik/configs/pull/370).
Canonical validation passed 670 maintained policy tests in 981.903 seconds,
37 duplication regressions and maintained wiring. The included full review
then completed under run `0f5bc071-42b0-4d95-a760-d53bc47d2827` and found
[one minor docstring inaccuracy](https://github.com/jscraik/configs/pull/369#discussion_r4302934040).
The validator binds all evidence to its repository, but only pull references
to the PR number. The finding was confirmed and its sentence corrected;
17 focused tests and independent review passed. The corrected sentence is
published as `22e5d74e53f676bd20c5a0d749e15cfa8d1935ea`. Its full canonical
validation passed 669 policy tests in 1074.934 seconds, 37 duplication
regressions and maintained checks. Exact-base native review independently
repeated 17 passing tests and found no regression. All 21 corrected-head
hosted checks passed. Fresh included full review
`4313d935-7409-49db-bb02-e8b35e45cdc9` completed both files with no actionable
comments and 100% touched-function docstring coverage. Its
[exact-head clarification](https://github.com/jscraik/configs/pull/369#issuecomment-6235457637)
qualified in the 15:04 gate. At 15:04:52 UTC, hosted Codex clearance was the only
remaining review blocker; zero threads remained unresolved.

PR 370 separately repairs the request producer and a source-bound Codex
service-failure retry. Historical revisions added authenticated actor and
provider identity, exact-head binding, chronology, mutation-time rechecks,
formal-review rejection and deduplication. Independent and hosted reviews
found late completion, edited-summary, equal-second ordering and empty-mode
gaps; each confirmed issue received focused rejection proof. CodeRabbit also
found a stale-inventory test gap, repaired with distinct inventories and a
mutation control. The [detailed results](agentic-review-p1-results.md#p2-hosted-follow-up-checkpoint)
retain the revision-specific commits, counts, commands and review artifacts.

The reviewed earlier helper was projected with backup and byte comparison.
An installed read-only probe rejected the authentic old quota response after
the head changed. It neither posted a live quota retry nor proved clearance.
Later corrections are not assumed installed, reviewed or accepted merely
because an earlier revision passed. Final delivery evidence follows below.

Jamie approved one temporary existing-credit review window of at most
15 minutes, with at most one manual Codex review request per PR 369 and 370,
followed by restoration to off. The window was used only for one manual PR 370
request and was restored OFF by 19:43:14 UTC, within a conservative maximum
of 4 minutes 13 seconds. Closed PR 369 received no request. Actual credit
consumption and monetary cost were not observed. No purchase, auto-reload,
automatic-review preference or paid CodeRabbit change was made.

This is a useful pilot observation, not a comparative accuracy result: the
completed provider review found one wording defect after earlier native
reviews had found no regression. Command delivery, persisted completion
evidence, source review and merge clearance are separate outcomes. The
included allowance initially reported one review per hour, making queue delay
part of the observed operator cost. A later provider notice reported five per
hour and four remaining. Neither snapshot establishes a fixed future allowance
or a plan change. No additional paid review was requested.

Metadata freshness also affected the real loop: refreshing PR 369's description
updated CodeRabbit's older summary after its qualifying verdict. The readiness
gate rejected that later unrecognised evidence instead of reusing the earlier
clearance. The operator must finish metadata changes before obtaining the
final explicit verdict. This is an observed integration cost, not evidence of
another source defect or grounds to weaken the freshness rule.

At 16:39:55 UTC, GitHub records PR 369 merged by `jscraik` as
`0157cedd0572f4e4c37c1109a5010d6bf6cdf58e`. Both changed files match their
reviewed `22e5d74e` versions in the accepted commit. The whole repository tree
also includes other concurrently accepted work and is not claimed identical.
The final update receipt had not passed: CodeRabbit required a later explicit
verdict after the metadata refresh, and current-head Codex clearance was
missing. This establishes merge and accepted content, not retrospective review
clearance. No review request was sent to the closed PR and the approved credit
window remained off and unused.

Further hosted reviews found an edited actor-owned retry, trailing content
hidden behind a pending marker, and edited legacy reinspection requests.
Controlled rejection cases reproduced each gap. Signed corrections `57eb68bb`
and `6db30f8a33b145ec39f327208d3e8ea5acbfaf44` retain accepted main's separate
CodeRabbit retry route, reject mixed modes and require exact neutral metadata
and unchanged request timestamps. The latter passed 22 focused tests and a
730-test policy aggregate; exact revision-specific proof remains in the
[detailed results](agentic-review-p1-results.md#observed-pr-369-merge-and-remaining-helper-repair).
CodeRabbit's incremental run `e53c3354-47bb-492a-9777-c4d5430f0809` covered both
files without actionable comments, but timed-out CI context is not independent
CI verification. Unknown pending layouts and live quota-retry writes remain
outside the proven path.

Codex's automatic code and security reviews completed on this head without
findings at 17:41:59 and 17:41:44 UTC; the matching PR-body thumbs-up reaction
followed at 17:42:02. The live update gate at 18:09:03 verified 21 passing
current-head check contexts, zero unresolved threads and no outstanding Codex
requirement. The three repaired findings were reconciled with published
regressions and independent current-head evidence. CodeRabbit remained the
only outstanding reviewer: its earlier green status said `Review rate limited`.
The guarded included full-review request at 18:10 started run
`dd330ddd-e662-4e82-bcc4-44ea22c6b00d` on both final files against current main.
It finished at 18:12:49. Although the summary reported no concrete merge-blocking
risk, its published review recorded one trivial duplication finding; clarification
confirmed that this prevented a no-findings verdict. The local correction
extracts shared authenticated-actor and unedited-request filters while retaining
each path's body matching and chronology. A later Codex pass reported the same
duplication plus a retry-reuse defect after a neutral pending update. The new
23rd test reproduced that failure. The correction permits later minimal neutral
metadata only while a valid, unedited, actor-owned retry exists; removal before
mutation and invalid neighbouring cases remain blocked. All 23 focused tests
and pinned lint passed. The pre-integration aggregate passed 732 policy tests
in 1091.535 seconds and 37 duplication regressions; complete-base independent
review repeated 23 tests without an actionable defect. Before push, GitHub
showed CodeRabbit's completed autofix commit `e613492b` on the same branch.
The normal local merge preserves its shared API and additional rejection tests
with the retry correction. The combined tree passed 23 focused tests, pinned
lint, complete-base independent review, 732 policy tests in 1099.822 seconds
and 37 duplication regressions. Signed normal merge
`29f3504df31fb8dc8034a223080e9dc7f8b75557` is pushed; its committed diff budget
passed at 398 net lines without an override. Protected description repair and
exact readback passed. Hosted CI and reviews on this head are running;
publication alone is not clearance. Final hosted evidence follows below.

At 19:50:52 UTC, the update receipt passed for `29f3504d` against `main`:
all 21 check contexts, both required current-head reviewers and zero unresolved
threads. CodeRabbit's full run `2e584bbb-c916-4c05-bb06-84cf93db09c8`
covered both files without actionable comments; its
[explicit verdict](https://github.com/jscraik/configs/pull/370#issuecomment-6239887999)
was accepted without changing the parser. Codex code and security reviews
completed without findings after the single approved manual request. The
edited-failure chronology finding was independently refuted and reconciled
under a restricted receipt; the detailed report preserves its proof limits.
The description was then updated through the receipt-bound helper and read
back exactly against the unchanged head and base. Refreshed hosted workflow
`28fa3abf-ffab-424c-b52e-556ba30f083d` passed, including metadata and full tests.
The metadata-triggered summary update required a later
[CodeRabbit verdict](https://github.com/jscraik/configs/pull/370#issuecomment-6240204791).
The final update receipt passed at 20:10:59 UTC with all 21 checks, both required
reviewers and zero unresolved threads. GitHub reports the same head mergeable
with clean merge state. PR 370 remains open; its merge is not authorised.

The exact reviewed helper was projected with backup and byte comparison.
Installed help, read-only rejection of the authentic stale quota source and
the actual normal Codex request passed. A repeat live CodeRabbit deduplication
check was rejected by automatic approval review because it could duplicate a
completed review or incur unapproved cost. It was not executed; dry-run and
read-only source-binding proof provide the bounded fallback. No live quota-retry
write or whole-runtime validation is claimed.

For SDK review context, Jamie approved a bounded metadata summary and one
temporary manual SDK-to-Configs link. The summary was published and its
template-format defect repaired; SDK validation attempt two passed. The link
could not be saved on the existing plan while preserving two inherited custom
checks. The unsaved draft was discarded and original settings restored exactly.
No link, upgrade or additional charge was applied. The single earlier approved
Configs review cost $1.50; automatic billing was not enabled.

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
task's owned report scope. That combined snapshot classified as full; an
isolated prose check does not validate it. The initial two-report proof used
accepted `0d4a39d8`. The current report delivery uses an isolated snapshot of
accepted `0599ffe87bc2c0db3ea4cd7d53b50aead9deec96`; its prose wrapper passed
all 12 documentation-dependent tests. Neither result accepts unrelated changes.

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
