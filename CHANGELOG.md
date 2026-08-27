# Changelog

All notable Skills SDK changes are recorded here. The project is currently in
the `0.x` contract-building phase; a schema-version change is required when a
breaking contract change cannot remain compatible.

## 0.1.0

- Establish the public, portable Python package boundary.
- Add typed inventory, intake, package, packaging, evaluation, risk, security,
  and candidate-bound receipt contracts.
- Add deterministic, non-executing scenario evaluation with candidate-bound
  observations, case results, receipts, and typed blocker outcomes.
- Add an explicit `scenario-set/v2`, observation, case-result, and evaluation-
  receipt family for secret-free provider identity binding and digest-only
  exact-match decisions, while preserving every v1 evaluation contract and
  evaluator behavior.
- Add `package-receipt/v2` with canonical manifest/digest binding while
  preserving `package-receipt/v1` acceptance semantics.
- Package versioned JSON Schemas and a semantic `SchemaRegistry` validator.
- Expose a boundary-only `skills-sdk` CLI with explicit lifecycle and Tessl
  preparation route names; no route publishes, installs, or mutates a runtime.
