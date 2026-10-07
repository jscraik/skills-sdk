# Command-line interface

## Supplied content-review evidence

`skills-sdk review-content '<package>' --source-revision '<revision>' --assessment '<assessment.json>' --json`
binds supplied reviewer metadata to the current candidate and its captured
source files. It reads a bounded regular assessment file without following
symlinks. Exit `0` means the supplied assessment is valid, complete for the
actual file inventory and contains only clear dispositions; exit `2` returns
a typed blocker for invalid inputs, stale evidence, findings or gaps.
This command does not perform semantic review, execute a judge, contact a
provider or authorise promotion. A passing result is not accuracy proof.

From the repository checkout root, install the pinned development environment
and inspect the CLI through the managed `uv` entrypoint:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --version
```

The CLI exposes these routes. Existing-copy maintenance is the only route
below that permits a host write, and requires explicit `--apply`. The names
do not by themselves implement the SDK's target create, update, full check,
external-intake, private Tessl delivery, or Codex installation workflow:

```text
inventory   intake   check-local   validate   build   eval   package   project   verify
tessl prepare   tessl verify
compare-copy   maintain-entrypoint
```

Use `mise exec -- uv run --frozen skills-sdk "<route>" --help` for a short route description. The
`intake`, `check-local`, `validate`, `build`, `eval scenario-quality`, `eval scorer-quality`,
`eval scorer-calibration`, `eval scenario-coverage`, and `eval selected-case`
are implemented local commands:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk intake ./skills/example --context ./intake-context.json --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk check-local ./skills/example --context ./intake-context.json --scenario-set active-v2 --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision "<40-lowercase-hex>" --scenario-set active-v2 --contract-version v2 --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scorer-quality ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scorer-calibration ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval selected-case ./skills/example --source-revision "<40-lowercase-hex>" --case happy-diff --mode release --host-input ./host-input.json --json --robot
```

The `intake`, `validate`, and `build` routes accept repeatable
`--require-file references/README.md` and opt-in `--check-reference-content`.
Required paths must be unique portable package-relative paths. Textual references
must be nonempty UTF-8; JSON and YAML must parse. Binary resources are not text
requirements. These flags do not establish semantic accuracy or review execution.
Neither policy is required by default. The existing `check-local/v1` composition
does not expose these flags; do not infer full package-quality coverage from it.

All listed commands are non-interactive and non-mutating. For an invocation that
reaches a service, exit `0` means intake normalized with an `admit` decision,
validation passed, a receipt was built, or a scenario/scorer assessment
passed. Exit `2` means a structured blocker, blocked receipt, or
normalized non-admit intake decision was returned. Intake decision blocker
codes remain visible in both JSON and human output. Malformed invocations are
rejected by `argparse` with exit `2` before a versioned result exists.
`intake` reads a `skill-package-intake-context/v1` JSON file and returns
`skill-package-intake/v1`; `validate` returns `skill-package-validation/v1`; a successful `build` returns
a candidate-bound `package-receipt/v2` whose digest covers the canonical
manifest, without writing into the package. The generic parser continues to
accept `package-receipt/v1` for compatibility. A blocked build may have
`candidate: null` when the source identity cannot be resolved.
`check-local` composes intake, package validation, an explicit ten-case v2
scenario set, scorer-quality declarations, and held-out scorer calibration in
that order. It stops at the first non-admit decision, blocked receipt, or
candidate-identity change. Its `local-check/v1` JSON envelope carries each
stage's existing versioned receipt, the candidate, and the blocked stage;
validate it with `SchemaRegistry().validate("local-check.v1", payload)`.
If safe descriptor-relative context reads are unavailable, it returns exit
`2` with a `blocked` envelope, `blocked_stage: context`, no stages, and the
same typed `unsupported_context_read` blocker used by `intake`. Exit `0` means only
`local_checks_passed`. `promotion_authorized` is always `false`: this command
does not execute scenarios or a judge, admit a package, publish to Tessl, or
install a runtime copy. Correct the input and rerun to obtain a fresh
candidate-bound result. The context must carry truthful source, owner, rights,
and check evidence; a synthetic context cannot prove real provenance.
Human output retains the blocked intake decision and blocker codes, or the
blocked check's finding codes and messages, as well as the stage status.
`--json` emits the versioned contract for individual routes. `--robot` is an accepted no-op that
reserves the prompt-free automation contract. Other routes remain stable
discovery boundaries while their deeper implementations are built in separate,
candidate-bound lanes:

- `inventory` is read-only source-inventory intent.
- `eval scenario-quality` performs read-only package-local definition checks.
  Its default v1 contract retains the 5/8/10 release-set policy. Explicit
  `--contract-version v2 --scenario-set <id>` selects exactly ten active cases
  without loading historical Markdown fixtures or executing cases.
- `eval scenario-coverage "<package>" --source-revision "<revision>"
  --scenario-set "<id>" --coverage-plan ./plan.json --json` audits declared
  claims against the checked ten-case active set. The bounded host-supplied
  plan is read without following symlinks. Malformed or stale plans block with
  exit `2`; a complete declared map exits `0`, including maps retaining owned
  gaps. Inspect `coverage_complete` and `open_gap_ids`; exit `0` is not release
  clearance, semantic accuracy, case execution, or proof of a complete claim
  inventory. The versioned result is `scenario-coverage/v1`.
- `eval scorer-quality` checks the candidate's `references/evals.yaml`
  `scorer_quality` declaration, including six probe types, judge parameters,
  rationale-audit samples, segmentation, and strict field types. It emits a
  `scorer-quality/v1` receipt; declared probes are not executed calibration.
- `eval scorer-calibration` checks the candidate's held-out
  `references/scorer-calibration/manifest.json`, JSONL examples, and matching
  raw scorer artifacts. It enforces threshold consistency, minimum positive
  and negative coverage, false-positive and false-negative limits, and scorer
  identity agreement with the valid declaration. It emits a
  `scorer-calibration/v1` receipt. The SDK reads supplied artifacts but neither
  runs a judge nor proves their external provenance.
- `eval selected-case` loads one declared case for the requested mode, runs a
  caller-supplied bounded text adapter, validates separately supplied semantic
  assertion evidence against the candidate, case, provider, and output digest,
  and emits an `evaluation-receipt/v2`. The host-input JSON contains
  `request`, `input_payload`, optional `adapter`, and optional
  `assertion_evidence` members. `assertion_evidence` is a
  `selected-case-judge-evidence/v1` artifact that binds the complete semantic
  assertion contract, candidate, scenario set, case, provider output, judge
  adapter, and judge-result digest. Its `evidence_refs` must include the
  host-supplied `judge-results/<judge_result_sha256>` path; the SDK does not
  create that artifact. Omitting the adapter or assertion evidence
  produces a typed blocker. This route does not discover provider executables,
  read credentials, select a model or profile, or establish live-model truth.
  Semantic signals must carry portable evidence references; the command does
  not infer them from keywords. Deterministic `contains`, `not_contains`, and
  `must_not` assertions are evaluated against the private supplied output.
  This JSON CLI route is controlled supplied-output proof. Host-injected
  provider-then-judge execution uses the Python
  `execute_selected_case_with_judge` API; JSON input does not import arbitrary
  provider or judge executables.
- `package` names a reserved local contract lane and does not execute.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

The intended managed installation source is an exact SDK-checked version in
Jamie's private Tessl `jscraik` workspace, not Foundry or Agent-Skills files.
No current CLI route publishes, reads back, or installs such a version. Only
Jamie chooses a public release. Origin-verified OpenAI-provided plugins and
OpenAI system skills keep their provider-managed loading and installation
routes. That route exemption does not waive applicable SDK checks or evidence
when those packages separately enter an SDK workflow.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through portable receipt contracts; host paths belong only in explicit
local adapter arguments.

## Existing-copy maintenance and comparison

The explicit `compare-copy` and `maintain-entrypoint` routes are documented in
[Runtime copy integration](runtime-copy-integration.md). Comparison is read-only.
Entrypoint maintenance requires `--apply` for a digest-bound change to an
existing host file; it is not the reserved `project` package-installation route.

## PR-sweep verification

The implemented `verify` subcommands inspect supplied local evidence without
contacting GitHub, resolving threads, changing a checkout, or authorizing a merge:

```bash
skills-sdk verify recurring-findings ./recurring-ledger.json --json --robot
skills-sdk verify pr-sweep-dirty-closeout --repo-root ./primary-checkout --ledger ./dirty-ledger.json --json --robot
skills-sdk verify pr-sweep-dirty-closeout --repo-root ./primary-checkout --require-clean --json --robot
```

The recurring-finding command checks the ledger schema, normalized-invariant
fingerprints, duplicate identities and occurrences, and the three-occurrence
guardrail rule. The dirty-closeout command requires the explicit worktree top
level and reads `git status` there without optional Git locks. A complete
ledger permits non-destructive accounting only;
`--require-clean` still fails if any staged, unstaged, or untracked path exists.
Both commands return `pr-sweep-validation/v1`: exit `0` for `pass` and `2` for
`fail` or `blocked`. Host paths are input arguments; the result contains only
repository-relative dirty paths. The skill's hosted checks, review, receipt,
authorization, and merge gates remain separate.
