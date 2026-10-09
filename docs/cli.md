# Command-line interface

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
external-intake, registry delivery, or host installation workflow:

```text
inventory   intake   check-local   check-quality   validate   build   review-content   eval   package   project   verify
tessl prepare   tessl verify
compare-copy   maintain-entrypoint   validate-plugin
```

### Portable plugin inspection

Use `skills-sdk validate-plugin ./my-plugin --source-revision "<40-lowercase-hex>" --json --robot`
to inspect root `plugin.json` and bind the complete captured package. Add
`--require-version` and `--require-description` for those explicit SDK metadata
policies. Base-format optionality is preserved without those flags. Exit `0`
means structural pass, `2` means a typed blocked result. Both emit
`plugin-package-validation/v1`; human output labels the release limitation and
retains per-skill findings. No execution, admission, wrapping, publication or
installation occurs. MCP transport validity and artwork approval are not proved.
See [the API boundary](api.md#portable-plugin-validation) for capture limits and
[delivery state](projects/sdk-workflow/tasks.md) for subsequent workflow slices.
Portable plugin inspection was accepted in PR #52. Existing `validate` and `build` remain
standalone-skill commands; they do not auto-detect plugins.

The accepted route includes `--verify-evidence FILE` on this same command. Keep
the evidence file outside the plugin source root to avoid self-inclusion and a
changed candidate. Supply the same source revision and explicit
`--require-version` / `--require-description` flags used for the original capture; the CLI
compares the supplied envelope with a fresh capture of the actual plugin root
through `verify_plugin_package_validation`. Evidence must be a regular no-follow
JSON file of at most 16 MiB. Duplicate members, malformed JSON, invalid or stale
evidence, mismatches and unreadable source return typed blocked output with exit
`2`. A matching structural result uses the existing output and exit conventions,
and known special evidence files are rejected before opening the leaf. Post-open
type and drift checks remain; this is not an atomic filesystem snapshot.
Verification is not permission or release approval. Settings values are not echoed. Explicit
metadata-policy flags remain in blocked output, including evidence read, JSON
and mismatch failures. Corrected evidence retains the same requested policy.
The default
validation route without this option is unchanged. Structural verification does
not establish matched evaluation, execution permission or release readiness.

### Existing local routes

Use `mise exec -- uv run --frozen skills-sdk "<route>" --help` for a short route description. The
`intake`, `check-local`, `validate`, `build`, `review-content`, `eval scenario-quality`, `eval scorer-quality`,
`eval scorer-calibration`, `eval scenario-coverage`, and `eval selected-case`
are implemented local commands:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk intake ./skills/example --context ./intake-context.json --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk check-local ./skills/example --context ./intake-context.json --scenario-set active-v2 --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk review-content ./skills/example --source-revision "<40-lowercase-hex>" --assessment ./assessment.json --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scenario-quality ./skills/example --source-revision "<40-lowercase-hex>" --scenario-set active-v2 --contract-version v2 --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scorer-quality ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval scorer-calibration ./skills/example --source-revision "<40-lowercase-hex>" --json --robot
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk eval selected-case ./skills/example --source-revision "<40-lowercase-hex>" --case happy-diff --mode release --host-input ./host-input.json --json --robot
```

## Explicit local quality workflow

`skills-sdk check-quality '<package>' --request '<request.json>' --assessment '<assessment.json>' --json --robot`
composes the additive `local-check/v2` workflow. Its `local-check-request/v2`
input declares `create`, `update` or `external-check` intent, the exact candidate,
intake context, applicable file/reference policy, claim coverage plan and content
review lane. Update intent also requires a same-package baseline identity and
`--baseline-root '<baseline>'`; the service observes that source rather than
trusting the declaration. A no-op update is valid. These intents select checks,
not source authoring, copying or installation.

The ordered stages are baseline capture for updates, intake, selected-policy
validation, scenario coverage, scorer quality, held-out scorer artifact
assessment and content review. The first failed stage, non-admit intake,
incomplete coverage or changed candidate stops downstream work. An audit with
owned coverage gaps still blocks this composition. Final captures recheck both
the candidate and any update baseline. Correct the input and rerun for fresh
evidence; earlier stage receipts remain visible in a blocked result.

Exit `0` means `local_checks_passed`; exit `2` returns a versioned blocked
envelope, including unreadable, duplicate-member or symlinked JSON inputs.
Request reads have a one-MiB budget and assessment reads have an eight-MiB
budget. The CLI supports supplied content assessments only; an observed lane
requires the public API's explicitly supplied trusted callback, otherwise it
blocks. It never imports an arbitrary adapter from a file or module name.
`--robot` remains a non-interactive no-op.

`promotion_authorized` and `evaluation_executed` remain `false`. Scorer checks
assess supplied artifacts, not live judge execution or fresh calibration.
Supplied content review is not semantic review execution or accuracy proof.
The observed API lane retains its separate callback receipt; caller-owned
callback side effects cannot be claimed absent from its invocation receipt.
Security, executed evaluations, matched local/cloud improvement, registry
publication and runtime installation remain separate incomplete lanes.

## Supplied content-review evidence

`mise exec -- uv run --frozen skills-sdk review-content '<package>' --source-revision '<revision>' --assessment '<assessment.json>' --json`
binds supplied reviewer metadata to the current candidate and its captured
source files. It reads a bounded regular assessment file without following
symlinks. Exit `0` means the supplied assessment is valid, complete for the
actual file inventory and contains only clear dispositions; exit `2` returns
a typed blocker for invalid inputs, stale evidence, findings or gaps.
This command does not perform semantic review, execute a judge, contact a
provider or authorise promotion. A passing result is not accuracy proof.

The `intake`, `validate`, and `build` routes accept repeatable
`--require-file references/README.md` and opt-in `--check-reference-content`.
Required paths must be unique portable package-relative paths. Textual references
must be nonempty UTF-8, ignoring a leading BOM; JSON and YAML must parse.
Textual references larger than eight MiB return `reference_content_limit`
before decoding or parsing. Binary resources are not text
requirements. These flags do not establish semantic accuracy or review execution.
YAML references also return `reference_content_limit` above 128 nested
collections or 100,000 incremental parser events. This is a work budget, not
a wall-clock timeout.
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
- `eval observed-calibration` invokes numeric judge callbacks for every held-out
  probe and declared trial. The CLI requires `--adapter-mode supplied-offline`:
  its text outputs and numeric verdicts are supplied fixtures, not fresh model
  results. Use `skills-sdk eval observed-calibration ./skills/example
  --source-revision "<40-lowercase-hex>" --host-input ./calibration.json
  --adapter-mode supplied-offline --json --robot`. The bounded no-follow input
  has exactly `plan` and `executions` members. Each execution has `case_id`,
  `mode`, `request`, `input_payload`, `safety_evidence`, `provider`, and `judge`.
  The provider has `descriptor`, `output_text`, and `evidence_refs`; the judge
  has `identity`, `parameters`, and a `verdict` containing `evidence` and `score`.
  The plan freezes candidate, scorer, judge, parameters, policy, assertion digest,
  and ordered probe IDs, output digests and expected labels. Labels remain in
  the harness, outside the delegate input. The `observed-calibration/v1` result
  records invocation count and ordered outcomes; incomplete, drifted or unsafe
  batches block. Exit codes are `0` for pass and `2` for blocked. Neither outcome
  proves external authenticity or authorises promotion. See the maintained
  [installed calibration proof](../tests/installed_observed_calibration_smoke.py)
  for a complete synthetic input and accepted/rejected/recovery example.
- `eval selected-case` loads one declared case for the requested mode, runs a
  caller-supplied bounded text adapter, validates separately supplied semantic
  assertion evidence against the candidate, case, provider, and output digest,
  and emits an `evaluation-receipt/v2`. The host-input JSON contains
  `request`, `input_payload`, `safety_evidence`, optional `adapter`, and optional
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
  `safety_evidence` is `pre-execution-safety-evidence/v1`: actual built package,
  supplied safety-review receipt, completed SDK static screening, and the six
  explicit capability-review outcomes. The safety receipt must retain the
  canonical screening and checklist digests. Before adapter access, the SDK
  recaptures the source and requires the supplied screening to match it. Missing,
  contradictory, future, stale, or incomplete evidence blocks execution; receipt
  IDs alone do not clear this gate. Review freshness defaults to one hour.
  Static indicators and supplied review metadata do not establish scanner
  execution, reviewer authenticity, or comprehensive security clearance.
- `package` names a reserved local contract lane and does not execute.
- `project` names runtime projection intent; parsing it does not prove
  installed behavior.
- `tessl prepare` and `tessl verify` name preparation and verification only;
  neither publishes or changes registry state.

The intended managed installation source is an exact SDK-checked plugin version
through a verified registry route, initially Jamie's private Tessl `jscraik`
workspace, not Foundry or Agent-Skills files. The
[registry-independent target](workflow.md#registry-transition) does not add a
replacement-registry endpoint flag or turn the existing `tessl` discovery routes
into generic registry clients. No current CLI route publishes, reads back, or
installs such a version. Only
Jamie chooses a public release. Origin-verified OpenAI-provided plugins and
OpenAI system skills keep their provider-managed loading and installation
routes. That route exemption does not waive applicable SDK checks or evidence
when those packages separately enter an SDK workflow.

Run `bash scripts/validate-repository.sh` for the repository's complete local
schema, lint, test, build, and diff checks. Do not pass credentials or machine
paths through portable receipt contracts; host paths belong only in explicit
local adapter arguments.

## Matched evaluation candidate

These S4 commands are unmerged integration work. They use supplied evidence or
explicit supplied-offline callbacks, not discovered live model adapters.
Use the [API contract](api.md#matched-whole-plugin-evaluation-candidate) for the
full-plugin, ten-case, child calibration, safety and budget requirements.

```bash
skills-sdk eval matched-assessment --input ./assessment.json --json --robot
skills-sdk eval matched-handoff --input ./handoff.json --json --robot
skills-sdk eval matched-calibration --input ./calibration.json --adapter-mode supplied-offline --json --robot
skills-sdk eval matched-local --input ./local.json --adapter-mode supplied-offline --json --robot
skills-sdk eval matched-cloud --input ./cloud.json --adapter-mode supplied-offline --json --robot
skills-sdk eval matched-regression --input ./regression.json --adapter-mode supplied-offline --json --robot
skills-sdk eval matched-cloud-regression --input ./cloud-regression.json --adapter-mode supplied-offline --json --robot
```

Use the pinned `mise exec -- uv run --frozen skills-sdk` command prefix when
working from this repository. Input JSON is external host input, not a plugin
manifest; keep it outside the plugin source tree. The shared reader applies
no-follow input checks with a 16 MiB matched-input limit and rejects duplicate
members or malformed JSON. The larger matched allowance holds repeated complete
plugin and calibration evidence; existing intake and calibration limits are unchanged.

- `matched-assessment` requires exactly `plan`, `lane`, `baseline` and
  `candidate`; it assesses supplied paired judgments without execution.
- `matched-handoff` requires exactly `local` and `cloud_plan`; readiness binds
  a qualified local candidate to the cloud baseline without authorising spend.
- `matched-calibration` requires exactly `plan`, `rubric` and `executions`;
  the ordered probe callbacks return supplied dimensional judgments.
- `matched-local` requires exactly `plan`, `calibrations` and `executions`.
  `calibrations` contains both child-target bundles; `executions` contains
  exactly ten baseline/candidate pairs with explicit private plugin context
  and safety inputs.
- `matched-cloud` replaces `plan` with `handoff` while retaining both bundles
  and the complete execution batch.
- Both regression routes require `initial`, `assignments`, `plan`,
  `calibrations` and `executions`. Assignments identify failed-case owners;
  a complete rerun and unchanged source are required for closure.

Exit `0` means assessed, ready, passing calibration, completed execution or
closed regression as appropriate; exit `2` means blocked or open. JSON emits
the corresponding versioned contract, not hidden source documents. The lane
summary is currently a derived API property and is not emitted as a JSON field.
Offline callbacks do not prove externally generated answers or judge scores,
live-model improvement, authenticated review, publication or promotion.
Reported-cost limits block before callbacks because cost observations are not
available; elapsed deadlines prevent later callbacks but are not hard cancellation.

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
