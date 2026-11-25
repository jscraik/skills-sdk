# Tessl worker setup

Tessl runs `.tessl/cloud-launch-setup.sh` from the selected repository checkout
before starting a Factory agent. The hook prepares SDK dependencies; it does
not run validation, start another agent, publish packages or grant task authority.

The hook supports Linux x86_64, matching the SDK's CI bootstrap archive.
It reuses `scripts/circleci-mise-bootstrap.sh` to fetch and verify the pinned
mise archive, installs mise into `~/.local/bin`, and installs the tools declared
in `.mise.toml`. Frozen dependency setup includes the `images` extra used by
the full validation route. Tool preparation does not require GitHub credentials;
the hook removes those variables from its child environment. The later agent's
permissions remain controlled by its selected Tessl environment.

Trust is scoped to the checkout through environment variables. Global and system
configuration are excluded from preparation without changing worker-owned files.
Preparation state, including mise trust records, is kept in a temporary
directory and removed whether setup succeeds or fails. Installed tools
remain available to the agent;
existing worker trust records are unchanged. Repeated execution refreshes the
same tools and dependency environment. A failed bootstrap or dependency sync
stops preparation; it does not establish validation success. Installed tools
can remain after a later failure in the disposable worker.

## GitHub issue intake preflight

Before applying the `tessl` label, identify the active issue loop ID in Tessl
and fetch the source branch the loop uses. Compare the loop's live project
with the manifest at the exact source revision:

```bash
python3 scripts/check_tessl_loop_project.py --revision "$source_revision" --loop "$loop_id"
```

The command uses the signed-in Tessl CLI and starts no cloud run. If the
command fails, resolve the project mismatch or lookup failure before labeling
the issue. The command reads the committed manifest, so local edits to
`tessl.json` do not affect the result.

## Validation and cloud verification

Local regression tests use disposable directories and stand-in tools. They
check repeat execution, preserved input and settings, scoped trust, credential
removal and early failures. CI bootstrap tests separately exercise checksum
verification. Neither proves installation on a real Factory worker.

Use the documented
[Tessl cloud setup checker](https://docs.tessl.io/automations/cloud-setup-hook)
against the exact delivered branch before accepting the cloud setup. Select
the `skills-sdk-lab/skills-sdk` project explicitly, with `codex` and
`gpt-6.1-sol`; read-only GitHub access is sufficient for this check. The checker
must report both hook runs passing, `AGENT=codex`, an empty `WORKDIR` for the
repository root, and the expected Python and uv versions. Then verify the
agent can execute `mise exec -- bash scripts/validate-repository.sh`, the SDK
validation command. Record the exact revision, command and pass/fail/blocked
outcome; preparation success alone does not prove validation.
The hook's child-process PATH does not configure the later agent, so that
command must find mise through Tessl's documented `~/.local/bin` path.

The checker is a paid cloud run and requires separate launch approval.
A timeout includes preparation time and does not enforce a credit cap.
Preserve the owner's 20,000-credit reserve and check the current allowance,
revision, environment and stop conditions before any authorised launch.
Do not enable automatic triggers merely to verify this hook. Keep local,
hosted CI, cloud preparation and actual task validation results separate.
