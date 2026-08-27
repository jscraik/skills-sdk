# Skills SDK

Skills SDK is a portable Python contract layer and local tooling surface for
Agent Skills packages. It defines explicit, versioned contracts for inventory,
intake, evaluation, risk, security, manifests, and receipts. Its local
source-consuming services validate standalone packages and, after a candidate
identity is resolved and validation passes, build candidate-bound manifest and
receipt data; inventory, intake, evaluation, risk, and security are
caller-populated contract lanes. The core remains independent of a host
repository, provider account, runtime installation, or registry.

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
series. The implemented local commands are `validate` and `build`. The other
lifecycle names, including `inventory`, `intake`, `eval`, `package`,
`project`, `verify`, and `tessl prepare`/`tessl verify`, are explicit discovery
boundaries: they parse arguments and provide route-specific help when
explicitly requested with `--help`, but do not execute provider work, install
anything, mutate a runtime, or publish to a registry.

## What the SDK guarantees

- Typed Pydantic contracts for package identity, source and ownership, intake,
  inventory, evaluation scenarios and scorers, risk and security, validation,
  manifests, and receipts.
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

The SDK does not own canonical package source, provider execution, runtime
projection or installation, Tessl or other registry publication, or installed
behavior. Those are separate lanes and must supply their own evidence for the
same candidate identity. See [`docs/compatibility.md`](docs/compatibility.md)
for the compatibility policy and evidence boundary.

## Quick start

The supported development floor is Python `>=3.12,<3.13`. From a checkout:

```bash
uv sync --frozen
uv run skills-sdk --version
uv run skills-sdk --help
```

The default help route stays short. Load more detail only for the route you
need:

```bash
uv run skills-sdk inventory --help
uv run skills-sdk validate --help
uv run skills-sdk build --help
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
`id_ed25519`, and `.key`/`.pem`/`.p12`/`.pfx`/`.token` suffixes),
runtime/source-control directories, unreadable files, and an unstable source
are typed blockers. This is a filename policy, not a content secret scan, so
credential-bearing content in an otherwise permitted filename is not detected
by this validator. It also rejects unsupported frontmatter keys and requires
the supplied source revision to be 40 lowercase hexadecimal characters.

Replace `<40-lowercase-hex>` with the revision that identifies the source you
are validating:

```bash
uv run skills-sdk validate ./path/to/skill \
  --source-revision <40-lowercase-hex> \
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
uv run skills-sdk validate tests/fixtures/synthetic-skill \
  --source-revision 0000000000000000000000000000000000000000 \
  --json --robot
```

Expected evidence is exit `0`, `status: "pass"`, and a candidate with
`package_id: "synthetic-skill"`. A blocked validation is:

```bash
uv run skills-sdk validate tests/fixtures/synthetic-skill \
  --source-revision not-a-revision \
  --json --robot
```

Expected evidence is exit `2`, `status: "blocked"`, and a finding with code
`invalid_source_revision`; the candidate is `null` because the supplied
revision is not a valid 40-character lowercase hexadecimal value.

## Build a candidate-bound receipt

`build` runs the same read-only validation and, when it passes, returns a
`package-receipt/v1` with a deterministic manifest, package digest, included
files, and the resolved candidate identity. It does not create an archive or
write a receipt into the package. For a valid invocation that reaches the build
service, a blocked result contains a typed blocker, does not claim a package
digest, and exits `2`.

```bash
uv run skills-sdk build ./path/to/skill \
  --source-revision <40-lowercase-hex> \
  --json --robot
```

The committed fixture also makes both build outcomes concrete. A successful
build is:

```bash
uv run skills-sdk build tests/fixtures/synthetic-skill \
  --source-revision 0000000000000000000000000000000000000000 \
  --json --robot
```

Expected evidence is exit `0`, `status: "built"`, and populated `manifest` and
`package_digest` fields with `mutation_performed: false`. A blocked build is:

```bash
uv run skills-sdk build tests/fixtures/synthetic-skill \
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

## Python API

Use the service functions for local package work and the model families for
portable contracts:

```python
from pathlib import Path

from skills_sdk.packaging import build_skill_package
from skills_sdk.validation import validate_skill_package

package_root = Path("./path/to/skill")
source_revision = "0" * 40  # replace with the source's actual 40-character revision

validation = validate_skill_package(package_root, source_revision=source_revision)
if validation.status == "pass":
    receipt = build_skill_package(package_root, source_revision=source_revision)
    assert receipt.status == "built"
```

For contract families, schema loading, model-level invariants, and the bare
wire-shape exceptions, see [`docs/api.md`](docs/api.md). The small
[`examples/inventory_contract.py`](examples/inventory_contract.py) example
shows a portable candidate identity without requiring a provider, credential,
runtime installation, or generated receipt.

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
uv sync --frozen
bash scripts/validate-repository.sh
```

The wrapper checks generated-schema drift, Ruff, the full pytest suite, the
source and wheel build, and `git diff --check`. For a schema change, inspect
the generated files and keep schema, behavior, and compatibility tests in the
same change. Read [`CODESTYLE.md`](CODESTYLE.md) for implementation style and
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution contract.

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
