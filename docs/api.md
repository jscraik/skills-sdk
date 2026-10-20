# Python API

The public API is the typed contract layer under `skills_sdk`. The top-level
package exports the inventory, risk, evaluation, and provider execution
contracts listed in its `__all__`. Import family-specific contracts such as
`PackageCandidateIdentity`, `PackageManifest`, `PackageReceipt`,
`PackageReceiptV2`, and
`PackageHardeningReceipt` from
`skills_sdk.models` (or their submodules), as shown below.

Start with [read-only intake](#read-only-intake) or
[schema validation](#schema-validation). These entries describe accepted SDK
services, not a published release or live-provider clearance. Issue #92's
whole-plugin quality composition merged via PR #93 at `93526d6`; unmerged
native calibration, matched and quality work remains in its owning preserved
branch. The optional judge adapter below is a separate delivery candidate until
its PR is merged; it does not admit those broader families.
See the [delivery ledger](projects/sdk-workflow/tasks.md#accepted-delivery-ledger).

Contents:

- [Plugin presentation assessment](#plugin-presentation-assessment)
- [Whole-plugin quality composition](#whole-plugin-quality-composition)
- [Portable plugin validation](#portable-plugin-validation)
- [Contract families](#contract-families)
- [Matched whole-plugin evaluation](#matched-whole-plugin-evaluation)
- [Read-only intake](#read-only-intake)
- [Explicit standalone-skill plugin preparation](#explicit-standalone-skill-plugin-preparation)
- [Schema validation](#schema-validation)

## Plugin presentation assessment

Accepted PR #60 adds the bounded S2 presentation assessment
`check_plugin_presentation(plugin_root, *, source_revision, request)` in
`skills_sdk.validation`, returning `PluginPresentationCheck`. Supply a `Path`
and dictionary or canonical `PluginPresentationRequest`. Four additive families
carry assertions and results: `plugin-image-approval/v1`,
`plugin-presentation-copy-approval/v1`, `plugin-presentation-request/v1` and
`plugin-presentation-check/v1`. Models/schemas check supplied consistency;
only the service freshly captures actual complete-plugin bytes and modes.

Requests bind candidate, modes, exactly one approval per unique referenced image
and copy approval for the selected settings digest. Approvals retain public-safe
evidence references/digests and supplied rights/professional-quality assertions.
The fixed `openai-icons-2026-10-08/v1` profile requires `interface.logo` and
`composerIcon`; dark variants and up to twenty unique raster screenshots are
optional. References use explicit `./` paths to captured ordinary files.
Optional `onboardingSkill` names a validated direct child skill's `SKILL.md`.

Images are nonempty and at most five MiB. Icons are square and at least 48 by 48;
raster dimensions cannot exceed 4096. Screenshots may be non-square. PNG, JPEG
and WebP match their extension and decode completely as static images. Optional
`skills-sdk[images]` accepts Pillow `>=12.3.0,<13`; the repository lockfile retains
12.3.0 for reproducible validation. Missing decoding support returns
`image_decoder_unavailable`. Bounded static SVG geometry is not rendering or
full SVG conformance; active/linked content and SVG screenshots block. Base
help does not import Pillow. Icons additionally require supplied recognisability,
small-size, light/dark and distinctiveness assertions; screenshots omit these.

The service is read-only and checks source stability after inspection. Valid
byte or mode drift rejects retained approvals; corrected source or renewed
candidate-bound approval recovers. Raw settings and private copy are not echoed.
Rights, visual judgement and copy accuracy remain supplied claims, not independent
review. Mutation, execution, release, archive, publication and host-display
authority remain false. A pass neither normalises standalone input nor prepares
a release archive. Delivery state is in the [task record](projects/sdk-workflow/tasks.md).

## Whole-plugin quality composition

Issue #92: PR #93 merged at `93526d6`; the asynchronous
`await check_plugin_quality(plugin_root, request, *, assessments=None, presentation_request=None)`
in `skills_sdk.evaluation` resolves to `PluginQualityResult`; calling it without
`await` returns a coroutine, not a receipt. Omitting assessments uses an empty
mapping and retains first-stop child semantics. If the earlier child gates pass,
missing supplied content review produces `plugin_quality_child_blocked`.
With passing children, an omitted presentation
request produces `plugin_quality_presentation_missing`. Two additive families carry the contract:
`plugin-quality-request/v1` and `plugin-quality/v1`.

Each supplied-only workflow runs sequentially in one worker, keeping filesystem
scans and child composition off the caller's event loop. Cancellation releases
the caller, but cannot forcibly stop the bounded read-only worker. It may finish
its checks; cancellation grants no mutation, provider or release authority.
Across event loops and callers, at most two plugin-quality operations are
admitted per process. Excess calls return `plugin_quality_capacity_exceeded`
without retaining input or submitting work; retry after an admitted operation
finishes. Cancellation keeps a running worker's slot occupied until it finishes.
This bound does not govern work in other processes or memory callers retain.

Whole-plugin envelopes check every retained JSON key and string with the SDK's
existing public-text redaction checks. This includes request intake and policy
paths, coverage identifiers and prose, capture findings, scenario case identifiers,
scorer and calibration metadata, and presentation evidence. Invalid requests
return `plugin_quality_request_invalid` without retaining that text in JSON.
This is semantic model/service validation, beyond the structural JSON Schema;
it detects supported credential and machine-path patterns, not every secret.

Raw API requests and presentation requests each have a 1 MiB compact UTF-8 JSON
budget, checked before recursive normalisation or downstream services. This
matches the CLI's input-file ceiling; whitespace in CLI files still counts
towards its file limit. Supplied result envelopes have a 64 MiB compact JSON
budget. These composition limits reject oversized inputs, including otherwise
valid standalone receipts, without changing those standalone contracts. The
budget walker charges container sizes and visits strings in bounded chunks;
it rejects noncanonical values and nesting beyond 64 levels without serialising
the entire envelope. Unsafe or oversized captured evidence returns an empty
`plugin_quality_input_invalid` blocker rather than retaining rejected text.

The request binds the root candidate identity, mode manifest and one explicit
`LocalCheckRequestV2` per direct child skill, sorted and unique, all at the root
source revision. Child-path uniqueness and ordering are semantic constraints
enforced by the SDK models and `SchemaRegistry`, beyond structural JSON Schema.
Schema-only validation does not prove these constraints.
Captured manifest descriptions and versions, retained child identity versions,
and presentation image or copy evidence references must pass the composition's
existing public-text checks for credential-shaped text and machine paths.
Unsafe retained metadata returns `plugin_quality_input_invalid` without retaining
the evidence. These pattern checks do not guarantee detection of every secret;
standalone plugin and presentation contracts remain unchanged. Raw or copied
request and result envelopes reject child counts above 128 before recursive
normalisation; structural field limits remain in place too.
The service freshly captures the root, composes
`check_local_quality` for each child in order, then `check_plugin_presentation`,
and recaptures the root before success. It stops at the first blocker and retains
the partial evidence. Changed bytes, modes, settings or images, missing or
unrequested assessments, and a missing presentation request block.

The supported profile is skill-only, create or external check, with supplied
content review. Update intent and `mcp.json` are rejected. Other ordinary plugin
files are captured in the root candidate, retaining paths, content digests,
byte sizes and modes rather than raw file contents, but
receive no quality assessment beyond the presentation images that settings
reference. Directories are checked only transiently during each capture; an
empty directory's presence or mode is not retained candidate identity.
`assessments` must be a concrete `dict`, not another `Mapping`, keyed by requested
child path. Its combined supplied evidence is bounded by
`PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES` (32 MiB of compact UTF-8 JSON for the
whole mapping, including paths and separators, checked before any child runs); an
oversized, cyclic or non-dict bundle returns `plugin_quality_assessments_invalid`.
CLI request, assessment and presentation files require an object root. Other
roots and empty inputs return `plugin_quality_input_invalid` with exit status 2
before JSON decoding or service execution. Leading JSON whitespace is accepted;
valid objects retain nested arrays and ordinary grammar/duplicate-member checks.
This avoids decoding an already invalid root, not the bounded input-text read or
every allocation within an admitted object. Direct API blocker codes are unchanged.
CLI JSON decoding also checks nesting at 64 levels and a 4,194,304-node
structural budget before materialisation. This retains admission of the tested
four-child compact assessment bundle below 32 MiB; long strings use constant
scanner state. These resource checks do not replace complete JSON grammar,
duplicate-member rejection or the per-assessment eight-MiB contract.
The service also checks the complete normalized mapping of valid assessments,
including model defaults, before child execution. Malformed individual evidence
still stops at its existing child review stage rather than escaping as an exception.
The same budget is reapplied to the normalized assessments retained in a supplied
`plugin-quality/v1` result, so a forged envelope cannot exceed what the service
admits. Whitespace-padded `package_id`, `source_revision` and digest strings are
rejected before normalization in both requests and results. A
`plugin_quality_source_changed` result may retain an unresolved blocked recapture
or one that differs in content or modes, but a resolved recapture must keep the
selected `package_id` and `source_revision`.
Its retained passed presentation must remain consistent with the initial capture's
settings and image bytes even when the final capture changes.
A successful run recaptures the root several times through the accepted validation
and presentation services to bind source stability and image bytes. For a
maximum-size plugin that is a proportionate input cost, not a measured latency or
memory figure. Sharing one capture needs a snapshot API in those services and is
follow-up scope.
`mutation_performed`, `evaluation_executed`, `execution_authorized` and
`release_ready` are always `false`. A pass is local composition evidence only: it
is not independent artwork approval, release clearance, installation or
runtime proof. Models and schemas check supplied consistency; only the service
recaptures source and derives presentation image references from the captured
settings. The model retains no raw settings, so it cannot prove that a supplied
image set equals the declared references; it checks retained image paths, digests
and sizes against the initial capture. The packaged success schema requires every
evidence member and at least one child; blocker codes, retained stages and the
cross-object comparisons stay model and registry checks.

## Portable plugin validation

The additive `validate_plugin_package` service in `skills_sdk.validation` captures
a root-manifest plugin without executing it or changing its source. Supply a
`Path`, a forty-character source revision and optional `PluginValidationPolicy`
from `skills_sdk.models`. The policy can require nonempty version and description
metadata; neither is a mandatory base-format field. This inspection capability
was accepted in PR #52 and is recorded in the
[task record](projects/sdk-workflow/tasks.md).

The `plugin-package-validation/v1` result retains a `PortablePluginManifest`
projection, all captured file hashes/sizes/ordinary permissions, a separate mode
digest, and each immediate `skills/<name>/SKILL.md` subtree's existing
`SkillPackageValidation`. Invalid child findings remain visible and block the
plugin; deeper nested skills are resources, not automatically discovered skills.
Discovery requires the literal filename `SKILL.md`; lookalikes such as
`SKILL-md` and `SKILLXmd` do not create children or duplicate a discovered child.
An exact entrypoint that is a directory blocks. Retained child file roles must
match their captured relative paths, preserving the standalone role semantics.
Existing standalone APIs do not auto-detect or wrap plugins.

Root `plugin.json` supplies the canonical name and declares
`https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`. Names need not match
the source directory. To preserve the frozen SDK identifier grammar, every
plugin candidate uses `plugin-` followed by the SHA-256 of its exact UTF-8
manifest name as `package_id`. The original name is retained separately.
Byte-content identity covers sorted paths and hashes, including unused overlays,
shared assets and integration files. Permission changes affect
`mode_manifest_sha256`, not the historical content digest; compare both evidence
lanes when consuming a capture.

Unknown root fields and non-object `extensions` produce warning findings and
are ignored. The unknown-field diagnostic lists all unknown keys in sorted,
JSON-escaped form, including misspellings, without their values. It uses one
aggregated warning within the existing metadata parsing budget rather than one
finding per key. Other known fields with wrong types block. The result records which
OpenAI settings object is selected and its canonical JSON digest: an inline
`extensions.com.openai` object replaces the complete compatibility overlay;
otherwise `.codex-plugin/plugin.json`, if present, supplies the object. It never
overrides root identity or component discovery. Settings values are not echoed
or interpreted as permission, artwork or host-compatibility approval.

Capture rejects symbolic links, unsafe resources and special files. It permits
at most 1,024 files, 2,048 total entries, 64 nested directories, 16 MiB per file
and 64 MiB total file bytes; metadata JSON is limited to one MiB, 32 nested
containers and 65,536 inspected values. At most 128 direct skills are assessed.
Parsing uses captured bytes; a second whole capture rejects observed content,
permission or directory changes. These are bounded observations, not a promise
of a filesystem-wide atomic snapshot or protection after validation returns.

`pass` establishes this structural capture only. MCP configuration bytes are
bound but transport validity is explicitly unassessed. Icon decoding/approval,
rights/admission, security, evaluation, wrapping, archive emission, export,
publication and installation remain separate gates. `mutation_performed`,
`execution_authorized` and `release_ready` remain false. Validate the envelope
through `SchemaRegistry().validate("plugin-package-validation.v1", payload)`;
semantic binding checks supplement JSON Schema. This is not a generic receipt
accepted by `parse_receipt`.
The hash-only envelope model and SchemaRegistry check supplied consistency;
they do not prove that selected-settings digests or projected metadata were
derived from actual source bytes. They cannot authenticate source provenance or
reconstruct unavailable bytes. Raw settings are never echoed.

The accepted portable-plugin route includes
`verify_plugin_package_validation(plugin_root, validation, *, source_revision, policy=None)`
in `skills_sdk.validation`. It normalises the supplied full envelope and compares
it with fresh no-follow `validate_plugin_package` capture using the caller's
revision and policy. Invalid, mismatched, stale or unreadable source/evidence
returns a typed blocked result; corrected evidence can recover. Neither a
match nor verification grants execution, permissions or release authority.
Keep any serialised evidence file outside the plugin root; including it changes
the captured candidate. Supply the original capture's explicit policy.
Blocked results retain a valid caller policy even when evidence or the revision
is invalid. Invalid caller policies return `plugin_input_invalid` before source
capture; they cannot override policy through the supplied envelope.
Child candidate IDs remain bound to their directory names even when malformed
skill metadata blocks identity discovery. Invalid directory names retain the
standalone validator's deterministic fallback ID; supplied IDs cannot replace it.
Nested child file sizes must be integers without string or boolean coercion;
this plugin-envelope boundary does not change standalone manifest parsing.
Retained paths must preserve component-kind blockers they prove: a root `skills`
file or descendants beneath file-only `mcp.json` or skill-entrypoint locations.
Empty directory kinds are not retained and still require fresh source assessment.
Raw and copied envelope identities, child names, file hashes and finding codes reject padding
before shared models can trim it. Already-normalised shared objects expose only
their canonical values, not their original input history. Versions and descriptions
retain their existing whitespace semantics. A captured settings overlay must be
selected or superseded by inline settings. Retained MCP files require the explicit
unassessed warning; blocked children and missing required version or description
metadata retain their specific blocker findings even when other blockers exist.
Capture rejects known non-regular files from no-follow metadata before opening
them. Post-open checks remain necessary for races; capture is not an atomic snapshot.
This verifier was accepted in PR #52. Its structural source comparison does not
establish the separate matched evaluation or release gates described below.

The [plugin-first, registry-independent target](workflow.md#managed-release-format)
does not change the implemented APIs below. Standalone-skill validation remains
supported; its evidence is not automatically whole-plugin clearance. Registry
preparation remains local contract composition, not a Tessl transport or a
generic registry client. New plugin and import/export boundaries require the
[explicit compatibility proof](compatibility.md#plugin-first-and-registry-independent-migration-target)
before they are documented as available here.

## Contract families

**Supplied content review:** `assess_content_review` from `skills_sdk.validation`
checks a `ContentReviewAssessment` against the safely captured current package.
Import that model and `ContentReviewResult` from `skills_sdk.models`. The supplied
review covers description and progressive disclosure in `SKILL.md`, plus every
actual file under `references/`. Each disposition is `clear`, `finding`, or an
owned `gap`. Completed dispositions require declared, digest-bound source
evidence for their own path; evidence for another file cannot satisfy that
disposition. Missing coverage, stale candidate identity, wrong source digests,
malformed assessment, findings and gaps block. Binary references are included
in the review inventory without being interpreted as text.

This service verifies supplied reviewer metadata and source binding. It does
not independently establish accuracy, relevance, freshness, or an exhaustive
gap inventory; `semantic_review_executed` and `promotion_authorized` remain
false. It performs no reviewer or provider call. Source evidence digests are
not proof that an external reviewer actually assessed those bytes. Actual
review adapter execution uses the separate `execute_content_review` API from
`skills_sdk.evaluation`. Supply a trusted caller-owned `OfflineContentReviewAdapter`
with a secret-free local reviewer identity and an asynchronous `review` method.
The adapter receives a `ContentReviewInput` containing candidate identity and
private immutable source bytes. Treat those bytes as untrusted data, not host
instructions. The SDK verifies the returned assessment and detects candidate
drift, invalid results, reviewer mismatch and callback failure. The callback has
a thirty-second deadline enforced by the parent outside the callback's event
loop. A separate thirty-second startup deadline covers child imports and
adapter metadata. An eight-MiB source limit applies after safe capture and
before invocation. Caller cancellation stops the SDK-owned worker and propagates
cancellation to the caller. Cleanup allows at most 250 milliseconds of process
joins before returning; it does not wait for cooperative callback cancellation.

`ContentReviewExecutionResult` records the observed callback invocation and
returned assessment digest. It does not establish general semantic accuracy,
authenticate an external reviewer, or grant promotion. The host owns adapter
trust, sandboxing and side effects. Execution uses Python's `spawn` context,
not `fork`: supply an importable, safely pickleable adapter and protect script
entrypoints with `if __name__ == "__main__"`. Adapter transfer occurs before
the startup timer and is trusted caller code, not a bounded untrusted ingress
operation. Daemon process contexts cannot spawn this worker. Unsupported
transfer or daemon contexts return `unsupported_content_review_isolation`
without invoking the callback. Adapter state changes remain in the child, not
the caller's object. Worker termination does not undo filesystem or other
external side effects and does not guarantee callback `finally` blocks run.
This is deadline isolation, not a security sandbox. The input limit is not a
preallocation memory budget. The SDK
does not load arbitrary plugins, retrieve credentials, or select a paid
provider. The `review-content` CLI only checks supplied evidence; it does not
dynamically invoke this adapter.

**Declared scenario coverage:** `assess_scenario_coverage` from
`skills_sdk.evaluation` audits a `ScenarioCoveragePlan` against the package's
checked ten-case active set. Import the plan and `ScenarioCoverageResult` from
`skills_sdk.models`. A plan binds the exact candidate and scenario-set id,
declares `claims` with `id` and `statement`, maps each claim exactly once to
`case_ids` or `gap_ids`, and declares each gap's `id`, `reason` and `owner`.
Unknown cases, unmapped claims, duplicate ids, stale candidates, or unowned gaps
block. An audit may pass with named gaps while `coverage_complete` remains false.
Neither result authorises promotion or proves that a mapped case actually tests
its claim. This checks the supplied inventory; it does not discover every claim,
review semantic quality, execute cases, or calibrate a judge.

`SkillValidationPolicy` from `skills_sdk.validation` selects optional package
requirements. `required_files=("references/README.md",)` requires those exact
portable relative paths to be readable regular files in the captured manifest.
`check_reference_content=True` checks UTF-8 and nonempty content for Markdown,
text, JSON and YAML references, plus JSON/YAML syntax. Binary references remain
valid resources. These checks reuse the bytes that bind the candidate; they
do not follow symlinks or reread files outside the package. Recognized Markdown
suffixes are `.md`, `.markdown`, `.mdown`, `.mkd`, `.mkdn`, `.mdwn`, `.mdtxt` and
`.mdtext`; suffix matching is case-insensitive. A leading UTF-8 BOM is ignored
when checking textual content. Each textual reference is limited to eight MiB
before decoding or parsing; larger inputs return `reference_content_limit`.
This bounds the syntax parser input, not the earlier package byte capture or
total host memory usage.
JSON rejects non-standard constants such as `NaN` and `Infinity`. YAML syntax
validation accepts application-defined tags and multiple documents without
constructing tagged objects; it does not establish application validity or safety.
Incremental YAML parsing stops above 128 nested collections or 100,000 parser
events and returns `reference_content_limit`. These work budgets are not a
wall-clock deadline or a total host memory guarantee.

Apply the policy to `validate_skill_package`, `build_skill_package`, or
`intake_skill_package`. Defaults are unchanged. Invalid applicable-file policy
returns `invalid_validation_policy`; missing required files and invalid textual
references return finding-specific blockers. These are deterministic checks,
not proof of accuracy, relevance, link freshness, semantic description quality,
or completed reviewer execution.

- **Archive verification:** import `verify_package_archive` from
  `skills_sdk.packaging`, and `PackageArchiveVerificationPolicy` and
  `PackageArchiveVerificationReceipt` from `skills_sdk.models`.
  `verify_package_archive(path, expected_archive_sha256=..., expected_package_receipt=...)`
  reads a bounded ZIP snapshot without extraction or mutation and returns
  `package-archive-verification/v1` with `pass` or a typed `blocked` result.
  A pass binds observed payload sizes and digests to the manifest and candidate;
  optional expectations compare the archive digest and a built package receipt v2.
  Only stored and DEFLATE entries are supported. Unsupported compression and
  malformed ZIP streams return `archive_invalid_zip` before unsafe expansion.
  Use `SchemaRegistry().validate("package-archive-verification.v1", payload)`
  for structural and semantic validation. This additive result intentionally
  remains outside `parse_receipt`, which returns `unsupported_receipt_family`;
  it does not establish provider, runtime, or publication evidence.

- **Inventory:** `PackageInventory`, `PackageInventoryRecord`,
  `PackageInventoryV2`, `PackageInventoryRecordV2`, `ValueDecision`,
  `ValueDecisionV2`, source provenance, rights, ownership, disposition, and
  mantra assessment.
- **Intake and package identity:** `PackageCandidateIdentity`, `SkillIdentity`,
  `PluginIdentity`, `PackageSource`, `PackageOwner`, `IntakeDecision`, and
  `NormalizedPackage`. Use `intake_skill_package` with a
  `SkillPackageIntakeContext` to structurally validate and normalize a local
  standalone-skill directory. The service derives candidate-bound provenance
  from the validated bytes and preserves the caller's explicit identity,
  provenance, rights, and owner-continuity checks in a
  `SkillPackageIntakeReceipt`. It does not copy source, execute package code,
  access a network, establish ownership or rights truth, or admit a package to
  Foundry. Archive intake remains a separate composition boundary.
- **Explicit standalone-to-plugin preparation:**
  `normalize_standalone_skill_package`, `PluginNormalizationMetadata` and
  `PluginNormalizationReceipt` copy one admitted standalone skill into a new
  plugin candidate, generate caller-supplied root `plugin.json` metadata, then
  freshly validate the whole plugin and bind its one child to the original
  intake identity. Source is not rewritten and an existing destination is never
  replaced. The receipt requires `admit`
  caller-supplied provenance, rights, ownership and continuity checks; those
  assertions are not independently authenticated. This route does not normalize
  updates against an existing plugin baseline, combine multiple skills, assess
  visual approval, build an archive, publish, install or clear release:
  `release_ready` is always `false`. Validate its serialized receipt with
  `SchemaRegistry().validate("plugin-normalization.v1", payload)`.
- **Packaging:** `PackageManifest`, `PackageManifestFile`, `PackageReceipt`,
  `PackageReceiptV2`,
  `PackageHardeningPolicy`, and `PackageHardeningReceipt` with typed blockers,
  explicit warnings, and immutable candidate binding. Use
  `build_skill_package` before `harden_skill_package`; hardening consumes the
  receipt and does not rescan the source filesystem. Builders emit
  `PackageReceiptV2`, which binds `package_digest` to the canonical manifest;
  `PackageReceipt` preserves the historical `package-receipt/v1` contract for
  compatible readers.
- **Evaluation:** `ScenarioSet`, `ScenarioCase`, `ScorerProfile`,
  `ScenarioObservation`, `ScenarioCaseResult`, and `EvaluationReceipt`. Use
  `evaluate_scenario_set` to score externally produced observations with a
  deterministic scorer. The service never executes a prompt, provider, or
  package. Unsupported oracles, incomplete calibration, and mismatched
  candidate identities return typed blockers rather than guessed outcomes.
  The additive v2 family (`ScenarioSetV2`, `ScenarioCaseV2`,
  `ScenarioObservationV2`, `ScenarioCaseResultV2`, and `EvaluationReceiptV2`)
  binds observations and receipts to a hardened, secret-free
  `ProviderIdentityV2` and lets
  `evaluate_scenario_set_v2` decide `exact_match` from expected and observed
  SHA-256 digests only. The v1 symbols and `evaluate_scenario_set` retain their
  historical behavior. `ProviderIdentity` preserves the
  `provider-identity/v1` wire contract; provider-bearing evaluation-v2
  payloads require `provider-identity/v2` and do not reinterpret v1 identities.
  `assess_scenario_quality` is a separate pre-execution service over one
  package-local `references/evals.yaml`; it returns `ScenarioQualityReceipt`
  with the applied release thresholds bound in `effective_policy`, and never
  supplies observations or claims that a scenario ran. See
  [scenario definition quality](scenario-quality.md) for its input and policy.
  Explicit `contract_version="v2"` returns `ScenarioQualityReceiptV2` with
  a required ten-case active release set; the default v1 result is unchanged.
  `assess_scorer_quality` and `assess_scorer_calibration` are separate,
  candidate-bound read-only services. Their `ScorerQualityReceipt` and
  `ScorerCalibrationReceipt` check, respectively, strict scorer declarations
  and supplied held-out examples plus raw scorer artifacts. Calibration
  verifies scorer identity, thresholds, declared judge-parameter agreement,
  coverage, and false positives while retaining the applied policy, judge
  parameters, confusion matrix, and rates. Quality receipts retain valid
  declared judge parameters when supplied.
  Neither service runs a judge, turns declared probe IDs into execution evidence, or
  expands the active scenario set.
- **Observed calibration:** `execute_scorer_calibration(plan, executions)` accepts
  an `ObservedCalibrationPlan` and ordered `CalibrationProbeExecution` host
  capabilities. It composes the existing guarded selected-case executor rather
  than importing a provider transport or accepting completed probe claims.
  Every probe runs for the declared trial count, bounded to 128 invocations.
  The first trial uses `provider` and `judge`; subsequent trials require an
  explicit `trial_adapters` tuple of `CalibrationTrialAdapters(provider, judge)`.
  All provider and judge objects must be distinct across the entire batch,
  including across roles. Missing, malformed or aliased schedules block before
  adapter metadata access. The SDK does not clone or reopen host capabilities.
  PR #55 accepted this lifetime repair; controlled proof is not live calibration quality.
  Judges return `CalibrationJudgeVerdict` with bound assertion evidence and an
  actual callback-returned numeric score. The harness retains held-out labels;
  delegates receive only ordinary `SelectedCaseJudgeInput`. Identity/settings
  are checked around the callback; full-batch request and safety preflight
  precedes dispatch. `ObservedCalibrationReceipt` retains a first-stop ordered
  result prefix, invocation count, confusion-policy outcome and typed blockers.
  Callbacks may be controlled offline fixtures: `evidence_scope` is
  `observed_adapter_callbacks`, while `external_authenticity_verified`,
  `mutation_performed` and `promotion_authorized` remain literal `false`.
  Adapter invocation is not proof of externally generated scores or trusted
  ground-truth labels. Calibration probes do not enlarge the ten active cases.
- **Risk and security:** `RiskClassification`, `RiskSensor`,
  `SecurityScreeningResult`, and redacted `SecurityFinding` metadata.
- **Registry preparation:** `RegistryIdentity`, `RegistryPreparationRequest`,
  and `RegistryPreparationReceipt`. Use `prepare_private_registry_candidate` with
  a built `PackageReceiptV2` and its matching `PackageHardeningReceipt` to
  create a deterministic local preparation receipt. The prepared result binds
  the candidate, registry namespace, package/version, manifest digest,
  hardening-receipt digest, and portable evidence paths. Blocked inputs retain
  typed blockers and cannot claim prepared digests. Path-shaped hardening
  evidence remains in blocker `evidence_refs`; other accepted hardening
  evidence is retained only through `source_evidence_sha256` rather than being
  exposed or reinterpreted as a path. Credential-shaped evidence is likewise
  digest-bound and never copied into the receipt. Hardening warnings use the
  same projection: the complete warning is digest-bound, safe portable evidence
  references remain readable, and raw warning IDs/messages are not copied.
  This service performs no registry I/O or publication.
  Credential-shaped request evidence is rejected. Unsafe source blocker
  code/message text is replaced by a generic typed blocker and bound through
  `source_blocker_sha256`; safe source metadata and portable references remain
  readable.
- **Package safety evidence:** `PackageSafetyEvidenceReceipt`,
  `PackageSafetyEvidenceReference`, `PackageSafetyFinding`, and
  `PackageSafetyBlocker`. The receipt binds one exact candidate and the
  canonical manifest `package_digest` from its upstream `PackageReceiptV2` to
  a caller-supplied reviewer adapter and one of four states. The manifest
  digest and the candidate's source `content_sha256` identify different
  artifacts and are intentionally not required to be equal:
  `not_reviewed`, `reviewed_no_issue`, `issue_found`, or
  `metadata_insufficient`. A reviewed-no-issue state requires digest-bound
  evidence and forbids findings; issue-found requires evidence, a warning or
  blocker finding, and typed blockers. Metadata-insufficient requires a typed
  blocker but cannot claim an observed issue. There is no generic `safe`
  field. Draft 2020-12 validates the structural state, shape, uniqueness, and
  public-text constraints it can express. Cross-object evidence membership,
  blocker-reference membership, and primary-blocker equality remain explicit
  semantic invariants identified by schema metadata and enforced by
  `SchemaRegistry.validate`. The contract validates supplied metadata and never
  performs a review, rights decision, admission, provider call, installation,
  runtime action, or publication. A raw safety payload cannot dereference its
  opaque `input_receipt_id`; when a caller has the upstream
  `PackageReceiptV2`, call
  `SchemaRegistry.validate_package_safety_evidence_against_package_receipt`
  to require matching receipt ID, candidate, and canonical manifest digest.
  A raw upstream mapping is first validated through the `package-receipt/v2`
  JSON boundary before that binding is applied.
- **Pre-execution safety:** `PreExecutionSafetyEvidence` and
  `CapabilitySafetyReview` retain actual upstream, review, screening and checklist
  artifacts. `skills_sdk.validation.screen_package_security` uses the existing
  safe package capture to inspect manifested bytes without running the package,
  scanner subprocesses, network requests or credentials. Indicators select
  relevant reviews; they are not proof of exploitability. The canonical
  `sdk-capability-checklist/v1` covers content/injection, secrets/privacy,
  filesystem/subprocess, network/external writes, dependencies/binaries and
  tools/privileges. Content and privacy always require review. Script presence
  cannot downgrade filesystem and dependency review to non-applicable; other
  observed capabilities select their corresponding checks. Every non-applicable
  entry still needs a rationale and retained review evidence.
  `skills_sdk.evaluation.assess_pre_execution_safety` assesses bindings and
  freshness; supplying `package_root` also requires actual recapture agreement.
  Its `None` result means that these checks passed, not general security
  approval. Host clocks and freshness budgets are not supplied artifact fields.
  The default maximum review age is one hour, and an explicit host budget must
  be an integer between one second and one day. Reviews cannot predate their
  upstream build or be in the future.
  Both selected-case execution APIs require `SelectedCaseExecutionInput`, which
  wraps the provider input payload and safety evidence without sending safety
  metadata to the provider. Bare payloads block before adapter access. Both APIs
  enforce recapture before provider/judge properties, calls or cleanup. Omitting
  it returns a candidate-bound evaluation blocker. The low-level provider-call
  primitive is transport orchestration, not skill-workflow admission. Supplied
  reviewer claims, external scanner execution, general semantic accuracy and
  complete plugin-bundle security remain separate evidence lanes.
- **Provider execution envelopes:** `ProviderExecutionRequest` records a
  candidate-, scenario-, provider-, safety-receipt-, and input-digest-bound
  request prepared for an external adapter. `ProviderExecutionResult` records
  that adapter's externally observed `completed`, `failed`, `blocked`, or
  `indeterminate` result with output or evidence digests and typed blockers or
  errors. The SDK locally validates this evidence envelope; it does not prove
  that the external provider actually produced the reported outcome.
  Both contracts require `ProviderIdentityV2`, reject raw payload and
  credential fields, and carry literal-false execution/privacy/cost claims.
  A prepared request must bind supplied `reviewed_no_issue` package-safety
  evidence; other safety states cannot authorize preparation. A bound result
  cannot start before its request was prepared. These cross-envelope relations
  require the supplied receipt or request and are enforced by the named
  `SchemaRegistry` binding methods rather than standalone Draft validation.
  Optional usage metadata is an adapter-reported unit count, not billing or
  cost evidence. The SDK validates these envelopes but does not authorize or
  perform provider execution, contact a network, read credentials, evaluate an
  output, or establish provider truth. Replay provenance is optional, but when
  non-null it binds both the prior result ID and the SHA-256 of that prior
  result's complete canonical JSON envelope (UTF-8, keys sorted, compact
  separators). A result cannot reference itself as its replay source.
- **Offline provider-call orchestration:**
  `skills_sdk.providers.execute_provider_call` accepts one revalidated prepared
  `ProviderExecutionRequest`, its private digest-bound JSON input, and one
  injected `TextProviderAdapter`. The adapter descriptor selects complete or
  pull-driven stream mode and is restricted to injected, offline
  `response_generation`; provider identity must match the request. The SDK
  reads only the method selected by the descriptor. Each stream pull returns
  either one `ProviderAdapterChunk` or `ProviderAdapterTerminal`, or a
  `ProviderAdapterBatch` tuple. Batches must contain one to eight events by
  default (never exceeding the configured buffer limit); a zero buffer limit
  permits direct events only. A terminal event must be last in its batch. The
  SDK applies the documented input, metadata, nesting, output, chunk, event,
  deadline, and cleanup limits with zero retries. A successful
  `ProviderCallOutcome` keeps complete text private and exposes only a
  `provider-call-result/v1` public result containing digests, counts, redacted
  terminal evidence, adapter-reported usage and cost observations, and its
  request-bound `ProviderExecutionResult`. Known failures become typed terminal
  outcomes; invalid caller or adapter contracts raise `ContractError`.
  Cancellation remains cancellation after bounded cleanup. This service does
  not discover adapters, read credentials, contact a network, evaluate output,
  or establish external provider truth.
- **Optional Codex CLI judge (delivery candidate):** Import `CodexJudgeAdapter`
  and `CodexJudgeSettings` from `skills_sdk.providers.codex_judge`. Supply a
  trusted executable, isolated temporary-work parent, frozen rubric, explicit
  model/CLI version and every ambient MCP server name to disable. The host must
  authorise invocation; constructing an adapter grants no authority or budget.
  The host must authorise the actual data and provider destination. Task,
  response, rubric and assertion operands are private prompt fields sent intact
  to that authorised judge, including text that resembles a path or credential.
  Public-metadata redaction protects identities, diagnostics and evidence
  references; it is not prompt sanitisation or permission to send real secrets.
  `assess(task, response, assertions)` returns a numeric observation and digests;
  its rationale and canonical result bytes are private provider output, omitted
  from the observation representation and unsuitable for public logging.
  `judge(inputs)` implements the existing selected-case judge protocol and
  emits `SelectedCaseJudgeEvidence` bound to the candidate, output and assertion
  contract. For `judge`, pass an async `retain_result(ref, bytes)` callback
  that stores the supplied canonical verdict bytes under the supplied portable
  reference and returns `None`. Evidence is emitted only after that callback
  succeeds; the trusted host owns actual retention and access control. The
  callback may be an async function or an object with async `__call__`. It
  must use non-blocking storage awaits and propagate cancellation;
  synchronous callbacks are rejected. Blocking code inside trusted async host
  code is outside the adapter isolation guarantee. Direct
  `assess` also returns those bytes as private `result_json` for host retention.
  One adapter supports one active assessment; overlapping calls are rejected.
  Requested shell/web/apps/plugins restrictions, read-only sandbox and ephemeral
  operation are passed as CLI arguments. Input/output limits and deadlines are
  enforced by the adapter. Direct `assess` shares one requested native execution
  budget between its version probe and execution. The probe is capped at ten
  seconds and the remaining budget; execution receives only what remains.
  Each owned process has a separate cleanup bound of five seconds, which may
  extend wall time beyond the execution budget. `cleanup()` closes the adapter,
  cancels active work and waits up to six seconds for owned teardown; it does
  not report success while that work remains active. Cancelling the cleanup
  waiter does not cancel resource teardown again. Caller cancellation remains
  cancellation when teardown fails, with a safe cleanup-code note; the cleanup
  hook reports the typed teardown blocker. Selected-case orchestration
  retains its authoritative 30-second overall judge deadline, including startup,
  and one-second cleanup deadline; it may cancel an invocation before a larger
  native timeout. This adapter does not extend those shared engine budgets.
  Configuration, global instructions, hooks, rules and authentication
  remain inherited. Tool-event rejection is retrospective and cannot prevent
  an available tool from acting; the host must verify isolation for its data.
  The adapter supports POSIX process-group cleanup, not Windows. Failed,
  incomplete, malformed, tool-bearing and foreign-assertion output cannot
  become evidence. Unknown event types, duplicate JSON members, invalid verdict
  fields and post-completion events produce typed `ContractError` blockers
  without raw output disclosure. Additional ordinary event metadata is allowed.
  Nonzero exits retain only safe category, exit-code, byte-count and digest
  diagnostics in `last_failure`; successful observations are not backend
  identity or sampling attestation. No live provider acceptance is claimed by
  the controlled subprocess tests, including CLI/backend output-schema
  compatibility. A backend schema rejection remains a typed process failure,
  with an `output_schema_rejected` diagnostic when recognised, not evidence.
  `CodexNativeJudgeParameters` is available from `skills_sdk.models` with
  generated schema `codex-native-judge-parameters.v1`. These frozen requested
  settings have structural JSON Schema checks plus integration-model semantic
  checks for portable identities and unique simple ASCII MCP names. Consumers load
  the packaged resource with Draft 2020-12 and `FormatChecker`, then call
  `CodexNativeJudgeParameters.model_validate` for semantic acceptance. This
  provider-specific family is deliberately absent from portable core's
  `SchemaRegistry`; the adapter validates its own settings in the integration layer.
  They explicitly record unavailable temperature control; they cannot
  satisfy existing temperature-bound calibration. No native calibration,
  matched-family or whole-plugin quality integration is included.
- **Selected-case behavioral orchestration:**
  `load_selected_case` validates one case from package-local
  `references/evals.yaml`, including exact mode eligibility, and projects its
  existing acceptance declarations into a candidate-bound `ScenarioSetV2`.
  It rejects prompts above the provider input limit. When execution starts, the
  package definition must match its source: `execute_selected_case` reloads it
  and rejects a definition that no longer matches that source.
  `execute_selected_case` composes the existing `execute_provider_call` and
  `evaluate_scenario_set_v2` services for one injected adapter. Semantic
  assertion signals must be supplied through a `SelectedCaseJudgeEvidence`
  artifact bound to the candidate, scenario set, case, provider output digest,
  and a digest of the complete semantic assertion contract. The artifact also
  identifies the judge adapter and its result digest. The host must include the
  portable `judge-results/<judge_result_sha256>` path in `evidence_refs`; the
  SDK does not invent an artifact path. The service never derives
  semantic proof from keyword matches or an unreferenced boolean. Deterministic text
  absence or presence checks remain SDK-owned. Missing adapters, missing judge
  evidence, unavailable output, or identity mismatches return blocked
  evaluation receipts. `SuppliedTextProviderAdapter` is a no-I/O adapter for
  controlled host or test evidence. These APIs prove portable orchestration,
  not live-provider authorization, execution provenance, or model quality.
  `execute_selected_case_with_judge` is an additive Python API for a host that
  supplies both adapters. It validates the selected case and prepared request,
  calls the provider once, then passes that actual private output and the
  complete semantic assertions to a `SelectedCaseJudgeAdapter`. The SDK binds
  returned judge evidence to the output digest and judge identity before its
  deterministic scorer runs. Missing capabilities, unavailable output, failed
  cleanup, judge failure, malformed evidence, and identity mismatches block.
  Judge and cleanup deadlines bound receipt return on a persistent event loop,
  not termination of arbitrary host code: a hook that suppresses cancellation
  may continue after a timeout and overlap cleanup. Hosts must make judge hooks
  cancellation-cooperative or isolate untrusted execution outside this process;
  `asyncio.run` may wait for an uncooperative hook during loop shutdown.
  The host owns credentials, transport, and judge-result persistence; the SDK
  does not verify content behind a logical evidence reference. A supplied-text
  provider remains controlled offline proof even through this API.
- **Runtime-lock planning:** `RuntimeLock` (`runtime-lock/v1`) describes
  candidate-bound intended state for a logical user or project target. Each
  entry binds package and candidate identity, version, package digest, registry
  identity, package and preparation receipt IDs, and an ordered digest inventory
  of portable relative files. `InstallPlan` (`install-plan/v1`) describes a
  deterministic `install`, `update`, or `no_change` transition, or a typed
  blocked result. The planner rejects a registry receipt whose
  `input_receipt_id` does not identify the exact package receipt, carries the
  current lock digest as its rollback identity, and always reports
  `mutation_performed: false`. These contracts do not prove an apply attempt,
  rollback, journal, race-safe host mutation, discovery, activation, or runtime
  outcome. A future host adapter must emit those evidence families separately
  without putting absolute paths, credentials, raw logs, or environment state
  into portable core contracts.
- **Runtime execution evidence:** `InstallationResult`, `RollbackJournal`,
  `RollbackOutcome`, `DiscoveryObservation`, `ActivationObservation`, and
  `RuntimeOutcomeReceipt` are additive, adapter-supplied v1 families. They bind
  the exact candidate, package digest, plan, logical target, adapter identity,
  timestamps, and digest-only evidence while keeping installation, rollback,
  discovery, activation, and runtime outcome distinct. Explicit
  `validate_against_*` methods prove cross-receipt equality; standalone Draft
  validation remains structural for those cross-object relations. The SDK does
  not resolve host paths, copy files, invoke a runtime, activate a skill, or
  claim evaluation quality, safety, cost, persistence, or usability.
  Every receipt-shaped runtime observation requires its literal `lane` field;
  omission fails through Pydantic, `SchemaRegistry`, and generic receipt
  parsing rather than reaching an untyped mapping lookup.
  Optional provider-result and evaluation-receipt references are not proof by
  presence alone: callers must use `validate_against_provider_result` and
  `validate_against_evaluation_receipt` to verify the referenced ID, canonical
  digest, and candidate identity.
  `InstallationResult.operation` preserves the planned `install`, `update`, or
  `no_change` transition in the standalone observation. Pydantic and
  `SchemaRegistry` enforce its lock-digest and mutation semantics; Draft
  2020-12 enforces the operation-to-mutation rule, while equality between lock
  digest fields remains a semantic check.

## Matched whole-plugin evaluation

Accepted in PR #53, this bounded S4 implementation does not establish complete
workflow parity or live-provider quality. It provides the public evaluation APIs
`assess_matched_pair`, `execute_matched_calibration`, `execute_matched_lane`,
`prepare_matched_cloud_handoff`, `execute_matched_cloud`,
`execute_matched_regression` and `execute_matched_cloud_regression`.

`MatchedComparisonPlan` requires a `MatchedPluginScope` containing two passing
complete `PluginPackageValidation` captures, including file-mode digests.
Their complete candidate identities must differ; an identical baseline and
candidate is not an improvement comparison. A shared package identifier with
a different revision or content digest remains admissible.
The bounded slice supports one through nine child skills with the same logical
child paths in both variants. It requires exactly ten ordered unique active
cases, per-skill driver coverage for every child, and a cross-skill case when
there is more than one child. Existing `ScenarioCoveragePlan` claims and
mappings must preserve the same objective without open gaps. This verifies
mapping consistency, not the truth or completeness of supplied claims.

Each case has child-bound scorers, selected skill paths and optional shared
reference paths retained by both captures. Both plan admission and runtime
context require eligible Markdown paths and reject hidden evaluation,
scorer, rubric, calibration and held-out paths. References cannot duplicate
the selected children's automatically included `SKILL.md` entrypoints; ordinary
captured files such as root `README.md` remain eligible. Captures retain hashes
and sizes, not source text or encoding proof. Structural plan admission does
not establish readability: source-backed context preparation requires every
selected document to decode as UTF-8 before provider or judge access, otherwise
execution returns a typed blocker. Unselected binary resources remain valid
captured resources. The ten singleton `ScenarioSetV2`
values on each side use `release=False`; together they form the managed active
set, rather than ten independent release sets. Plugin identity properties derive
from complete captures, not caller-supplied parent aliases.
`MatchedVariantCalibrationBundle` binds the plugin candidate and modes to exact
child/assertion/scorer targets. Every target retains observed dimensional
calibration with at least six held-out probes and the shared judge, settings
and rubric. Probes and repeated trials do not enlarge the ten active cases.

Host adapters remain private `MatchedCaseExecution` / `MatchedVariantExecution`
capabilities. Providers implement `MatchedCompleteProviderAdapter` or
`MatchedStreamingProviderAdapter`, including frozen `parameters`; judges
implement `DimensionalJudgeAdapter`, including their own frozen `parameters`.
The first trial uses the variant's provider and judge; `additional_trials`
contains exactly one fresh `MatchedTrialAdapters(provider, judge)` pair for
each later trial. Admission rejects reused adapter instances anywhere in the
lane before host property access. Each invoked adapter receives the existing
bounded single-call cleanup; later unused capabilities remain caller-owned.
Hosts must supply fresh capabilities again for a separate lane execution.
Distinct instances do not prove that a host has avoided aliasing an external
session behind different wrappers; that remains the host's responsibility.
Each `MatchedLaneSpec` requires `generator_mode`, either `complete` or `stream`.
Every variant and trial descriptor must match that frozen mode; mismatch blocks
before that provider callback, without a completed comparison. The mode is part
of the plan digest and retained trial request commitments. Streaming remains
bounded by the provider lifecycle, with source, settings and elapsed-budget
checks at every pull and iterator cleanup on success or rejection.
`PluginExecutionContext` and
`prepare_matched_plugin_context(definition, context)` bind the selected driver,
selected child documents and permitted references to fresh whole-plugin source.
Hidden evaluation, scorer, calibration and rubric documents are excluded from
the generator context. Context paths and source bytes remain private inputs;
portable receipts retain identities and digests instead of source text.

### Explicit Codex profiles

`skills_sdk.providers.codex_profiles` exposes `CodexProfileSource`,
`describe_codex_profile`, `compile_codex_profile`, `CodexProfileInvocation`,
`CodexProfiledCompleteAdapter`, `CodexProfiledStreamingAdapter` and
`CodexProfiledJudgeAdapter`. These are an outer, supplied-offline adapter seam;
the portable core does not import Codex or discover host configuration.
PR #56 accepted this seam, not live-provider execution or real-provider settings application.

`CodexProfileSource` holds a logical name and explicit immutable bytes:
`profile_bytes`, optional `provider_bytes`, `catalogue_bytes` and
`defaults_bytes`. Use only `oss-local.config.toml` or `oss-cloud.config.toml` as
the logical name. Unresolved dependencies or effective options block without
ambient fallback. Source and invocation representations omit private byte and
configuration bodies; callers must still keep those bodies out of public logs.

Call `describe_codex_profile(source, model_revision=...)` before constructing
the lane. The returned `ProviderIdentityV2` uses an explicit
`provider/native-model` identity, preserving native model tags without loosening
the frozen URI restriction. Adapter ID `codex-profile-offline-v1` and its digest
bind the logical name, profile bytes, dependencies, supplied defaults and binding
contract version. The model revision is a caller claim, not authenticated model
version evidence. Changed inputs require rebinding the plan and its affected
calibration and execution evidence.

`compile_codex_profile(plan, source, role)` returns an immutable private driver
invocation for `generator` or `judge`. Declared profile settings override selected
catalogue defaults, which override explicit caller defaults. Every required
option must resolve. Temperature and trial count come from the corresponding
frozen lane role. Catalogue paths and disabled MCP launch commands are not
forwarded; the selected model record is supplied directly and optional
integrations remain disabled. This is the bounded SDK adapter contract, not a
claim of complete Codex-version configuration compatibility.

Supply a fresh driver for each adapter and trial. Driver `complete` and `stream`
methods receive `(invocation, request, payload)`; driver `judge` receives
`(invocation, inputs)`. Cleanup retains the existing lifecycle. The adapter
compiles once, then compares immutable source, plan, lane, role and invocation
snapshots around callbacks and stream pulls, rejecting drift without accepting
the returned output. It does not reparse or rehash profile dependencies on each
pull. The adapter passes compiled settings to
the driver; separate proof is needed that a real external implementation applies
them. These APIs do not authorise provider calls, spending or credential access.
Closed option values and malformed provider ports reject at input admission.
Advertised reasoning levels constrain the resolved effort when supplied;
absent capability metadata leaves external effort support unverified.
Permission-profile names remain symbolic driver inputs; resolving host policy
and proving its application remain the driver's responsibility.

Focused tests cover controlled driver delivery, role-specific parameters,
streaming, rejection, recovery and public provider-call cleanup. Controlled local
CLI tests retain fresh profile-bound calibration and ten-case execution in both
modes. The calibration CLI rejects stale configuration, missing profile plans
and mismatched judge settings, then accepts corrected inputs without exposing
held-out labels to the judge. Controlled cloud CLI and installed-wheel local,
calibration and cloud checks prove stale-profile rejection and corrected-input
recovery. These are offline fixtures, not external model-quality evidence.
The existing matched services still own source safety, budget, calibration,
whole-plugin scope and local-to-cloud handoff admission.

Admission requires selected-child safety plus complete
`PluginPreExecutionSafetyEvidence`. `screen_plugin_security` applies bounded
static signatures across captured files; `assess_plugin_pre_execution_safety`
joins fresh source, screening, applicable supplied checklist evidence and
freshness. These are supplied assessments and static screening, not authenticated
independent security review or proof that executable resources are harmless.

Each lane requires explicit `MatchedRunBudget` and `MatchedSelectionPolicy`.
Provider and judge allowances are at most 128 each; elapsed time is checked
before and after callbacks. Expiry stops later admission but cannot cancel a
running callback. A requested reported-cost bound blocks before callbacks
because adapters provide no cost observations; it is not an enforced spend cap.
`MatchedExecutionReceipt.summary` recomputes equal-case-weight descriptive
selection from a completed lane. Minimum repeated-trial coverage, qualifying
confidence, trial-range stability, directional case count and mean threshold
control `candidate`, `baseline`, `unchanged` or `inconclusive`. The summary is a
derived API property, not a serialised receipt field or a statistical guarantee.
Plans whose lane trial count cannot meet the selection policy are rejected
before callbacks. Each case, variant and trial gets a distinct request and
idempotency identity derived from the frozen plan digest and lane. Execution
receipts retain those actual requests and reject swapped or reused trial
identities. Repeating the identical frozen experiment reproduces those identities;
this separates trials within one experiment but does not bypass transport-side
caching or establish authentication across separate runs.

A cloud handoff requires a qualifying local candidate and no unresolved
regressions. Its complete capture becomes the cloud baseline while case scope,
coverage, assertions, input commitments, rubric and selection policy remain
bound. Failed cases require explicit owners and a full ten-case controlled
rerun; closure requires retained passing rerun evidence and unchanged captured
fixture source. All rerun candidate contexts must name the same absolute plugin
root, so the retained before/after capture covers every executed candidate case.
Different source copies block before provider or judge access even when their
initial captures agree; equivalent relative and absolute paths remain accepted.
Baseline calibration commitments also remain frozen across recovery. Corrected
candidate calibration may be rebound, but substituting another passing baseline
bundle changes the experiment controls and blocks both execution and retained
receipt validation. Declaring an owner alone cannot close a regression.

The additive wire families are `matched-comparison-plan/v1`,
`matched-pair-assessment/v1`, `matched-calibration/v1`,
`matched-variant-calibration/v1`, `matched-execution/v1`,
`matched-cloud-handoff/v1`, `matched-cloud-execution/v1`,
`matched-regression/v1`, `matched-cloud-regression/v1` and
`plugin-pre-execution-safety-evidence/v1`. Their corresponding dotted resource
names are available through `SchemaRegistry`; semantic checks supplement JSON
Schema. Callback observations may be supplied offline. They prove neither
external authenticity, live-model quality, promotion authority nor provider
spending. See [CLI input boundaries](cli.md#matched-evaluation) and
[compatibility limits](compatibility.md#matched-evaluation-integration).

## Read-only intake

`source_repository` accepts a credential-free `owner/repository` slug, not a
URL or a local checkout path. Raw intake checks must be actual booleans.
Existing `IntakeChecks` instances are accepted using their current boolean
values; any coercion performed before intake cannot be recovered. Pass raw
data to `SkillPackageIntakeContext.model_validate` to enforce this boundary
before coercion. Shared package models retain their existing behavior.

Intake owner, maintainer, and license fields require public strings without
machine paths or credential-shaped text. This screening also applies to
serialized receipts and typed inputs; it does not establish that arbitrary
text contains no private information. Ordinary names, SPDX expressions, and
credential-free public license URLs remain accepted. The generated intake
schema rejects inconsistent admission checks and package types. Candidate
bindings, content digests, and evidence-derived decisions still require
`SchemaRegistry.validate`, as identified by its semantic-validation metadata.

Run this example from the repository root with the pinned environment:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen python - <<'PY'
from pathlib import Path

from pydantic import ValidationError

from skills_sdk.intake import intake_skill_package
from skills_sdk.models import SkillPackageIntakeContext

# Synthetic fixture assertions: replace these with the caller's real evidence.
payload = {
    "source_repository": "jscraik/skills-sdk",
    "source_revision": "1" * 40,
    "source_path": "tests/fixtures/synthetic-skill",
    "source_kind": "git",
    "owner": {
        "owner": "sdk-tests",
        "maintainer": "sdk-tests",
        "ownership_state": "canonical",
        "rights": {
            "basis": "authored",
            "license": "Apache-2.0",
            "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
        },
    },
    "checks": {
        "identity": True,
        "provenance": True,
        "rights": True,
        "owner_unchanged": True,
    },
}
context = SkillPackageIntakeContext.model_validate(payload)
for package_root in (Path(context.source_path), Path("pyproject.toml")):
    receipt = intake_skill_package(package_root, context)
    if receipt.status == "normalized":
        print("normalized:", receipt.candidate.package_id)
        print("decision:", receipt.decision.decision.value)
    else:
        print("blocked:", receipt.blocker.code)
        for finding in receipt.validation.findings:
            print(finding.code, finding.evidence_refs)

# Invalid context fails before the service runs; it produces no receipt.
try:
    SkillPackageIntakeContext.model_validate({**payload, "source_revision": "invalid"})
except ValidationError:
    print("invalid context: ValidationError")
PY
```

The fixture directory produces `normalized`; the regular file
`pyproject.toml` produces a typed package-root blocker. Invalid context raises
`pydantic.ValidationError` before package inspection. A normalized receipt
can still contain a `block` or `needs_owner_decision` decision when supplied
checks are false: normalization does not establish admission or rights truth.
Inspect both status and decision. The synthetic revision above demonstrates
the contract's format; production callers must supply the actual source revision.

The service is always read-only, so it needs no dry-run flag or filesystem
rollback. It does not copy, execute, install, or publish the package. Validate
serialized intake receipts with
`SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))` to enforce
structural and model-level bindings. The context schema is registered as
`skill-package-intake-context.v1`; neither family is supported by the generic
`parse_receipt` function.

## Explicit standalone-skill plugin preparation

Managed single-skill releases are explicitly normalized into a separate
complete-plugin candidate. Supply a valid standalone skill directory, a new
destination, truthful caller-owned intake evidence, and root plugin metadata.
The API preserves the source, copies its files and permissions beneath
`skills/<skill-name>/`, creates root `plugin.json`, and captures fresh
whole-plugin validation. The whole-plugin identity covers the new candidate;
its sole child retains the standalone skill candidate identity.

Normalization introduces no plugin dependencies. Before issuing a prepared
receipt, a final no-follow capture checks destination files, bytes, permissions
and directories against the intended output, and checks its directory identity
against the retained opened output descriptor. Capture rechecks each entry's
identity and metadata after traversal. These sequential checks detect observed
drift; they are not an atomic filesystem snapshot.

Preparation requires a caller-controlled destination parent and an exclusive
writer for the operation. Parents owned by another user or writable by group
or others are rejected before creation. Owner and mode checks do not establish
exclusive access through ACLs or exclude other processes running as the same
user. Callers must exclude those writers; hostile concurrent namespace mutation
requires isolation outside this API. Portable directory creation cannot
atomically return the created inode's descriptor. The receipt binds captured
state under this boundary; later changes require fresh downstream validation.
Any retained passing validation, including in a blocked receipt, must bind its
sole child to the original standalone candidate. If destination validation
belongs to another child, the blocker and creation signal remain, but that
unrelated passing validation is not retained as source proof. Packaged JSON
Schema checks structure; the model and schema registry enforce this identity
relationship.

The operation is create-only: unsafe paths, symlinks, and existing destinations
are rejected rather than overwritten. The destination's parent directory must
already exist. On a partial filesystem error, the
receipt reports whether a candidate directory was created so the caller can
inspect and correct it before retrying. A prepared result is not complete
product acceptance, visual approval, archive proof, publication, installation,
or runtime evidence. Updates to an existing managed plugin must retain and
compare a known baseline in a separate update route.

Run from the checkout root with the pinned Python environment. This complete
synthetic example creates a candidate in a fresh temporary directory and removes
that directory on exit. It does not modify the committed source fixture. The
context assertions demonstrate the input contract; they are not verified rights
or provenance evidence for a real package.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from skills_sdk.intake import normalize_standalone_skill_package
from skills_sdk.models import PluginNormalizationMetadata, SkillPackageIntakeContext

context = SkillPackageIntakeContext.model_validate({
    "source_repository": "jscraik/skills-sdk",
    "source_revision": "0" * 40,
    "source_path": "tests/fixtures/synthetic-skill",
    "source_kind": "git",
    "owner": {
        "owner": "sdk-tests",
        "maintainer": "sdk-tests",
        "ownership_state": "canonical",
        "rights": {
            "basis": "authored",
            "license": "Apache-2.0",
            "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
        },
    },
    "checks": {
        "identity": True, "provenance": True,
        "rights": True, "owner_unchanged": True,
    },
})
with TemporaryDirectory(prefix="sdk-normalization-example-") as folder:
    receipt = normalize_standalone_skill_package(
        Path(context.source_path),
        Path(folder).resolve() / "example-plugin",
        context,
        PluginNormalizationMetadata(
            name="example-plugin", version="1.0.0",
            description="A synthetic single-skill plugin.",
        ),
    )
    if receipt.status == "blocked":
        print(receipt.blocker.code)
    else:
        print(receipt.status, receipt.plugin_validation.candidate.content_sha256)
        assert receipt.release_ready is False
```

Expected output starts with `prepared` followed by the captured plugin digest.
For a blocker, inspect its code and `candidate_created` before retrying; a real
caller must retain any partial output for inspection and select a fresh
destination. The temporary-directory cleanup here is only for this synthetic
example, not a general recovery procedure.


The metadata uses `plugin-normalization-metadata/v1`; the result uses
`plugin-normalization/v1`. Neither is accepted by generic `parse_receipt`.
Use the registered schemas for structural and semantic binding checks.
Metadata admission enforces the canonical manifest's aggregate one-MiB UTF-8
byte limit, including JSON escapes and both required text fields. Structural
JSON Schema provides necessary per-field character bounds; only the model and
`SchemaRegistry` enforce the combined encoded-byte budget.
Prepared receipts require the exact canonical manifest digest, size and mode
`0644`, no host-settings overlay, and exactly the admitted files beneath
`skills/<source-name>/`. Structural schema checks do not enforce this file
closure or authenticate hashes. Original standalone evidence does not record
file modes or empty directories; the service checks their preservation through
live captures, rather than claiming receipt-only proof of them.
An unsupported or unsafe initial capture returns
`standalone_source_capture_blocked`, not an assertion of observed drift.
Before creating a destination, normalization also reserves capacity for the
canonical manifest and `skills/<source-name>/` wrapper. Exceeding complete-output
file, byte, resource or directory-depth limits returns
`standalone_source_capacity_exceeded` with `candidate_created: false`.
Unsafe destination resolution, including Python 3.12 symlink loops, returns
`candidate_normalization_failed` without writing through the path.
Containment also checks live directory identities and parent descriptors, so
different case spellings cannot place output inside the source. These checks
and later recaptures are point-in-time safeguards, not an atomic namespace lock.
`source_changed` means an observed difference in captured source relative to
admitted or pre-copy evidence, including later permission or directory drift.
Correct the responsible input, retain the blocker, and use a fresh destination;
changed source requires fresh intake and downstream evidence.

The additive `skills_sdk.evaluation.check_local_quality` async service accepts
a package path and a `LocalCheckRequestV2` or closed raw request. Keyword inputs
are `baseline_root`, `assessment` and an explicit trusted offline `adapter`.
It returns `LocalCheckResultV2` (`local-check/v2`) with ordered original service
receipts and final source captures. Import request, policy, stage and result
models from `skills_sdk.models`; validate serialized inputs and outputs through
`SchemaRegistry` using `local-check-request.v2` and `local-check.v2`.
Await this asynchronous service inside an existing async caller. This fragment
requires a prepared package path, request and supplied content assessment:

```python
from skills_sdk.evaluation import check_local_quality

result = await check_local_quality(package_root, request, assessment=assessment)
```

Supplied and observed content evidence cannot be substituted for each other.
Declared intake context and coverage plan must match their stage receipts.
This composition does not execute scenario/judge evaluation or authorise
promotion. Callback invocation is recorded only in its separate observed lane.

The agent-facing `skills-sdk check-local` CLI emits the registry-only
`local-check/v1` envelope. Use
`SchemaRegistry().validate("local-check.v1", payload)` to check its ordered,
candidate-bound stage receipts and blocked-stage semantics. It does not
execute provider evaluations or authorize package promotion.
Direct Draft 2020-12 validation checks the required envelope fields, state,
stage count, order, and receipt families. Candidate equality, intake
admission, first-blocker ordering, and nested receipt invariants require
`SchemaRegistry.validate` and its semantic model check.

## Schema validation

`validate_recurring_findings(ledger_path)` and
`validate_pr_sweep_dirty_closeout(repo_root, ledger_path=None,
require_clean=False)` are read-only services exported by `skills_sdk.validation`
and the package root. They return `PrSweepValidationResult` with version
`pr-sweep-validation/v1`, a `pass`, `fail`, or `blocked` status, and actionable
findings. The dirty-closeout result also separates staged, unstaged, untracked,
ledgered, and unledgered repository-relative paths. A ledger never satisfies
`require_clean` for a dirty checkout. These services neither fetch hosted PR
state nor execute any merge or cleanup action.

The supplied recurring ledger is `schema_version: 1` and is checked against
`pr-sweep-recurring-findings.v1`; serialized results can be checked with
`SchemaRegistry().validate("pr-sweep-validation.v1", result.model_dump(mode="json"))`.
Schema validity does not itself prove the recurring-finding fingerprint or
guardrail rule; use the service for those semantic checks.


Use `SchemaRegistry` for packaged JSON Schema structural validation. It also
applies model-level semantic invariants for the supported contract families:

```python
from skills_sdk.core import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity

candidate = PackageCandidateIdentity(
    package_id="example-skill",
    source_revision="0" * 40,
    content_sha256="0" * 64,
)
# package-identity.v1 is the wire identity shape and has no schema_version key.
SchemaRegistry().validate("package-identity.v1", candidate.model_dump(mode="json", exclude={"schema_version"}))
```

The schema registry accepts only known schema names and raises `ContractError`
for an
unknown schema or invalid payload. It adds Pydantic semantic checks for
manifest, provider identity, provider execution, private-registry preparation,
package-safety evidence, runtime lock, installation plan, runtime execution
evidence, receipt, risk, security, scenario, and scorer schemas. The registered
`package-identity.v1` and inventory schemas receive structural validation only;
they do not receive model-level semantic checks. The packaged candidate,
skill-identity, plugin-identity, source, owner, normalized-package, and legacy `intake-decision.v1`
schemas are not registered with
`SchemaRegistry`; when those families need structural validation, load their
packaged JSON Schema resource with a Draft 2020-12 validator configured with
`jsonschema.FormatChecker()` so `date-time` and other declared formats are
asserted, then call the
corresponding Pydantic model explicitly (for example,
`PackageInventoryRecord.model_validate(payload)` for an inventory record).
The new `skill-package-intake.v1` and
`skill-package-intake-context.v1` families are registered as described above.
Validation is read-only: it does not write receipts, contact providers, install
packages, or publish to a registry.

`ProviderExecutionRequest`, `ProviderExecutionResult`,
`TextProviderAdapterDescriptor`, and `ProviderCallPublicResult` are registered
schema families, not generic receipts. Their `schema_version` values therefore fail
closed through `parse_receipt` and must be validated by model or
`SchemaRegistry` name. Cross-envelope claims require the supplied objects:
`validate_provider_execution_request_against_safety_evidence` binds the safety
receipt identity, canonical digest, and candidate, while
`validate_provider_execution_result_against_request` binds the request digest
and duplicated request/result identities, and
`validate_provider_execution_replay_against_prior_result` binds optional replay
provenance to the supplied prior result. Standalone schema validation cannot
establish those external-object relations. Cross-envelope digests use canonical
JSON from the fully validated model's `model_dump(mode="json")`; they do not
hash an adapter's non-canonical input spelling, omitted defaults, or timestamp
offset representation. Replay digests apply that same rule to the validated
prior result model. `parse_receipt` accepts only explicitly registered
receipt wire versions:
`receipt-base/v1`, package receipt v1/v2, evaluation receipt v1/v2, and
`registry-preparation/v1`, `package-safety-evidence/v1`,
`installation-result/v1`, `rollback-outcome/v1`,
`discovery-observation/v1`, `activation-observation/v1`, and
`runtime-outcome/v1`. A prepared
registry artifact maps to the generic
`pass` status while preserving `artifact_status="prepared"`; a blocked artifact
remains blocked. Parsing validates the versioned registry schema and does not
reinterpret older receipt payloads. A reviewed-no-issue safety artifact maps
to generic `pass`; the other three
safety states map to generic `blocked` while remaining available through
`artifact_status`. This mapping does not imply that an adapter ran or that a
package is generally safe. An unknown future or foreign `schema_version`
fails with the typed
`unsupported_receipt_family` error instead of being interpreted through the
generic base receipt schema. Missing or non-string versions fail with
`invalid_receipt_schema_version`.

`runtime-lock/v1` and `install-plan/v1` are registered for structural and
Pydantic semantic validation but are not generic receipts: generic receipt
parsing must not reinterpret intended runtime state or a non-mutating plan as
evidence that installation occurred.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
