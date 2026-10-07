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
| S1 | Record the target workflow, map all 52 source capabilities, repair stale command discovery. | Links and repository checks pass; source statuses remain distinct from SDK statuses. | Locally verified; delivery pending |
| S2 | Add applicable package policy and reference/description quality checks through existing validation seams. | Accepted, rejected, and corrected package inputs through public services and installed CLI; source remains unchanged. | Queued |
| S3 | Bind applicable security evidence and executed scenario/scorer evidence before evaluation. | Relevant checks are required; absent, stale, wrong-candidate, and contradictory evidence block; neighbouring valid inputs pass. | Queued |
| S4 | Implement matched baseline/candidate evaluation, local then cloud adapter handoff, and failure ownership. | Frozen identities, both variants, same-model lift, calibrated judging, rejected drift, and controlled recovery; live runs separately authorised. | Queued |
| S5 | Compose archive preparation/verification and supported private registry/readback/install boundaries. | Complete resources/modes, exact candidate/version/digest, controlled adapter failures and recovery; real external state separately proved. | Queued |
| S6 | Join feedback-to-regression and reconcile consumer cutover or retirement coverage. | Every scoped failure has an owner and retained regression; clean-room entrypoints run without sibling projects; all legacy rows have disposition. | Queued |

## Proof lanes and resume point

Use `pass`, `fail`, `blocked`, or `not_run` for each lane. Record exact command,
candidate revision, evidence reference, what it proves, and the next check.
Do not turn a successful local gate into hosted, provider, registry, or runtime
clearance. Required proof blocks completion of its dependent slice only.

- Current accepted SDK base: `3fcd1565781a9a7da7b8594be61972d4b0d8f089`.
- Source assessment base: Agent-Skills `532962c65ef0549d16168c0e899c9cb8dc032188`.
- Current work: S1 in an isolated task branch.
- Next action: deliver S1, then start S2 with explicit applicable-file policy
  and deterministic reference checks using the safely captured package bytes.
  Keep semantic accuracy review separate from structural validation.
- Local validation for S1 on 2026-10-07:
  `bash scripts/validate-repository.sh` -> `pass` (1977 passed, one skipped;
  schemas, style, build, installed PR-sweep smoke, and diff check passed).
  `bash scripts/validate-codestyle.sh` -> `pass` (all six changed docs included).
  `git diff --cached --check` -> `pass` after removing extra EOF blank lines.
  The pinned `skills-sdk --help` route -> `pass`; no provider was executed.
- Inventory proof: all 52 source ids mapped exactly once, with no extra ids.
- Simplification outcome: `no_justified_edit`; the workflow, inventory, and
  temporary task record have separate consumers and maintenance purposes.
- Hosted delivery/review: `not_run`.
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
