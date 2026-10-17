# Command-line interface

From the repository checkout root, install the pinned development environment
and inspect the CLI through the managed `uv` entrypoint:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv sync --frozen
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --help
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk --version
```

The CLI exposes these routes. Existing-copy maintenance is the only route
below that permits a host/runtime write, and requires explicit `--apply`.
`normalize-plugin` is a separate create-only operation: it writes a new plugin
candidate at the caller's destination and refuses to replace an existing path.
Apart from those two documented write operations, the other routes are
read-only. The routes do not by themselves implement the complete SDK create,
update, external-intake, registry delivery, or host installation workflow:

```text
inventory   intake   check-local   check-quality   validate   build   review-content   eval   package   project   verify
tessl prepare   tessl verify
compare-copy   maintain-entrypoint   validate-plugin   normalize-plugin   check-plugin-presentation
```

A missing command, including `skills-sdk tessl` without a subcommand, is a
usage error: exit `2` with a diagnostic on stderr. Help requests still exit `0`.
Named discovery-only routes use exit `3` with their explicit diagnostic.

### Distinguishing usage errors from typed blockers

Exit `2` alone does not show that a versioned result exists. Check stdout and
stderr separately. This example creates a disposable package named `demo-skill`
in a temporary directory outside the checkout, then runs the `validate` route
from the checkout root. The revision is a synthetic value with the required
shape; it does not identify real source history. The `pwd -P` step resolves
symlinked ancestors, such as the one in a default macOS `mktemp` path. The SDK
refuses to traverse them and reports `unreadable_package_root` and
`unreadable_skill_md` with exit `2` for an otherwise valid package. Passing the
physical path keeps that no-follow check in force:

```bash
DEMO="$(cd "$(mktemp -d)" && pwd -P)"
mkdir "$DEMO/demo-skill"
printf -- '---\nname: demo-skill\ndescription: Demonstrates validate exit codes.\n---\n\n# Demo skill\n' > "$DEMO/demo-skill/SKILL.md"
REV=0123456789abcdef0123456789abcdef01234567
export MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml"
mise exec -- uv run --frozen skills-sdk validate --json --robot
mise exec -- uv run --frozen skills-sdk validate "$DEMO/demo-skill" --source-revision abc123 --json --robot
mise exec -- uv run --frozen skills-sdk validate "$DEMO/demo-skill" --source-revision "$REV" --json --robot
```

- The first command omits the required `package_root`. `argparse` rejects it with
  exit `2`, empty stdout, and a usage text plus an `error:` line on stderr. No
  JSON exists, so a caller that parses stdout loses the diagnostic. Recover by
  correcting the invocation, using `--help` for the accepted arguments.
- The second command is well formed, so it reaches the validator. It exits `2`
  with empty stderr and a parseable `skill-package-validation/v1` result on
  stdout with `"status": "blocked"` and the finding `invalid_source_revision`
  for the short revision `abc123`.
  Valid JSON and exit `2` still mean the operation was rejected. Read the
  `findings` codes, fix the cause, and run again.
- The third command supplies the 40-character lowercase `$REV`. It exits `0`
  with `"status": "pass"` and no findings. Here `mutation_performed` is `false`.
  The pass shows only that the revision has a valid shape and the package is
  structurally valid. `$REV` is synthetic, not authenticated provenance.

Observed on disposable synthetic inputs, the package files kept identical
SHA-256 digests across all three runs. Argparse wording can change, and other
routes can format diagnostics differently, so branch on the exit status first.
Then parse stdout only when the invocation reached a service, and check its
`schema_version` and `status`. Never run skill or plugin content to diagnose a
result.

### Plugin presentation assessment

Accepted PR #60 provides the bounded S2 presentation assessment through
`skills-sdk check-plugin-presentation ./my-plugin --source-revision '<40-lowercase-hex>' --request ./request.json --json --robot`.
Keep the request outside plugin source. It must be regular no-follow JSON bounded
to one MiB; duplicate members, malformed input and symlinks block. Exit `0` means
offline assessment pass; `2` returns typed `plugin-presentation-check/v1` blockers.
Human output states the limitation; `--robot` is prompt-free, not authority.

The [API profile](api.md#plugin-presentation-assessment) defines image limits,
approval coverage and optional onboarding references. `skills-sdk[images]` adds
raster decoding; missing support blocks raster inspection while base help and
bounded SVG remain available. Retained approval is invalid after byte/mode drift.
Corrected inputs need fresh affected checks. A pass is not release, archive,
independent rights/visual review, installation or display clearance. Existing
`validate-plugin` and standalone commands retain their meanings.

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

Add `--verify-evidence FILE` to `validate-plugin` to verify a supplied envelope.
Keep the evidence file outside the plugin source root to avoid self-inclusion
and a changed candidate. Supply the same source revision and explicit
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
The default validation route without this option is unchanged. Structural
verification does not establish matched evaluation, execution permission or
release readiness.

Worked capture and verification, run from a directory that holds both the plugin
and a separate `evidence/` directory:

```bash
REV="<40-lowercase-hex>"
FLAGS=(--source-revision "$REV" --require-version --require-description)
skills-sdk validate-plugin ./my-plugin "${FLAGS[@]}" --json --robot > evidence/plugin-validation.json
skills-sdk validate-plugin ./my-plugin "${FLAGS[@]}" --json --robot --verify-evidence evidence/plugin-validation.json
```

Capture exits `0` and writes a `plugin-package-validation/v1` result with
`"status": "pass"`. Verification of the unchanged plugin exits `0` and prints the
same structural result. A formatting-only edit to the evidence file still
verifies, because the parsed result is unchanged. A content edit is blocked with
exit `2`: finding `plugin_evidence_invalid` when the file is malformed or breaks
the evidence contract, and `plugin_evidence_mismatch` when it parses but differs
from the fresh capture (for example a changed `openai_settings_sha256`). That
exit is the expected rejection, not an ordinary pass command.
After a source change, capture again and verify the new file; after an evidence
change, restore or recapture it. Keep the same revision and policy flags in both
commands.

This check is structural. It does not authenticate caller-supplied provenance,
establish that the skills are accurate or useful, execute the plugin, or grant
release, publication or installation authority. Skill bodies stay flexible and
the plugin remains the unit of ownership; see [the API boundary](api.md#portable-plugin-validation).

### Explicit standalone-skill plugin preparation

Use `normalize-plugin` only when the caller explicitly wants to preserve a
standalone skill and create a separate managed-plugin candidate:

```bash
MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk normalize-plugin ./skills/example ./example-plugin --context ./intake-context.json --plugin-name example-plugin --plugin-version 1.0.0 --plugin-description "A concise description of the plugin." --json --robot
```

The command requires a bounded, regular no-follow
`skill-package-intake-context/v1` JSON file (at most one MiB) whose provenance,
ownership, rights and continuity checks admit the source. Metadata is supplied
explicitly by the caller and validated against
`plugin-normalization-metadata/v1`. The command copies the standalone skill beneath
`skills/<skill-name>/`, writes a canonical root `plugin.json`, and freshly
validates the complete plugin. It never edits the input, follows unsafe paths,
or overwrites an existing destination. A partial write is reported with
`candidate_created` so the caller can inspect and correct the destination
before retrying. The destination parent must already exist; the example uses
the current directory as that parent.
The canonical manifest must fit one MiB after UTF-8 encoding and JSON escaping.
Unsupported or unsafe source capture returns
`standalone_source_capture_blocked`. The complete output must also fit capture
bounds after adding its manifest and wrapper; a pre-write capacity rejection
returns `standalone_source_capacity_exceeded` with `candidate_created: false`.
Destination symlink loops return typed `candidate_normalization_failed`
output, not a traceback. Directory-identity checks also reject source-contained
parents through different case spellings before creating output. An observed difference from admitted or
pre-copy source evidence returns `source_changed`. Correct the responsible source or metadata and
retry into a fresh destination, retaining previous failures. Changed candidates
require fresh intake and downstream evidence.

With `--json`, a completed service call emits `plugin-normalization/v1`.
Exit `0` means a separate candidate was prepared and whole-plugin structural
validation passed; exit `2` means a typed blocker. Malformed or unreadable
context and invalid metadata are rejected before a versioned receipt is created.
A prepared receipt
retains the standalone intake result and binds the sole plugin child to that
candidate. Caller-supplied provenance, ownership and rights assertions are not
independently authenticated. The receipt always sets `release_ready` to
`false`: preparation is not semantic accuracy, presentation or rights approval,
archive creation, publication, installation, or runtime verification. This
route does not update an existing plugin against a baseline; updates retain a
known baseline and require a separate update workflow.

#### Worked example: rights refusal, occupied destination and recovery

This example uses only synthetic data. The repository name, revision, owner and
rights decision are fixture assertions, not authenticated evidence. Run every
command from the SDK checkout root, in one shell session, and keep the fixture
outside the source tree. The example sets the permissions it relies on, so it
behaves the same under a `022` or `002` umask without changing the umask.
Set up a physical temporary directory, one standalone skill and an intake context
whose rights decision is still unconfirmed:

```bash
WORK="$(cd "$(mktemp -d)" && pwd -P)"
mkdir -p "$WORK/source/demo-skill" "$WORK/output" "$WORK/snap"
chmod 0755 "$WORK/output"
printf '%s\n' '---' 'name: demo-skill' 'description: Synthetic skill used to demonstrate plugin preparation.' '---' '' '# Demo skill' '' 'Reply with a short greeting.' > "$WORK/source/demo-skill/SKILL.md"
cat > "$WORK/intake-context.json" <<'EOF'
{
  "schema_version": "skill-package-intake-context/v1",
  "source_repository": "example/synthetic-skills",
  "source_revision": "0123456789abcdef0123456789abcdef01234567",
  "source_path": "demo-skill",
  "source_kind": "local",
  "owner": {
    "owner": "synthetic-owner",
    "maintainer": "synthetic-owner",
    "ownership_state": "canonical",
    "rights": {"basis": "authored", "license": "Apache-2.0", "evidence_ref": "SKILL.md"}
  },
  "checks": {"identity": true, "provenance": true, "rights": false, "owner_unchanged": true}
}
EOF
prepare() {
  MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk normalize-plugin "$WORK/source/demo-skill" "$WORK/output/$1" --context "$WORK/intake-context.json" --plugin-name demo-plugin --plugin-version 1.0.0 --plugin-description "Synthetic plugin candidate." --json --robot
}
measure() {
  python3 - "$1" <<'EOF'
import hashlib, os, stat, sys
root, rows = sys.argv[1], []
if not os.path.isdir(root):
    sys.exit("not a directory: " + root)
for base, dirs, files in os.walk(root):
    for name in dirs + files:
        path = os.path.join(base, name)
        mode = os.lstat(path).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            sys.exit("not a regular file: " + path)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        rows.append("%s %s %s" % (os.path.relpath(path, root), digest, oct(stat.S_IMODE(mode))))
if not rows:
    sys.exit("no files under: " + root)
print("\n".join(sorted(rows)))
EOF
}
snap() { measure "$1" > "$WORK/snap/$2" || { echo "measurement failed: $2" >&2; return 1; }; }
same() { snap "$1" "$3" && cmp -s "$WORK/snap/$2" "$WORK/snap/$3" && echo "unchanged: $3" || { echo "CHANGED or unmeasured: $3" >&2; return 1; }; }
snap "$WORK/source" source.before
```

`measure` records each regular file's relative path, SHA-256 content digest and
permission bits. It fails, and prints no rows, when the directory is missing,
empty or holds a non-regular file. `same` compares a fresh measurement with an
earlier one and returns non-zero on any difference or measurement failure.

First run with the unconfirmed rights decision. Expect exit `2`, blocker
`rights_unconfirmed`, `candidate_created: false` and no `demo-plugin` directory:

```bash
prepare demo-plugin; echo "exit=$?"; ls "$WORK/output"; same "$WORK/source" source.before source.refused
```

Correct only the fixture rights decision, then occupy the intended destination
with a sentinel file and record its baseline before the next call:

```bash
python3 -c 'import json,sys;p=sys.argv[1];d=json.load(open(p));d["checks"]["rights"]=True;open(p,"w").write(json.dumps(d,indent=2)+"\n")' "$WORK/intake-context.json"
mkdir "$WORK/output/demo-plugin" && printf 'keep me\n' > "$WORK/output/demo-plugin/sentinel.txt"
snap "$WORK/output/demo-plugin" sentinel.before
```

Run the same command again. Expect exit `2`, blocker `candidate_destination_exists`
and `candidate_created: false`. The command does not replace or delete the
sentinel; compare it and the source with their earlier measurements:

```bash
prepare demo-plugin; echo "exit=$?"; same "$WORK/output/demo-plugin" sentinel.before sentinel.refused; same "$WORK/source" source.before source.occupied
```

Recover by choosing a fresh destination beneath the existing caller-owned
`$WORK/output` parent. Never delete the occupied directory to recover. Expect exit
`0`, `status: prepared`, `candidate_created: true`, `release_ready: false` and
`source_mutated: false`. The candidate has a root `plugin.json` and a copied
`skills/demo-skill/SKILL.md`, and `source_intake.candidate` binds the standalone
revision and content digest:

```bash
prepare fresh; echo "exit=$?"; measure "$WORK/output/fresh"; same "$WORK/output/demo-plugin" sentinel.before sentinel.recovered; same "$WORK/source" source.before source.recovered
```

Each `same` line compares regular-file paths, content digests and permission
bits against the baseline taken before the call. The comparison covers those
properties only: not symlinks, timestamps, other metadata or provenance. Writing
the fixture, changing the rights decision and creating `fresh` are intentional
edits, not source mutation. A line starting `CHANGED or unmeasured` means the
preservation claim is not established. The prepared receipt shows structural
validation only. It does not authenticate the caller's provenance or rights
assertions, replace semantic review, approve icons, or authorize release,
publication or installation, and no package content is executed. This route
creates a new candidate; it does not update an existing plugin.

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

### Revision metadata and captured content

`--source-revision` is caller-supplied metadata. The validator checks only its
shape: 40 lowercase hexadecimal characters. The SDK does not read Git history
and does not prove that the inspected bytes are the contents of that commit.
The candidate's `content_sha256` is the digest of the package bytes captured
from the directory. Editing a file changes `content_sha256`, while the same
`--source-revision` value is carried unchanged. A malformed revision such as
uppercase or short hexadecimal returns `invalid_source_revision` with exit `2`
and no candidate. Callers must establish provenance and source-to-revision
agreement independently. A structural pass is not semantic review, execution
approval or release authority. See [the API contract](api.md) for the
candidate model.

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

### Worked example: required reference recovery

From the SDK checkout root, first export
`MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml"`.
With those variables set, run `mise install python uv ruff vale` and then
`mise exec -- uv sync --frozen`, and only then run the example. The script creates a disposable synthetic package under the physical temporary
path, so it also works on macOS.
The revision is a concrete 40-character lowercase hexadecimal value. The script
never executes package content; `inventory` hashes the package files before and
after each validation call.

```bash
WORK="$(cd "$(mktemp -d)" && pwd -P)"
PKG="$WORK/sample-skill"
REV=0123456789abcdef0123456789abcdef01234567
mkdir -p "$PKG/references"
cat > "$PKG/SKILL.md" <<'EOF'
---
name: sample-skill
description: Use when checking a disposable example of required reference validation.
---

# Sample skill

Read `references/README.md` for the sample notes.
EOF
inventory() {
  (
    cd "$PKG" || exit 1
    find . -type f -exec shasum -a 256 {} + >"$WORK/inventory.raw" || exit 1
    [ -s "$WORK/inventory.raw" ] || exit 1
    sort "$WORK/inventory.raw" >"$WORK/inventory.sorted" || exit 1
    shasum -a 256 <"$WORK/inventory.sorted"
  )
}
run() {
  label="$1"; shift
  before="$(inventory)" || { echo "$label INVENTORY FAILED"; return 1; }
  mise exec -- uv run --frozen skills-sdk validate "$PKG" --source-revision "$REV" \
    --require-file references/README.md "$@" --json >"$WORK/$label.out" 2>"$WORK/$label.err"
  echo "$label exit=$?"
  after="$(inventory)" || { echo "$label INVENTORY FAILED"; return 1; }
  [ "$before" = "$after" ] && echo "$label input unchanged" || echo "$label INPUT CHANGED"
}
run missing
: > "$PKG/references/README.md"
run empty --check-reference-content
printf '# Sample notes\n\nThese notes are intentionally short.\n' > "$PKG/references/README.md"
run corrected --check-reference-content
```

The observed output of exactly these commands was:

```text
missing exit=2
missing input unchanged
empty exit=2
empty input unchanged
corrected exit=0
corrected input unchanged
```

Each `$WORK/<label>.err` file was empty. Each `$WORK/<label>.out` file holds one
`skill-package-validation/v1` result:

| Step | Exit | Status | Finding code | Meaning |
| --- | --- | --- | --- | --- |
| `missing` | `2` | `blocked` | `required_file_missing` | The selected policy requires `references/README.md`, and no readable regular file exists there. |
| `empty` | `2` | `blocked` | `empty_reference` | The file now exists, and `--check-reference-content` rejects it because a textual reference must contain content. The flag checks captured files under `references/` with a supported textual suffix (Markdown, `.txt`, `.json`, `.yaml`, `.yml`), so another malformed JSON or YAML reference would also block. Other suffixes, such as `.toml` or `.png`, are not content-checked. |
| `corrected` | `0` | `pass` | none | The same selected policy accepts the nonempty UTF-8 reference. |

Without `--check-reference-content`, the empty file would satisfy the
`--require-file` presence check. Creating the empty file and then the nonempty
file are the author's own repairs between calls. The unchanged inventory before
and after each call shows that the paths and bytes of regular files did not
change; it does not cover permissions, timestamps, symlinks or other metadata,
so a `chmod` alone leaves it unchanged. Each result also carries
`mutation_performed`. The inventory runs each stage
as its own checked step, writes to files under `$WORK` rather than a pipeline,
and sorts plain text lines, so it needs no `sort -z` option. If any stage fails
or finds no files, the script prints `INVENTORY FAILED` and never claims the
input is unchanged. Both flags are opt-in. A pass
shows that the required file exists and, with the content flag, that each
supported textual reference under `references/` is nonempty UTF-8 and, for JSON
and YAML, parses. It also means the ordinary `validate` checks
passed, including the package root, safe capture, frontmatter and identity, so
a valid `references/README.md` beside a `SKILL.md` without frontmatter still
returns exit `2` with `invalid_frontmatter`. A pass does not establish semantic
accuracy, review execution, publication or release clearance.

The CLI is non-interactive. Except for the explicit destination creation of
`normalize-plugin` and `maintain-entrypoint --apply`, the listed operations are
non-mutating. For an invocation that reaches a service, exit `0` means intake
normalized with an `admit` decision,
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
reserves the prompt-free automation contract. Discovery-only reserved routes
(`inventory`, `package`, `project`, `tessl prepare`, `tessl verify`) parse and
then exit `3` with a `discovery-only:` stderr message. They do not perform the
named lifecycle work and must not be treated as success. The machine-readable
capability table lives in `skills_sdk.cli.routes.ROUTE_CAPABILITIES`; every
argparse route must appear there. Other routes remain stable discovery
boundaries while their deeper implementations are built in separate,
candidate-bound lanes:

- `inventory` is read-only source-inventory intent and currently discovery-only.
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
  In the accepted PR #55 lifetime repair, repeated trials allocate fresh controlled
  provider/judge instances after plan validation. No extra JSON fields are
  required; this does not clone live adapters or turn fixture scores into
  external model evidence.
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

## Matched evaluation

These bounded S4 commands were accepted in PR #53. They use supplied evidence or
explicit supplied-offline callbacks, not discovered live model adapters.
Use the [API contract](api.md#matched-whole-plugin-evaluation) for the
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

All five supplied-offline execution routes honour the provider descriptor's
`complete` or `stream` mode. Stream fixtures deliver the supplied `output_text`
as bounded Unicode-safe chunks followed by terminal evidence; they do not
accept arbitrary event scripts or contact a provider. Existing provider-call
byte, event, timeout and cleanup limits still apply. Invalid modes return a
typed blocked receipt; corrected inputs can be retried without changing source.
For local, cloud and regression lanes, every descriptor must match the plan's
explicit `generator_mode`; mixing complete and stream variants cannot produce
a completed matched comparison. Supplied calibration retains its separate
contract and does not gain a matched-lane mode field.

- `matched-assessment` requires exactly `plan`, `lane`, `baseline` and
  `candidate`; it assesses supplied paired judgments without execution.
- `matched-handoff` requires exactly `local` and `cloud_plan`; readiness binds
  a qualified local candidate to the cloud baseline without authorising spend.
- `matched-calibration` requires exactly `plan`, `rubric` and `executions`;
  the ordered probe callbacks return supplied dimensional judgments.
  The PR #55 lifetime repair allocates a fresh controlled pair for each
  declared trial, with unchanged JSON input shape and receipt schemas.
- `matched-local` requires exactly `plan`, `calibrations` and `executions`.
  `calibrations` contains both child-target bundles; `executions` contains
  exactly ten baseline/candidate pairs with explicit private plugin context
  and safety inputs.
- `matched-cloud` replaces `plan` with `handoff` while retaining both bundles
  and the complete execution batch.
- Both regression routes require `initial`, `assignments`, `plan`,
  `calibrations` and `executions`. Assignments identify failed-case owners;
  a complete rerun and unchanged source are required for closure. All candidate
  contexts must use the same absolute plugin root; distinct copies block even
  with matching initial captures. Equivalent relative paths remain accepted.
  Baseline calibration commitments remain frozen; candidate calibration can be
  rebound after a correction. A different passing baseline bundle still blocks
  recovery because it changes the retained experiment controls.

### Explicit profile inputs

PR #56 accepted these supplied-offline inputs. They do not discover a live
provider or establish external settings application, model quality or authority.

The local, cloud and regression execution inputs may additionally contain
`profiles`, with exactly `generator` and `judge`. Both select the same logical
lane name: `oss-local.config.toml` or `oss-cloud.config.toml`. Without this
member, the field sets above remain unchanged. `matched-calibration` accepts
`profiles` together with `profile_plan`, the matched plan defining the selected
lane's identities and settings. Its separate `plan` still owns held-out probes
and calibration policy. Profile wrapping preserves fresh capabilities for every
probe and trial; reused capabilities and mismatched fixture settings block.

Each role contains exactly `name`, `profile_toml`, `provider_toml`,
`catalogue_json`, `defaults_toml` and `configuration_sha256`. These are explicit
text contents, not file paths. `profile_toml` is required; the three dependency
texts may be `null` only when no unresolved input needs them. The adapter does
not read a profile's catalogue path, resolve credential environment variables,
discover home settings or execute disabled MCP commands.

Build the model identity with `describe_codex_profile` before freezing the
matched plan. Use `compile_codex_profile(plan, source, role)` from
`skills_sdk.providers.codex_profiles` to obtain the expected configuration
digest. The CLI rejects a fixture digest mismatch before allocating callbacks.
Profile provenance is part of the plan's adapter identity, so changing supplied
bytes requires a new plan and affected downstream evidence, not merely a new
fixture digest. The accepted-local-candidate cloud baseline remains governed by
the existing handoff checks.

Controlled local CLI tests cover complete and stream modes: a wrong expected
configuration blocks with zero callbacks, then corrected inputs complete ten
cases with profile-bound evidence. Controlled cloud refinement preserves the
accepted local candidate as its baseline. Installed-wheel local, calibration
and cloud commands reject stale profiles and accept corrected inputs.
Supplied output text and judge results remain controlled fixtures, not evidence
that Codex or an external model used these settings.

Matched plans require distinct complete baseline and candidate identities.
An identical A/A input returns a typed blocker; corrected distinct inputs can
be retried. The same package identifier with a different source revision or
content digest remains valid.
Selected references must be eligible Markdown files, not hidden evaluation
inputs or duplicate automatically included child `SKILL.md` entrypoints.

Exit `0` means assessed, ready, passing calibration, completed execution or
closed regression as appropriate; exit `2` means blocked or open. JSON emits
the corresponding versioned contract, not hidden source documents. Text output
includes available top-level and cloud-execution blockers, and input-blocked
cloud-regression feedback codes and reasons. Full nested rerun evidence remains
available in JSON. The lane summary is currently a derived API property and is
not emitted as a JSON field.
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

## Prompt translations

Run the checkout-scoped commands below from the repository checkout root so
`$PWD/.mise.toml` and relative paths resolve to this checkout.

| User phrase | Canonical action |
| --- | --- |
| “Validate this skill” | Run `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk validate "<package-root>" --source-revision "<40-lowercase-hex>" --json --robot`; for an invocation that reaches the validator, treat exit `0` as a passing result and exit `2` as a typed blocker. Argparse also uses exit `2` for malformed invocations before a versioned result exists. |
| “Build this package” | Run `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen skills-sdk build "<package-root>" --source-revision "<40-lowercase-hex>" --json --robot`; a successful build returns a candidate-bound receipt. A blocked result may lack candidate identity when it cannot be resolved. Neither result is an archive or publication. Argparse rejects malformed invocations before a versioned receipt exists. |
| “Make it available” | First name the target lane. Local `validate` or `build` proves only a candidate contract. The intended path checks the exact plugin version, publishes through a verified registry adapter (initially private Tessl `jscraik`), and installs through a selected host adapter. These external operations are not implemented by the current CLI; a future registry default needs separate transition proof. Only Jamie may select public release. |
| “Check the schemas” | Run `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen python scripts/generate_schemas.py --check` for generated-schema drift. For hand-maintained resources, also run `MISE_CEILING_PATHS="$PWD/.." MISE_TRUSTED_CONFIG_PATHS="$PWD/.mise.toml" mise exec -- uv run --frozen pytest tests/test_core_contracts.py tests/test_package_lifecycle.py tests/test_package_receipts.py`. This focused test route loads the hand-maintained schemas through `SchemaRegistry` and exercises their Draft 2020-12 and payload contracts. Record `pass` only when both commands exit `0` and all tests pass; record `fail` for schema drift or a failed assertion, and `blocked` if either command cannot run or complete, with the concrete reason and nearest meaningful fallback. |
| “Is it verified?” | Identify the evidence lane and candidate identity, then inspect that lane's result; a local receipt alone does not prove runtime, provider, registry, or hosted state. |
| “Move this workflow into the SDK” | Move the portable lifecycle behavior, contracts, schemas, tests, documentation, and evidence production together; do not leave a wrapper or required checkout dependency on Agent-Skills. |
| “Put this skill in the Foundry” | Hold the candidate and provenance for SDK processing without treating custody as clearance, installation, distribution, or permanent post-processing ownership. |
| “Retire Agent-Skills” | Require the documented clean-room SDK and Foundry independence evidence plus replacement-or-retirement coverage; documentary ownership alone is not a retirement pass. |
