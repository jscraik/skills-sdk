# Contributing

Use a dedicated branch and the pull-request template. Keep each change within
one contract, lifecycle operation, provider, or compatibility boundary. Public
contract changes require schema, behavior, and compatibility tests.

Use Python 3.12 and the exact `uv` environment. Follow [CODESTYLE.md](CODESTYLE.md)
and keep generated schemas, public exports, parser registration, fixtures, and
compatibility documentation synchronized with contract changes.

Run:

```bash
uv sync --frozen
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
and run the projected `pr-readiness.py --phase create` gate. Before updating the
description or claiming merge readiness, run its `--phase update` gate against
the current hosted head. Refresh the description only through the projected
`pr-body-refresh.py` helper so the update receipt, repository identity, pull
request number, required sections, fields, command evidence, and checklist stay
bound together. The hosted `validate` job checks the body against the trusted
base template; the first validator-bearing pull request uses the candidate only
for the explicit bootstrap case where the base has no validator yet.
