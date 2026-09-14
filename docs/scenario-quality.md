# Scenario definition quality

`assess_scenario_quality` and `skills-sdk eval scenario-quality` inspect one
standalone package's `references/evals.yaml`. They produce deterministic
`scenario-quality/v1` evidence without running a scenario, calling a provider,
reading a host registry, promoting artifacts, or mutating the package. Passing
receipts are candidate-bound; early validation blockers may retain
`candidate: null` when identity cannot be resolved.

## Input contract

The supported top-level fields are `schema_version`, `skill_name`, `claims`,
`scorer_quality`, `release_scenario_sets`, and `cases`. Scenario cases accept
the documented identity, context, prompt, mode, deterministic-check,
acceptance, artifact-reference, and optional `output_contract` fields used by
current package producers. Unsupported fields and assertion types are typed
blockers rather than silently ignored extensions. YAML aliases and duplicate
keys are rejected; input is size- and node-bounded.

Structured output obligations must be explicit:

```yaml
output_contract:
  required_fields: [outcome]
acceptance:
  - type: text_field_equals
    field: outcome
    value: pass
```

The assessor does not infer fields from prompts, case names, package names, or
expected prose. Each required output field needs a field-aware assertion.

## Scope and policy

Without `--scenario-set`, the command checks every case and applies no release
cardinality floor. With `--scenario-set`, it checks the named release set and
applies `ScenarioQualityPolicy`: at least eight cases, one
pressure-or-regression case, and one negative-or-edge case. These fixed values
are the portable v1 release policy inherited from the characterized source.
Changing them requires a new schema version and compatibility evidence. Every
receipt records the applied thresholds and observed category counts so model
and schema consumers can reproduce the decision.

```bash
skills-sdk eval scenario-quality ./skills/example \
  --source-revision <40-lowercase-hex> \
  --scenario-set example-release-v1 --json --robot
```

Exit `0` means the selected definitions passed. Exit `2` returns a versioned
blocked receipt. Invalid source revisions retain `candidate: null`.

## Source disposition

- Reimplemented portably: deterministic definition checks, release selection,
  stable findings, and release floors characterized from Agent-Skills commit
  `d933d8019311b9afd3439ac0a81197cd8cf38245`.
- Reused: existing SDK candidate identity, safe package validation, blocker,
  schema-registry, JSON rendering, and exit-status contracts.
- Retired from this lane: Agent-Skills handle resolution, `.harness` and
  generated-artifact discovery, Ruby fallback, local acceptance-trace IDs,
  Tessl parity, promotion, and command-envelope machinery.
- Deferred: scorer quality and calibration, scenario execution, providers,
  A/B judging, review handoff, installation, and publication.

This lane is the scenario-quality row of the accepted creation-and-repair
workflow. It does not complete Foundry cutover or Agent-Skills retirement.
