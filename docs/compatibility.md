# Compatibility

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

## Contract policy

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

`runtime-lock/v1` and `install-plan/v1` are additive schema families. They are
registered for structural and Pydantic semantic validation but are not generic
receipts: generic receipt parsing must not reinterpret intended runtime state
or a non-mutating plan as evidence that installation occurred. Later host
adapter apply, rollback, discovery, activation, and outcome families must use
new explicit schema versions rather than changing these v1 meanings.

## Separate evidence lanes

The SDK's local contract and schema checks do not prove provider execution,
runtime installation, Tessl publication, or installed behavior. Those lanes
must bind the same candidate identity and report their own evidence.
