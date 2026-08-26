# Python API

The public API is the typed contract layer under `skills_sdk`. Import models
from `skills_sdk` for the most common top-level contracts, or from
`skills_sdk.models` when a family-specific name is clearer.

## Contract families

- **Inventory:** `PackageInventory`, `PackageInventoryRecord`, source
  provenance, rights, ownership, disposition, and mantra assessment.
- **Intake and package identity:** `PackageCandidateIdentity`, `SkillIdentity`,
  `PluginIdentity`, `PackageSource`, `PackageOwner`, `IntakeDecision`, and
  `NormalizedPackage`.
- **Packaging:** `PackageManifest`, `PackageManifestFile`, and
  `PackageReceipt` with typed blockers and immutable candidate binding.
- **Evaluation:** `ScenarioSet`, `ScenarioCase`, and `ScorerProfile`. Judge and
  external scorers must declare calibration probes and deterministic checks
  first.
- **Risk and security:** `RiskClassification`, `RiskSensor`,
  `SecurityScreeningResult`, and redacted `SecurityFinding` metadata.

## Schema validation

Use `SchemaRegistry` for packaged JSON Schema plus the model-level semantic
invariants:

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
manifest, receipt, risk, security, scenario, and scorer schemas. For inventory,
identity, source, owner, normalized-package, and intake records, validate the
corresponding Pydantic model explicitly after the structural schema check.
Validation is read-only: it does not write receipts, contact providers, install
packages, or publish to a registry.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
