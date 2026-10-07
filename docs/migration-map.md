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

| Source capability id | SDK state | Current owner or gap | Next slice |
| --- | --- | --- | --- |
| `authoring` | Partial | SkillIR and target ownership; authoring route pending | S2 |
| `check` | Partial | check-local joins local read-only stages | S2/S3 |
| `manifest_schema` | Implemented | PackageManifest; schema generation and tests | Retain |
| `receipt_schema` | Implemented | Versioned receipt models and parsing | Retain |
| `risk_classification` | Contract only | RiskClassification; caller-supplied sensors | S3 |
| `risk_mode_taxonomy` | Pending | Applicable threat selection has no SDK service | S3 |
| `package_security_signature` | Partial | Safety evidence binds candidate/reviewer; no scanner | S3 |
| `skill_ir` | Implemented | build_skill_ir and read_frontmatter | Retain |
| `package_identity` | Implemented | build_skill_package; candidate/manifest binding | S5 archive emission |
| `install_preview` | Partial | plan_runtime_install API; no apply | S5 |
| `skill_intake` | Partial | Directory intake; archive composition pending | S2/S5 |
| `skill_intake_review` | Partial | Caller-supplied rights and owner checks; semantic review pending | S2/S3 |
| `lockfile_preview` | Partial | RuntimeLock and InstallPlan | S5 |
| `real_install` | Pending | InstallationResult contracts; no host apply | S5 |
| `project_conformance` | Pending | project CLI discovery boundary | S6 |
| `sdk_lenses` | Pending | User-selected lenses; no SDK selection service | S2 |
| `review_plan` | Pending | No portable review-plan service | S2/S3 |
| `review_handoff` | Partial | Safety/judge evidence contracts; full handoff pending | S3/S4 |
| `review_execution` | Pending | No SDK reviewer orchestration | S3 |
| `review_verification` | Partial | Candidate-bound safety evidence validation | S3 |
| `determinism_audit` | Pending | No audit service | S6 disposition |
| `trust_store` | Pending | No trust ledger service | S3 disposition |
| `observability_feedback` | Pending | No feedback/regression composition | S6 |
| `refs_ingestion` | Pending | Captured reference files; no ingestion service | S2 disposition |
| `evals` | Partial | Deterministic and selected-case services | S3/S4 |
| `eval_profiles` | Partial | Injected provider descriptors; host profile integration pending | S4 |
| `ab_rubric` | Partial | Scorer/judge contracts; matched scorecard pending | S4 |
| `ab_preview` | Pending | No matched A/B CLI route | S4 |
| `ab_plan` | Pending | No matched experiment plan service | S4 |
| `ab_run` | Pending | Single-case execution API; matched run pending | S4 |
| `ab_judge_preview` | Partial | SelectedCaseJudgeInput; pair preparation pending | S4 |
| `ab_judge_score` | Partial | Injected selected-case judge API; matched decision pending | S4 |
| `scenario_quality_gate` | Implemented | assess_scenario_quality and eval scenario-quality | Retain |
| `package_verify` | Implemented | validate_skill_package and validate CLI | S2 semantic coverage |
| `signing` | Pending | Native Git signing is delivery; package signing adapter pending | S5 disposition |
| `sandbox` | Partial | Bounded injected adapters; no host sandbox runner | S3/S4 |
| `security_adapter` | Pending | Safety evidence accepts reviewers; no detection/execution adapter | S3 |
| `static_docs` | Pending | SDK API/CLI docs; no legacy static projection service | S6 disposition |
| `capability_evidence` | Partial | Typed schemas and bindings; no legacy verifier service | S1/S6 |
| `skill_explorer` | Pending | No explorer product selected | S6 disposition |
| `schema_registry` | Implemented | SchemaRegistry with semantic validation | Retain |
| `registry` | External service | SDK owns adapters; does not operate registry service | S5 |
| `local_plugin_readiness` | Partial | Runtime observation contracts; no discovery/activation adapter | S5 |
| `sdk_plugin_lifecycle` | Partial | Skill intake/build; complete native plugin pipeline pending | S2/S5 |
| `remote_marketplace` | External service | Marketplace operation requires a separate product decision | S6 disposition |
| `publish` | Pending | Registry preparation API; no publication adapter | S5 |
| `rollback` | Partial | Rollback evidence contracts; no rollback execution | S5 |
| `uninstall` | Pending | No uninstall execution adapter | S5 disposition |
| `compiled_package_pipeline` | Partial | Manifest build and ZIP verification; archive emission pending | S5 |
| `emitters` | Pending | No general emitter service selected | S5 disposition |
| `ci_adoption_gates` | Partial | SDK CI checks repository; package adoption gate pending | S6 |
| `package_hardening` | Implemented | harden_skill_package API | S5 CLI composition |

## Migration proof

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
