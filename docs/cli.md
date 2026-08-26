# Command-line interface

Install the pinned development environment and inspect the CLI through the
managed `uv` entrypoint:

```bash
uv sync --frozen
uv run skills-sdk --help
uv run skills-sdk --version
```

The current CLI is intentionally boundary-only. It parses these explicit
routes and returns successfully without provider, runtime, or distribution
side effects:

```text
inventory   intake   validate   build   eval   package   project   verify
tessl prepare   tessl verify
```

Use `uv run skills-sdk <route> --help` for a short route description. The
routes are stable discovery boundaries while their deeper implementations are
built in separate, candidate-bound lanes. In particular:

- `inventory` is read-only source-inventory intent.
- `validate`, `build`, `eval`, and `package` name local contract lanes; the
  current command parser does not execute them yet.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through the public CLI contract.
