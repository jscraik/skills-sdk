# Contributing

Use a dedicated branch and the pull-request template. Keep each change within
one contract, lifecycle operation, provider, or compatibility boundary. Public
contract changes require schema, behavior, and compatibility tests.

Use Python 3.12 and the exact `uv` environment. Follow [CODESTYLE.md](CODESTYLE.md)
and keep generated schemas, public exports, parser registration, fixtures, and
compatibility documentation synchronized with contract changes.

## Contract acceptance and review

### Contributing skill authoring and update behaviour

Skills SDK owns the authoring guidance and enforcement for managed skills,
not only inspection after authoring elsewhere. Use the
[skill authoring contract](docs/workflow.md#skill-authoring-contract) when
designing or updating `SKILL.md`, its resources and its evaluation evidence.
Keep the portable implementation independent of Agent-Skills and Foundry.
This responsibility does not imply that every authoring route is executable;
check [current CLI support](docs/cli.md) before claiming automation.

1. Select create, update or inspect/adopt before changing a candidate. For
   creation, define the user outcome and selection boundaries. For an update,
   retain the known baseline and the finding or regression being corrected.
   For external adoption, retain provenance, ownership, rights and risk evidence
   before execution; do not silently rewrite the supplied source.
2. Choose a layout suited to the task and identify applicable package rules.
   Explain inputs, resources, authority limits, actions, recovery, outputs and
   completion evidence. Use supporting files only when they serve that outcome.
   Required fields and safe resource relationships are contracts; identical
   headings, line counts and prose style are not universal quality proof.
3. Separate deterministic validation from semantic review and behavioural
   evaluation. Retain findings and gaps, test neighbouring negative cases and
   corrected inputs, and distinguish skill selection from successful execution.
   An authoring improvement needs observed evidence, not only a cleaner document.
4. Bind changed source to a fresh candidate and rerun affected and dependent
   gates. Preserve the baseline and legitimate unchanged, rejected or
   inconclusive results. Bare-skill proof does not grant whole-plugin release
   clearance; publication, installation and runtime proof remain separate.

Change existing SDK guidance, services and tests together when their contract
changes. Do not create a second authoring framework or transfer ownership back
to a neighbouring repository. Review research-derived recommendations before
turning them into enforced rules; use the public-contract procedure below.

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

A capability-changing PR must update the affected status descriptions, or
explain in its description why none change. Use the existing
[workflow](docs/workflow.md) for accepted capabilities and boundaries,
[migration map](docs/migration-map.md) for legacy disposition, entrypoints,
proof and remaining actions, and [task record](docs/projects/sdk-workflow/tasks.md)
for delivery state. Review code and those documentation changes together.
After merge, reconcile the accepted revision in the task record before selecting
the next slice. Unmerged work remains labelled separately. Link and entrypoint
checks must not infer semantic completeness, live execution or migration parity.

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

The full wrapper reports elapsed seconds and failure status for schemas,
codestyle, tests, build, installed proof and diff hygiene. Tests run in two
isolated pytest-xdist workers with no test-selection exclusions and a slow-test
report. Use serial focused pytest when investigating a worker-sensitive failure;
do not relabel that narrower result as full proof.

For ordinary documentation-only changes, run
`bash scripts/validate-docs.sh --base <accepted-base> --head <current-head>`.
The classifier verifies Git identity, all committed changes, dirty tracked
paths and untracked non-ignored paths. It accepts only regular non-executable
prose in the documented allowlist. Other changes require the full wrapper.
The reduced route retains the existing documentation-dependent contract tests;
prose classification does not waive tests that consume those documents.
Hosted PR classification uses the trusted base implementation; a base without
that implementation defaults to full validation. Pushes to main remain full.
See [validation scope and phases](docs/standards.md#validation-scope-and-phases).

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
