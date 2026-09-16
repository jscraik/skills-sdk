# SDK entrypoint

The default `skills-sdk --help` route is intentionally short. It exposes the
portable lifecycle commands without executing providers, inspecting runtime
state, or performing distribution work. Python initialization still imports
public contract models and service modules; short help does not imply an
isolated import graph.

For a new checkout or missing pinned tools, prepare the environment:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise install python uv ruff vale
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
```

Reuse a prepared environment. For CLI discovery, run only the help needed:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk inventory --help
```

For focused checks while editing, run `bash scripts/validate-codestyle.sh`.
Before a commit or pull request, run `bash scripts/validate-repository.sh`;
it already includes the codestyle check. Repeat or broaden checks only after a
relevant change, failure, or unresolved concern.

The `inventory --help` route is the first detailed contract route. Commands
that prepare, publish, install, or activate a candidate remain separate
evidence lanes; `tessl prepare` does not publish and `project` does not prove
runtime behavior.

The standards and tool-pin contract is documented in
[`CODESTYLE.md`](../CODESTYLE.md) and [`docs/standards.md`](standards.md).
