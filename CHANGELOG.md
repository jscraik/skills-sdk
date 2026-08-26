# Changelog

All notable Skills SDK changes are recorded here. The project is currently in
the `0.x` contract-building phase; a schema-version change is required when a
breaking contract change cannot remain compatible.

## 0.1.0

- Establish the public, portable Python package boundary.
- Add typed inventory, intake, package, packaging, evaluation, risk, security,
  and candidate-bound receipt contracts.
- Package versioned JSON Schemas and a semantic `SchemaRegistry` validator.
- Expose a boundary-only `skills-sdk` CLI with explicit lifecycle and Tessl
  preparation route names; no route publishes, installs, or mutates a runtime.
