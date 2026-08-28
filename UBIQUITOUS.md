---
schema_version: 1
---

# Skills SDK vocabulary

This glossary gives readers and contributors one vocabulary for the portable
contract layer and its evidence boundaries. It distinguishes local source
proof from provider, runtime, distribution, and publication state.

## Language

### Package and identity

**Agent Skills package**:
A filesystem package whose required entrypoint is `SKILL.md` and whose other
files are validated as portable package content. It is source input, not proof
that a skill is installed or active.
_Avoid_: runtime installation, plugin cache, published package

**Candidate identity**:
The exact tuple of `package_id`, `source_revision`, and `content_sha256` that
identifies the source state carried into downstream manifests and receipts.
_Avoid_: package path, display name, runtime name

**Source revision**:
The caller-supplied 40-character lowercase hexadecimal revision for the source
being inspected, normally a Git revision. The SDK validates its shape; it does
not resolve or fetch the revision.
_Avoid_: package version, timestamp, branch name

**Content digest**:
The SHA-256 `content_sha256` value derived from the deterministic list of
captured package paths and their file hashes. It identifies the candidate's
content and is distinct from the digest of a manifest payload.
_Avoid_: package digest, archive checksum

**Package digest**:
The SHA-256 digest of the canonical package manifest emitted on a successful
build receipt. It is an artifact digest, not a replacement for candidate
identity.
_Avoid_: content digest, source revision

**Portable path**:
A normalized, relative POSIX path that stays within the owning field's
declared context. Package manifest and receipt paths are package-root-relative;
inventory fields such as `current_path`, `SourceProvenance.path`, and
`direct_consumers` may be workspace- or source-root-relative. The type does not
choose that base. Absolute paths, parent traversal, backslashes, line
terminators, and unnormalized forms are invalid at the contract boundary.
_Avoid_: machine path, absolute path, host path

### Lifecycle and evidence

**Validation lane**:
The read-only local inspection of package shape, frontmatter, safe traversal,
and file content needed to produce a `skill-package-validation/v1` result.
_Avoid_: execution, installation, runtime verification

**Typed blocker**:
A machine-readable code and message explaining why a contract or proof lane
cannot complete, with portable evidence references when they are available. A
blocker is an explicit result, not a waiver or a silent omission; callers must
not invent an evidence path when the failure has no package-local reference.
_Avoid_: warning-only failure, best-effort success, suppressed error

**Package manifest**:
A candidate-bound description of the files selected for a package, including
portable paths, SHA-256 file hashes, sizes, roles, and build provenance. It is
the content description used by the receipt lane; it is not an archive.
_Avoid_: tarball, installer, publication record

**Receipt**:
A versioned, immutable proof-lane result carrying status, evidence, and the
candidate identity when it has been resolved. A `package-receipt/v1` can be
`built` or `blocked`, and does not claim provider, runtime, or registry state.
_Avoid_: deployment record, publication receipt, runtime health check

**Structural schema validation**:
Checking a payload against one of the packaged Draft 2020-12 JSON Schemas.
This is the shape check and may be followed by semantic model validation.
_Avoid_: business-rule validation, execution test

**Semantic validation**:
Applying the Pydantic model invariants that relate fields after structural
schema validation, such as candidate binding, unique identifiers, and status
rules. Only the contract families registered by `SchemaRegistry` receive this
extra check through the registry.
_Avoid_: schema loading, runtime test

**Inventory snapshot**:
A read-only set of package records that preserves the caller-supplied record
order and describes source, ownership, rights, value, risk, intended
disposition, and runtime visibility. It is not canonically ordered or
deterministic unless the caller supplies and documents an ordering.
_Avoid_: live runtime inventory, installation list

**Intake decision**:
An explicit `admit`, `block`, `reject`, or `needs_owner_decision` result over a
candidate and its identity, provenance, rights, and owner-unchanged checks.
_Avoid_: implicit approval, publication decision

**Normalized package**:
A portable package identity, source, owner, lifecycle state, and dependencies
prepared before any provider or runtime projection. Normalization preserves
ownership evidence; it does not install or publish the package.
_Avoid_: installed package, provider artifact

### Boundaries and actors

**Boundary route**:
A named CLI route that makes a lifecycle intent discoverable while its deeper
implementation is not available in this SDK. The current boundary routes parse
arguments and expose route-specific help when `--help` is requested, without
executing side effects.
_Avoid_: implemented command, successful operation

**Skill identity**:
The package identity for a standalone skill: a kebab-case name, package ID,
version, and `package_type: "skill"`. It is independent of runtime activation.
_Avoid_: skill instance, runtime handle

**Plugin identity**:
The package identity for a plugin, with its own package ID, name, version, and
`package_type: "plugin"`. It is distinct from a standalone skill and from any
client adapter that may consume it.
_Avoid_: skill identity, installed plugin

**Provider lane**:
An adapter-specific interaction with an external provider or account. Provider
execution and its receipts are outside the portable SDK core and require their
own candidate-bound evidence.
_Avoid_: local validation, registry state

**Runtime projection**:
The separate act of installing or activating a candidate in a selected host
runtime. A `project` boundary route or a local receipt does not prove that this
projection happened.
_Avoid_: source package, validation result

**Publication lane**:
The external distribution or registry operation that makes a candidate
available to readers or clients. Tessl preparation and local package building
are not publication.
_Avoid_: build, runtime projection, source admission

## Relationships

- One **Agent Skills package** produces one **Candidate identity** for a given
  source revision and captured content digest.
- One **Candidate identity** can bind zero or more **Package manifests** and zero
  or more lane-specific **Receipts**; each receipt must state which lane ran.
- A **Validation lane** can emit a passing result or one or more **Typed
  blockers** without executing the package.
- An **Inventory snapshot** contains zero or more inventory records; an
  **Intake decision** resolves whether a candidate may enter its canonical
  ownership path.
- **Structural schema validation** checks payload shape before registered
  **Semantic validation** applies cross-field contract invariants.
- A **Boundary route** may lead to a provider, **Runtime projection**, or
  **Publication lane**, but it does not establish that downstream state.

## Flagged Ambiguities

- “Build” can mean constructing an archive or returning a proof artifact.
  In this repository, use **build a candidate-bound receipt**: `build` validates
  read-only; after validation passes, it computes a manifest and package digest.
  A blocked validation returns a typed blocker without a manifest or package
  digest, and the command writes nothing.
- “Validate” and “verify” are not interchangeable. Use **validation lane** for
  the implemented local package check; reserve **verify** for a future or
  external evidence-checking lane unless the owning contract says otherwise.
- “Package” can mean the source directory, the manifest, or the reserved CLI
  route. Say **Agent Skills package**, **package manifest**, or **package route**
  when the distinction matters.
- “Publish”, “install”, and “project” describe downstream operations. Do not
  infer any of them from a passing local validation or built receipt.
- `content_sha256` identifies captured candidate content; `package_digest`
  identifies the canonical manifest payload. Keep both names explicit.

## Prompt Translations

| User phrase | Canonical action |
| --- | --- |
| “Validate this skill” | Run `uv run --frozen skills-sdk validate <package-root> --source-revision <40-lowercase-hex> --json --robot`; for an invocation that reaches the validator, treat exit `0` as a passing result and exit `2` as a typed blocker. Argparse also uses exit `2` for malformed invocations before a versioned result exists. |
| “Build this package” | Run `uv run --frozen skills-sdk build <package-root> --source-revision <40-lowercase-hex> --json --robot`; for an invocation that reaches the builder, call the result a candidate-bound receipt, not an archive or publication. Argparse rejects malformed invocations before a versioned receipt exists. |
| “Make it available” | First name the target lane. Use `validate` or `build` for local contract proof; hand installation, provider execution, and publication to their owning adapter or registry workflow. |
| “Check the schemas” | Run `uv run --frozen python scripts/generate_schemas.py --check` for generated-schema drift, then use `SchemaRegistry` or the documented Draft 2020-12 validator for the payload family. |
| “Is it verified?” | Identify the evidence lane and candidate identity, then inspect that lane's result; a local receipt alone does not prove runtime, provider, registry, or hosted state. |

## Example Dialogue

> **Developer:** “The skill built successfully, so can I say it is published?”
>
> **Domain expert:** “No. **Build** produced a local candidate-bound
> **Receipt** and **Package manifest**. **Publication** is a separate lane whose
> registry evidence must bind the same **Candidate identity**.”
>
> **Developer:** “What should I call a failure that stops the candidate?”
>
> **Domain expert:** “Use **Typed blocker** and include its code and message;
> add portable evidence references when they are available. Do not invent a
> path, turn it into a warning, or use a waiver.”

## Agent Integration

[`AGENTS.md`](AGENTS.md) is the active instruction surface and points here.
[`ARCHITECTURE.md`](ARCHITECTURE.md) maps the code boundaries and invariants
that give these terms their repository-specific meaning.
Keep executable identifiers such as `build`, `validate`, `SchemaRegistry`, and
schema names unchanged; use this glossary to clarify their meaning in prose
and prompts.

## Sources

- [`AGENTS.md`](AGENTS.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`README.md`](README.md)
- [`docs/agent-entrypoint.md`](docs/agent-entrypoint.md)
- [`docs/api.md`](docs/api.md)
- [`docs/cli.md`](docs/cli.md)
- [`docs/compatibility.md`](docs/compatibility.md)
- `src/skills_sdk/validation/skill_package.py`
- `src/skills_sdk/packaging/manifest.py`
- `src/skills_sdk/core/schema_registry.py`
- `src/skills_sdk/models/package.py`
- `src/skills_sdk/models/packaging.py`
