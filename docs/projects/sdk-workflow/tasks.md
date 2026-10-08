# Skills SDK workflow delivery

Owner: Skills SDK maintainers. This task record tracks the owner-approved
workflow in [workflow.md](../../workflow.md). The capability inventory in
[migration-map.md](../../migration-map.md) replaces conversation-only migration
status. Update this record after each proved slice; archive it after all scoped
acceptance criteria pass.

## Goal and constraints

Deliver an independent, agent-accessible create/update/external-check workflow,
then applicable security, matched local/cloud evaluation, registry delivery,
selected installation, and regression feedback. Reuse existing SDK services,
models, schemas, and tests. Keep one writer per branch and one bounded slice
per reviewable change.

Preserve unrelated source edits and generated run state. No provider spending,
credential use, registry mutation, public publication, or home runtime mutation
is authorised by this task record. Implement portable boundaries and controlled
adapter proof first; live operations require their applicable authority.
Normal signed delivery remains governed by CONTRIBUTING.md and user authority.

## Ordered checklist

| Slice | Work | Completion proof | State |
| --- | --- | --- | --- |
| S1 | Record the target workflow, map all 52 source capabilities, repair stale command discovery. | Links and repository checks pass; source statuses remain distinct from SDK statuses. | Accepted in PR #44 |
| S2 | Add applicable package policy and reference/description quality checks through existing validation seams. | Accepted, rejected, and corrected package inputs through public services and installed CLI; source remains unchanged. | Package policy accepted in PR #45; claim coverage accepted in PR #46; bounded content-review adapter integrating |
| S3 | Bind applicable security evidence and executed scenario/scorer evidence before evaluation. | Relevant checks are required; absent, stale, wrong-candidate, and contradictory evidence block; neighbouring valid inputs pass. | Queued |
| S4 | Implement matched baseline/candidate evaluation, local then cloud adapter handoff, and failure ownership. | Frozen identities, both variants, same-model lift, calibrated judging, rejected drift, and controlled recovery; live runs separately authorised. | Queued |
| S5 | Compose archive preparation/verification and supported private registry/readback/install boundaries. | Complete resources/modes, exact candidate/version/digest, controlled adapter failures and recovery; real external state separately proved. | Queued |
| S6 | Join feedback-to-regression and reconcile consumer cutover or retirement coverage. | Every scoped failure has an owner and retained regression; clean-room entrypoints run without sibling projects; all legacy rows have disposition. | Queued |

## Proof lanes and resume point

Use `pass`, `fail`, `blocked`, or `not_run` for each lane. Record exact command,
candidate revision, evidence reference, what it proves, and the next check.
Do not turn a successful local gate into hosted, provider, registry, or runtime
clearance. Required proof blocks completion of its dependent slice only.

- Current accepted SDK base: `a07b3324f5eb89d42bc6a0387b842ef4678fd3fa`.
- Source assessment base: Agent-Skills `532962c65ef0549d16168c0e899c9cb8dc032188`.
- Current work: bounded content review on the accepted package-quality and
  claim-coverage base. [PR #46](https://github.com/jscraik/skills-sdk/pull/46)
  merged externally on 2026-10-07; its exact repair head
  `70079d5b75ed94042c76c002c865bfacb6a029b2` passed all five hosted check
  contexts and all three review threads are resolved. The accepted merge tree
  matches that repair head; this agent did not perform the hosted merge.
- Next action: prove and deliver the integrated content-review candidate through
  normal signed receipt-gated delivery. Supplied assessment validation is not
  semantic execution. The separate offline adapter records observed callback
  invocation, not general semantic accuracy or authenticated external review.
  Keep supplied mapping, semantic review, scenario execution, calibration and
  promotion evidence distinct; nine-area S2 and programme acceptance remain open.

### Historical evidence (superseded by the current state above)

The following records describe earlier candidate states, not current hosted
readiness or completion of the complete S2 workflow.
- Local validation for S1 on 2026-10-07:
  `bash scripts/validate-repository.sh` -> `pass` (1977 passed, one skipped;
  schemas, style, build, installed PR-sweep smoke, and diff check passed).
  `bash scripts/validate-codestyle.sh` -> `pass` (all six changed docs included).
  `git diff --cached --check` -> `pass` after removing extra EOF blank lines.
  `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help`
  -> `pass`; no provider was executed.
- Inventory proof: all 52 source ids mapped exactly once, with no extra ids.
- Simplification outcome: `no_justified_edit`; the workflow, inventory, and
  temporary task record have separate consumers and maintenance purposes.
- Hosted delivery/review: [PR #44](https://github.com/jscraik/skills-sdk/pull/44)
  is open. Initial CI failed PR-body command grammar; guarded metadata repair
  passed with exact readback and unchanged head. Review repair and current-head
  checks are pending; no merge-readiness claim.
- S1 follow-up review: permit pre-identity blockers, return corrections to their
  responsible gate, require registry preparation, and verify rollback after
  failed runtime mutation. `bash scripts/validate-repository.sh` -> `pass`
  for the repaired workflow (1977 passed, one skipped; build and installed
  smoke passed). Hosted reconciliation still needs current-head checks.
- S1 second review: add successful and rejected-selection terminals, preserve
  verified provider-managed exemptions in the diagram, and reconcile command
  status in architecture and product acceptance.
  `bash scripts/validate-repository.sh` -> `pass` (1977 passed, one skipped;
  schemas, style, build, installed smoke, and diff check passed). Signed
  delivery and current-head hosted review remain pending.
- S2 first increment: signed revision `5b050ba78b092a94b2c553e317c8b8e23ae41d85`.
  `bash scripts/validate-repository.sh` -> `pass` (1993 passed, one skipped;
  both installed smokes passed). The earlier wrapper run failed only its new
  smoke's symlinked macOS temporary ancestor; the fixture was corrected without
  relaxing package safety. Description accuracy, reference relevance and gaps
  remain unimplemented; this is not complete S2 or executed source parity.
- Provider, registry, and runtime execution: `not_run`; no live operation selected.

## Lens application

Architecture guidance selects existing seams and caller-visible proof.
Agent-native guidance requires discoverable commands and usable recovery.
Testing requires proportionate accepted/rejected behaviour evidence.
Evals Router binds claims, cases, scorer, candidate, and execution authority.
Scenario Generator keeps realistic tasks, hidden criteria, drift review, and
failure ownership. Simplify reviews each completed patch and may record
`no_justified_edit`; it does not remove safeguards without behaviour proof.

The skills' historical Agent-Skills commands are assessment references.
Destination validation uses SDK-owned commands. The existing v1 scenario policy
remains compatible; the managed v2 path retains ten active cases.
