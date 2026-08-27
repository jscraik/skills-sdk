# Architecture

Skills SDK is a portable Python contract layer and local tooling surface for
Agent Skills packages. It turns untrusted package source and contract-shaped
payloads into explicit, versioned records while keeping provider execution,
runtime projection, distribution, and publication outside the core package.

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
- Changing command behavior: start at `main` and `build_parser` in
  `src/skills_sdk/cli/main.py`, then read `docs/cli.md`.
- Changing vocabulary or agent routing: read [UBIQUITOUS.md](UBIQUITOUS.md)
  and [AGENTS.md](AGENTS.md) before editing prose or instructions.

## Bird's-eye view

There are two related local paths. A package path captures a filesystem view,
validates its entrypoint and files, and then (only after a pass) composes a
candidate-bound manifest and receipt. A contract path validates JSON-shaped
payloads against packaged schemas and, for registered families, applies the
corresponding Pydantic invariants.

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
    +--> structural schema result, semantic model result, or ContractError

Local candidate-bound proof
    |
    +--> provider, runtime, distribution, and publication adapters
         (separate lanes; not implemented by this core package)
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
| `src/skills_sdk/packaging/` | Composition of a successful validation into a deterministic manifest and candidate-bound receipt; no archive or source mutation. | `build_skill_package` in `manifest.py` |
| `src/skills_sdk/cli/` | Argument parsing, route discovery, JSON/human rendering, and stable exit behavior at the process boundary. | `build_parser`, `main`, `_print_result` |
| `src/skills_sdk/schemas/` | Committed JSON Schema resources generated from public Pydantic contracts and checked for drift. | `scripts/generate_schemas.py`, `SchemaRegistry.load` |
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
- `packaging` composes validation and packaging models. Its public wrapper
  loads the manifest implementation lazily so the validation and packaging
  imports remain acyclic.
- `cli` is the outermost process adapter. It imports the implemented services
  lazily, prints their versioned results, and maps a blocked result to the
  documented exit status.
- `schemas` are contract resources, not an independent source of domain
  meaning. The generator and the Pydantic models are changed together when a
  public contract changes.
- The repository's conceptual direction is `core -> services -> providers ->
  CLI`. This checkout currently implements the core, model, validation,
  packaging, and CLI portions; provider, runtime, distribution, and
  publication adapters remain explicit external boundaries.

## Architectural invariants

These are the absences and relationships that are easy to miss when reading a
single module:

- **Local operations are read-only.** `validate_skill_package` and
  `build_skill_package` do not execute package code, write receipts into the
  package, create archives, install anything, or publish anything. Successful
  and blocked results carry `mutation_performed: false`.
- **Every downstream local artifact is candidate-bound.** The tuple of
  `package_id`, `source_revision`, and `content_sha256` identifies the captured
  source state. A package digest describes the manifest artifact and does not
  replace candidate identity.
- **The filesystem boundary is conservative.** Validation uses descriptor-
  relative, no-follow traversal; rejects symlinks, unsafe directories,
  credential-like files, unreadable or unstable content, and non-portable
  paths; and records a deterministic sorted file manifest.
- **Failures are explicit.** Invalid input produces a typed `ContractError` or
  a versioned result containing typed blockers. There is no waiver or silent
  success path for a failed contract.
- **Shape and meaning are separate checks.** Packaged Draft 2020-12 schemas
  establish structural shape. Only the contract families registered with
  `SchemaRegistry` receive their additional Pydantic semantic checks through
  that registry; the compatibility docs describe the bare wire-shape
  exceptions.
- **Core ownership stays portable.** The package contains no implicit import
  of Agent-Skills, Tessl, Codex, a provider account, a host runtime, or a
  machine-specific filesystem layout. External adapters must supply their own
  candidate-bound evidence.
- **Evidence lanes do not collapse.** A local validation or receipt proves
  only its local lane. It does not prove hosted checks, provider acceptance,
  runtime installation, registry publication, or installed behavior.

## Cross-cutting concerns

### Vocabulary and reader routing

Use [UBIQUITOUS.md](UBIQUITOUS.md) for terms that change the action, especially
“build”, “validate”, “verify”, “install”, “publish”, “candidate”, and “receipt”.
The active agent rules live in [AGENTS.md](AGENTS.md); implementation style and
contribution workflow remain in `CODESTYLE.md` and `CONTRIBUTING.md`.

### Schema generation and compatibility

`scripts/generate_schemas.py` derives committed resources from the public
models and applies the JSON-Schema-expressible constraints. The generated
files are part of the compatibility surface. Run its `--check` mode whenever
contract models or schema behavior changes, and pair public changes with
schema, behavior, and compatibility tests.

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
uv sync --frozen
bash scripts/validate-repository.sh
```

The wrapper checks generated-schema drift, Ruff, the full pytest suite, source
and wheel builds, and `git diff --check`. For an executable change, also run
the exact CLI or Python path touched and record whether the result was `pass`,
`fail`, or `blocked`; local evidence does not substitute for hosted, provider,
runtime, or publication evidence.

## Further reading

- [README.md](README.md) — reader-facing overview and first local commands.
- [AGENTS.md](AGENTS.md) — active task routing, boundaries, and validation rules.
- [UBIQUITOUS.md](UBIQUITOUS.md) — canonical project vocabulary and prompt translations.
- `docs/agent-entrypoint.md` — minimal cold-agent route.
- `docs/api.md` — contract families and schema validation.
- `docs/cli.md` — command behavior and exit codes.
- `docs/compatibility.md` — versioning and evidence separation.
