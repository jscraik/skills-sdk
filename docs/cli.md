# Command-line interface

From the repository checkout root, install the pinned development environment
and inspect the CLI through the managed `uv` entrypoint:

```bash
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --version
```

The CLI exposes these explicit routes without provider, runtime, or
distribution side effects:

```text
inventory   intake   validate   build   eval   package   project   verify
tessl prepare   tessl verify
```

Use `MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk <route> --help`
for a short route description. The
`validate` and `build` routes are implemented local commands:

```bash
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate ./skills/example --source-revision <40-lowercase-hex> --json --robot
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build ./skills/example --source-revision <40-lowercase-hex> --json --robot
MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision <40-lowercase-hex> --json --robot
```

All three commands are non-interactive and non-mutating. For an invocation that
reaches a service, exit `0` means validation passed, a receipt was built, or
the `eval scenario-quality` assessment passed;
exit `2` means a structured blocker was returned. Malformed invocations are
rejected by `argparse` with exit `2` before a versioned result exists.
`validate` returns `skill-package-validation/v1`; a successful `build` returns
a candidate-bound `package-receipt/v2` whose digest covers the canonical
manifest, without writing into the package. The generic parser continues to
accept `package-receipt/v1` for compatibility. A blocked build may have
`candidate: null` when the source identity cannot be resolved.
`--json` emits the versioned contract. `--robot` is an accepted no-op that
reserves the prompt-free automation contract. The remaining routes are stable
discovery boundaries while their deeper implementations are built in separate,
candidate-bound lanes:

- `inventory` is read-only source-inventory intent.
- `intake` is reserved and parse-only. `skills-sdk intake --help` describes
  the boundary; `skills-sdk intake` exits `0` without output or a receipt.
  It does not call the Python intake service and accepts no package inputs,
  `--json`, or `--robot` options. Use the [Python intake example](api.md#read-only-intake)
  for validation and normalization. Neither surface copies or admits a package.
- `eval scenario-quality` performs read-only package-local definition checks;
  other evaluation execution remains outside this command.
- `package` names a reserved local contract lane and does not execute.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through the public CLI contract.
