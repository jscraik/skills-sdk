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

## Separate evidence lanes

The SDK's local contract and schema checks do not prove provider execution,
runtime installation, Tessl publication, or installed behavior. Those lanes
must bind the same candidate identity and report their own evidence.
