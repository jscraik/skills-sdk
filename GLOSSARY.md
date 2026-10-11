---
schema_version: 1
---

# Skills SDK glossary

Skills SDK's domain covers portable Agent Skills packages and the distinct
source, validation, provider, runtime, and distribution evidence associated
with them.

## Language

### Package and identity

**Agent Skills package**:
A collection of skill instructions and supporting content prepared for portable
use by agents. The source package alone does not establish installation or activation.
_Avoid_: runtime installation, plugin cache

**Candidate identity**:
The combination of package identity, source revision, and content digest that
identifies the exact source state under consideration.
_Avoid_: package path, display name, runtime name

**Source revision**:
The supplied reference identifying a particular state of the package source.
It is distinct from a package's release version.
_Avoid_: package version, timestamp

**Content digest**:
A fingerprint of the captured package paths and file contents that identifies
the candidate's content.
_Avoid_: package digest, archive checksum

**Package digest**:
A fingerprint of the canonical package manifest produced by a successful build.
It identifies that manifest rather than replacing the candidate identity.
_Avoid_: content digest, source revision

**Portable path**:
A relative location within a declared package, workspace, or source context
that is independent of a particular machine's filesystem layout.
_Avoid_: machine path, absolute path, host path

**Skill identity**:
The package identity, name, and version of a standalone skill, distinct from
any runtime activation of it.
_Avoid_: skill instance, runtime handle

**Plugin identity**:
The package identity, name, and version of a plugin, distinct from a standalone
skill or an installed copy.
_Avoid_: skill identity, installed plugin

### Lifecycle and evidence

**Validation lane**:
Read-only inspection of a package's structure and content against package
requirements, without executing or installing the package.
_Accepted aliases_: local package validation
_Avoid_: runtime verification, execution test

**Build**:
Read-only validation followed, on success, by creation of a candidate-bound
receipt and package manifest. A blocked build records the blocker without a
manifest or package digest.
_Avoid_: archive creation, publication, installation

**Verification**:
Checking specified evidence against the requirements of its owning contract.
A verification result establishes only the evidence lane and scope it checked.
_Avoid_: unqualified approval, runtime proof from local validation

**Typed blocker**:
An explicit, machine-readable reason why a contract check or evidence lane
cannot complete, accompanied by evidence references when available.
_Avoid_: warning-only failure, best-effort success, suppressed error

**Package manifest**:
A candidate-bound description of selected package files, their content
fingerprints, sizes, roles, and build provenance.
_Avoid_: tarball, installer, publication record

**Receipt**:
A versioned record of a particular evidence lane's result, status, and evidence,
bound to the candidate identity when that identity has been resolved.
_Avoid_: blanket approval, proof of unobserved downstream state

**Structural schema validation**:
Checking whether a contract payload has the required shape and permitted values.
_Avoid_: business-rule validation, execution test

**Semantic validation**:
Checking the relationships and invariants within a contract, including candidate
binding, identifier uniqueness, and status consistency.
_Avoid_: schema loading, runtime test

**Inventory snapshot**:
A supplied collection of package records describing source, ownership, rights,
value, risk, intended disposition, and runtime visibility at a point of inspection.
_Avoid_: live runtime inventory, installation list

**Intake decision**:
An explicit decision to admit, block, reject, or request an owner's decision
about a candidate, based on its identity, provenance, rights, and ownership checks.
_Avoid_: implicit approval, publication decision

**Normalized package**:
A package represented consistently by its identity, source, owner, lifecycle
state, and dependencies, with ownership evidence preserved.
_Avoid_: installed package, provider artifact

**Provider lane**:
Bounded orchestration of provider work through an adapter, separating SDK-owned
limits and public evidence from provider transport and observed external outcomes.
_Avoid_: local validation, registry state

**Runtime projection**:
Installing or activating a candidate in a selected host runtime.
Local package receipts alone do not establish that projection occurred.
_Avoid_: source package, validation result

**Publication lane**:
An external distribution or registry operation that makes a candidate available
to readers or clients.
_Accepted aliases_: publication
_Avoid_: local build, runtime projection, source admission

### Boundaries and actors

**Skills SDK**:
The owner of reusable lifecycle contracts, agent-facing instructions, evaluation
workflows, and tooling for creating, updating, checking, admitting, and orchestrating
installation of packages. This ownership does not establish that every intended
operation is implemented or that an external operation has occurred.
_Avoid_: candidate holding location, registry service, completed migration

**Skills Foundry**:
The holding location for skill and plugin candidates awaiting SDK processing,
including blocked or rejected candidates with recorded reasons. Custody does
not grant clearance or distribution rights and need not continue after processing.
_Avoid_: SDK contract library, Agent-Skills migration source

**Agent-Skills migration source**:
The transitional repository from which lifecycle behaviour and retained packages
are being separated into Skills SDK and Skills Foundry.
_Avoid_: canonical lifecycle owner, permanent upstream dependency

**Boundary route**:
A named command route that exposes lifecycle intent before the corresponding
operation is implemented.
_Avoid_: completed operation, implemented lifecycle workflow

## Relationships

- Candidate identity binds a package's identity to its source revision and
  captured content; package digest identifies its manifest separately.
- A successful build associates a receipt and manifest with the same candidate;
  a blocked result may lack candidate identity when it could not be resolved.
- Structural validation checks shape; semantic validation checks related
  contract invariants.
- Intake decisions concern candidate admission. Foundry custody, provider
  results, publication, and runtime projection have separate meanings and evidence.
