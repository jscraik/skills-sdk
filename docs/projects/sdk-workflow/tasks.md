# Skills SDK workflow delivery

Owner: Skills SDK maintainers. This task record tracks the owner-approved
workflow in [workflow.md](../../workflow.md). The capability inventory in
[migration-map.md](../../migration-map.md) replaces conversation-only migration
status. This record owns delivery state and accepted revisions; the workflow
owns the intended process and accepted capability boundaries, while the map
owns legacy dispositions, proof, limitations, and remaining actions. Update
these existing documents together at feature closeout; archive this record
only after all scoped acceptance criteria pass.

## Goal and constraints

Deliver an independent, agent-accessible create/update/external-check workflow,
then applicable security, matched local/cloud evaluation, registry delivery,
selected installation, and regression feedback. Reuse existing SDK services,
models, schemas, and tests. Keep one writer per branch and one bounded slice
per reviewable change.

Owner decision, 2026-10-08: use the
[plugin-first managed release format](../../workflow.md#managed-release-format).
Every SDK-managed skill release is an Agent Plugins package, including one-skill
releases; root `plugin.json` is canonical. Keep standalone-skill intake and
validation, preserve source during normalisation, and bind release evidence to
the completed plugin rather than wrapping a cleared skill afterwards. Existing
accepted services are not retroactively complete-plugin implementations.

Preserve unrelated source edits and generated run state. No provider spending,
credential use, registry mutation, public publication, or home runtime mutation
is authorised by this task record. Implement portable boundaries and controlled
adapter proof first; live operations require their applicable authority.
Normal signed delivery remains governed by CONTRIBUTING.md and user authority.

## Ordered checklist

| Slice | Work | Completion proof | State |
| --- | --- | --- | --- |
| S1 | Record the target workflow, map all 52 source capabilities, repair stale command discovery. | Links and repository checks pass; source statuses remain distinct from SDK statuses. | Accepted in PR #44; maintain affected rows at every feature closeout. |
| S2 | Add applicable plugin/skill policy and reference/description quality checks through existing validation seams. | Accepted, rejected, and corrected package inputs through public services and installed CLI; original source remains unchanged and release proof binds the complete plugin. | Partial: PRs #45–48 merged. Skill policy, declared claim coverage, supplied content assessment, bounded offline review and local stage composition exist. Plugin normalisation/composition, comprehensive semantic accuracy, external reference quality and full legacy parity remain open. |
| S3 | Bind applicable security evidence and executed scenario/scorer evidence before evaluation. | Relevant checks are required; absent, stale, wrong-candidate, and contradictory evidence block; neighbouring valid inputs pass. | Partial: PRs #49–50 merged. Static screening, guarded selected-case execution and observed numeric calibration exist. Independent scanner/reviewer provenance, live quality and remaining risk semantics remain open. |
| S4 | Implement matched baseline/candidate plugin evaluation, local then cloud adapter handoff, and failure ownership. | Frozen complete-plugin identities, both variants, per-skill/relevant cross-skill cases, same-model lift, calibrated judging, rejected drift and recovery; live runs separately authorised. | Locally validated candidate, unmerged. Reconcile plugin binding and integrate against the accepted calibration base before normal PR delivery. Local fixtures do not establish live local/cloud model lift. |
| S5 | Compose archive preparation/verification and supported private registry/readback/install boundaries. | Complete resources/modes, exact candidate/version/digest, controlled adapter failures and recovery; real external state separately proved. | Local archive and complete-plugin prototypes, unmerged. Resolve the remaining transport input-boundary finding, then integrate and prove against accepted main. Publication/readback/install execution remains separate. |
| S6 | Join feedback-to-regression and reconcile consumer cutover or retirement coverage. | Every scoped failure has an owner and retained regression; clean-room entrypoints run without sibling projects; all legacy rows have disposition. | Queued |

## Accepted delivery ledger

Accepted SDK baseline: [`817966b`](https://github.com/jscraik/skills-sdk/commit/817966b378be0da45928fbaef89b2ede3708b012),
verified on 2026-10-08. The workflow and migration map describe this same
revision. These merges accept the bounded capabilities below, not all acceptance
criteria of their parent slices.

| Delivery | Accepted revision | Bounded capability |
| --- | --- | --- |
| [PR #44](https://github.com/jscraik/skills-sdk/pull/44) | [`77640af`](https://github.com/jscraik/skills-sdk/commit/77640af82642f5b02ae2624337a1f0c170199f3e) | Target workflow, source inventory and command discovery. |
| [PR #45](https://github.com/jscraik/skills-sdk/pull/45) | [`812e10c`](https://github.com/jscraik/skills-sdk/commit/812e10cd149b2e07131078eb25d4354b02299d14) | Applicable package-quality policy. |
| [PR #46](https://github.com/jscraik/skills-sdk/pull/46) | [`a07b332`](https://github.com/jscraik/skills-sdk/commit/a07b3324f5eb89d42bc6a0387b842ef4678fd3fa) | Candidate-bound declared scenario-claim coverage. |
| [PR #47](https://github.com/jscraik/skills-sdk/pull/47) | [`6ce9924`](https://github.com/jscraik/skills-sdk/commit/6ce99240ebd349eee7d91e896153509b13e680ec) | Candidate-bound content assessment and bounded offline reviewer execution. |
| [PR #48](https://github.com/jscraik/skills-sdk/pull/48) | [`b208b1d`](https://github.com/jscraik/skills-sdk/commit/b208b1d20f1ff948013b4594336c4d7f260164d1) | Ordered local quality workflow with typed stop and recovery boundaries. |
| [PR #49](https://github.com/jscraik/skills-sdk/pull/49) | [`40139ca`](https://github.com/jscraik/skills-sdk/commit/40139ca2e813cd6e3555cff0366cd2262fdd5972) | Bounded static screening and candidate-bound safety gates before selected-case execution. |
| [PR #50](https://github.com/jscraik/skills-sdk/pull/50) | [`817966b`](https://github.com/jscraik/skills-sdk/commit/817966b378be0da45928fbaef89b2ede3708b012) | Observed numeric scorer-calibration callbacks; the CLI consumes supplied-offline fixtures. |

Repository tests and installed-entrypoint proof are linked in the migration map.
The ledger records hosted acceptance; it does not replace exact candidate
validation, current PR checks/reviews, or live provider and runtime evidence.

## Proof lanes and resume point

Use `pass`, `fail`, `blocked`, or `not_run` for each lane. Record exact command,
candidate revision, evidence reference, what it proves, and the next check.
Do not turn a successful local gate into hosted, provider, registry, or runtime
clearance. Required proof blocks completion of its dependent slice only.

- Source assessment base: Agent-Skills `532962c65ef0549d16168c0e899c9cb8dc032188`.
- Current work: this bounded documentation reconciliation records the accepted
  PRs above, the new plugin-first target and existing feature-closeout guidance.
  It changes no executable service, schema, active scenario set, or live-operation
  authority. Plugin-first support remains implementation work, not a doc-only pass.
- Next action: finish documentation validation and normal signed delivery, then
  reconcile queued plugin capture/normalisation against root `plugin.json`,
  direct skill discovery and OpenAI extension precedence before advancing S4/S5.
  Reuse existing models/services where valid; do not create a competing framework.
  Prove source preservation, accepted single/multi-skill packages, malformed or
  conflicting metadata, unsafe resources, post-wrap evidence rejection and
  corrected-input recovery through installed entrypoints with sibling projects
  unavailable. Preserve the accepted calibration implementation; integrate and
  refresh affected proof only after the complete-plugin identity seam is ready.
  Earlier branch-local validation does not prove this new product contract.
- Unmerged S4 evidence: the repaired candidate passed its local repository
  wrapper (2552 passed, one skipped), plus installed rejection/recovery proof.
  This is not accepted SDK functionality, hosted clearance, or live model proof.
- Unmerged S5 evidence: archive, complete-plugin capture/hardening and supplied
  transport-byte work remain local candidates. A custom-timezone callback at
  transport ingress remains an actionable blocker; resolve it before claiming
  final transport review clearance or starting its full validation.
- Provider, registry, and home runtime execution: `not_run` for these delivery
  slices. Controlled callbacks and installed offline fixtures do not establish
  external scanner quality, model lift, publication, or selected installation.
- S2/S3 and programme acceptance remain open. Keep supplied mapping, semantic
  review, scenario execution, calibration, promotion and external-state proof
  separate; use the map's remaining actions before selecting further work.

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
