# Support

Skills SDK support is for the portable contracts and the validation commands
documented in this repository. It does not provide support for a host
repository adapter, a runtime installation, a provider account, or registry
publication.

## Before opening an issue

1. Confirm the SDK version, Python version, and operating system.
2. Reproduce from a clean checkout with `uv sync --frozen`.
3. Run `bash scripts/validate-repository.sh` and include the exact command and
   outcome.
4. Include the smallest redacted payload or schema name that reproduces the
   issue. Never include credentials, private source, generated receipts, or
   machine-specific paths.

Open a repository issue with those details, or consult [`SECURITY.md`](SECURITY.md)
for security-sensitive reports. For contract changes, explain the candidate
identity, schema version, compatibility impact, and the proof that should
remain stable.
