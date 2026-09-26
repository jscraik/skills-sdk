# Contributing

Use a dedicated branch and the pull-request template. Keep each change within
one contract, lifecycle operation, provider, or compatibility boundary. Public
contract changes require schema, behavior, and compatibility tests.

Use Python 3.12 and the exact `uv` environment. Follow [CODESTYLE.md](CODESTYLE.md)
and keep generated schemas, public exports, parser registration, fixtures, and
compatibility documentation synchronized with contract changes.

## Contract acceptance and review

Before implementation, name one consuming workflow, the contract invariant,
and accepted and rejected examples. Keep these cases in the existing tests or
fixtures. For migration, follow the
[source-parity requirements](docs/compatibility.md#workflow-migration-proof).

For each changed invariant, select the supported boundaries that can expose
it: raw mappings or JSON, valid typed objects, forged top-level or nested typed
objects, direct models, packaged JSON Schema, `SchemaRegistry`, and the public
service or CLI. Cover malformed, empty, conflicting, and boundary values when
relevant, with a valid neighbouring case. Record intentional differences
between structural schema checks and semantic validation. Do not add tests
for unsupported entrypoints or infer complete coverage from the test count.

When review reproduces a defect, inspect that invariant across related
entrypoints before publishing the repair. Retain the reproduction, supported
neighbours, and any remaining coverage gap. Ask independent reviewers to
examine named failure mechanisms and the complete candidate; a clean focused
repair review proves only its inspected scope.

Complete known in-scope corrections before requesting fresh hosted review.
Run focused proof during repair and the required aggregate on the final
candidate. Repeat checks only after relevant changes, failures, or uncovered
risks. Keep one writer per branch. A signing, CI, or review blocker stops only
dependent actions; continue independent authorized diagnosis and local work.

Use behavioural tests for executable claims. Documentation checks may prove
links, examples, and required structure; matching prose or historical commit
identifiers does not prove runtime behaviour. Store dated validation outcomes
in audit records rather than making their wording a permanent test contract.

## Validation and delivery

Run:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise install python uv ruff vale
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
bash scripts/validate-codestyle.sh
bash scripts/validate-repository.sh
```

The codestyle wrapper runs the pinned Vale release with the SDK-owned prose
rules. Repair prose findings in the owning document; do not add inline
suppression comments or exclusions.

Commits use Conventional Commit subjects and native Git signing through the
configured signer. Do not bypass hooks or use an unsigned fallback. Pull
requests must follow the repository template; local checks do not establish
hosted CI, review, mergeability, publication, or runtime readiness.

Before creating a pull request, write the exact repository-relative scope file
and run the projected `python3 ~/.codex/scripts/pr-readiness.py --phase create --scope-file <scope-file> --write-receipt`
gate. Before updating the description or claiming merge readiness, run its
`--phase update --scope-file <scope-file> --write-receipt` gate against the current hosted head. Refresh the description
only through the projected `python3 ~/.codex/scripts/pr-body-refresh.py` helper
so the update receipt, repository identity, pull request number, required
sections, fields, command evidence, and checklist stay bound together. These
are user-level projected workflow controls, not repository-owned SDK scripts.
The hosted `validate` job checks the body against the trusted base template;
the first validator-bearing pull request uses the candidate only for the
explicit bootstrap case where the base has no validator yet.
