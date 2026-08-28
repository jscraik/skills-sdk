# Code style

This repository owns its standards. The portable rules below are adapted from
the Agent-Skills engineering contract; Agent-Skills paths, host tooling, and
runtime policy are not dependencies of this SDK.

## Python and public contracts

- Target Python 3.12 and annotate every public function, method, and parameter.
- Validate untrusted data at ingress with explicit Pydantic or boundary models.
  Internal deterministic logic consumes normalized values and emits typed
  errors or blockers rather than ambiguous booleans.
- Use `pathlib.Path` at filesystem boundaries. Portable contracts contain only
  logical relative paths, never home directories, checkout paths, credentials,
  environment dumps, or host identities.
- Prefer functions of at most 40 lines and no more than five parameters. Split
  modules before 800 lines; the repository guard rejects functions over 120
  lines so gradual readability improvements cannot regress without bound.
- Avoid mutable global state, broad exception handlers, hidden I/O, and
  nondeterministic identity generation in core code.

## Architecture and compatibility

- Preserve dependency direction: models and core contracts remain independent
  of validation, packaging, evaluation, providers, host adapters, and CLI code.
  Services may depend on core contracts; CLI code composes services.
- Keep schema versions explicit. Additive families must not reinterpret a
  frozen v1 model or generated schema. Unknown receipt families fail closed.
- Keep validation, provider execution, registry mutation, runtime installation,
  and publication as separate evidence lanes.

## Enforcement

- Do not use lint, type, formatter, test, coverage, security, or validation
  suppressions. Repair the cause or return a typed blocker.
- Use Python 3.12 and run `uv sync --frozen` before validation to create or
  refresh the exact pinned environment.
- Run `bash scripts/validate-codestyle.sh` for formatter, lint, type, structural,
  documentation-link, configuration, dependency-direction, and suppression
  checks.
- MyPy semantically checks the repository-standards implementation and its
  regressions. The repository-wide AST gate separately requires typed public
  interfaces without reinterpreting frozen Pydantic v1/v2 inheritance.
- Run `bash scripts/validate-repository.sh` before a commit or pull request.
  Generated output must be checked, not hand-edited, and caches/build artifacts
  remain ignored.
- Record every validation command with an explicit `pass`, `fail`, or `blocked`
  outcome. A blocked result includes its concrete reason and nearest meaningful
  fallback; it is never reported as a pass.
- Tool versions are exact and destination-owned in `pyproject.toml`,
  `.mise.toml`, and `uv.lock`.

See [Repository standards](docs/standards.md) for enforcement details and
[Compatibility](docs/compatibility.md) for public versioning rules.
