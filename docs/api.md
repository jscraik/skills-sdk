# Python API

The public API is the typed contract layer under `skills_sdk`. The top-level
package exports the inventory, risk, and evaluation contracts listed in its
`__all__`. Import family-specific contracts such as
`PackageCandidateIdentity`, `PackageManifest`, `PackageReceipt`,
`PackageReceiptV2`, and
`PackageHardeningReceipt` from
`skills_sdk.models` (or their submodules), as shown below.

## Contract families

- **Inventory:** `PackageInventory`, `PackageInventoryRecord`,
  `PackageInventoryV2`, `PackageInventoryRecordV2`, `ValueDecision`,
  `ValueDecisionV2`, source provenance, rights, ownership, disposition, and
  mantra assessment.
- **Intake and package identity:** `PackageCandidateIdentity`, `SkillIdentity`,
  `PluginIdentity`, `PackageSource`, `PackageOwner`, `IntakeDecision`, and
  `NormalizedPackage`.
- **Packaging:** `PackageManifest`, `PackageManifestFile`, `PackageReceipt`,
  `PackageReceiptV2`,
  `PackageHardeningPolicy`, and `PackageHardeningReceipt` with typed blockers,
  explicit warnings, and immutable candidate binding. Use
  `build_skill_package` before `harden_skill_package`; hardening consumes the
  receipt and does not rescan the source filesystem. Builders emit
  `PackageReceiptV2`, which binds `package_digest` to the canonical manifest;
  `PackageReceipt` preserves the historical `package-receipt/v1` contract for
  compatible readers.
- **Evaluation:** `ScenarioSet`, `ScenarioCase`, `ScorerProfile`,
  `ScenarioObservation`, `ScenarioCaseResult`, and `EvaluationReceipt`. Use
  `evaluate_scenario_set` to score externally produced observations with a
  deterministic scorer. The service never executes a prompt, provider, or
  package. Unsupported oracles, incomplete calibration, and mismatched
  candidate identities return typed blockers rather than guessed outcomes.
  The additive v2 family (`ScenarioSetV2`, `ScenarioCaseV2`,
  `ScenarioObservationV2`, `ScenarioCaseResultV2`, and `EvaluationReceiptV2`)
  binds observations and receipts to a secret-free `ProviderIdentity` and lets
  `evaluate_scenario_set_v2` decide `exact_match` from expected and observed
  SHA-256 digests only. The v1 symbols and `evaluate_scenario_set` retain their
  historical behavior.
- **Risk and security:** `RiskClassification`, `RiskSensor`,
  `SecurityScreeningResult`, and redacted `SecurityFinding` metadata.

## Schema validation

Use `SchemaRegistry` for packaged JSON Schema structural validation. It also
applies model-level semantic invariants for the supported contract families:

```python
from skills_sdk.core import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity

candidate = PackageCandidateIdentity(
    package_id="example-skill",
    source_revision="0" * 40,
    content_sha256="0" * 64,
)
# package-identity.v1 is the wire identity shape and has no schema_version key.
SchemaRegistry().validate("package-identity.v1", candidate.model_dump(mode="json", exclude={"schema_version"}))
```

The registry accepts only known schema names and raises `ContractError` for an
unknown schema or invalid payload. It adds Pydantic semantic checks for
manifest, provider identity, receipt, risk, security, scenario, and scorer schemas. The registered
`package-identity.v1` and inventory schemas receive structural validation only;
they do not receive model-level semantic checks. The packaged candidate,
skill-identity, plugin-identity, source, owner, normalized-package, and intake
schemas are not registered with
`SchemaRegistry`; when those families need structural validation, load their
packaged JSON Schema resource with a Draft 2020-12 validator, then call the
corresponding Pydantic model explicitly (for example,
`PackageInventoryRecord.model_validate(payload)` for an inventory record).
Validation is read-only: it does not write receipts, contact providers, install
packages, or publish to a registry.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
