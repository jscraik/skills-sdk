# SDK entrypoint

The default `skills-sdk --help` route is intentionally short. It exposes the
portable lifecycle commands without loading package-specific contracts,
provider credentials, runtime state, or distribution instructions.

Use the smallest explicit route for the current task:

```bash
uv sync --frozen
uv run skills-sdk --help
uv run skills-sdk inventory --help
bash scripts/validate-repository.sh
```

The `inventory --help` route is the first detailed contract route. Commands
that prepare, publish, install, or activate a candidate remain separate
evidence lanes; `tessl prepare` does not publish and `project` does not prove
runtime behavior.
