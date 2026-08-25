# Contributing

Use a dedicated branch and the pull-request template. Keep each change within
one contract, lifecycle operation, provider, or compatibility boundary. Public
contract changes require schema, behavior, and compatibility tests.

Run:

```bash
uv sync --frozen
bash scripts/validate-repository.sh
```
