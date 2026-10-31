# SDK entrypoint

Follow [the canonical workflow](workflow.md) to select the intent and ordered
proof gates. Use [the migration map](migration-map.md) to distinguish current
SDK behaviour from legacy capability labels and planned routes.

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
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk check-local --help
```

Before a commit or pull request, run focused behaviour and contract checks,
applicable codestyle checks and diff hygiene through permitted entrypoints.
Use `bash scripts/validate-codestyle.sh` when available. Full local validation
is optional; the appropriate current hosted validation, independent review
and readiness remain required before merge. Record blocked local checks
rather than bypassing guards or requiring manual terminal execution. Follow
[validation order and evidence](standards.md#validation-order-and-evidence),
and repeat checks only after a relevant change, failure or unresolved concern.

The `inventory --help` route is the first detailed contract route. The SDK's
target workflow owns agent-facing creation, update, checking, external intake,
and installation orchestration, but this help route does not make those stages
executable. Use [CLI command status](cli.md) to distinguish implemented routes
from discovery-only names. Commands that prepare, publish, install, or activate
a candidate remain separate evidence lanes; `tessl prepare` does not publish
and `project` does not prove runtime behavior. Foundry holding is not SDK
clearance. Verified OpenAI-provided plugins and OpenAI system skills remain on
their provider-managed paths rather than this managed installation route.

The standards and tool-pin contract is documented in
[`CODESTYLE.md`](../CODESTYLE.md) and [`docs/standards.md`](standards.md).

## Inspect an existing skill read-only

Start with the clean, tracked synthetic fixture in the repository checkout,
including no ignored files within that fixture.
Use the pinned route and the revision you are inspecting:

```bash
test -z "$(git status --porcelain --ignored -- tests/fixtures/synthetic-skill)" &&
  MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate tests/fixtures/synthetic-skill --source-revision "$(git rev-parse HEAD)" --json --robot &&
  test -z "$(git status --porcelain --ignored -- tests/fixtures/synthetic-skill)" &&
  echo "validation passed; fixture unchanged"
```

A package that passes returns a `skill-package-validation/v1` result with
`"status": "pass"`, `"mutation_performed": false`, and exit `0`. A blocked
result has `"status": "blocked"`, a finding with a `code` and `message`, and
exit `2`; fix the named cause and rerun. For example, a malformed
`--source-revision` returns `invalid_source_revision` with `"candidate": null`.
Other malformed invocations, such as an omitted `package_root`, can exit `2` from
argument parsing without this result. See [CLI command status](cli.md) for the
route contract.

A pass means only that the package meets the structural contract. Package
conformance, semantic review, host selection and delivery, and useful behavior
are separate checks. Validation does not execute the package or run a provider,
and it grants no execution, admission, publication, installation, or release
authority. The [authoring contract](workflow.md#skill-authoring-contract)
separates these checks and keeps skill bodies task-specific.
