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

Trust is scoped to the checkout through environment variables. Preparation
state, including mise trust records, lives in the temporary directory and is
removed on success or failure. Installed tools remain available to the agent;
existing worker trust records are unchanged. Repeated execution refreshes the
same tools and dependency environment. A failed bootstrap or dependency sync
stops preparation; it does not establish validation success. Installed tools
can remain after a later failure in the disposable worker.

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
agent can execute a maintained SDK validation command through `mise exec`.
The hook's child-process PATH does not configure the later agent, so that
command must find mise through Tessl's documented `~/.local/bin` path.

The checker is a paid cloud run and requires separate launch approval.
A timeout includes preparation time and does not enforce a credit cap.
Preserve the owner's 20,000-credit reserve and check the current allowance,
revision, environment and stop conditions before any authorised launch.
Do not enable automatic triggers merely to verify this hook. Keep local,
hosted CI, cloud preparation and actual task validation results separate.
