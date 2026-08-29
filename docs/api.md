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
  binds observations and receipts to a hardened, secret-free
  `ProviderIdentityV2` and lets
  `evaluate_scenario_set_v2` decide `exact_match` from expected and observed
  SHA-256 digests only. The v1 symbols and `evaluate_scenario_set` retain their
  historical behavior. `ProviderIdentity` preserves the
  `provider-identity/v1` wire contract; provider-bearing evaluation-v2
  payloads require `provider-identity/v2` and do not reinterpret v1 identities.
- **Risk and security:** `RiskClassification`, `RiskSensor`,
  `SecurityScreeningResult`, and redacted `SecurityFinding` metadata.
- **Registry preparation:** `RegistryIdentity`, `RegistryPreparationRequest`,
  and `RegistryPreparationReceipt`. Use `prepare_private_registry_candidate` with
  a built `PackageReceiptV2` and its matching `PackageHardeningReceipt` to
  create a deterministic local preparation receipt. The prepared result binds
  the candidate, registry namespace, package/version, manifest digest,
  hardening-receipt digest, and portable evidence paths. Blocked inputs retain
  typed blockers and cannot claim prepared digests. Path-shaped hardening
  evidence remains in blocker `evidence_refs`; other accepted hardening
  evidence is retained only through `source_evidence_sha256` rather than being
  exposed or reinterpreted as a path. Credential-shaped evidence is likewise
  digest-bound and never copied into the receipt. Hardening warnings use the
  same projection: the complete warning is digest-bound, safe portable evidence
  references remain readable, and raw warning IDs/messages are not copied.
  This service performs no registry I/O or publication.
  Credential-shaped request evidence is rejected. Unsafe source blocker
  code/message text is replaced by a generic typed blocker and bound through
  `source_blocker_sha256`; safe source metadata and portable references remain
  readable.

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

The schema registry accepts only known schema names and raises `ContractError` for an
unknown schema or invalid payload. It adds Pydantic semantic checks for
manifest, provider identity, private-registry preparation, receipt, risk,
security, scenario, and scorer schemas. The registered
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

`parse_receipt` accepts only explicitly registered receipt wire versions:
`receipt-base/v1`, package receipt v1/v2, evaluation receipt v1/v2, and
`registry-preparation/v1`. A prepared registry artifact maps to the generic
`pass` status while preserving `artifact_status="prepared"`; a blocked artifact
remains blocked. Parsing validates the versioned registry schema and does not
reinterpret older receipt payloads. An
unknown future or foreign `schema_version` fails with the typed
`unsupported_receipt_family` error instead of being interpreted through the
generic base receipt schema. Missing or non-string versions fail with
`invalid_receipt_schema_version`.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
