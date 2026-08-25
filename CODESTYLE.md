# Code style

- Target Python 3.12 and type every public interface.
- Keep the dependency direction `core -> services -> providers -> CLI`.
- Provider modules may import core contracts; core modules must not import a
  provider or host adapter.
- Split modules before 800 lines and prefer substantially smaller files.
- Use `pathlib.Path` for filesystem boundaries and validate untrusted data at
  ingress.
- Do not hard-code repository names, workspace identities, or user-specific
  paths in portable core code.
- Do not use lint, type, test, security, or validation suppressions.
- Run Ruff, tests, and package build through the pinned `uv` environment.
