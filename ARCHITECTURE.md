# Architecture

Skills SDK is a portable Python contract layer and local tooling surface for
Agent Skills packages. It defines versioned contract models for caller-provided
inventory, intake, evaluation, risk, and security data, and consumes package
source only through read-only validation and, after a resolved identity and a
passing validation, build candidate-bound manifest and receipt records.
The package also defines secret-free provider execution envelopes, prepares
local private-registry receipts, and plans intended runtime-lock transitions.
Provider calls, host apply or rollback, registry interaction, and publication
remain outside the core package.

This is a map of the stable seams that help a contributor decide where a
change belongs. It is intentionally shorter than the implementation
documentation: use the [README](README.md) for the reader-facing route, the
module and symbol names below for code search, and the linked detail docs for
operational contracts.

## Start here

- New to the repository: read [README.md](README.md), then follow
  `docs/agent-entrypoint.md` for the smallest first-run route.
- Changing a public contract or schema: start in `src/skills_sdk/models/`,
  inspect the matching resource under `src/skills_sdk/schemas/`, and read
  `docs/api.md` and `docs/compatibility.md`.
- Changing package validation: start with `SkillIR` in
  `src/skills_sdk/validation/skill_ir.py`, then follow
  `validate_skill_package` in `src/skills_sdk/validation/skill_package.py`.
- Changing the receipt path: follow `build_skill_package` through
  `src/skills_sdk/packaging/manifest.py` and the receipt models under
  `src/skills_sdk/models/packaging.py`.
- Changing private-registry preparation: follow
  `prepare_private_registry_candidate` in
  `src/skills_sdk/distribution/private_registry.py` and the versioned models
  under `src/skills_sdk/models/registry.py`.
- Changing package-safety evidence: start with
  `PackageSafetyEvidenceReceipt` in `src/skills_sdk/models/safety.py`; it
  validates adapter-supplied evidence and does not run a scanner or review.
- Changing provider execution envelopes: start with
  `ProviderExecutionRequest` and `ProviderExecutionResult` in
  `src/skills_sdk/models/provider_execution.py`; external adapters still own
  provider calls, credentials, and provider-result truth.
- Changing runtime-lock planning: follow `plan_runtime_install` in
  `src/skills_sdk/lifecycle/planning.py` and the versioned models in
  `src/skills_sdk/models/lifecycle.py`; host adapters still own apply,
  rollback, discovery, activation, and runtime-outcome evidence.
- Changing command behavior: start at `main` and `build_parser` in
  `src/skills_sdk/cli/main.py`, then read `docs/cli.md`.
- Changing vocabulary or agent routing: read [UBIQUITOUS.md](UBIQUITOUS.md)
  and [AGENTS.md](AGENTS.md) before editing prose or instructions.

## Bird's-eye view

There are two related local paths. A package path captures a filesystem view,
validates its entrypoint and files, and then (only after a resolved identity and
a pass) composes a candidate-bound manifest and receipt. A contract path
validates JSON-shaped payloads against packaged schemas and, for registered
families, applies the corresponding Pydantic invariants.

```text
Package source
    |
    v
validation/skill_ir.py + validation/skill_package.py
    |
    +--> SkillPackageValidation (pass or typed blockers)
    |
    +--> packaging/manifest.py (only after validation passes)
             |
             +--> PackageManifest + PackageReceipt

JSON-shaped contract payload
    |
    v
core/schema_registry.py + models/*
    |
    --> successful validation (`None`) after structural and applicable semantic checks, or ContractError

Local candidate-bound contracts
    |
    +--> distribution/private_registry.py
    |    (local receipt composition only; no registry interaction)
    |
    +--> models/provider_execution.py
    |    (locally validated envelopes for externally observed provider evidence;
    |     no provider call or locally proved provider outcome)
    |
    +--> lifecycle/planning.py
    |    (intended runtime-lock transition only; no host mutation)
    |
    +--> provider, host-runtime, registry, and publication adapters
         (separate external action and evidence lanes)
```

The CLI is an outer adapter over the implemented local services. `validate`
and `build` execute the two local paths above; the other lifecycle names are
parseable discovery boundaries and do not perform provider, installation,
runtime, or publication work.

## Code map

The paths below are coarse-grained ownership boundaries. Use symbol search for
the named types and functions; detailed behavior belongs in the module
docstrings and the linked API or CLI guides.

| Area | Responsibility | Start with |
| --- | --- | --- |
| `src/skills_sdk/core/` | Shared typed errors, portable paths, generic receipt parsing, and packaged schema lookup/validation. | `ContractError`, `require_portable_relative_path`, `Receipt`, `SchemaRegistry` |
| `src/skills_sdk/models/` | Frozen Pydantic contract families for identity, inventory, intake, evaluation, risk, security, validation, manifests, and receipts. | `PackageCandidateIdentity`, `SkillPackageValidation`, `PackageManifest`, `PackageReceipt` |
| `src/skills_sdk/validation/` | Read-only standalone-skill capture, closed-frontmatter parsing, safe no-follow traversal, deterministic file evidence, and typed findings. | `SkillIR`, `read_frontmatter`, `validate_skill_package` |
| `src/skills_sdk/packaging/` | Composition of validation into a deterministic manifest and candidate-bound build receipt, followed by read-only hardening over that receipt; no archive or source mutation. | `build_skill_package` in `manifest.py`, `harden_skill_package` in `hardening.py` |
| `src/skills_sdk/evaluation/` | Pure deterministic scoring over externally produced, candidate-bound observations; no prompt, provider, package, or runtime execution. | `evaluate_scenario_set` in `deterministic.py` |
| `src/skills_sdk/lifecycle/` | Pure planning of candidate-bound intended runtime-lock transitions; no installation, host inspection, rollback execution, or runtime mutation. | `plan_runtime_install` in `planning.py` |
| `src/skills_sdk/distribution/` | Deterministic, local preparation of a private-registry receipt over immutable package and hardening receipts; no credentials, network access, upload, or publication. | `prepare_private_registry_candidate` in `private_registry.py` |
| `src/skills_sdk/models/safety.py` | Candidate-bound package-safety evidence states, typed findings/blockers, and digest-bound evidence references; no scanner, rights, admission, or runtime behavior. | `PackageSafetyEvidenceReceipt` |
| `src/skills_sdk/models/provider_execution.py` | Secret-free request metadata and adapter-supplied observations of external provider outcomes; no provider client, credentials, network action, billing, or generic receipt dispatch. | `ProviderExecutionRequest`, `ProviderExecutionResult` |
| `src/skills_sdk/cli/` | Argument parsing, route discovery, JSON/human rendering, and stable exit behavior at the process boundary. | `build_parser`, `main`, `_print_result` |
| `src/skills_sdk/schemas/` | Committed JSON Schema resources: generator-managed contracts plus hand-maintained `receipt-base.v1`, `blocker.v1`, and `package-identity.v1` resources, each covered by its applicable schema checks. | `scripts/generate_schemas.py`, `SchemaRegistry.load` |
| `tests/` | Contract, fixture, CLI, import-boundary, and validation-architecture proof. | `test_skill_package_validation.py`, `test_skill_validation_architecture.py`, `test_public_repository_boundary.py` |
| `docs/` | Reader-facing API, CLI, compatibility, and first-run detail. | `docs/agent-entrypoint.md`, `docs/api.md`, `docs/cli.md`, `docs/compatibility.md` |
| `scripts/` | Repository-owned schema generation and aggregate validation commands. | `generate_schemas.py`, `validate-repository.sh` |
| `examples/` | Small dependency-light examples of portable contract use. | `examples/inventory_contract.py` |

## Dependency direction and boundaries

- `core` contains host-independent primitives. It may be shared by models and
  services, but it must not import a provider or host adapter.
- `models` express portable data and cross-field invariants. They may use
  shared core primitives such as portable-path validation; they do not perform
  filesystem, provider, runtime, or publication work.
- `validation` depends on core and models. It does not depend on the packaging
  service, which keeps the read-only inspection path independently loadable.
- `packaging` composes validation and packaging models. Hardening consumes the
  build receipt and never rescans source state. Its public wrapper loads service
  implementations lazily so validation and packaging imports remain acyclic.
- `distribution` composes validated v2 package, hardening, and registry
  identity contracts into a local preparation receipt. It does not contain a
  registry client, credential boundary, filesystem writer, or publication
  operation.
- `lifecycle` composes package and registry receipts with an existing logical
  runtime lock to produce a deterministic intended transition. It does not
  inspect a host, resolve installation paths, apply files, or execute rollback.
- `cli` is the outermost process adapter. During `main()` dispatch, the
  `validate` and `build` routes import their validation and packaging services
  lazily, print versioned results, and map a blocked result to the documented
  exit status.
- `schemas` are contract resources, not an independent source of domain
  meaning. The generator and the Pydantic models are changed together when a
  public contract changes.
- The CLI service-invocation path is
  `CLI -> validation/packaging -> models/core`: only `validate` and `build`
  invoke those services, while reserved routes remain parse-only. This is not
  the package import graph. Importing `skills_sdk.cli.main` first initializes
  `skills_sdk/__init__.py`, whose public convenience exports eagerly import
  evaluation, distribution, lifecycle, and their model dependencies. Those
  Python API services otherwise follow
  `evaluation/distribution/lifecycle -> models/core`; the reserved CLI routes
  do not call them. Provider clients, host-runtime adapters, registry clients,
  and publication adapters remain external boundaries.

## Architectural invariants

These are the absences and relationships that are easy to miss when reading a
single module:

- **Local operations are read-only.** `validate_skill_package` and
  `build_skill_package` do not execute package code, write receipts into the
  package, create archives, install anything, or publish anything. Successful
  and blocked results carry `mutation_performed: false`.
- **Resolved downstream local artifacts are candidate-bound.** Once candidate
  identity is resolved, manifests and successful receipts carry the tuple of
  `package_id`, `source_revision`, and `content_sha256` that identifies the
  captured source state. A blocked receipt may have `candidate: null` when an
  identity cannot be resolved, such as for an invalid source revision; callers
  must not invent one. A package digest describes the manifest artifact and
  does not replace candidate identity.
- **The filesystem boundary is conservative.** Validation uses descriptor-
  relative, no-follow traversal; rejects symlinks, unsafe directories,
  screened credential filenames, unreadable or unstable content, and
  non-portable paths; the filename and directory policies are fixed denylists,
  and the filename policy does not scan arbitrary file contents for secrets.
  Observed source changes are typed blockers, but the before/after stat check is
  best-effort rather than a transactional snapshot. It records a deterministic
  sorted file manifest.
- **Failures are explicit at each public entry point.** `SchemaRegistry.validate`
  translates unknown schemas and schema/model failures into `ContractError`,
  while direct Pydantic model construction may raise `pydantic.ValidationError`.
  Package `validate` and `build` paths return versioned results; blocked results
  carry typed findings or blockers. There is no waiver or silent success path
  for a failed contract.
- **Shape and meaning are separate checks.** Packaged Draft 2020-12 resources
  establish structural shape, but `SchemaRegistry` loads only its registered
  schema names. It applies additional Pydantic semantic checks only for
  registered families; other packaged resources are loaded directly with a
  Draft 2020-12 validator, as described in the [API guide](docs/api.md).
- **Core ownership stays portable.** The package contains no implicit import
  of Agent-Skills, Tessl, Codex, a provider account, a host runtime, or a
  machine-specific filesystem layout. External adapters must supply their own
  candidate-bound evidence.
- **Evidence lanes do not collapse.** A local validation or receipt proves
  only its local lane. It does not prove hosted checks, provider acceptance,
  runtime installation, registry publication, or installed behavior.
- **Runtime planning is intended state only.** `RuntimeLock` and `InstallPlan`
  bind package, registry, target, file, and digest identities while retaining
  `mutation_performed: false`. A future host adapter owns apply and rollback
  journals, race handling, installation results, discovery, activation, and
  runtime-outcome evidence.

## Cross-cutting concerns

### Vocabulary and reader routing

Use [UBIQUITOUS.md](UBIQUITOUS.md) for terms that change the action, especially
“build”, “validate”, “verify”, “install”, “publish”, “candidate”, and “receipt”.
The active agent rules live in [AGENTS.md](AGENTS.md); implementation style and
contribution workflow remain in `CODESTYLE.md` and `CONTRIBUTING.md`.

### Schema generation and compatibility

`scripts/generate_schemas.py` derives the generator-managed committed resources
from the public models and applies the JSON-Schema-expressible constraints. It
does not regenerate the hand-maintained `receipt-base.v1.schema.json`,
`blocker.v1.schema.json`, or `package-identity.v1.schema.json` resources. Run
its `--check` mode for the generated subset. The canonical focused route for
the hand-maintained subset is:

```bash
mise exec -- uv run --frozen pytest tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py
```

That route loads all three resources through `SchemaRegistry.load`, which
performs the Draft 2020-12 schema check, and exercises their candidate
identity, generic receipt, and typed-blocker contracts. The aggregate
`bash scripts/validate-repository.sh` command includes these modules through
its full pytest run, but does not execute a separate hand-maintained-schema
command. Record `pass` only when the focused command exits `0` with all tests
passing, `fail` when it exits non-zero with a schema or contract assertion, or
`blocked` when it cannot run or complete; a blocked result must include the
concrete reason and nearest meaningful fallback. All of these resources are
part of the compatibility surface; pair public changes with schema, behavior,
and compatibility tests.

### Errors, statuses, and evidence

The public result contracts distinguish `pass`, `built`, and `blocked` states;
the generic receipt API normalizes those into proof-lane status while retaining
the artifact status. Portable evidence references point inside the captured
package rather than exposing machine paths. See `docs/api.md` for the wire
shapes and model-level rules.

### Testing

Tests concentrate on the boundaries that carry the most meaning: Pydantic and
JSON Schema contracts, safe package traversal and frontmatter, candidate and
receipt binding, CLI output and exit codes, import isolation, and public-doc
surfaces. The repository wrapper is the aggregate local proof for those lanes.

## Common change paths

1. **A new or changed contract:** edit the owning model in `models/`, regenerate
   and inspect its schema, add or update focused fixtures/tests, then update
   `docs/api.md` or `docs/compatibility.md` if the public meaning changed.
2. **A validator rule:** keep parsing in `validation/skill_ir.py`, filesystem
   policy and findings in `validation/skill_package.py`, and add a regression
   fixture or architecture test for the boundary you changed.
3. **A receipt or manifest rule:** preserve validation-first composition in
   `packaging/manifest.py`, enforce cross-field rules in the packaging models,
   and test both built and blocked receipts.
4. **A CLI route:** change `cli/main.py` and its help/output tests together;
   keep reserved routes parse-only until their owning service exists.
5. **A terminology or instruction change:** update the canonical glossary and
   the nearest pointer in `AGENTS.md`, then check the reader-facing links in
   [README.md](README.md) and this architecture map.

## Validation route

Use the pinned environment and the repository wrapper before a commit or pull
request:

```bash
mise exec -- uv sync --frozen
bash scripts/validate-repository.sh
```

The wrapper checks generated-schema drift, Ruff, the full pytest suite, source
and wheel builds, and `git diff --check`. For an executable change, also run
the exact CLI or Python path touched and record whether the result was `pass`,
`fail`, or `blocked`; local evidence does not substitute for hosted, provider,
runtime, or publication evidence.

### Evidence for this architecture update

The documentation-only capability-map update was checked with these exact
repository commands:

- `mise exec -- uv run --frozen pytest tests/test_public_repository_boundary.py tests/test_repository_standards.py tests/test_skill_validation_architecture.py`
  — `pass` (`84 passed`).
- `bash scripts/validate-codestyle.sh` — `pass` (Ruff, MyPy, repository
  standards, and Vale completed without findings).
- `mise exec -- uv run --frozen python scripts/generate_schemas.py --check` —
  `pass` (no generated-schema drift).
- `bash scripts/validate-repository.sh` — `pass` (`926 passed`, `1 skipped`;
  source distribution and wheel built successfully).
- `git diff --check` — `pass`.
- `git verify-commit 841ab6ebbff3ffd7bee4d1ff60ecbee0d11739eb` — `pass`
  (good native ED25519 signature for the exact reconciliation commit).

External outcome lanes remain blocked rather than inferred from those local
checks:

| Lane | Outcome | Concrete reason | Nearest meaningful fallback |
| --- | --- | --- | --- |
| Provider | `blocked` | The repository contains envelopes, not a provider client, credentials, or an authorized provider call. | Provider execution model, schema, and adapter-boundary tests. |
| Registry | `blocked` | Private-registry preparation performs no registry authentication, upload, or mutation. | Deterministic registry-preparation contract tests. |
| Host runtime | `blocked` | Runtime lifecycle code plans transitions but has no host apply or rollback adapter. | Runtime-lock and installation-planning contract tests. |
| Tessl | `blocked` | Tessl CLI routes are parse-only and no Tessl integration was executed. | CLI parser/help tests and candidate-bound local contract checks. |
| Publication | `blocked` | Publication is external to the SDK and no destination or publication authority was supplied. | Local build, immutable receipt, and registry-preparation proof. |

## Further reading

- [README.md](README.md) — reader-facing overview and first local commands.
- [AGENTS.md](AGENTS.md) — active task routing, boundaries, and validation rules.
- [UBIQUITOUS.md](UBIQUITOUS.md) — canonical project vocabulary and prompt translations.
- `docs/agent-entrypoint.md` — minimal cold-agent route.
- `docs/api.md` — contract families and schema validation.
- `docs/cli.md` — command behavior and exit codes.
- `docs/compatibility.md` — versioning and evidence separation.
