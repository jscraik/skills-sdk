# Workflow migration map

Owner: Skills SDK maintainers. Consumer: the independent SDK workflow.
This inventory maps all 52 ids from Agent-Skills
`Infrastructure/config/skills-sdk/capability-matrix.v1.json` at source revision
`532962c65ef0549d16168c0e899c9cb8dc032188`. It replaces copying legacy status
labels into SDK progress claims. The legacy matrix remains source assessment
material; the SDK does not load it at runtime.

Use [workflow.md](workflow.md) for target policy, [CLI status](cli.md) and
[API contracts](api.md) for public entrypoints, and
[workflow tasks](projects/sdk-workflow/tasks.md) for acceptance and delivery.
Maintain this table when a public service, consumer, or retirement decision
changes. Every pending row requires implementation or an explicit reviewed
retirement decision before Agent-Skills retirement.

Accepted SDK baseline: [`ec8f0dae`](https://github.com/jscraik/skills-sdk/commit/ec8f0dae3b370cf9f9c8a85ce91f70e4846481f1),
verified on 2026-10-10 and shared with the workflow and task record. Entries below
describe that revision, not queued branches. Each row names its entrypoint or
absence, a proof or boundary reference, its limitation, and the remaining action.

PR #54 reconciled the descriptions without adding executable capabilities.
The current calibration lifetime candidate adds fresh per-trial adapters and
[lifecycle proof](../tests/test_calibration_lifetime.py), but is unmerged; the
`evals` row retains its accepted-main limitation until delivery completes.

Accepted PR #52 affects `package_identity`, `skill_intake`
and `sdk_plugin_lifecycle`: `validate_plugin_package` / `validate-plugin` add
root-manifest inspection, whole-file/mode binding, immediate skill findings and
OpenAI settings selection. Proof lives in
[plugin regressions](../tests/test_plugin_package.py) and the
[installed smoke](../tests/installed_plugin_intake_smoke.py). Its accepted repairs
add `verify_plugin_package_validation` / `validate-plugin --verify-evidence`
for fresh source-backed comparison of supplied envelopes; see
[verification proof](../tests/test_plugin_evidence.py). Schema validation alone
cannot establish selected-settings derivation from unavailable source bytes.
This is not
standalone wrapping, admission, artwork approval, MCP transport validation or
release delivery. Complete those separate gates after this bounded
slice; the table below records accepted main, not later local candidates.

The [plugin-first release decision](workflow.md#managed-release-format) changes
the destination contract, not these accepted implementation statuses. Existing
skill-level proof must be composed under a whole-plugin candidate before it can
support managed release. Reconcile queued S2/S4/S5 work with that identity and
root `plugin.json` before delivery; do not credit legacy compatibility layouts
or local prototypes as the canonical plugin path.
The [registry transition](workflow.md#registry-transition) also replaces a
permanent Tessl-only destination with registry-independent adapters, initially
Tessl. A future catalogue/distribution service is separately owned and remains
outside current SDK implementation authority. Do not start or create it until
the SDK workflow is complete and correct publication to Jamie's private Tessl
workspace is verified; the task record must retain this start-gate evidence.

The [mandatory icon policy](workflow.md#icons-and-presentation) and
[managed release gates](product-acceptance.md#managed-release-gates) strengthen
S2–S5 acceptance without inventing legacy capability ids. Generic asset capture
is not approved-artwork proof; safety evidence is not an update-permission diff;
bounded provider work is not a budgeted improvement decision. Destination,
discovery, archive and recovery proof remain explicit remaining actions below.

## Status meanings

- Implemented: a named SDK service exists with repository tests; this does not
  establish downstream cutover or live external behaviour.
- Partial: some contracts or bounded behaviour exist; the named handoff remains.
- Contract only: models validate supplied evidence but do not perform the action.
- Pending: no equivalent SDK service has been selected or completed.
- External service: SDK may integrate with the service but does not operate it.

The source statuses (29 implemented, 18 preview-only, two deferred, and three
out of scope) describe the source repository. For example, source installation
does not make SDK installation executable, and source schema-registry deferral
does not describe the implemented SDK SchemaRegistry.

## Capability disposition

| Source capability id | SDK state | SDK entrypoint, proof and limitation | Remaining action |
| --- | --- | --- | --- |
| `authoring` | Partial | `build_skill_ir` and intent-aware `check-quality` checking; [quality proof](../tests/test_quality_workflow.py). Neither edits source. | S2: create a minimal plugin before release-bound checks; preserve standalone intake source. |
| `check` | Partial | `check_local_quality` / `check-quality` join ordered local gates; [installed proof](../tests/installed_quality_workflow_smoke.py). No execution or promotion clearance. | S2/S3: close remaining semantic and security handoffs without duplicating local stages. |
| `manifest_schema` | Implemented | `PackageManifest`; [manifest tests](../tests/test_package_receipts.py). Structural content contract, not an archive. | Retain schema and semantic compatibility proof. |
| `receipt_schema` | Implemented | Versioned models and receipt parsing; [receipt tests](../tests/test_package_receipts.py). A receipt proves only its lane. | Retain family/version and rejection tests. |
| `risk_classification` | Contract only | `RiskClassification`; [risk tests](../tests/test_risk_security.py). Sensors remain caller supplied. | S3: select trusted risk assessment inputs and prove their binding. |
| `risk_mode_taxonomy` | Partial | `CapabilitySafetyReview` and six-category checklist; [safety proof](../tests/test_pre_execution_safety.py). Not complete legacy risk-mode parity. | S3: compare remaining taxonomy semantics and explicitly replace or retain them. |
| `package_security_signature` | Partial | `screen_package_security` inspects captured bytes; [screening tests](../tests/test_security_screening.py). Static indicators are not independent scanner or vulnerability proof. | S3: add relevant external scanner/reviewer evidence and validate its limits. |
| `skill_ir` | Implemented | `build_skill_ir` and `read_frontmatter`; [package parsing proof](../tests/test_skill_package_validation.py). Portable representation used by validation, not authoring or execution. | Retain parsing and identity proof. |
| `package_identity` | Implemented | `build_skill_package` and `validate_plugin_package`; [plugin identity proof](../tests/test_plugin_package.py). Complete-plugin bytes and a separate mode ledger are bound; capture is not publication. | S2/S5: compose release checks and emitted archives under the captured plugin identity and modes. |
| `install_preview` | Partial | `plan_runtime_install`; [planning proof](../tests/test_installation_planning.py). No host apply. | S5: implement selected host application and failure recovery. |
| `skill_intake` | Partial | `intake_skill_package` handles directory skills; `validate_plugin_package` inspects root-manifest plugins; [plugin proof](../tests/test_plugin_package.py). Neither silently wraps source or clears managed release. | S2/S5: explicitly normalise standalone inputs to a separate plugin candidate without rewriting source. |
| `skill_intake_review` | Partial | Intake rights/owner checks plus `assess_content_review`; [review proof](../tests/test_content_review.py). Claims and semantic quality are not independently authenticated. | S2/S3: verify external provenance and reviewer quality for adoption. |
| `lockfile_preview` | Partial | `RuntimeLock` and `InstallPlan`; [planning proof](../tests/test_installation_planning.py). No applied lock/runtime state. | S5: join plans to observed installation and rollback. |
| `real_install` | Pending | No host apply service; `InstallationResult` is [supplied evidence](../tests/test_runtime_execution_evidence.py). | S5: implement a bounded install adapter with exact-version readback. |
| `project_conformance` | Pending | `project` is a [CLI boundary](cli.md), not a conformance service. | S6: select conformance checks or record a reviewed retirement decision. |
| `sdk_lenses` | Pending | No SDK lens-selection service; [task policy](projects/sdk-workflow/tasks.md#lens-application) names human-selected lenses. | S2: decide whether portable lens selection adds a required consumer capability. |
| `review_plan` | Partial | Content assessments and capability checklists retain review scope; [content proof](../tests/test_content_review.py). No general legacy review-plan orchestration. | S2/S3: map remaining planning semantics before selecting a replacement. |
| `review_handoff` | Partial | `ContentReviewInput` captures callback input; [execution proof](../tests/test_content_review_execution.py). Safety/judge handoffs remain distinct; no complete external handoff. | S3/S4: bind supported external reviewer/judge adapters to their inputs. |
| `review_execution` | Partial | `execute_content_review` runs a bounded offline callback; [installed proof](../tests/installed_content_review_smoke.py). `review-content` only validates supplied assessments; no authenticated live reviewer quality or full parity. | S2/S3: prove a supported live reviewer lane and remaining legacy behaviour. |
| `review_verification` | Partial | `assess_content_review` and `assess_pre_execution_safety`; [safety proof](../tests/test_pre_execution_safety.py). Bindings/freshness do not authenticate reviewers. | S3: verify independent review provenance and scope. |
| `determinism_audit` | Pending | No general audit route in the [API](api.md); deterministic evaluation is narrower. | S6: define a necessary audit consumer or explicitly retire the legacy facade. |
| `trust_store` | Pending | No trust-ledger service in the [API](api.md); evidence validation is not trusted issuer selection. | S3: decide trust ownership and select an adapter or reviewed retirement. |
| `observability_feedback` | Partial | `execute_matched_regression` and `execute_matched_cloud_regression` retain explicit correction/rerun evidence; [feedback proof](../tests/test_matched_feedback.py). Automatic regression capture is not implemented. | S6: prove external feedback, retained regressions and consumer cutover. |
| `refs_ingestion` | Partial | `assess_content_review` inventories captured references; [review proof](../tests/test_content_review.py). No external reference retrieval or comprehensive accuracy review. | S2: decide external ingestion needs and retain explicit content-review gaps. |
| `evals` | Partial | Selected-case, observed calibration and matched plugin services exist; [installed matched proof](../tests/installed_matched_smoke.py). Supplied-offline CLI results do not prove fresh model quality. | S3/S4: repair stateful calibration lifetime and prove supported live adapters separately. |
| `eval_profiles` | Partial | Matched descriptors and `prepare_matched_cloud_handoff` bind same-lane settings and local lineage; [handoff proof](../tests/test_matched_handoff.py). Named TOML profiles are not integrated. | S4: implement explicit oss-local/oss-cloud profile selection and secret-free binding. |
| `ab_rubric` | Partial | `MatchedComparisonPlan` and calibration bind rubric and decision limits; [comparison proof](../tests/test_matched_comparison.py). Offline conformance is not live judge quality. | S4: prove selected profile and judge quality with authorised execution. |
| `ab_preview` | Partial | `assess_matched_pair` / `eval matched-assessment` assess supplied pair evidence; [CLI proof](../tests/test_matched_cli.py). Not a complete legacy preview-parity claim. | S4: disposition remaining legacy preview semantics and real-adapter proof. |
| `ab_plan` | Partial | `MatchedComparisonPlan` binds plugin candidates, ten cases, model/settings, rubric and budgets; [scope proof](../tests/test_matched_plugin_scope.py). Named host profiles remain absent. | S4: bind explicit profiles and retain rejection/recovery proof. |
| `ab_run` | Partial | `execute_matched_lane` / `eval matched-local` orchestrate plugin-bound trials; [installed proof](../tests/installed_matched_smoke.py). CLI execution uses supplied offline inputs. | S4: integrate selected model profiles and separately prove live quality. |
| `ab_judge_preview` | Partial | Matched calibration and trial inputs bind child/assertion context; [calibration proof](../tests/test_matched_plugin_calibration.py). This does not establish all legacy blinded-preview semantics. | S4: assess remaining blinded-pair parity before replacement or retirement. |
| `ab_judge_score` | Partial | `assess_matched_pair` and `execute_matched_lane` produce bound same-lane decisions; [execution proof](../tests/test_matched_execution.py). Unchanged/inconclusive outcomes do not promote candidates. | S4: prove real judge calibration and variability under supported profiles. |
| `scenario_quality_gate` | Implemented | `assess_scenario_quality` / `eval scenario-quality`; [quality proof](../tests/test_scenario_quality.py). Definition quality is not executed behaviour. | Retain v1 compatibility and ten-active-case v2 proof. |
| `package_verify` | Implemented | `validate_skill_package` / `validate`; [validation proof](../tests/test_skill_package_validation.py). Structural validation is not semantic or icon approval. | S2: retain content-review/coverage evidence; add candidate-bound icon approval, rights and destination file checks. |
| `signing` | Pending | Native Git signing is [delivery governance](../CONTRIBUTING.md), not package signing. | S5: decide package-signature requirements and adapter or explicit retirement. |
| `sandbox` | Partial | Bounded callback workers; [review execution tests](../tests/test_content_review_execution.py). Deadline isolation is not a security sandbox. | S3/S4: select host isolation and prove containment for supported adapters. |
| `security_adapter` | Partial | `screen_package_security` plus guarded selected-case execution; [installed safety proof](../tests/installed_pre_execution_smoke.py). No external scanner process or independent security review. | S3: integrate applicable trusted scanners/reviewers and baseline-to-candidate permission assessment; require renewed authority for expansion. |
| `static_docs` | Pending | Maintained [API](api.md)/[CLI](cli.md) documentation exists; no legacy static projection service. | S6: retain maintained documentation or justify a generated projection consumer. |
| `capability_evidence` | Partial | `SchemaRegistry` and bound results; [core tests](../tests/test_core_contracts.py). No complete legacy capability verifier. | S6: map consumer evidence requirements and explicitly replace remaining checks. |
| `skill_explorer` | Pending | No explorer route in the [CLI](cli.md). | S6: make an explicit explorer product or retirement decision. |
| `schema_registry` | Implemented | `SchemaRegistry`; [core proof](../tests/test_core_contracts.py). Semantic validation is not live execution. | Retain unknown-family rejection and registered semantic checks. |
| `registry` | External service | Registry identity/preparation [contracts](../tests/test_registry_contracts.py); SDK does not operate a catalogue or registry. | S5: prove initial private Tessl adapter/readback, retain independent SDK artifacts, and gate any future backend-default change on dual-destination proof. |
| `local_plugin_readiness` | Partial | Discovery/activation [evidence contracts](../tests/test_runtime_execution_evidence.py); no observing adapter. | S5: observe complete-plugin display and direct/indirect/incomplete/unrelated activation, including overlapping skills, on the selected host. |
| `sdk_plugin_lifecycle` | Partial | `validate-plugin` and `--verify-evidence` inspect complete root-manifest plugins and freshly compare supplied envelopes; [source verification proof](../tests/test_plugin_evidence.py). No release, installation or publication approval. | S2/S5: compose presentation, evaluation, exports and delivery under accepted capture; prove each later lane separately. |
| `remote_marketplace` | External service | [Registry ownership boundary](workflow.md#registry-transition), not an SDK-operated marketplace or independent distribution proof. | S6: retire marketplace operation from SDK ownership; any separately authorised service consumes SDK contracts and proves its own distribution. |
| `publish` | Pending | Registry preparation [API proof](../tests/test_registry_preparation.py); no publication adapter. | S5: prove private Tessl publication/readback, interrupted/repeated request idempotency and uncertain-outcome reconciliation before retry; do not assume arbitrary endpoint compatibility. |
| `rollback` | Partial | Rollback [evidence contracts](../tests/test_runtime_execution_evidence.py); no executing adapter. | S5: implement restoration and verify previous lock/runtime after failed mutation. |
| `uninstall` | Pending | No uninstall executor in the [API](api.md). | S5: select a bounded host removal contract or explicit retirement. |
| `compiled_package_pipeline` | Partial | Build and ZIP verification [proof](../tests/test_package_archive_verification.py); no accepted archive emission. | S5: prove complete plugin archive round-trip, artwork inclusion, private-material exclusion and versioned portable/Tessl export relationship with separate digests; block unsupported resource/mode loss. |
| `emitters` | Pending | No general emitter service in the [API](api.md). | S5: implement necessary adapter exports from one canonical content source; explicitly retire unused legacy outputs. |
| `ci_adoption_gates` | Partial | Repository [validation wrapper](../scripts/validate-repository.sh); not a package adoption gate. | S6: compose package admission evidence for the actual CI consumer. |
| `package_hardening` | Implemented | `harden_skill_package`; [hardening proof](../tests/test_package_hardening.py). No full-plugin or live security clearance. | S5: compose the CLI and archive handoff while retaining separate security evidence. |

## Migration proof

Disposition of these 52 capability ids is not a complete module, symbol or
production-caller migration audit. [SDK-1](product-acceptance.md#acceptance-matrix)
retains that exact-revision obligation, and SDK-8 retains released-consumer and
legacy-retirement proof. Do not close either from this table alone.

Before porting each executable behaviour, inspect its source implementation,
accepted/rejected neighbours, actual consumer, and failure semantics. Run
source and destination public entrypoints on portable equivalent fixtures when
possible. Record blocked source execution and deliberate parity differences.
Retain SDK tests and compatibility notes; do not copy private source or host
paths. Follow [workflow migration proof](compatibility.md#workflow-migration-proof).

Do not recreate a legacy facade merely to retain its name. Reuse SDK validation,
evaluation, provider, packaging, and lifecycle services; select a new interface
only when it simplifies a named consumer. Clean-room package tests must prove
normal SDK paths work without either sibling checkout. Foundry handoff and
Agent-Skills consumer retirement retain separate evidence.
