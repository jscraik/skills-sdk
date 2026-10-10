# Compatibility

## Plugin-first and registry-independent migration target

The [managed release policy](workflow.md#managed-release-format) selects root
`plugin.json` and direct `skills/<skill-name>/SKILL.md` discovery for SDK-managed
releases, including single-skill plugins. Current standalone-skill APIs and
receipt schemas remain supported; migration needs explicit schema, behaviour
and compatibility proof rather than retroactive reinterpretation or removal.
Establish complete-plugin identity before release-bound evidence. A standalone
skill's passing receipt is not clearance for a newly assembled plugin.

Keep canonical skill contents in one source. A Tessl import/export adapter may
emit a distinct artifact with a distinct digest, but must prove required bytes,
paths and executable modes are preserved or block unsupported content. Keep
SDK and Tessl evaluation provenance, score meaning and not-evaluated/blocked/
stale states separate. No shared filename or passing lint substitutes for an
archive round-trip or selected-host test.

The [registry transition](workflow.md#registry-transition) makes Tessl the
initial backend, not a permanent SDK dependency. Existing registry preparation
contracts do not implement replacement-registry transport or establish a Tessl
endpoint override. Recheck the chosen backend and host independently; a
catalogue is not distribution, and runtime hooks may retain a CLI dependency
after registry storage changes. This section records a target, not new APIs.

## Selected-case safety admission

The additive `pre-execution-safety-evidence/v1` input retains actual artifacts
and explicit capability-review outcomes. Frozen package-safety, provider-request
and security-screening v1 payloads remain parseable without reinterpretation.
Parsing those contracts does not grant execution admission. Selected-case API
and CLI dispatch now requires the actual safety input and fresh source recapture;
ID-only requests return a typed blocked evaluation instead of invoking adapters.
This is deliberate execution hardening, not a claim of authenticated review or
external scanner execution. Supplied manual-review fixtures prove guard behavior,
not comprehensive security accuracy or completed plugin processing.

Typed safety inputs use canonical SDK model classes, including nested models.
Custom subclasses are rejected before their serializers run. Copied members
are audited for unknown fields, byte strings, cycles and mutation constants,
then revalidated; ordinary typed timestamps and closed raw JSON remain supported.
Pipe-to-shell indicators require both filesystem/subprocess and network review,
including commands written in non-script instructions or references.

The packaged Draft 2020-12 schema enforces exactly six ordered checklist IDs,
unique checklist evidence IDs and nonblank, public-safe rationale text. The
model and `SchemaRegistry` additionally enforce digest and cross-object joins,
supported screening, evidence references and applicable capability outcomes.
The resource labels these remaining semantic checks; standalone structural
acceptance does not establish safety admission or source freshness.

Content-review worker packets use a separate bounded wire budget: the public
eight-MiB normalized assessment limit plus 64 KiB for the envelope. Compact
UTF-8 serialization avoids ASCII escaping that expands Unicode assessments.
The sender and receiver enforce the same per-packet bound; the public model
limit and CLI wire-file limit remain unchanged. A valid exact-limit assessment
can complete offline review; one byte beyond the model limit remains invalid.

The content-review startup deadline is anchored immediately after the spawned
process launch returns, outside the trusted adapter-transfer operation. Delayed
parent observation does not restart it. Child invocation and failed-metadata
completion timestamps preserve timeout classification even when packets are
already queued. Timely startup and short callbacks remain valid.

## Local quality composition v2

`local-check-request/v2` and `local-check/v2` are additive closed contracts;
the five-stage `local-check/v1` command remains unchanged. The v2 service and
`check-quality` CLI bind explicit intent, applicable policy and complete claim
coverage before content assessment. Updates observe the supplied baseline path
and recheck it after the journey. Source paths are host inputs, not persisted
contract fields. The result retains the selected request and upstream receipts,
but is not an authenticated attestation of execution or semantic truth.
Once intake runs, `applied_policy` retains the policy supplied to validation and
must equal the selected request policy. Earlier blockers keep it null; missing
or contradictory applied-policy evidence cannot support a passing result.

Packaged JSON Schema enforces structural types and update-baseline presence.
Models and `SchemaRegistry` additionally enforce candidate/lineage equality,
ordered first-stop evidence, selected intake/coverage context, content lane and
final capture relationships. Captures with a candidate bind their manifest
digest even when blocked, and their file paths must retain canonical sorted
order before hashing. Recovery blocker codes must match the reported failure.
Passing calibration matches the selected scorer's
identity, threshold and declared parameters; passing content review matches
captured file digests and actual reference coverage. A last-stage receipt from
a changed candidate remains a typed blocker, not a cross-candidate evidence join.
Only the service observes source bytes and applies
the selected policy. Generic schema validation cannot prove these observations.
Both families remain outside the generic receipt parser. No earlier receipt
family is reinterpreted as permission to execute, promote or publish.

This is an SDK-owned composition of accepted intake, validation, scenario,
scorer and content services, not a claim of complete Agent-Skills extraction.
Static held-out artifact assessment is not fresh calibration execution. The
API accepts explicit trusted callbacks; the CLI only accepts supplied review
evidence and blocks an observed request without that callback. Tests and
calibration probes do not enlarge the exactly ten active managed scenarios.

## Observed calibration contracts

`observed-calibration-plan/v1` and `observed-calibration/v1` are additive
contracts. They do not reinterpret read-only `scorer-calibration/v1`, change
caller-supplied completion IDs into proof, or grant evaluation promotion.
Raw, typed and copied inputs are revalidated at the model and service boundaries;
`SchemaRegistry` adds semantic bindings beyond structural JSON Schema.
Typed calibration inputs require canonical SDK model classes throughout the
nested payload. Raw inputs require canonical dictionaries, lists and tuples with
JSON scalars or canonical typed request timestamps; mapping views, custom
containers, sets and iterators are rejected before coercion or iteration.
Wrap validation audits raw members before the handler can
discard subclass identity; copied unknown fields and byte strings are rejected
before coercion. Normalisation reads raw members without calling model serializers,
while preserving strict numeric values and canonical typed request timestamps.
Receipts bind ordered held-out probes and trials to the candidate, output digest,
assertion contract, scorer, judge and settings. Passing results require every
declared invocation and the frozen confusion-matrix policy. Blocked partial
results cannot claim multiple unrecorded invocations after the first stop.
Policy-failure blockers require complete results that actually fail the policy;
preflight blockers require zero execution, and execution blockers require an
unfinished result prefix. Blocker codes cannot relabel complete passing evidence.

The API observes injected numeric callbacks. The CLI invokes explicitly supplied
offline verdicts; it does not discover executables, read credentials, spend
provider credits, or authenticate scores and labels. Controlled installed API/CLI
tests prove acceptance, preflight rejection and corrected-input recovery without
Agent-Skills or Foundry imports. They do not prove a real model's calibration.
Fresh model execution remains a separate evidence lane. The unmerged matched
integration candidate below adds controlled callback composition without
claiming live-model proof.

## Matched evaluation integration candidate

The S4 matched families are additive unmerged integration work, not accepted
main contracts or proof of full Agent-Skills parity. They preserve existing
`observed-calibration-plan/v1`, `observed-calibration/v1` and read-only
`scorer-calibration/v1` semantics. Supplied artifact checks cannot become
executed calibration merely by declaring completed probes.

The current strict plan requires two complete passing plugin captures and mode
digests with distinct complete candidate identities, one through nine matching child paths, exactly ten ordered active
cases, per-child driver coverage and multi-child cross-skill coverage. Scenarios
are child-bound singleton `ScenarioSetV2` values with `release=False`; full
coverage uses the existing claims/mappings with no open gaps. Captured file
identity and modes, case scope, assertions and scorer contracts remain separate
but joined evidence. Complete child/assertion calibration bundles require at
least six observed held-out probes per target. These probes and trial repeats
do not create extra active cases.
Matched reference eligibility is checked consistently at plan admission and
runtime context preparation: hidden evaluation inputs, non-Markdown files and
duplicates of automatically selected child `SKILL.md` entrypoints reject.
Ordinary captured Markdown reference paths remain supported. Portable captures
retain metadata, not source bytes or encoding proof. UTF-8 readability is
checked during fresh source-backed context preparation before provider or
judge access; invalid selected bytes return a typed blocker. Unselected binary
resources need not decode as text. Path rules supplement JSON Schema through
the registered models; schema acceptance alone is not execution clearance.

Private execution context requires fresh source binding, selected-child safety
and complete supplied plugin safety evidence with applicable checks and static
screening. This does not authenticate review or prove runtime safety. Explicit
callback and elapsed budgets retain first-stop observations; elapsed checks
cannot interrupt a running callback. Requested cost budgets produce a
zero-callback blocker rather than a claimed spend cap. Descriptive selection
requires sufficient trials, confidence, stability and directional evidence;
`unchanged` and `inconclusive` are not promotion signals. Summary is a derived
API property, not an additional serialised receipt field.

Matched lane capabilities use a distinct provider and judge instance for every
trial. `MatchedVariantExecution.additional_trials` supplies each later pair as
`MatchedTrialAdapters`; missing, extra or reused instances block admission
before host property access. Existing per-call cleanup and cancellation stay
unchanged; uninvoked capabilities remain caller-owned. These private host
capabilities are not portable receipt fields. Draft receipts produced before
the request-binding repair must be regenerated; the matched family did not
exist on the accepted base and is not a frozen released format yet.
The unmerged lane specification now requires explicit `generator_mode`:
`complete` or `stream`. Both variants and all trials must use that mode. It is
part of plan and trial commitments, so prior draft plans lacking the field and
receipts derived from them must be regenerated; this is not a reinterpretation
of an accepted-main family. Completed receipts already enforce exact provider
and judge counts through their declared coverage ceiling and full pair count.
The unfinished-pair allowance applies only to blocked prefixes.

Cloud handoff preserves the qualifying local plugin as baseline and freezes
scope, coverage and scoring objectives. Regression closure requires owned
failures, a complete controlled ten-case rerun and unchanged fixture source.
The full rerun uses one absolute candidate root; distinct source copies reject
before host callbacks even when their initial captures match. This private
host-input restriction adds no filesystem paths to portable receipts. Identical
baseline and candidate identities reject at plan validation; sharing only a
package identifier, revision or content digest is not itself a rejection.
Baseline calibration commitments cannot change during regression recovery,
even if both bundles pass. Corrected-candidate calibration can change while the
baseline controls remain frozen. Retained regression receipts enforce the same
rule; old draft receipts that violated it must be regenerated.
The supplied-offline CLI observes callbacks without external authenticity,
live-quality, spending, publication or promotion proof. Matched offline
fixtures support descriptor-selected complete and pull-stream protocols across
calibration, local, cloud and both regression routes. This does not widen the
existing public `SuppliedTextProviderAdapter` complete-only contract. See
[API families](api.md#matched-whole-plugin-evaluation-candidate) and
[CLI commands](cli.md#matched-evaluation-candidate). The retained historical
validation command for PR #53 candidate
`ca1db74570a945f4843013d61d47b2e2eea77e73` was
`PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=-x bash scripts/validate-repository.sh`:
`pass`, 3,182 tests passed and one skipped. Its disposable offline cache
bindings and proof limits are recorded in the
[task record](projects/sdk-workflow/tasks.md). This result does not validate
the subsequent reference-context, selected-child ownership, trial-feasibility,
trial-identity, adapter-contract, receipt-cost or safety repairs. Those require
fresh combined validation and delivery evidence in
[PR #53](https://github.com/jscraik/skills-sdk/pull/53); neither the historical
result nor this candidate establishes accepted-main contracts, live quality or
hosted clearance.

## Supplied content-review contracts

Typed assessment inputs and callback results use the canonical
`ContentReviewAssessment` model. Custom subclasses return an
`invalid_content_review` blocker before their serializers run. Raw closed
assessment data and canonical typed models remain supported.

The same canonical-only rule applies to nested review contract models before
their serializers run. Assessments have an eight-MiB normalized UTF-8 JSON
budget, enforced by the direct model, services and `SchemaRegistry`.
Packaged schemas annotate this semantic budget as
`x-max-normalized-json-bytes`; generic JSON Schema validators do not enforce
serialized byte length. The review CLI separately bounds the supplied JSON
file at eight MiB, including whitespace, and reports `content_review_input_limit`
for oversized files. Other intake-context readers keep their one-MiB budget.

`content-review-assessment/v1`, `content-review/v1` and
`content-review-execution/v1` are additive closed
families. They do not reinterpret package validation or scenario-quality
receipts. `SchemaRegistry` checks packaged structure and semantic model
invariants, including same-path evidence for every completed disposition; owned
gaps can remain incomplete and block. The public service additionally compares
candidate, actual reference inventory and source-evidence digests with the captured package. A standalone
schema cannot prove those filesystem relations or reviewer truth. These
families remain outside the generic receipt parser and do not authorise
execution, promotion, installation or publication.

Review collections accept materialized lists or tuples, not streaming iterators.
Blocked review results require a blocker-severity finding; warning-only findings
cannot justify a blocked result. Returned review evidence requires observed
adapter invocation. These semantic invariants are enforced by models and
`SchemaRegistry`, not by standalone JSON Schema alone.

The offline callback service runs a caller-selected, importable and safely
pickleable adapter in a spawned process. It never falls back to in-process
execution or unsafe `fork`. Script callers need a guarded main entrypoint.
Child-local state changes do not update the original adapter object. Unsupported
transfer is a typed blocker; supplied-review validation remains read-only and
does not require process execution. See [API](api.md) for the separate startup,
callback, trusted-transfer and cleanup boundaries.

Skills SDK keeps portable contracts independent of Agent-Skills, Skills
Foundry, Codex, Tessl, and any local runtime filesystem. Host adapters and
providers consume the contracts through explicit boundaries; they are not
implicit dependencies of the core package.

## Runtime and dependency floor

- Python `>=3.12,<3.13`.
- Pydantic `>=2.11,<3` for typed contract models.
- JSON Schema Draft 2020-12 for packaged schemas.
- The repository's pinned `uv.lock` is the reproducible development toolchain.
- Filesystem package validation requires descriptor-relative, no-follow
  traversal support. Unsupported platforms return a typed blocker instead of
  weakening the symlink and special-file boundary.

Filesystem validation hashes one descriptor-captured view and rejects observed
file or directory changes during traversal. This is a best-effort quiescence
check for locally controlled source, not a transactional snapshot against a
privileged concurrent writer. Promotion callers must validate an immutable
source revision or prepared snapshot when adversarial concurrent mutation is
in scope.

The host-facing `runtime-copy-comparison/v1` and
`entrypoint-maintenance-result/v1` JSON families are versioned public result
contracts with packaged Draft 2020-12 schemas. Additive optional fields require
a compatible schema update; incompatible shape or meaning changes require a
new schema version.

## Contract policy

`package-archive-verification/v1` is an additive, read-only verification
result. It binds ZIP payloads to their manifest and candidate, with optional
archive-digest and package-receipt/v2 comparisons; it does not establish
installation or publication. Stored and DEFLATE entries are supported;
BZIP2, LZMA, and other methods are rejected before payload reads to preserve
bounded decompression. Malformed ZIP data returns typed blockers.
Manifest bytes must match the advertised length and satisfy the packaged
manifest schema before model conversion. Local and central compression headers
must agree. Fixed-size reads support large integer policy limits without
passing those limits directly to platform-sized read arguments.
EOCD-like bytes in ZIP comments are handled after locating a unique nonempty
central directory; competing nonempty directories fail closed. Only the
in-memory parser view omits the comment; the archive digest
still covers all original bytes, and the source archive is not changed.
Validate this family with `PackageArchiveVerificationReceipt` or
`SchemaRegistry` using `package-archive-verification.v1`. The generic
`parse_receipt` dispatcher intentionally returns `unsupported_receipt_family`
for it. Existing package-receipt/v1 and v2 parsing is unchanged.

Every versioned Pydantic model carries a `schema_version` where the contract
defines one. The `package-identity.v1`, `package-source.v1`, and
`package-owner.v1` JSON schemas intentionally accept the bare wire shape
without that envelope field.
`receipt-base.v1` requires `schema_version` and is not a bare-shape exception.
Use the corresponding model dump when a versioned payload is required. Unknown
model fields are rejected, portable paths are validated at the boundary, and
candidate-bound evidence keeps source revision and content digest together. A
validation failure is an explicit blocker; there is no waiver or suppression
path.

Within the `0.1.x` line, compatible additions may add optional data without
changing the meaning of existing fields. Changing required fields, enum
values, semantic invariants, or schema meaning requires a new schema version,
updated fixtures, and a compatibility note. Tests and the generated schemas
are the executable compatibility proof.

`skill-package-intake/v1` and `skill-package-intake-context/v1` are additive
contracts for read-only normalization and its caller-supplied context. They
do not reinterpret existing package, intake-decision, or receipt families.
`SchemaRegistry` validates them using `skill-package-intake.v1` and
`skill-package-intake-context.v1`, including their model-level invariants.
Neither belongs to generic `parse_receipt` dispatch: context payloads and both
normalized and blocked intake receipts fail with `unsupported_receipt_family`.
Use the intake models or registry directly; normalization is not admission,
installation, or publication evidence. Existing supported generic receipts
retain their dispatch behavior.

Intake rejects repository locators outside the documented `owner/repository`
slug form and rejects non-boolean raw checks before coercion. Prevalidated
shared check models retain their current values; intake cannot recover their
original inputs. Blocked receipts with a retained validation identity must bind
that identity to their candidate. These intake-local invariants do not change
the shared package, check, or validation contracts.

Intake receipt construction revalidates nested typed evidence, including
models inside mappings or sequences, just as it validates raw payloads.
Preconstructed shared models do not bypass their field constraints at this
receipt boundary; shared model configuration remains unchanged.
Evidence sequences use lists or tuples. Other iterable inputs, including
iterators and deques, are rejected rather than passed to nested coercion.
Cycles and nesting beyond the registry's 100-level JSON boundary fail validation;
repeated references without cycles remain valid. Intake always requires a
valid source revision, so even blocked intake retains its resolved candidate
and decision. Shared validation may still return an unresolved candidate for
an invalid revision; such a result cannot become an intake receipt.
Top-level intake context and receipt instances are revalidated on entry too;
passing a preconstructed instance does not bypass these intake constraints.
The generated intake schemas enforce the same repository slug grammar,
including rejection of trailing newlines. `build_intake_decision` revalidates
typed candidate and check inputs before projecting a decision; forged shared
instances cannot bypass the intake boundary or coerce non-boolean checks.
Repository slugs are checked before whitespace stripping or byte decoding;
direct model and service callers cannot normalize invalid raw locators.

`package-inventory/v2` and `package-inventory-set/v2` add the explicit
`needs_review` value decision for candidates whose value evidence is still
blocked. The corresponding `v1` models and schemas remain unchanged and reject
that value. Consumers may continue reading `v1`; producers that need the
pending-review state must emit the matching `v2` record or set envelope.

`package-receipt/v1` remains valid with its historical opaque
`package_digest`: consumers may validate its shape and receipt invariants, but
must not infer that the digest covers the embedded manifest. Builders now emit
`package-receipt/v2`, which preserves the v1 fields and additionally requires
`package_digest` to equal the SHA-256 digest of the canonical JSON manifest.
The generic receipt parser accepts both versions. Producers that require
manifest binding must emit v2; consumers may continue reading v1 while they
migrate without changing v1 semantics.

`scenario-observation/v1`, `scenario-case-result/v1`, and
`evaluation-receipt/v1` add a deterministic local evaluation boundary without
changing `scenario-set/v1` or `scorer-profile/v1`. The evaluator accepts only
deterministic scorer profiles and currently decides only `expected_signal`
oracles. Other scorer and oracle types remain valid declarations but require a
separate adapter and produce a typed blocker in the local service.

The explicit v2 evaluation family adds `scenario-set/v2`,
`scenario-observation/v2`, `scenario-case-result/v2`, and
`evaluation-receipt/v2`. V2 observations require the hardened, redaction-safe
`provider-identity/v2`; completed receipts bind one provider across every case
result. Provider identity v2 accepts provider-native slash-separated model IDs
while rejecting URI-scheme-bearing model IDs, empty path segments, and the
expanded credential-component set. `provider-identity/v1` retains its original
field grammar, credential screening, model behavior, and schema bytes;
provider-bearing v2 evaluation payloads reject a v1 identity instead of
reinterpreting it. V2 exact-match cases compare only
`expected_output_sha256` with the observation's `output_sha256`. A missing
expected digest returns the typed `exact_match_digest_required` blocker,
structured oracles remain blocked, and no raw output is accepted or retained.
Generic receipt parsing dispatches both evaluation receipt versions without
changing their payload meaning.

Selected-case orchestration reuses the existing v2 scenario, observation,
provider, and evaluation receipt families without changing their wire shape.
The additive `execute_selected_case_with_judge` Python API preserves the
existing supplied-evidence route while allowing a host-injected provider call
to finish before a host-injected judge sees its actual output. Both routes
produce the same v2 receipt family; neither turns a logical judge-result
reference into verified persisted content or proves a live provider when a
supplied-text adapter is injected.
Package-local case categories `edge` and `negative` project to the existing v2
`boundary` category only inside this loader. Requested modes must already be
declared by the selected case. Semantic assertion results remain external judge
evidence and require portable references plus matching candidate, scenario set,
case, provider, output, full assertion-contract, judge-adapter, and judge-result
digest identities; the SDK does not reinterpret textual keyword presence as
semantic proof. Deterministic text assertions are evaluated locally over the
private adapter output and are not retained as raw output.

The v1 models, schemas, fixtures, registry names, parser dispatch, and
`evaluate_scenario_set` semantics remain unchanged. In particular, v1
`exact_match` remains an `unsupported_oracle` outcome; callers must opt into
the v2 types and evaluator rather than placing v2 fields in a v1 payload.

Generic receipt parsing is fail-closed by wire version. Only explicitly
registered receipt families are accepted; a structurally base-compatible
future or foreign family is not treated as `receipt-base/v1`. Unknown families
return `unsupported_receipt_family`, while missing or non-string versions
return `invalid_receipt_schema_version`. This routing rule does not change the
payload meaning, candidate matching, or immutable generic representation of
any supported v1 or v2 receipt.

`scenario-quality/v1` is an additive registry-only receipt family. Validate it
with `ScenarioQualityReceipt` or `SchemaRegistry`; generic `parse_receipt`
intentionally returns `unsupported_receipt_family`. Version 1 fixes its portable
release policy at five to ten total cases with a target of eight, one
pressure-or-regression case, and one negative-or-edge case. The generated Draft
2020-12 schema and Pydantic model enforce identical policy evidence. Existing
generic receipt dispatch remains unchanged.

`scenario-quality/v2` is an opt-in registry-only family with an explicit
active release-set selector and exactly ten selected cases. It requires
`effective_policy` on the wire, including in blocked receipts, so consumers
can inspect the applied 10/10/10 budget rather than infer it from a model
default. All five `effective_policy` fields are required on the wire.
Additional YAML cases and nonselected historical release sets remain
source material, not active cases; Markdown fixtures are not imported
automatically. The v1 policy, schema, and default CLI behavior remain
unchanged, and generic `parse_receipt` still rejects both scenario-quality
versions as unsupported receipt families.

`registry-identity/v1` and `registry-preparation/v1` are additive contracts.
Registry identity fields reject credential-shaped values at component
boundaries while permitting ordinary identifiers that merely contain similar
text. A prepared receipt requires a built `package-receipt/v2`, a matching
package-hardening receipt, matching package/version identity, immutable
manifest and hardening digests, and portable unique evidence paths. The generic
receipt parser dispatches the new receipt without changing package v1/v2 or
evaluation v1/v2 semantics. Unknown receipt families continue to fail closed.
Blocked preparation binds non-path or credential-shaped hardening evidence by
SHA-256 separately from portable `evidence_refs`, so valid hardening inputs are
neither silently discarded nor exposed or reinterpreted as filesystem paths.
This contract records local preparation only; a future publication adapter must
produce separate registry evidence and bind the same candidate identity.

`package-safety-evidence/v1` is additive and does not reinterpret
`risk-classification/v1`, `security-screening/v1`, `package-hardening/v1`, or
any existing receipt family. Its four states are explicit: `not_reviewed`,
`reviewed_no_issue`, `issue_found`, and `metadata_insufficient`. Callers must
not translate a scanner `pass`, an empty finding list, or a skipped review
into `reviewed_no_issue` without the required digest-bound evidence. Generic
receipt parsing exposes `reviewed_no_issue` as `pass` and the remaining states
as `blocked`, while retaining the original state as `artifact_status`.
Unknown future safety families fail closed. The contract contains no generic
`safe` boolean and does not decide rights, admission, runtime behavior, or
publication.

`provider-execution-request/v1` and `provider-execution-result/v1` are
additive, secret-free adapter-envelope contracts. They require
`provider-identity/v2` and bind the exact candidate, scenario case, provider,
and digest-only request or result evidence. A prepared request does not prove
authorization or execution. A completed result is an adapter-supplied
observation, not an evaluation pass, safety or quality decision, billing
record, future availability claim, or general success statement. These
families are deliberately absent from generic receipt dispatch, so older
receipt payloads and unknown-family failure behavior remain unchanged.
Optional non-null replay provenance requires the prior result ID and the
SHA-256 of its complete canonical JSON envelope together; self-references fail semantic
validation. Direct Draft validation enforces the all-or-none field shape, and
`SchemaRegistry` applies the cross-field self-reference invariant.

`provider-call-adapter/v1` and `provider-call-result/v1` are additive offline
orchestration contracts in the `0.1.x` line. They do not change
`provider-identity/v2` or either provider-execution `/v1` envelope. The public
`skills_sdk.providers.execute_provider_call` service accepts only a prepared,
digest-bound request and an injected descriptor matching that request. The
selected pilot supports `response_generation` in complete or pull-driven
stream mode, preserves complete output outside public model serialization, and
performs zero automatic retries. Expected provider and adapter failures use
typed terminal evidence; contract violations raise `ContractError`, and caller
cancellation is not converted into a provider result. Passing offline
conformance does not prove a real provider outcome, supported provider, billing
accuracy, release, registry state, runtime state, or consumer compatibility.

`runtime-lock/v1` and `install-plan/v1` are additive schema families. They are
registered for structural and Pydantic semantic validation but are not generic
receipts: generic receipt parsing must not reinterpret intended runtime state
or a non-mutating plan as evidence that installation occurred. Later host
adapter apply, rollback, discovery, activation, and outcome families must use
new explicit schema versions rather than changing these v1 meanings.

The additive `installation-result/v1`, `rollback-journal/v1`,
`rollback-outcome/v1`, `discovery-observation/v1`,
`activation-observation/v1`, and `runtime-outcome/v1` families record distinct
adapter observations without changing runtime-lock or install-plan semantics.
Generic receipt parsing recognizes only the five receipt-shaped result and
observation families; rollback journals remain typed supporting evidence.
Draft 2020-12 enforces structural, state, public-text, and portable-path rules.
Cross-object equality and digest binding require the named Pydantic
`validate_against_*` method and are declared in schema semantic-validator
metadata rather than being silently approximated.
Optional provider-result and evaluation-receipt pairs in `runtime-outcome/v1`
likewise require their dedicated `validate_against_*` methods; pair completeness
is structural metadata, not proof that the referenced object was supplied.
Installation results include the planned operation so standalone consumers
cannot interpret a mutating `no_change` observation as successful evidence.
Digest equality across sibling fields remains part of Pydantic and registry
semantic validation because Draft 2020-12 cannot compare arbitrary values.
The five generic-receipt families require their version-specific `lane` on the
wire. Rollback outcome mutation state must match whether the bound journal has
an applied mutation for every status. `rollback_failed` and `indeterminate`
may therefore truthfully report either mutation state, but only when it agrees
with the journal; `blocked` remains non-mutating and `rolled_back` requires an
applied mutation with every journal entry applied. Generic parsing keeps a
rolled-back outcome blocked because rollback is not an installed success.

## Workflow migration proof

### Portable plugin capture increment

The additive `plugin-package-validation/v1` family does not reinterpret
`PluginIdentity`, `SkillIdentity`, standalone validation, intake, build or their
existing schemas. Only `validate-plugin` selects this new route. The canonical
source is root `plugin.json` under Agent Plugins 1.0.0, assessed against the
[normative specification](https://agent-plugins.org/specification) and
[OpenAI packaging semantics](https://developers.openai.com/plugins/build/plugins)
on 2026-10-08. This is a new portable contract, not executed Agent-Skills parity.

Source inspection of the queued Tessl-format implementation at revision
`02a43847f926a0ba7f9b4c29d763237d2805c939` supplied the bounded no-follow capture,
child/subtree binding and second-capture mechanisms. The consumer is subsequent
SDK whole-plugin preparation and evaluation, not the future registry service.
Deliberate differences: root manifest replaces Tessl metadata authority; no
required workspace/private field or directory-name match; base optional metadata
stays optional; unknown root fields and malformed `extensions` warn and are
ignored. Unknown diagnostics retain all sorted JSON-escaped key names, not
values, in an aggregated warning bounded by the metadata input budget.
Immediate child discovery replaces selectors and requires literal `SKILL.md`,
not lookalike filenames. Child file-role checks join retained roles to captured
relative paths without changing frozen standalone roles. OpenAI inline objects
replace, never merge, fallback settings. An ignored fallback is captured but
not parsed. Selected malformed fallback JSON blocks with typed invalid input.

The SDK rejects all symlinks and imposes documented capture/parsing budgets,
stricter than the portable standard's containment rules. Child assessment keeps
the existing SDK standalone semantics; an invalid child blocks this SDK result
while retaining sibling findings. A plugin with no discovered skills may be
structurally valid; that is not proof
of a useful managed release. MCP bytes and selected settings are bound without
claiming transport, destination, permissions or artwork validation. Ordinary
file modes have their own digest; the frozen candidate content formula is
unchanged. Empty directories are observed for capture stability but are not
part of candidate file identity.

Hash-only model and SchemaRegistry validation establish supplied envelope
consistency, not derivation of metadata or selected settings from actual source.
PR #52 accepted `verify_plugin_package_validation` and CLI
`validate-plugin --verify-evidence FILE` to compare a normalised full envelope
with fresh no-follow capture under the caller's revision and policy. Invalid,
stale, mismatched or unreadable inputs block. Raw settings remain private and
verification grants no execution, permission or release authority. The CLI reads
regular no-follow JSON up to 16 MiB and rejects duplicate members and malformed
input; default inspection behaviour remains unchanged. That accepted structural
verification does not establish the separate unmerged S4 execution route.
Blocked outputs preserve validated caller policy across evidence and revision
failures; malformed caller policy remains a typed input blocker before capture.
Blocked children also retain path-bound candidate IDs, including the unchanged
standalone fallback formula for invalid directory names. Model and registered
schema validation reject replaced IDs even when child identity is absent.
Plugin evidence also rejects coercible nested file sizes before parsing the
unchanged standalone manifest model. File paths retain component-kind blockers
they directly prove, including nonempty descendants of file-only locations;
empty directories still require source verification. The shared CLI context
reader rejects known special leaves before opening, while preserving no-follow,
post-open type, read-budget and drift checks for its existing callers.
The plugin-only ingress also rejects padded candidate identities, child identity
names, file hashes and finding codes before shared models can trim them. Frozen standalone
normalisation is unchanged; already-normalised objects cannot reveal their input
history. Descriptive whitespace remains valid. Captured fallback presence excludes
the `none` settings selection, while inline settings may still supersede malformed
unused fallback bytes. Retained MCP files require their unassessed warning, and
blocked children or missing required metadata retain their specific blocker codes
and severities. These checks apply to bound envelopes, not empty input blockers;
they do not establish source authenticity or MCP execution safety.

Synthetic accepted/rejected/recovery cases are in
[`test_plugin_package.py`](../tests/test_plugin_package.py) and
[`test_plugin_envelope_review.py`](../tests/test_plugin_envelope_review.py), with
safe synthetic pre-open cases in
[`test_plugin_context_preopen.py`](../tests/test_plugin_context_preopen.py) and
[`installed_plugin_intake_smoke.py`](../tests/installed_plugin_intake_smoke.py).
The latter uses the installed wheel's public API, packaged schema and CLI with
no sibling project, provider, registry or editable SDK import. See the task
record for validation/delivery state; test presence alone is not passing proof.

### Existing migration increments

The additive `scenario-coverage-plan/v1` and `scenario-coverage/v1` families
audit caller-declared claim-to-case-or-gap mappings against the package's
ten active scenarios. Existing scenario-quality v1/v2 receipts, local-check v1,
and their policies do not change. Calibration probes and historical cases
cannot satisfy an active-case mapping. Named gaps preserve incomplete coverage,
even when the mapping audit passes. Model and `SchemaRegistry` validation
enforce cross-field semantics beyond structural JSON Schema. Neither family
enters generic `parse_receipt` dispatch; use its model or registry. The source
skill's Evals Router audit shape guides this implementation; no executed
Agent-Skills parity or semantic reviewer execution is claimed.

Coverage mappings and active-case identifiers preserve surrounding whitespace
exactly, matching the scenario-quality inventory rather than normalising it.
Whitespace-only and non-text identifiers remain invalid. Distinct identifiers
such as `case-0` and ` case-0 ` remain distinct and can be mapped separately.

Direct plan models and `SchemaRegistry` reject duplicate declaration or mapping
identifiers, unknown claim or gap references, mapping entries without case or
gap references, repeated references, and unused gaps. A declaration may omit a claim's mapping so
the audit can report `unmapped_claim`; contract validation alone does not
establish complete coverage. Active-case membership requires the package
inventory and is checked by the audit, not standalone plan validation.

The applicable package-quality policy is an additive increment, not full
reference-review parity. Legacy `reference_quality_contract` checks nonempty
reference content and structured syntax, but also applies filename/title
heuristics and contract-specific fields. The SDK ports the deterministic byte
and syntax checks behind explicit `check_reference_content`; semantic title,
description, coverage and source-accuracy review remain separate work.
Binary references are deliberately excluded from text checks, rather than
requiring every resource to decode as UTF-8. JSON rejects non-standard numeric
constants and validates large integer tokens without numeric conversion.
Markdown suffixes listed in the API contract receive the same checks as `.md`;
leading UTF-8 BOMs are not content. The opt-in text check has an eight-MiB
per-reference parsing budget with a typed `reference_content_limit` blocker.
This does not bound the preceding package capture or waive source safety.
YAML uses syntax events, not object construction, so custom tags and
multiple documents remain valid reference formats. This deliberately differs
from the source's single-document constructor; syntax acceptance is not safety
clearance. Incremental YAML parsing stops above 128 nested collections or
100,000 events with `reference_content_limit`; excessive but syntactically
valid documents are deliberately blocked. This does not promise a wall-clock
deadline. Required files are explicit policy,
not a global OpenAI or repository layout requirement. Defaults and versioned
validation/build/intake envelopes remain unchanged. Corrected source produces
a new candidate digest; validation never changes the source.
The existing result envelope does not record the effective validation policy.
Retain the selected policy and exact command with evidence; an unspecified
passing v1 validation result does not prove these opt-in checks ran.

Retained proof includes `tests/test_package_quality_policy.py` and the installed
API/CLI smoke in `tests/installed_package_quality_smoke.py`. Source semantics
were inspected; live Agent-Skills execution is not claimed by these SDK tests.

Before porting a workflow, identify the source revision, production consumer,
supported input forms, policy declarations, and failure semantics. Use the
source implementation and representative accepted and rejected cases to
establish the expected behaviour before writing the SDK implementation.
Do not infer compatibility from a destination policy or a similar model name.

Exercise equivalent cases through the source and SDK public entrypoints.
Retain synthetic, portable fixtures in the existing test family; never copy
private package contents or machine paths. Cover declared policy values as
well as effective defaults, alternative supported selector shapes, and
malformed neighbours. Document deliberate differences and their consumer
impact. If the source cannot run, record the exact blocker and the narrower
source inspection or fixture evidence; do not claim executed parity.

Local SDK proof, downstream consumer cutover, and Agent-Skills retirement
remain separate outcomes. Required schema and compatibility checks still
apply. Run `bash scripts/validate-repository.sh` and record `pass`, `fail`, or
`blocked`; for `blocked`, record the concrete blocker and nearest fallback.

### Scorer assessment extraction

At Agent-Skills source revision `532962c65ef0549d16168c0e899c9cb8dc032188`,
`build_scorer_quality_receipt` checks `references/evals.yaml` scorer metadata
and six calibration probe declarations; `build_scorer_calibration_receipt`
checks a held-out bundle manifest, JSONL examples, raw artifacts, threshold,
coverage, and false positives. The SDK's `assess_scorer_quality` and
`assess_scorer_calibration` retain those accepted/rejected distinctions through
candidate-bound public services and CLI routes. The SDK deliberately rejects
YAML aliases and duplicate keys through its existing bounded loader, requires
raw artifacts to be in the declared directory and validated candidate, rejects
duplicate held-out ids and artifact paths or string-coerced numeric limits, and
requires the bundle scorer identity to agree with a valid declaration. These
are stricter safety and binding checks than the source preview. Both systems
assess caller-supplied artifacts; neither executes a live judge or proves
external artifact provenance. The ten active managed scenarios are unchanged.
The SDK receipts intentionally replace the source preview's query, local
paths, pass-check list, and acceptance-trace strings with candidate identity,
portable blocker findings, applied calibration policy, retained judge
parameters, and confusion-derived rates. Source `preview` maps to SDK `pass`;
source `blocked` remains `blocked`. Expected scores outside `[0, 1]` are also
blocked by the SDK's stricter typed outcome check.
For judge scorers, the quality receipt retains declared model, temperature,
and trial count; held-out bundles must match those parameters as well as scorer
identity and threshold. A mismatch yields a typed blocker, not calibration proof.
The SDK also binds each expected outcome to its probe type: obvious-correct
must pass, and rejection probes must fail. The comparative verbosity probe
must declare `short_correct_wins`; it may also declare the losing verbose
candidate as `fail` with a score below the pass threshold. This preserves the
source's combined direction and losing-candidate evidence. Label and score
must be supplied together when either is present. A partial or contradictory
label, score, or direction remains blocked, and no judge is executed here.
This extraction covers scorer quality and held-out calibration only; it does
not complete the nine-area evaluation workflow or downstream consumer cutover.

`local-check/v1` is an additive registry-only CLI envelope for the ordered,
read-only intake-to-check slice. Its generated schema and Pydantic model bind
the candidate, stage names and receipt types, blocked stage, and no-promotion
flags; validate serialized output with `SchemaRegistry().validate("local-check.v1", payload)`.
The generated Draft 2020-12 schema enforces wire-visible fields and stage
shape; candidate equality and nested receipt invariants still require the
registry's semantic validator, as declared by the schema metadata.
Unsupported safe context reads produce an empty-stage blocked envelope with
an `unsupported_context_read` typed blocker. The existing stage receipt
versions and generic `parse_receipt` dispatch do not change. A local pass is
not external admission, live execution, publication, or installation proof.

## Separate evidence lanes

The PR-sweep validators provide portable SDK API and CLI equivalents for two
Agent-Skills local checks. Source assessment is pinned to Agent-Skills revision
`532962c65ef0549d16168c0e899c9cb8dc032188`:
`Skills/agent-ops/pr-green-sweep/scripts/validate_recurring_findings.py` and
`Infrastructure/scripts/validation-and-linting/validate_pr_sweep_dirty_closeout.py`.
The source recurring-finding test family
`Infrastructure/tests/test_pr_green_sweep_recurring_findings.py` passed 12 cases
using the SDK test interpreter with bytecode and pytest cache writes disabled.
On one disposable Git fixture, the source and SDK dirty-closeout CLIs both
returned pass for clean, fail with `primary_worktree_dirty` for a modified
tracked file, then pass after restoration. SDK regression fixtures separately
cover the recurring guardrail's accepted, rejected, and corrected forms.
This is bounded source-parity evidence, not consumer cutover or full PR-sweep
workflow equivalence.

The recurring validator retains the source ledger's schema version and
three-occurrence guardrail semantics. The dirty validator retains the
distinction between ledgered dirt and a clean checkout. Deliberate differences:
the SDK requires an explicit repository root, returns versioned portable
results with exit `2` for rejected or blocked input instead of the source
scripts' exit `1`, redacts host paths and untrusted values, and blocks unsafe
Git status inspection rather than executing configured helpers. It does not
run the source environment wrapper, hosted PR review, readiness receipt,
thread resolution, merge, or cleanup. Installing and repointing the consumer
skill remains separate cutover proof.


The SDK's local contract and schema checks do not prove provider execution,
runtime installation, Tessl publication, or installed behavior. Those lanes
must bind the same candidate identity and report their own evidence.

## Tessl to Codex native-plugin compatibility question

The following CLI 0.111.0 experiment concerns the older Codex compatibility
layout. Retain it as historical evidence, not a claim about today's CLI or the
new canonical root-manifest format. The next adapter proof must cover the
portable plugin target and any explicitly selected compatibility import.

The SDK does not yet claim that a Tessl plugin archive can carry a complete
Codex-native plugin. Tessl's documented plugin manifest selects skills, rules,
commands, MCP metadata, and hooks; OpenAI's native plugin also requires its
manifest and any referenced assets and executable resources. These are separate
package and host contracts, not interchangeable plugin identities.

With Tessl CLI 0.111.0, a disposable plugin containing a valid
`.tessl-plugin/plugin.json`, `.codex-plugin/plugin.json`, one skill and reference,
`hooks/hooks.json` and its script, `.mcp.json` and its referenced script, and an
asset passes `tessl plugin lint` and `tessl plugin pack`. Archive inspection
shows the skill, reference, hook files, and `.mcp.json`, but omits the Codex
manifest, asset, and MCP script. The MCP metadata can therefore survive while
its executable resource does not. An exploratory `include` array in the Tessl
manifest did not alter the archive, despite lint passing; it is not a supported
inclusion contract. An out-of-package `skills: ../skills` path was rejected,
and restoring the valid path recovered a passing pack with the same omissions.

To reproduce the archive comparison from the disposable fixture parent, run
`tar -tzf skills-sdk-v4-fixture.tgz`. Its complete listing was
`.tessl-plugin/plugin.json`, `skills/fixture-skill/SKILL.md`,
`skills/fixture-skill/references/example.md`, `hooks/session_start.py`,
`hooks/hooks.json`, `.mcp.json`, and `tile.json`. The fixture source also
contained `.codex-plugin/plugin.json`, `assets/icon.txt`, and `scripts/mcp.js`;
none appeared in that archive listing. This is an archive-content observation,
not a claim that the existing Tessl-format wrapper for skill evaluation is
absent or unusable.

Compatibility question for Tessl: what documented manifest field or package
layout includes *all* required plugin resources, including canonical root
`plugin.json`, any selected compatibility manifest, assets and scripts outside skill directories, in
the versioned archive without changing their contents, relative paths, or
executable modes? If that is supported, which Codex integration installs the
complete archive as one plugin rather than only materializing its skills, MCP
configuration, and hooks? Until both questions have tested answers, a local
Tessl pack, SDK receipt, or install plan must not be labelled native-plugin
preservation, Codex discovery, private-registry installation, or execution
proof. Do not move unrelated resources into a synthetic skill merely to make
the archive appear complete.
