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
The same decision makes distribution registry-independent: Tessl is the initial
backend to prove; a separately operated registry becomes primary only after
the [transition gates](../../workflow.md#registry-transition). Do not start or
create that registry, including a catalogue or prototype, until the Skills SDK
workflow meets its agreed acceptance criteria and publication to Jamie's private
Tessl workspace is verified by exact-version and private-visibility readback.
Record that proof here before separately authorised registry work begins.
A catalogue may then precede independent distribution; neither service building
nor live publication is authorised by this record. Preserve one canonical content source and bind
distinct portable/export artifact digests through an explicit adapter.

The [brAInwav product-family boundary](../../../ARCHITECTURE.md#brainwav-product-family)
keeps `skills-sdk` and future `skills-registry` in separate repositories.
Registry UI, API and workers stay together initially. Workers consume an
installed, pinned SDK package through public APIs and versioned schemas;
website, accounts, catalogue, artifact storage/access and job operations belong
to the registry. Production editable/checkout imports and duplicated SDK rules
are excluded. Prove the packaged consumer boundary and credential isolation when
that work is authorised. This is future ownership, not a new implementation
slice or registry-start authority.

The same owner direction requires an approved professional icon for every
Jamie-owned managed plugin, including one-skill releases. Apply the
[icon policy](../../workflow.md#icons-and-presentation) and
[strengthened acceptance gates](../../product-acceptance.md#managed-release-gates)
through existing slices. Preserve valid third-party branding and rights. Artwork
creation is an explicit preparation operation, not a validator side effect or
permission to spend; no installed-copy bulk rewrite is authorised.

Preserve unrelated source edits and generated run state. No provider spending,
credential use, registry mutation, public publication, or home runtime mutation
is authorised by this task record. Implement portable boundaries and controlled
adapter proof first; live operations require their applicable authority.
Normal signed delivery remains governed by CONTRIBUTING.md and user authority.

## Ordered checklist

| Slice | Work | Completion proof | State |
| --- | --- | --- | --- |
| S1 | Record the target workflow, map all 52 source capabilities, repair stale command discovery. | Links and repository checks pass; source statuses remain distinct from SDK statuses. | Accepted in PR #44; maintain affected rows at every feature closeout. |
| S2 | Add applicable plugin/skill policy, approved icons and reference/description quality checks through existing validation seams. | Accepted, rejected, and corrected package inputs through public services and installed CLI; original source remains unchanged and release proof binds the complete plugin. | Partial: PRs #45–48 merged. Skill policy, declared claim coverage, supplied content assessment, bounded offline review and local stage composition exist. Plugin normalisation/composition, icon validation/approval, comprehensive semantic accuracy, external reference quality and full legacy parity remain open. |
| S3 | Bind applicable security evidence, update-permission differences and executed scenario/scorer evidence before evaluation. | Relevant checks are required; absent, stale, wrong-candidate, and contradictory evidence block; neighbouring valid inputs pass; expanded permissions need renewed authority. | Partial: PRs #49–50 merged. Static screening, guarded selected-case execution and observed numeric calibration exist. Permission-delta interpretation, independent scanner/reviewer provenance, live quality and remaining risk semantics remain open. |
| S4 | Implement budgeted matched plugin evaluation, local then cloud adapter handoff, and failure ownership. | Frozen complete-plugin identities, both variants, per-skill/relevant cross-skill cases, same-model lift, calibrated judging, rejected drift and recovery; declared stopping, improvement and regression limits; no promotion for inconclusive results. | Locally validated candidate, unmerged. Reconcile plugin binding and budget/decision acceptance against the accepted calibration base before normal PR delivery. Local fixtures do not establish live local/cloud model lift. |
| S5 | Compose plugin archive/presentation verification, explicit exports and registry-independent publication/readback/install boundaries, initially Tessl. | Complete resources/modes, private-material exclusion, versioned destination profiles, separate portable/export digests, exact checked version, uncertain-outcome readback, idempotency and observed recovery; host display/activation separately proved. | Local Tessl-format plugin and transport prototypes, unmerged and not canonical portable intake. Reconcile metadata ownership and the transport input-boundary finding before integration. Initial Tessl execution and any future backend transition remain separate. |
| S6 | Join feedback-to-regression and reconcile consumer cutover or retirement coverage. | Every scoped failure has an owner and retained regression; clean-room entrypoints run without sibling projects; all legacy rows have disposition. | Queued |

## Accepted delivery ledger

Accepted SDK baseline: [`c38a769`](https://github.com/jscraik/skills-sdk/commit/c38a7696ebc8e283cd69a1914f8abb543b459f2a),
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
| [PR #51](https://github.com/jscraik/skills-sdk/pull/51) | [`c38a769`](https://github.com/jscraik/skills-sdk/commit/c38a7696ebc8e283cd69a1914f8abb543b459f2a) | Reconciled accepted coverage and plugin-first release policy, mandatory icons and the separate registry start gate; no executable capability added. |

Repository tests and installed-entrypoint proof are linked in the migration map.
The ledger records hosted acceptance; it does not replace exact candidate
validation, current PR checks/reviews, or live provider and runtime evidence.

## Proof lanes and resume point

Use `pass`, `fail`, `blocked`, or `not_run` for each lane. Record exact command,
candidate revision, evidence reference, what it proves, and the next check.
Do not turn a successful local gate into hosted, provider, registry, or runtime
clearance. Required proof blocks completion of its dependent slice only.

Name delivery state separately: proposed, implemented locally, validated locally,
under review, merged, published, or verified in a host. Record exact revision and
proof for each applicable lane; these are not interchangeable completion labels.

The focused commands below are historical runs in the pinned Python 3.12
environment. Their repository command text is retained; transient local cache
and tool-state environment overrides are omitted from this portable record.
Documenting these commands does not claim a new test run.

- Source assessment base: Agent-Skills `532962c65ef0549d16168c0e899c9cb8dc032188`.
- Documentation reconciliation merged in
  [PR #51](https://github.com/jscraik/skills-sdk/pull/51) at `c38a769`. It records the plugin-first
  target, mandatory icon policy and strengthened acceptance without changing
  executable services or live-operation authority.
- Current work: portable plugin inspection and binding, locally validated on
  `codex/sdk-portable-plugin-intake` with documentation from PR #51. The additive
  `validate_plugin_package` / `validate-plugin` route captures root-manifest
  candidates, complete file bytes and modes, per-skill findings and OpenAI
  settings precedence. Focused and installed proof live in
  [plugin tests](../../../tests/test_plugin_package.py) and
  [installed smoke](../../../tests/installed_plugin_intake_smoke.py).
  Historical proof for `41c2dfcf373f4c345ec0fc03ba38633bb0484d58`:
  `bash scripts/validate-repository.sh` passed on 2026-10-08 with 2,566 tests
  passed, one skipped, wheel build and all installed-entrypoint checks passing.
  The pre-reconciliation repair passed that command on 2026-10-08 with 2,629 tests
  passed, one skipped, wheel build and all installed-entrypoint checks passing.
  It repairs child-role binding, literal entrypoint discovery and named
  unknown-key diagnostics. It also adds source-backed full-envelope
  verification through `verify_plugin_package_validation` and
  `validate-plugin --verify-evidence FILE`; hash-only contract consistency does
  not establish source derivation. This work remains unmerged against accepted
  main `c38a769`; local proof and hosted delivery are separate states.
- PR #52 reconciliation follows the completed bot task at `86760d2`. The local
  candidate preserves digest-only receipts instead of retaining arbitrary raw
  settings. Canonical digest tests cover inline and fallback nested settings,
  private-value non-disclosure, tamper rejection and corrected-input recovery.
  Focused plugin, evidence, CLI and public-boundary checks on 2026-10-08:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_evidence.py tests/test_plugin_evidence_cli.py tests/test_plugin_review_regressions.py tests/test_plugin_package.py tests/test_public_repository_boundary.py -q
  ```

  Result: `pass` — 133 tests passed. After restoring the no-settings
  orphan-digest regression:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_evidence.py -q
  ```

  Result: `pass` — 12 tests passed. The reconciled candidate then passed
  `bash scripts/validate-repository.sh` on 2026-10-08: 2,632 tests passed, one
  skipped, with schema, code style, build, installed-entrypoint and diff checks
  passing. Earlier aggregate proof remains historical; signed delivery and
  current-head hosted evidence are separate closeout requirements.
- Signed repair `49fd6fc367dca04e97cd0319913b8c5f4aaaed10` was pushed to
  [PR #52](https://github.com/jscraik/skills-sdk/pull/52) on 2026-10-09. Its five
  hosted review threads were resolved by their reviewers or the owner. A local
  base review then found a blocked-output policy-retention defect. The follow-up
  repair preserves valid caller policy across malformed or mismatched evidence,
  CLI read and JSON failures, and invalid source revisions. Invalid policy
  fails before source capture. Focused policy, evidence and plugin checks on
  2026-10-09:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_evidence.py tests/test_plugin_evidence_cli.py tests/test_plugin_package.py -q
  ```

  Result: `pass` — 103 tests passed. The earlier 2,632-test aggregate result applies to
  the previous repair; the final follow-up result is recorded below.
  Hosted review `5466755715` then identified missing candidate-ID binding for
  blocked children. The same follow-up repairs that boundary, including invalid
  directory-name fallback IDs. Its manifest-allowlist allegation was refuted by
  the committed allowlist and passing typed-model roundtrip tests. The expanded
  focused plugin, standalone, core and receipt suite ran on 2026-10-09:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_child_binding.py tests/test_plugin_evidence.py tests/test_plugin_evidence_cli.py tests/test_plugin_package.py tests/test_plugin_review_regressions.py tests/test_skill_package_validation.py tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py -q
  ```

  Result: `pass` — 352 tests passed, one skipped. Independent delta reviews
  found no actionable issues.
  Review `5466988582` added a pre-open special-file finding and repeated the
  policy-mismatch finding already covered by the repair. The follow-up also
  rejects known non-regular files before opening them, including the standalone
  reader found by the bounded sibling check. Post-open race checks remain.
  The in-progress aggregate was interrupted to include this final correction;
  partial test output is not a passing aggregate result.
  After correcting the new test's message assertion to the existing sanitised
  public diagnostic, the pre-open regression command was:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_capture_preopen.py -q
  ```

  Result: `pass` — 13 tests passed on 2026-10-09. The final candidate
  passed `bash scripts/validate-repository.sh` on 2026-10-09: 2,674 tests passed,
  one skipped, with generated schemas, code style, build, all installed-entrypoint
  acceptance/rejection/recovery checks and `git diff --check` passing.
- Signed input and evidence repair
  [`ed488df`](https://github.com/jscraik/skills-sdk/commit/ed488dfcfdb665143d9a0551c48be08acc0fbfe8)
  was published in PR #52 through signed reconciliation commit
  [`3629e329`](https://github.com/jscraik/skills-sdk/commit/3629e3293facfa2da9425be62b2c9dd4b4439801)
  on 2026-10-09. The reconciliation tree is identical to the validated repair
  tree. Review `5467338707` requested the exact focused commands recorded above;
  this documentation correction does not change implementation or test inputs.
- Review `5467422704` added three input-boundary findings on `3629e329`:
  coercible nested child sizes, erased component-kind blockers, and known
  special evidence files opened before rejection. The follow-up rejects those
  inputs, preserves standalone size parsing and shared CLI success semantics,
  and retains post-open checks. A bounded sibling check also covers component
  directories proved by captured descendants; empty directories are not inferred.
  The new regression command reproduced 27 failures with one passing race check
  before repair, then passed all 28 cases after repair:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_envelope_review.py tests/test_plugin_context_preopen.py -q
  ```

  Result: `pass` on 2026-10-09 for that initial repaired test set. The expanded
  neighbouring-input, unsupported-host, shared-caller and contract suite ran:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_envelope_review.py tests/test_plugin_context_preopen.py tests/test_plugin_evidence.py tests/test_plugin_evidence_cli.py tests/test_plugin_child_binding.py tests/test_plugin_capture_preopen.py tests/test_intake_cli.py tests/test_content_review.py tests/test_local_check_cli.py tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py -q
  ```

  Result: `pass` — 402 tests passed on 2026-10-09. The first aggregate stopped
  at the 800-line module limit before pytest. Combining the equivalent
  descriptor-support conditions repaired that failure without changing the limit.
  The reader regression command then passed all nine cases:

  ```sh
  mise exec -- uv run --frozen pytest -p no:cacheprovider -o addopts='' tests/test_plugin_context_preopen.py -q
  ```

  Result: `pass` on 2026-10-09. The final
  `bash scripts/validate-repository.sh` result was `pass`: 2,705 tests passed,
  one skipped, generated schemas, code style, wheel build, every installed
  API/CLI acceptance/rejection/recovery check and `git diff --check` passed.
  The earlier 2,674-test aggregate remains historical. Synthetic device metadata
  and temporary FIFO fixtures do not establish atomic capture or live host proof.
- Next action: publish the input-boundary follow-up and focused-command record, then
  reconcile current-head hosted review and checks for PR #52 before receipt-gated merge.
  Preserve the accepted calibration service
  and queued local-winner handoff; integrate downstream work only after the
  complete-plugin identity seam is ready. Earlier branch-local validation does
  not prove the new product contract.
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

### Queued-work assessment and next bounded slice

Read-only assessment on 2026-10-08 found that queued capture, build, hardening
and transport use `.tessl-plugin/plugin.json` as authoritative metadata. Root
`plugin.json` and the Codex overlay are retained as ordinary files, not
interpreted as a canonical portable contract. Immediate-child skill discovery,
full-file recapture, per-skill findings and a separate mode ledger are reusable.
Byte-content identity must not be described as including modes when the current
contract binds modes separately. Current ZIP/TGZ verification proves supplied
representations of that bundle, not a portable-to-Tessl export relationship.

The queued matched handoff already requires the qualifying local candidate as
the cloud baseline, preserves frozen controls, and compares both cloud variants
within one cloud model lane. Preserve it. Callers still supply the refined
candidate; neither candidate authoring nor live cloud quality is established.
These are source-inspection results, not new test runs or accepted-main claims.

Active slice: **canonical portable plugin intake and binding**, within the existing
validation, intake, packaging, model/schema and CLI seams. No registry server,
provider execution, publication or installation is part of this slice.

- Accept root-only single- and multi-skill Agent Plugins candidates using the
  selected specification and direct skill discovery, with Tessl unavailable.
- Establish whole-plugin identity before downstream evidence; retain complete
  resources, modes and per-skill findings. Prove changed shared bytes or modes
  invalidate their affected evidence, and bare-skill receipts cannot clear a
  newly assembled plugin.
- Capture referenced artwork bytes as resources in this slice, without claiming
  decoding, visual approval or observed host display. Preserve the required
  release-policy gate for the following presentation slice.
- Implement OpenAI extension precedence without merging an ignored overlay.
  Separate standard conformance from stricter SDK policy, including unknown
  fields and metadata conflicts; never label an SDK-only rejection a standard
  requirement. Keep supported compatibility imports explicit, not competing
  canonical metadata sources.
- Preserve standalone-skill public contracts and original source. Keep wrapping
  into a new candidate as an explicit later normalisation step, not a silent
  change to existing skill identity.
- Prove valid, malformed/type-invalid, unsafe-path/resource, stale-evidence and
  corrected-input cases through public models, schemas, API and installed CLI
  with Agent-Skills, Foundry and registry services unavailable. Run focused
  proof and the required aggregate after relevant implementation changes.

After intake binding, add a bounded icon/presentation validation slice using
existing models and services, not a new framework. Prove approval/rights binding,
destination image limits, safe manifest references, exact packed assets, changed
icon invalidation, and accepted/rejected/corrected inputs. Keep visual approval
distinct from decoding and authorised host-display proof distinct from offline
validation. Inventory existing managed plugins for missing or unsuitable art
through supplied candidates, then schedule normal versioned updates; preserve
acceptable art and verified provider-managed exemptions.

Then compose explicit standalone normalisation, plugin-bound evaluation and
archive preparation. Reconcile declared optimisation budgets and permission
changes before dependent execution, and require adapter-version, presentation,
interruption/retry and recovery proof before delivery. A separate bounded Tessl export adapter must retain
unchanged skill contents, distinct artifact digests and a verified relationship,
or block when required resources/modes cannot survive. Preserve the existing ten
active scenarios. No current candidate authorises advancing to live operations.

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
