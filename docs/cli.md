# Command-line interface

Install the pinned development environment and inspect the CLI through the
managed `uv` entrypoint:

```bash
uv sync --frozen
uv run skills-sdk --help
uv run skills-sdk --version
```

The CLI exposes these explicit routes without provider, runtime, or
distribution side effects:

```text
inventory   intake   validate   build   eval   package   project   verify
tessl prepare   tessl verify
```

Use `uv run skills-sdk <route> --help` for a short route description. The
`validate` and `build` routes are implemented local commands:

```bash
uv run skills-sdk validate ./skills/example --source-revision <40-lowercase-hex> --json --robot
uv run skills-sdk build ./skills/example --source-revision <40-lowercase-hex> --json --robot
```

Both commands are non-interactive and non-mutating. For an invocation that
reaches a service, exit `0` means validation passed or a receipt was built;
exit `2` means a structured blocker was returned. Malformed invocations are
rejected by `argparse` with exit `2` before a versioned result exists.
`validate` returns `skill-package-validation/v1`; a successful `build` returns
a candidate-bound `package-receipt/v1` without writing into the package. A
blocked build may have `candidate: null` when the source identity cannot be
resolved.
`--json` emits the versioned contract. `--robot` is an accepted no-op that
reserves the prompt-free automation contract. The remaining routes are stable
discovery boundaries while their deeper implementations are built in separate,
candidate-bound lanes:

- `inventory` is read-only source-inventory intent.
- `eval` and `package` name reserved local contract lanes and do not execute.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through the public CLI contract.
