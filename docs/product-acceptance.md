# Product acceptance

This is the SDK-owned acceptance record for the independent Skills SDK product.
Its original programme baseline was
`541e16e27ad73fe5045640aead2b5373fe1a338f`; later evidence blocks name their
own exact candidate and base. It does not turn local contracts, schemas, old
temporary worktrees, or programme summaries into product proof.

Update a row only when its candidate and evidence are durable. Use
`not_verified`, `in_progress`, `verified_local`, `delivered`, or `blocked`, and
state which evidence lane the status covers. A local status never establishes
release, provider, runtime, registry, distribution, or consumer truth.

## Acceptance matrix

The target owner is the SDK agent-facing `SKILL.md`, references, and evaluation
workflow for complete skill and plugin creation, updates, checks, external
intake, and selected installation through SDK-owned registry and host adapters,
initially Tessl and Codex. Use the [workflow](workflow.md) for current accepted
capabilities and the [delivery record](projects/sdk-workflow/tasks.md) for merged
revisions; the historical evidence blocks below do not override those states.
Foundry holds candidates awaiting SDK processing, including rejected or
blocked candidates retained with reasons; holding does not clear or distribute
them. The existing `admit_to_foundry` inventory disposition retains its
evidence-gated intended meaning and is not a holding-state synonym.
Managed releases are complete root-manifest plugins, including one-skill
releases. Checked versions need verified publication/readback through the
selected registry before managed installation; private Tessl `jscraik` is the
initial route, not a permanent requirement. Do not start or create the future
registry, including a catalogue or prototype, until the SDK workflow meets its
agreed acceptance criteria and correct private Tessl publication is verified.
An independent registry becomes
primary only after the [transition gates](workflow.md#registry-transition);
only Jamie can choose public release.
Origin-verified OpenAI-provided plugins and system skills remain provider-managed
and exempt. These are acceptance targets, not claims that the operations exist
today. The portable core stays independent of those integration clients.

| ID | Required outcome | Current evidence | Status | Next closure condition |
| --- | --- | --- | --- | --- |
| SDK-1 | Exact-revision disposition of the full Agent-Skills SDK surface | No durable module, symbol, and production-caller matrix is stored here. | `not_verified` | Import the independently reviewed classification as an exact-revision SDK record and resolve every entry to one allowed owner. |
| SDK-2 | Executable portable lifecycle engines | Intake, validation, package construction, deterministic scoring, safety evidence contracts, registry preparation, and runtime planning exist. Whole-report orchestration and other temporary candidates are missing and cannot be counted. | `in_progress` | Close every named engine with durable implementation, public interface, conformance, and recovery proof. |
| SDK-3 | Provider protocol and reference adapter | The SDK-3.1 offline executor, typed complete-or-stream adapter protocol, credential boundary, public evidence, and local conformance are implemented and verified below. No packaged reference adapter or real-provider evidence exists. | `verified_local` | Select and prove a packaged reference adapter, then separately close authorized real-provider and hosted Ubuntu evidence. |
| SDK-4 | Runtime host protocol and transactional lifecycle | Candidate-bound planning and evidence models exist without package install, host apply, rollback, discovery, activation, uninstall, or retirement mechanisms. Existing-copy maintenance is narrower than installation. | `in_progress` | Implement SDK-owned host integration, initially Codex, and prove selected checked registry-version identity, discovery, behavior, rejection and recovery without changing provider-managed exemptions. |
| SDK-5 | Registry adapter interfaces and selected implementations | Immutable local preparation exists without registry interaction, private-visibility readback, upload, promotion, deprecation, or revocation. | `in_progress` | Prove initial private Tessl publication/readback/install through an explicit adapter; keep canonical artifacts and evidence independent. A future registry default requires representative dual-destination proof, not catalogue visibility alone. |
| SDK-6 | Executable CLI and composable orchestration | `intake`, `check-local`, `check-quality`, `review-content`, `validate`, `validate-plugin` (including `--verify-evidence`), `build`, `eval scenario-quality`, `eval scorer-quality`, `eval scorer-calibration`, `eval observed-calibration`, `eval selected-case`, `verify recurring-findings`, `verify pr-sweep-dirty-closeout`, `compare-copy`, and `maintain-entrypoint` execute locally; maintenance may modify an existing host file only with `--apply`. `inventory`, `package`, `project`, and `tessl` remain discovery boundaries. Static scorer checks do not execute judges; observed calibration CLI uses supplied offline verdicts. No complete plugin create/update/external-intake/check/install workflow is established. | `in_progress` | Connect the agent-facing workflow to complete-plugin orchestration and prove stable JSON, exit, failure, recovery and mutation boundaries for every implemented route. |
| SDK-7 | Independent product operations | Pinned Python tooling, schemas, tests, CI, and reproducible local builds exist. Release, supported matrix, fuzzing, benchmarks, signed artifacts, documentation publication, and maintained examples remain incomplete. | `in_progress` | Record selected matrices and thresholds, then close release and maintenance evidence without relying on Agent-Skills. |
| SDK-8 | Released external-consumer proof and retirement | No released SDK consumer, checked private Tessl version, selected Codex runtime installation, or completed Agent-Skills fallback retirement is proved here. | `not_verified` | Prove maintained consumers and non-exempt installed versions against a released SDK, preserve verified OpenAI exemptions, and complete parity, rollback, and retirement evidence. |

None of these rows is complete. The matrix is not a completion percentage and
does not change Foundry source custody, package rights, host policy, provider
credentials, registry identity, or distribution authority.

## Managed release gates

The following strengthen existing SDK-2 through SDK-8 acceptance; they are not
a second delivery tracker. Coverage below was inspected at accepted code
`817966b378be0da45928fbaef89b2ede3708b012` on 2026-10-08. These requirements
are product policy, not claims that the gates already execute. Use the
[workflow policy](workflow.md#icons-and-presentation) for icon design and current
OpenAI destination limits, and the [current resume point](projects/sdk-workflow/tasks.md#proof-lanes-and-resume-point)
for implementation order.

| Gate | Existing accepted proof and limitation | Required acceptance |
| --- | --- | --- |
| Icons and presentation | [Skill capture](../tests/test_skill_package_validation.py) and [ZIP verification](../tests/test_package_archive_verification.py) bind generic asset bytes. [Intake](../tests/test_package_intake.py) checks supplied package rights; neither proves image rights, approval, decoding or host display. | Every Jamie-owned managed plugin has approved professional artwork. Bind approval and rights, decoded file validation, safe manifest closure, exact archive presence and candidate identity. Reject missing, malformed, oversized, non-square, escaping, stale or unapproved artwork; corrected inputs recover without source mutation. Preserve licensed third-party branding. Verify names, descriptions and starter prompts against actual capability, with screenshots/onboarding only when applicable. An authorised host observation must separately show the correct icon. |
| Destination compatibility | Existing skill contracts and archive checks do not implement canonical portable-plugin conversion or destination presentation profiles. | Pin specification and adapter versions; prove representative portable and destination packages preserve required content and behaviour. Unsupported components return explicit blockers, never silent loss. Distinguish declared, structurally checked and observed compatibility. |
| Discovery and activation | [Runtime evidence contracts](../tests/test_runtime_execution_evidence.py) validate supplied observations; the SDK does not observe or activate a plugin. | An authorised observing adapter proves direct, indirect, incomplete and unrelated requests, including overlapping skills. Expected activation, negative activation and clarification/routing all need evidence for the exact installed candidate. |
| Update permissions | [Safety evidence](../tests/test_pre_execution_safety.py) and [static screening](../tests/test_security_screening.py) support candidate-bound checks, not baseline-to-candidate permission interpretation. | Compare hooks, MCP servers, destinations, dependencies and access. Unchanged or reduced permissions have valid neighbouring cases; expansion is visible and blocks dependent operations without renewed authority. Corrected input or applicable approval recovers without inheriting baseline authority. |
| Bounded optimisation | [Provider limits](../tests/test_provider_call.py) and [observed calibration](../tests/test_observed_calibration.py) bound work; they do not establish an optimisation budget, matched lift or live quality. | Freeze budgets, stop rules, minimum meaningful improvement and regression limits before execution. Prove same-lane comparability, variability reporting, budget exhaustion and rejected promotion for unchanged/inconclusive results. Cloud baseline is the accepted local winner; changed candidates need fresh affected safety and evaluation evidence. |
| Artifact completeness | [Archive verification](../tests/test_package_archive_verification.py) checks supplied ZIP content against the manifest; it is not archive emission or complete-plugin/mode preservation. | Inspect emitted and converted archives, not just directories. Required resources, artwork and executable modes survive; missing files, unsafe paths and incompatible representations block. Exclude secrets, private review/provider evidence and held-out answers. Public attribution remains available where required. |
| Recovery and retries | [Provider calls](../tests/test_provider_call.py) classify retryable failures but perform zero automatic retries. [Runtime evidence](../tests/test_runtime_execution_evidence.py) models recovery without executing publication, install or rollback. | Prove interruption, repeated requests, idempotency and conflict handling. Read back uncertain publication before any retry; unavailable readback blocks dependent mutation. Failed installation preserves or restores the previous working version, with observed lock/runtime recovery and a typed blocker when recovery cannot be verified. |

For the future [registry consumer boundary](../ARCHITECTURE.md#brainwav-product-family),
prove isolated SDK operation without registry accounts, databases or server
imports, and consumer tests against the installed pinned SDK package actually
deployed. Reject production dependence on editable/neighbouring checkouts or
private SDK modules. Registry workers use public APIs/versioned schemas without
duplicating lifecycle logic or inheriting website publishing credentials.
Registry display must retain the exact version's artwork and attributed
evidence. These are future consumer acceptance criteria, not authority to start
the registry before the existing gate or claims of deployed proof.

Image and approval checks must distinguish file validity from visual quality;
passing a decoder is not professional-design approval. An icon-only change
requires a new candidate and affected proof, followed by normal versioned
delivery. Inventory and schedule existing managed plugins; do not bulk-rewrite
installed copies or alter verified provider-managed packages.

Keep exactly ten active managed scenarios. Implementation, compatibility,
security, calibration and held-out tests are not capped at ten. Validators and
build remain read-only; generation, normalisation and repair are explicit
preparation operations. Prove accepted, rejected and corrected inputs through
supported public API and installed CLI routes without sibling projects. Use
controlled adapters for offline proof and obtain separate authority for external
state checks. No row above authorises provider spending, credentials, uploads,
publication, installation or registry creation.

## Evidence invalidated by temporary-worktree loss

The former provider-call, whole-report, evaluation, archive follow-up, runtime,
and product-acceptance worktrees are physically absent. Their Git registrations
are stale, and the provider branch contains no candidate commit beyond
`c5b04b0116474852153a3258eb15f74befc9eb70`. Narrative checkpoints may guide
reconstruction, but their uncommitted bytes, hashes, and test runs are not
reusable acceptance evidence.

Merged source remains durable. Pull request 27 is represented by merge commit
`541e16e27ad73fe5045640aead2b5373fe1a338f`, whose reviewed source head was
`6bb92d07b87896f5463c22b582394c01dcf8f0c2`. This records topology only; it does
not retroactively alter the review gate that existed before the external merge.

## Historical pilot: provider call conformance

This section retains the SDK-3.1 pilot contract and its dated evidence. It is
not the current slice instruction; use the existing
[delivery record](projects/sdk-workflow/tasks.md#proof-lanes-and-resume-point).

### Outcome and consumer

`SDK-3.1` supplies one SDK-owned, offline, portable text-provider executor that
an evaluation orchestrator can call through an injected adapter. The immediate
consumer is SDK evaluation execution. The SDK owns request normalization,
bounded orchestration, typed events and public evidence. An adapter owns
credentials, transport, provider-specific payloads, and externally reported
truth.

### Public API and ownership

The service owner is `src/skills_sdk/providers/call.py`, exposed as
`skills_sdk.providers.execute_provider_call`. Contract-only models belong in
`src/skills_sdk/models/provider_call.py`; the existing
`src/skills_sdk/models/provider_execution.py` remains the owner of the
`provider-execution-request/v1` and `provider-execution-result/v1` evidence
envelopes. The root `skills_sdk` package may re-export the new entrypoint only
after its focused import and behavior proof passes.

The selected public shape is one asynchronous entrypoint:

```python
async def execute_provider_call(
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: TextProviderAdapter,
    *,
    limits: ProviderCallLimits = DEFAULT_PROVIDER_CALL_LIMITS,
    clock: ProviderCallClock = DEFAULT_PROVIDER_CALL_CLOCK,
) -> ProviderCallOutcome: ...
```

`request` must be a revalidated, `prepared` request whose declared capability
is `response_generation`. `input_payload` is private JSON-compatible input and
must hash to `request.input_sha256` through the repository's canonical JSON
digest; it is never copied into public evidence. `JsonValue` means null,
boolean, integer or finite float, string, or recursively nested string-keyed
objects and arrays within the selected size and depth limits.
The injected adapter has one immutable, secret-free descriptor that must match
the request's `ProviderIdentityV2`, and it offers either one complete text
response or one pull-driven text event stream. The limits object may only
tighten the SDK defaults.

`ProviderCallOutcome` contains a private complete text value only on success
and a public, request-bound execution result with compact event evidence. The
public result contains no raw input, output, credential, provider payload, or
exception text. Expected unsupported capability, policy block, adapter or
provider failure, timeout, and indeterminate interruption are typed terminal
outcomes. Invalid caller input, forged models, identity or digest mismatch,
malformed adapter events, limit violations, and events after termination fail
the call with `ContractError`. Caller cancellation remains
cancellation after bounded cleanup; cleanup failure is attached as redacted
diagnostic evidence and never replaces the primary failure or cancellation.

### Scope

The smallest effective mechanism is one asynchronous call entrypoint supporting
one non-streaming text result and one pull-driven streaming text event path.
Reuse `ProviderExecutionRequest`, `ProviderExecutionResult`, and
`ProviderIdentityV2`; add an additive adapter descriptor, capability negotiation,
execution result, and event contract only where the existing envelopes cannot
express observable behavior.

This unit excludes network access, real providers, credentials, dependency
installation, automatic retries, CLI wiring, evaluation judging, runtime or
registry mutation, a packaged reference adapter, release, and remote promotion.

### Supported pilot matrix and compatibility

- The package contract is Python `>=3.12,<3.13`; the pilot must run on Python
  3.12 and may not claim compatibility with another Python line.
- The selected offline conformance matrix is CPython 3.12 on the repository's
  `ubuntu-latest` GitHub Actions job. Local macOS or Windows runs may provide
  additional evidence, but neither operating system is selected as a supported
  pilot target until it has a pinned required job and recorded result.
- The repository package remains in the `0.1.x` compatibility line. New
  provider-call wire models are additive `/v1` families. They must not change
  the fields, enum meanings, schema validation, or public behavior of
  `provider-execution-request/v1`, `provider-execution-result/v1`, or
  `provider-identity/v2`.
- `SDK-3.1` names this programme unit, not a package release or schema version.
  Passing the pilot does not select a reference provider, publish a release, or
  establish support for a provider, registry, runtime, or consumer platform.

### Selected limits and behavior

- Accept JSON-compatible input up to 256 KiB, with metadata up to 64 KiB and a
  maximum nesting depth of 32.
- Accept a complete non-streaming text result up to 1 MiB.
- Limit each streaming text chunk to 16 KiB, total output to 1 MiB, and the
  stream to 4,096 events.
- Permit one in-flight adapter pull and buffer at most eight validated events.
- Apply a 30-second overall deadline and five-second idle deadline through a
  caller-injected SDK clock. The provider adapter cannot supply or replace the
  timeout scheduler. Cleanup gets one bounded second.
- Perform zero automatic retries in this pilot. Preserve retry classification
  as typed evidence so bounded retry remains an explicit parent requirement.
- Preserve the primary failure when cleanup also fails. Distinguish known
  provider or adapter failure from indeterminate interruption.
- Keep complete output private. Public results contain compact bindings,
  redacted classifications, usage and cost observations, timestamps, and
  evidence references without raw prompts, output, credentials, or exceptions.
- Reject external descriptors that attempt discovery by filesystem glob,
  environment scan, network lookup, or implicit import side effects.
- Cancellation stops further pulls and runs bounded cleanup. No event emitted
  after cancellation, deadline, or terminal failure may change the result.

### Proof groups

1. Descriptor identity, capability negotiation, and unsupported-mode blockers.
2. Non-streaming success, size boundaries, request/result binding, and private
   output separation.
3. Streaming ordering, chunk/event/output limits, bounded pull and buffering,
   and exactly one terminal result.
4. Overall and idle deadlines, including a stalled pull and stalled end-of-stream.
5. Caller cancellation and bounded cleanup, including cleanup failure.
6. Credential isolation and redaction-safe known and indeterminate failures.
7. Usage and decimal cost preservation without treating provider claims as SDK
   measurement truth.
8. Deterministic replay with offline fixtures, schema parity, forged-model
   revalidation, and unchanged v1 provider-envelope behavior.

### Measurable acceptance and proving commands

The focused proof must execute the real public entrypoint through deterministic
offline adapters. Acceptance requires all of the following:

- Every proof group above has a passing success case and its named failure or
  boundary case; the size, depth, event, buffering, pull, deadline, and cleanup
  limits are asserted at the exact boundary and one unit beyond it.
- Success produces exactly one terminal result bound to the request and output
  digest, retains complete output only in the private return value, and emits
  no secrets or raw payloads in public models, exception text, or captured logs.
- Each blocked, failed, timed-out, indeterminate, and cancelled path stops
  further adapter pulls. Cleanup runs at most once within one second, and a
  cleanup failure preserves the original terminal classification.
- The suite proves at most one in-flight pull, at most eight buffered validated
  events, no state change after termination, zero automatic retries, and
  deterministic public evidence for the same fixture and injected clock.
- Existing provider request, result, identity, schema, and import-boundary tests
  pass unchanged. Generated schema checks and the aggregate repository gate
  finish with exit `0`.

Run and record these exact commands on the completed candidate:

```bash
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_provider_call.py tests/test_provider_call_review_regressions.py tests/test_provider_call_adapter_boundaries.py tests/test_provider_call_typing.py tests/test_provider_execution_contracts.py tests/test_provider_execution_review_regressions.py tests/test_public_repository_boundary.py
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen python scripts/generate_schemas.py --check
bash scripts/validate-repository.sh
```

### Completed local evidence

The signed acceptance baseline at `e7014ac9498920acfababa1934dcaeae146aee7d`
was implemented as one 18-path SDK-3.1 candidate, with this acceptance update as
its nineteenth owned path. On the frozen implementation bytes:

- The then-current focused command passed 281 tests in 63.21 seconds.
- Schema generation check passed with exit `0`.
- `bash scripts/validate-codestyle.sh` passed formatting, Ruff, MyPy,
  repository standards, and documentation checks.
- The original independent review returned `NO_FINDINGS` after reproducing the deadline,
  cancellation, redaction, malformed-event, buffering, digest, selected-mode,
  and static adapter-typing boundaries.
- `bash scripts/validate-repository.sh` passed 1,442 tests with one skip in
  272.94 seconds and built both the source distribution and wheel.
- `git diff --check` passed, and the reviewed implementation hashes remained
  unchanged after the aggregate gate.

The preserved implementation commit
`1ceeb54ff8a1c8be0589a32b28c4a70b560dcde8` supplied the replay provenance for
then-observed `origin/main` at `f5ebdbde687265e58033403f8a0cfb9debc54abe`.
Independent compatibility review then found that the provider adapter owned
the scheduler intended to enforce SDK deadlines. The repaired implementation
commit `665b035` moves scheduling to a caller-injected SDK clock and adds a
regression proving an adapter-supplied bypass clock cannot disable the overall
deadline. The exact PR #29 documentation contract was then integrated locally;
the containing commit is the final candidate for this evidence block.

On that then-final candidate before the current review-repair commits, the
focused provider and architecture suite passed,
the generated-schema check passed, and `bash scripts/validate-repository.sh`
passed 1,443 tests with one skip and built the source distribution and wheel.
Final independent re-review confirmed the deadline bypass was closed and
treated the pending intake commit `ff02000` as a future overlap rather than a
present dependency.

This is local macOS offline conformance evidence only. It does not establish
the selected `ubuntu-latest` hosted job, real-provider behavior, a packaged
reference adapter, credential or spend authority, an installed consumer,
publication, release, or programme completion. The zero-retry pilot preserves
retry classification but does not close the parent retry-policy requirement.

## Remaining decisions

- Select the separately packaged reference provider adapter and its owner.
- Select retry policy and budgets beyond the zero-retry pilot.
- Select real-provider credentials, data, spend, and execution authority.
- Select supported Python and operating-system release matrices.
- Select registry and runtime adapters and their real destinations.
- Select the first maintained external consumer and Agent-Skills retirement
  condition.

Unknown selections remain blockers for their own lanes, not permission to infer
support or to stop unrelated local conformance work.
