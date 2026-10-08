# Skills SDK

Skills SDK is a portable Python contract layer and local tooling surface for
Agent Skills packages. It defines explicit, versioned contracts for inventory,
intake, evaluation, risk, security, manifests, and receipts. Its local
source-consuming services validate standalone packages and, after a candidate
identity is resolved and validation passes, normalize intake context or build
candidate-bound manifest and receipt data. Bounded offline evaluation, supplied
review assessment and static security screening have separate evidence limits;
they do not establish live provider or reviewer truth. The core remains independent of a host
repository, provider account, runtime installation, or registry.

Within the [brAInwav product family](ARCHITECTURE.md#brainwav-product-family),
`skills-sdk` owns reusable tooling. The future `skills-registry` is a separate
repository for the service; its workers consume a pinned SDK package version.
Its creation remains subject to the [registry start gate](docs/workflow.md#registry-transition).

The Python API can deterministically prepare an intended runtime-lock
transition with `plan_runtime_install`. The plan is portable and
mutation-free: it does not resolve host paths, write a lock, install files,
execute rollback, or prove discovery, activation, or runtime behavior. Package
installation, runtime-lock application, rollback, discovery, and activation
require future SDK-owned host integration and separate evidence contracts. The narrower
existing-copy comparison and maintenance routes are documented in
[`docs/runtime-copy-integration.md`](docs/runtime-copy-integration.md).

> Thin Surfaces. Strong Guardrails. Progressive Disclosure. Durable Memory.
> Professional Output.

## Contents

- [Current status](#current-status)
- [What the SDK guarantees](#what-the-sdk-guarantees)
- [Quick start](#quick-start)
- [Validate a standalone skill](#validate-a-standalone-skill)
- [Build a candidate-bound receipt](#build-a-candidate-bound-receipt)
- [Python API](#python-api)
- [Contract and evidence boundaries](#contract-and-evidence-boundaries)
- [Repository layout](#repository-layout)
- [Development and validation](#development-and-validation)
- [Project language and further reading](#project-language-and-further-reading)

## Current status

The repository is version `0.1.0` and is in the contract-building `0.x`
series. The implemented local commands are `intake`, `check-local`, `check-quality`, `review-content`, `validate`,
`build`, `eval scenario-quality`, `eval scorer-quality`,
`eval scorer-calibration`, `eval observed-calibration`, `eval selected-case`, `verify recurring-findings`,
`verify pr-sweep-dirty-closeout`, `compare-copy`, and `maintain-entrypoint`.
Comparison is read-only. Maintenance is read-only by
default and requires explicit `--apply` to change an existing host file. The
other lifecycle names, including `inventory`, `package`,
`project`, and `tessl prepare`/`tessl verify`, are explicit discovery
boundaries: they parse arguments and provide route-specific help when
explicitly requested with `--help`, but do not execute provider work, install
anything, mutate a runtime, or publish to a registry.

Skills SDK owns the agent-facing `SKILL.md`, references, evaluation workflow,
and executable orchestration for skill and plugin creation, updates, checks,
external intake, and installation of selected checked versions. Its reusable
core stays portable; supported registry and host adapters, initially Tessl and
Codex, remain SDK integration
responsibilities, not core dependencies. Most of this end-to-end route is still
planned, not implemented. Agent-Skills is a transitional migration source and
must not become a runtime, test, documentation, or release dependency. Skills
Foundry holds candidates awaiting SDK processing, including blocked candidates;
holding is not SDK clearance, installation, distribution, or a requirement for
permanent post-processing custody.

The [target release format](docs/workflow.md#managed-release-format) is a complete
Agent Plugins package with root `plugin.json`, even for one skill. Optional
Foundry holding or new authoring/external intake leads to plugin normalisation,
SDK checking, a verified registry version and selected host installation.
Tessl `jscraik` is the initial private backend, not a permanent dependency.
Do not start or create a separate registry, including a catalogue or prototype,
until the SDK workflow is complete and publication to Jamie's private Tessl
workspace is verified. That registry becomes primary only after further
[publication, readback, download and installation proof](docs/workflow.md#registry-transition).
Keep one canonical content source; Tessl exports belong to an explicit adapter.
Neither a local receipt nor the current `tessl prepare` route proves this flow.
Only Jamie chooses a public release. Verified OpenAI-provided plugins and
OpenAI system skills remain on their provider-managed paths; names, locations,
and compatible formats alone do not establish an exemption.

The migration is complete only when the SDK provides independently usable
routes and proof for those lifecycle stages, Foundry can hold candidates
without importing Agent-Skills, and every remaining Agent-Skills
consumer has moved or been explicitly retired. Until then, the unimplemented
CLI names above remain discovery boundaries except for the implemented
local commands listed above.
[`ARCHITECTURE.md`](ARCHITECTURE.md) defines the
required evidence and `pass`, `fail`, and `blocked` outcomes for that retirement
decision.

The [canonical workflow](docs/workflow.md) defines the ordered quality,
security, evaluation, registry, installation, and correction gates. The
[migration map](docs/migration-map.md) distinguishes legacy capabilities from
current SDK behaviour; the [task record](docs/projects/sdk-workflow/tasks.md)
tracks their implementation and proof.

## What the SDK guarantees

- Typed Pydantic contracts for package identity, source and ownership, intake,
  inventory, evaluation scenarios, scorer profiles, observations, case results
  and receipts, risk and security, validation, manifests, and packaging
  receipts.
- Read-only standalone-skill intake and normalization through
  `intake_skill_package`. The service reuses structural package validation,
  binds source provenance to the resulting candidate, and preserves
  caller-supplied ownership, rights, and admission checks without establishing
  their real-world truth or performing Foundry admission.
- Deterministic, non-executing evaluation of externally produced observations,
  with explicit blockers for unsupported oracles, incomplete calibration, and
  candidate or scenario-set identity drift.
- Candidate-bound, read-only scenario-definition quality assessment through
  `skills-sdk eval scenario-quality`; it does not execute scenarios or providers.
- An opt-in v2 evaluation family with secret-free provider identity binding,
  digest-only exact-match decisions, deterministic receipt identity, and
  generic receipt parsing. Existing v1 payloads and evaluator semantics remain
  unchanged.
- A local private-registry preparation contract that binds a v2 package
  receipt, package-hardening receipt, secret-free registry identity, immutable
  manifest digest, and caller-supplied evidence into a deterministic
  `registry-preparation/v1` receipt. Preparation performs no publication,
  registry mutation, credential use, or network access.
- A package-safety evidence contract that records whether an exact candidate
  was not reviewed, reviewed with no observed issue, had an issue found, or
  lacked sufficient metadata. Evidence references are portable and
  digest-bound; the receipt never emits a generic `safe` boolean or decides
  rights, admission, installation, runtime behavior, or publication.
- Secret-free provider execution request and result envelopes for external
  adapters. They bind one candidate, scenario case, provider identity, input or
  output digests, and typed outcomes without carrying prompts, outputs,
  credentials, costs, or a provider client.
- Bounded offline provider-call orchestration through one injected adapter.
  The service supports complete and pull-driven text modes, keeps raw input and
  output private, emits compact typed evidence, and performs no discovery,
  credential access, network transport, or automatic retry.
- Packaged JSON Schema resources with a `SchemaRegistry` for registered schema
  names. The registry applies structural validation to those names and
  semantic invariants only for registered model families; other packaged
  resources can be loaded directly with a Draft 2020-12 validator as described
  in [`docs/api.md`](docs/api.md).
- Filesystem-safe, read-only standalone-skill validation with portable paths,
  closed YAML frontmatter, deterministic file manifests, and typed blockers.
- Receipts that bind a resolved candidate keep `package_id`, a 40-character
  source revision, and a SHA-256 content digest together across proof lanes;
  blocked receipts may omit the candidate when its identity cannot be resolved.
- A prompt-free CLI contract with JSON output and stable exit behavior for the
  implemented commands.

The SDK core does not own canonical package source, real-provider credentials
or transport, registry operation, or host mutation. SDK-owned adapters must
orchestrate selected registry and runtime paths when implemented; their
external outcomes remain separate lanes and must supply
their own evidence for the same candidate identity. See
[`docs/compatibility.md`](docs/compatibility.md) for the compatibility policy
and evidence boundary.

## Quick start

The supported development floor is Python `>=3.12,<3.13`. From the checkout root:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --version
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
```

The default help route stays short. Load more detail only for the route you
need:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk inventory --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build --help
```

The first-run route and its boundaries are also documented in
[`docs/agent-entrypoint.md`](docs/agent-entrypoint.md).

## Validate a standalone skill

`validate` reads a package and returns a `skill-package-validation/v1` result;
it never executes the skill and never mutates the source tree. A package must
contain a regular `SKILL.md` with closed YAML frontmatter, a non-empty
`name` matching its directory name, and a non-empty `description`. Files and
directories must use portable relative paths; symlinks, screened credential
filenames (`.env`, `.env.*`, `credentials.json`, `secrets.json`, `id_rsa`,
`id_ed25519`, and `.key`/`.pem`/`.p12`/`.pfx`/`.token` suffixes), and
screened directories (`.agents`, `.cache`, `.codex`, `.git`, `.gnupg`,
`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.ssh`, `.tox`, `.venv`,
`__pycache__`, `node_modules`, and `venv`), are typed blockers. These are
fixed filename and directory denylists; unreadable files are also blockers,
while metadata outside the screened directories, such as
`.hg` or `.svn`, may be included. The filename policy is not a content secret
scan, so credential-bearing content in an otherwise permitted filename is not
detected by this validator. It also rejects unsupported frontmatter keys and
requires the supplied source revision to be 40 lowercase hexadecimal
characters.

The validator blocks source changes observed by its before/after file and
directory-stat checks, but this is a best-effort quiescence check rather than
a transactional snapshot. Promotion under adversarial concurrent mutation
requires an immutable source revision or a prepared snapshot; see
[`docs/compatibility.md`](docs/compatibility.md).

Replace `<40-lowercase-hex>` with the revision that identifies the source you
are validating:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate ./path/to/skill \
  --source-revision "<40-lowercase-hex>" \
  --json --robot
```

For a valid invocation that reaches the validation service, exit status `0`
means `status: "pass"`. Exit status `2` means the service returned
`status: "blocked"` and contains one or more typed findings. `--json` emits
the versioned result; `--robot` is an accepted no-op that reserves the
prompt-free automation contract. Human output includes finding codes and
portable evidence references when a finding has them. Argparse also uses exit
status `2` for malformed invocations such as a missing `package_root`; that
usage error occurs before a versioned validation result is produced. The full
command contract is in
[`docs/cli.md`](docs/cli.md).

The committed `tests/fixtures/synthetic-skill` fixture makes the validation
contract runnable from the repository root. A passing validation is:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate tests/fixtures/synthetic-skill \
  --source-revision 0000000000000000000000000000000000000000 \
  --json --robot
```

Expected evidence is exit `0`, `status: "pass"`, and a candidate with
`package_id: "synthetic-skill"`. A blocked validation is:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate tests/fixtures/synthetic-skill \
  --source-revision not-a-revision \
  --json --robot
```

Expected evidence is exit `2`, `status: "blocked"`, and a finding with code
`invalid_source_revision`; the candidate is `null` because the supplied
revision is not a valid 40-character lowercase hexadecimal value.

## Build a candidate-bound receipt

`build` runs the same read-only validation and, when it passes, returns a
`package-receipt/v2` with a deterministic manifest, a package digest bound to
the canonical manifest bytes, included files, and the resolved candidate
identity. The SDK continues to parse `package-receipt/v1` with its historical
opaque-digest semantics. Build does not create an archive or write a receipt
into the package. For a valid invocation that reaches the build service, a
blocked result contains a typed blocker, does not claim a package digest, and
exits `2`.

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build ./path/to/skill \
  --source-revision "<40-lowercase-hex>" \
  --json --robot
```

The committed fixture also makes both build outcomes concrete. A successful
build is:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build tests/fixtures/synthetic-skill \
  --source-revision 0000000000000000000000000000000000000000 \
  --json --robot
```

Expected evidence is exit `0`, `status: "built"`, and populated `manifest` and
`package_digest` fields with `mutation_performed: false`. A blocked build is:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build tests/fixtures/synthetic-skill \
  --source-revision not-a-revision \
  --json --robot
```

Expected evidence is exit `2`, `status: "blocked"`, and a typed blocker with
code `invalid_source_revision`; `manifest` and `package_digest` are `null`.
For a valid invocation that reaches the build service, exit `2` is the blocked
receipt outcome; malformed invocations are rejected by argparse before a
versioned receipt exists. The receipt is evidence for the local validation lane
only. It does not prove that a provider accepted the package, that a runtime
installed it, or that a registry published it.

## Harden an immutable package receipt

Package hardening consumes the typed build receipt rather than rescanning the
filesystem. It checks the immutable manifest for forbidden runtime, generated,
dependency, and secret-bearing paths; explicit size budgets; SDK provenance;
and required package roles. The result is a candidate-bound
`package-hardening/v1` receipt. Hardening is read-only, exposes every warning,
and never converts a blocked build into a package digest.

```python
from skills_sdk.packaging import harden_skill_package

hardening = harden_skill_package(receipt)
if hardening.status == "blocked":
    for blocker in hardening.blockers:
        print(blocker.id, blocker.message)
```

This contract proves deterministic local package hardening only. It does not
sign, archive, publish, install, or execute the package.

## Python API

Use the service functions for local package work and the model families for
portable contracts. Validation and build are separate read-only calls, so the
source can change between them and a build can return a typed blocked receipt:

```python
from pathlib import Path

from skills_sdk.packaging import build_skill_package, harden_skill_package
from skills_sdk.validation import validate_skill_package

package_root = Path("./path/to/skill")
source_revision = "0" * 40  # replace with the source's actual 40-character revision

validation = validate_skill_package(package_root, source_revision=source_revision)
if validation.status == "pass":
    receipt = build_skill_package(package_root, source_revision=source_revision)
    if receipt.status == "built":
        assert receipt.manifest is not None
        assert receipt.package_digest is not None
        hardening = harden_skill_package(receipt)
        print(hardening.status, receipt.package_digest)
    else:
        assert receipt.blocker is not None
        print(receipt.blocker.code, receipt.blocker.message)
else:
    for finding in validation.findings:
        print(finding.code, finding.message)
```

For contract families, schema loading, model-level invariants, and the bare
wire-shape exceptions, see [`docs/api.md`](docs/api.md). The small
[`examples/inventory_contract.py`](examples/inventory_contract.py) example
shows a portable candidate identity without requiring a provider, credential,
runtime installation, or generated receipt.

After a successful v2 build and package-hardening pass, callers can prepare a
private-registry candidate locally:

```python
from skills_sdk.distribution import prepare_private_registry_candidate
from skills_sdk.models import RegistryIdentity, RegistryPreparationRequest

registry_receipt = prepare_private_registry_candidate(
    receipt,
    hardening,
    RegistryPreparationRequest(
        registry=RegistryIdentity(registry_id="private-registry", namespace="example-team"),
        package_name=receipt.candidate.package_id,
        version=receipt.manifest.version,
        evidence=("evidence/private-registry-preparation.json",),
    ),
)
assert registry_receipt.mutation_performed is False
assert registry_receipt.publication_performed is False
```

This function validates immutable receipt inputs and returns either
`prepared` or a typed `blocked` result. It does not contact a registry, check
credentials, upload an artifact, reserve a version, or prove publication.

## Contract and evidence boundaries

The same candidate identity should travel through each local proof artifact,
while the artifact type states which lane actually ran:

| Surface              | What the SDK represents                                                       | What it does not establish                                   |
| -------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Inventory and intake | Source, ownership, rights, value, and admission decisions                     | Canonical ownership when the evidence is missing             |
| Validation           | Package shape, safe traversal, frontmatter, file manifest, and typed findings | Skill execution or runtime behavior                          |
| Evaluation           | Candidate-bound scenarios and scorer calibration requirements                 | A passing score from a scorer that did not run               |
| Risk and security    | Sensor coverage, redacted findings, and explicit pass/review/block states     | Provider or runtime security beyond the declared sensors     |
| Manifest and receipt | Immutable candidate, files, digest, timestamps, and blockers                  | Distribution, installation, publication, or hosted readiness |
| Registry preparation | Candidate-, hardening-, registry-, digest-, and evidence-bound local intent    | Registry acceptance, upload, version reservation, or publication |
| Package safety evidence | Candidate-, package-digest-, reviewer-, finding-, and evidence-bound state | Rights, admission, runtime behavior, or a general safety guarantee |

This separation is deliberate: local contract proof, hosted CI and review,
provider or registry state, and installed behavior are different claims.

## Repository layout

```text
src/skills_sdk/          Public Python package and service boundaries
src/skills_sdk/schemas/  Versioned JSON Schema resources
tests/                   Contract, fixture, CLI, and architecture tests
docs/                    API, CLI, compatibility, and entrypoint guidance
examples/                Small dependency-light contract example
scripts/                 Schema generation and repository validation wrappers
```

## Development and validation

Install the pinned environment and run the repository gate before a commit or
pull request:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise install python uv ruff vale
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
bash scripts/validate-repository.sh
```

The canonical focused route for the hand-maintained schema subset is:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py
```

This route loads `receipt-base.v1.schema.json`, `blocker.v1.schema.json`, and
`package-identity.v1.schema.json` through `SchemaRegistry.load`, which checks
each resource with `Draft202012Validator`; its contract cases then exercise
candidate identity, generic receipt, and typed-blocker behavior. The wrapper
checks generator-managed schema drift, Ruff, the full pytest suite, the source
and wheel build, and `git diff --check`; its full pytest run includes this
focused route but does not label it separately. Record the focused command as
`pass` only when it exits `0` and pytest reports all tests passed, `fail` when
it exits non-zero with a schema or contract assertion, or `blocked` when it
cannot run or complete because of an environment or dependency problem. For a
blocked run, record the concrete reason and nearest meaningful fallback rather
than treating it as a pass. For any schema change, inspect both the generated
and hand-maintained resources and keep schema, behavior, and compatibility
tests together. Read [`CODESTYLE.md`](CODESTYLE.md) for implementation style
and [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution contract.

## Project language and further reading

Use the canonical vocabulary in [`UBIQUITOUS.md`](UBIQUITOUS.md) when “build”,
“publish”, “install”, “candidate”, “receipt”, or “verification” could mean more
than one lane. For a coarse-grained map of the code and its invariants, see
[`ARCHITECTURE.md`](ARCHITECTURE.md). The remaining public trust surfaces are:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — bird's-eye code map, boundaries, and invariants.
- [`docs/cli.md`](docs/cli.md) — implemented commands, reserved routes, output, and exit codes.
- [`docs/api.md`](docs/api.md) — public Python contract families and schema validation.
- [`docs/compatibility.md`](docs/compatibility.md) — runtime floor, schema evolution, and evidence separation.
- [`docs/agent-entrypoint.md`](docs/agent-entrypoint.md) — minimal first-run route.
- [`SUPPORT.md`](SUPPORT.md) — safe reproduction and support requests.
- [`SECURITY.md`](SECURITY.md) — private reporting and untrusted-input boundaries.
- [`CHANGELOG.md`](CHANGELOG.md) — recorded contract changes.
