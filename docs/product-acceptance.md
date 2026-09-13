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

| ID | Required outcome | Current evidence | Status | Next closure condition |
| --- | --- | --- | --- | --- |
| SDK-1 | Exact-revision disposition of the full Agent-Skills SDK surface | No durable module, symbol, and production-caller matrix is stored here. | `not_verified` | Import the independently reviewed classification as an exact-revision SDK record and resolve every entry to one allowed owner. |
| SDK-2 | Executable portable lifecycle engines | Intake, validation, package construction, deterministic scoring, safety evidence contracts, registry preparation, and runtime planning exist. Whole-report orchestration and other temporary candidates are missing and cannot be counted. | `in_progress` | Close every named engine with durable implementation, public interface, conformance, and recovery proof. |
| SDK-3 | Provider protocol and reference adapter | The SDK-3.1 offline executor, typed complete-or-stream adapter protocol, credential boundary, public evidence, and local conformance are implemented and verified below. No packaged reference adapter or real-provider evidence exists. | `verified_local` | Select and prove a packaged reference adapter, then separately close authorized real-provider and hosted Ubuntu evidence. |
| SDK-4 | Runtime host protocol and transactional lifecycle | Candidate-bound planning and evidence models exist without host apply, rollback, discovery, activation, uninstall, or retirement mechanisms. | `in_progress` | Implement adapter-driven transactional lifecycle and prove it against an isolated fake host before any selected real runtime. |
| SDK-5 | Registry adapter interfaces and selected implementations | Immutable local preparation exists without registry interaction, upload, promotion, deprecation, or revocation. | `in_progress` | Select a registry adapter and close offline idempotency and lifecycle conformance before separately authorized external proof. |
| SDK-6 | Executable CLI and composable orchestration | `validate` and `build` execute; other advertised lifecycle routes remain parse-only. | `in_progress` | Connect only implemented services and prove stable JSON, exit, failure, and recovery behavior for every advertised selected route. |
| SDK-7 | Independent product operations | Pinned Python tooling, schemas, tests, CI, and reproducible local builds exist. Release, supported matrix, fuzzing, benchmarks, signed artifacts, documentation publication, and maintained examples remain incomplete. | `in_progress` | Record selected matrices and thresholds, then close release and maintenance evidence without relying on Agent-Skills. |
| SDK-8 | Released external-consumer proof and retirement | No released SDK consumer proof or completed Agent-Skills portable fallback retirement is stored here. | `not_verified` | Prove a maintained destination against a released SDK and complete its accepted parity, rollback, and retirement record. |

None of these rows is complete. The matrix is not a completion percentage and
does not change Foundry source custody, package rights, host policy, provider
credentials, registry identity, or distribution authority.

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

## Next dependency-ready unit: provider call conformance

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
- Apply a 30-second overall deadline and five-second idle deadline through an
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
mise exec -- uv run --frozen pytest tests/test_provider_call.py tests/test_provider_call_adapter_boundaries.py tests/test_provider_call_typing.py tests/test_provider_execution_contracts.py tests/test_provider_execution_review_regressions.py tests/test_public_repository_boundary.py
mise exec -- uv run --frozen python scripts/generate_schemas.py --check
bash scripts/validate-repository.sh
```

### Completed local evidence

The signed acceptance baseline at `e7014ac9498920acfababa1934dcaeae146aee7d`
was implemented as one 18-path SDK-3.1 candidate, with this acceptance update as
its nineteenth owned path. On the frozen implementation bytes:

- The focused command above passed 281 tests in 63.21 seconds.
- Schema generation check passed with exit `0`.
- `bash scripts/validate-codestyle.sh` passed formatting, Ruff, MyPy,
  repository standards, and documentation checks.
- Independent review returned `NO_FINDINGS` after reproducing the deadline,
  cancellation, redaction, malformed-event, buffering, digest, selected-mode,
  and static adapter-typing boundaries.
- `bash scripts/validate-repository.sh` passed 1,442 tests with one skip in
  272.94 seconds and built both the source distribution and wheel.
- `git diff --check` passed, and the reviewed implementation hashes remained
  unchanged after the aggregate gate.

The preserved implementation commit
`1ceeb54ff8a1c8be0589a32b28c4a70b560dcde8` was replayed without source
changes onto current `origin/main` at
`f5ebdbde687265e58033403f8a0cfb9debc54abe`. The only merge conflict was the
expected add/delete history for this acceptance record, which was retained.
On that current-main integration candidate, the same focused command passed
281 tests, the generated-schema check passed, and
`bash scripts/validate-repository.sh` passed 1,442 tests with one skip and
built the source distribution and wheel.

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
