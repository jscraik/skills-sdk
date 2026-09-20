# Command-line interface

From the repository checkout root, install the pinned development environment
and inspect the CLI through the managed `uv` entrypoint:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --version
```

The CLI exposes these routes. Existing-copy maintenance is the only route
below that permits a host write, and requires explicit `--apply`:

```text
inventory   intake   validate   build   eval   package   project   verify
tessl prepare   tessl verify
compare-copy   maintain-entrypoint
```

Use `mise exec -- uv run --frozen skills-sdk "<route>" --help` for a short route description. The
`intake`, `validate`, and `build` routes are implemented local commands:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk intake ./skills/example --context ./intake-context.json --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval selected-case ./skills/example --source-revision "<40-lowercase-hex>" --case happy-diff --mode release --host-input ./host-input.json --json --robot
```

All four commands are non-interactive and non-mutating. For an invocation that
reaches a service, exit `0` means intake normalized with an `admit` decision,
validation passed, a receipt was built, or the `eval scenario-quality`
assessment passed. Exit `2` means a structured blocker, blocked receipt, or
normalized non-admit intake decision was returned. Intake decision blocker
codes remain visible in both JSON and human output. Malformed invocations are
rejected by `argparse` with exit `2` before a versioned result exists.
`intake` reads a `skill-package-intake-context/v1` JSON file and returns
`skill-package-intake/v1`; `validate` returns `skill-package-validation/v1`; a successful `build` returns
a candidate-bound `package-receipt/v2` whose digest covers the canonical
manifest, without writing into the package. The generic parser continues to
accept `package-receipt/v1` for compatibility. A blocked build may have
`candidate: null` when the source identity cannot be resolved.
`--json` emits the versioned contract. `--robot` is an accepted no-op that
reserves the prompt-free automation contract. The remaining routes are stable
discovery boundaries while their deeper implementations are built in separate,
candidate-bound lanes:

- `inventory` is read-only source-inventory intent.
- `eval scenario-quality` performs read-only package-local definition checks.
- `eval selected-case` loads one declared case for the requested mode, runs a
  caller-supplied bounded text adapter, validates separately supplied semantic
  assertion evidence against the candidate, case, provider, and output digest,
  and emits an `evaluation-receipt/v2`. The host-input JSON contains
  `request`, `input_payload`, optional `adapter`, and optional
  `assertion_evidence` members. `assertion_evidence` is a
  `selected-case-judge-evidence/v1` artifact that binds the complete semantic
  assertion contract, candidate, scenario set, case, provider output, judge
  adapter, and judge-result digest. Omitting the adapter or assertion evidence
  produces a typed blocker. This route does not discover provider executables,
  read credentials, select a model or profile, or establish live-model truth.
  Semantic signals must carry portable evidence references; the command does
  not infer them from keywords. Deterministic `contains`, `not_contains`, and
  `must_not` assertions are evaluated against the private supplied output.
- `package` names a reserved local contract lane and does not execute.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through portable receipt contracts; host paths belong only in explicit
local adapter arguments.

## Existing-copy maintenance and comparison

The explicit `compare-copy` and `maintain-entrypoint` routes are documented in
[Runtime copy integration](runtime-copy-integration.md). Comparison is read-only.
Entrypoint maintenance requires `--apply` for a digest-bound change to an
existing host file; it is not the reserved `project` package-installation route.
