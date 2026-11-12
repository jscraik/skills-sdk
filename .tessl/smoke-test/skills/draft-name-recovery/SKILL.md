---
name: draft-name-recovery
description: Prepare only the agreed SDK name-mismatch documentation patch and executed proof for local signed delivery.
schemas:
  output:
    $ref: ./schemas/output.schema.json
---

This is a split drafting experiment, not the stock Factory implement skill.
Require EXPECTED_HEAD as a lowercase 40-hex SHA from launch instructions.
Verify `git rev-parse HEAD` equals it before changes. If missing, mismatched,
already implemented or the reserved scope has changed, stop with no_action
or needs_input as appropriate. Never infer paid authority from this file.

Your sole product write is docs/agent-entrypoint.md. Read its existing
inspection and missing-description sections and the repository's guidance.
Add one concise British-English example showing recovery from name_mismatch
when a user copied a skill into a differently named directory. Preserve
existing text and anchors. No SDK implementation, tests, config or gate edits.

Use the already-proven pinned setup in the adjacent validate-contracts skill's
references/setup.md if dependencies are absent. It is authorised only within
the disposable worker. Do not broaden installs or add a cloud setup hook.

Before editing, record this file's SHA256 and Git diff so platform-generated
AGENTS.md/tessl.json changes cannot be mistaken for your product patch.
On an owned physical temporary path outside the clone, create a harmless
synthetic package with valid name recovery-demo and description, initially
inside copied-directory. Run the maintained pinned skills-sdk validate
command with --json --robot and a clearly synthetic 40-hex source revision.
Capture actual exit/stdout/stderr. Initial status must be blocked, finding
name_mismatch, mutation_performed false, exit 2. Explicitly rename only that
owned directory to recovery-demo and rerun: pass, no findings, exit 0.
Hash SKILL.md immediately before and after each call; both must preserve bytes.
Never execute its body. A package directory rename changes package identity;
do not reuse candidate-bound receipts or imply provenance from synthetic SHA.

Write the guide from that executed evidence: starting condition, invocation,
typed finding, explicit author recovery and rerun. Structural pass does not
grant semantic review, execution, admission, installation or release clearance.
Keep the example compact; link existing explanations. Do not implement another
tutorial framework, validator or helper script. If behaviour differs, fail
with the actual blocker rather than changing SDK code or inventing output.

Check diff hygiene. Run applicable supported repository checks when possible;
record blocked checks honestly. Do not create a Git commit just to make the
docs classifier accept the worker. Full validation and receipt gates belong
to local delivery; worker smoke/test evidence cannot substitute for them.

Return a UTF-8 unified Git diff for exactly docs/agent-entrypoint.md relative
to the verified checkout. Max patch size 65536 characters. Preserve names,
regular-file mode and newline encoding. Record before/after file hashes.
Use Tessl's required launch-result.json: succeeded with output matching the
declared schema only when the requested edit and rejection/recovery proof
exist; otherwise failed/needs_input/no_action with truthful reason. The
structured patch and proof are retrieved from that report, not a Git push.
Never include unrelated generated diffs, secrets, environment dumps or bulky
logs. A schema-valid patch is not permission to apply it or PR readiness.

Do not commit, sign, stage, push, create/relabel/comment on issues or PRs,
request reviews, merge, change settings/permissions/project links, delegate,
start/resume/retry runs or call paid downstream services. No write-enabled
environment is required. Source reads, the one doc edit, owned fixtures/cache
and platform reporting artifact are the only worker operations. Coordinator
checks and applies your result locally, then owns native signing and receipts.
