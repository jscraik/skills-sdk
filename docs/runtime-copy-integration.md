# Runtime copy integration

## Bounded verification

Use the SDK entrypoint to compare a maintained skill source with an existing
runtime copy without executing package code or changing either tree:

```bash
skills-sdk compare-copy /path/to/source/example /path/to/runtime/example --source-revision <40-character-source-revision>
```

Both trees must pass the existing package validator. The command compares every
captured relative filename, file hash, and byte count. Missing, extra, and changed
files produce `drift`; invalid metadata, unsafe traversal, or invalid revision
produce `blocked`. Both non-success outcomes exit 2. Only `pass` exits 0.
Add `--json` for a `runtime-copy-comparison/v1` object containing both complete
validation records and the sorted differing paths.

This local comparison is not a receipt, SDK admission, proof of authorization,
installation, activation, or synchronization stability. It does not compare
permissions, prove a Git checkout matches the supplied revision, or provide an
atomic snapshot across two concurrent writers. The caller must identify the
actual source revision and keep sources quiescent for a meaningful observation.

## Integration checklist

- [x] Reuse existing no-follow source validation without relaxing its gates.
- [x] Add a real read-only CLI path with non-success exit statuses.
- [x] Exercise matching, changed, missing, extra, and invalid fixture trees.
- [ ] Reconcile any maintained-source validation failures.
- [x] Implement explicit existing-entrypoint maintenance outside core, with
  recoverable backups and refusal of unexpected current state.
- [ ] Bind an authorized runtime transition to its source and current state.
- [ ] Prove runtime equality after apply and account for competing writers.

The `project` discovery route does not currently implement an apply adapter.
Do not use its parse-only exit status as evidence of synchronization. Source
validation and this comparison remain separate from the explicit maintenance
adapter; neither proves a completed runtime integration.

## Existing entrypoint maintenance

`maintain-entrypoint` is an explicit host adapter, not package installation or
admission. It updates an existing regular `SKILL.md`, or an explicitly selected
sibling Markdown document with `--supporting-document`. It does not create a
package, execute retained workflows, register a plugin, alter other files,
or reinterpret the SDK package-validation and install-plan contracts.

```bash
skills-sdk maintain-entrypoint /path/to/source/example/SKILL.md /path/to/runtime/example/SKILL.md --backup-root /path/to/backups --expected-source "<source-file-sha256>" --expected-current "<current-file-sha256>"
```

The default is read-only. `matching` exits 0, `repairable` exits 2, and rejected
inputs exit 2. Add `--apply` only for a separately authorized repair after
checking for active writers. The hash arguments bind bytes; they do not grant
authority. Never refresh an unexpected current digest merely to overwrite it.
Add `--json` for an `entrypoint-maintenance-result/v1` object. Its status is one
of `matching`, `repairable`, `repaired`, `blocked`, or `indeterminate`; failures
include a stable blocker code rather than requiring exception-text parsing.

For a supporting document, pass that existing same-named `.md` file as both
source and target and add `--supporting-document`. Both the source and target
directories must still contain valid identifying `SKILL.md` files; the supplied
hashes bind the document itself. Nested references, scripts, missing files, and
package-wide installation are outside this maintenance route.

The candidate must contain closed, unambiguous YAML, the existing skill name,
and a non-empty description. This format check serves existing-entrypoint
maintenance only: full SDK validation may still reject legacy package names
or fields, and those failures remain blockers for SDK package claims.

The adapter opens paths without following symlinks and holds a cooperative lock
in the host's stable `/tmp` namespace. The lock identity comes from the opened
target-parent device and inode plus the target filename, so path aliases and
alternate backup roots serialize the same repair. It stages replacement bytes
and preserves the prior bytes through an exclusive, independent snapshot before
atomic publication. The backup root must be outside both package trees. The
adapter preserves target mode bits and syncs the backup directory before
publication. It does not preserve
ownership, ACLs, or extended attributes on the replacement, or establish
crash-durable preexisting content. The backup directory must already
exist on the target filesystem. Failed publication retains the backup and
cleans only operation-owned temporary paths. Keep backups until the repair is
accepted; restoration is a separate explicitly authorized operator action.

Observed concurrent writes or directory replacement return a non-success result.
Publication uses an operating-system atomic name exchange and fails closed when
that primitive is unavailable. A target replaced at the exchange boundary is
retained under the reported recovery name and returns `indeterminate`; the
approved prior bytes remain in the separate backup. Inspect them before
attempting recovery. This is not a lock
against arbitrary external writers or a synchronization daemon. Do not apply
against a known active writer, claim automatic rollback, or infer recurring
stability from one successful repair.
