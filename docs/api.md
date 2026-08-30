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
- **Package safety evidence:** `PackageSafetyEvidenceReceipt`,
  `PackageSafetyEvidenceReference`, `PackageSafetyFinding`, and
  `PackageSafetyBlocker`. The receipt binds one exact candidate and the
  canonical manifest `package_digest` from its upstream `PackageReceiptV2` to
  a caller-supplied reviewer adapter and one of four states. The manifest
  digest and the candidate's source `content_sha256` identify different
  artifacts and are intentionally not required to be equal:
  `not_reviewed`, `reviewed_no_issue`, `issue_found`, or
  `metadata_insufficient`. A reviewed-no-issue state requires digest-bound
  evidence and forbids findings; issue-found requires evidence, a warning or
  blocker finding, and typed blockers. Metadata-insufficient requires a typed
  blocker but cannot claim an observed issue. There is no generic `safe`
  field. Draft 2020-12 validates the structural state, shape, uniqueness, and
  public-text constraints it can express. Cross-object evidence membership,
  blocker-reference membership, and primary-blocker equality remain explicit
  semantic invariants identified by schema metadata and enforced by
  `SchemaRegistry.validate`. The contract validates supplied metadata and never
  performs a review, rights decision, admission, provider call, installation,
  runtime action, or publication. A raw safety payload cannot dereference its
  opaque `input_receipt_id`; when a caller has the upstream
  `PackageReceiptV2`, call
  `SchemaRegistry.validate_package_safety_evidence_against_package_receipt`
  to require matching receipt ID, candidate, and canonical manifest digest.
  A raw upstream mapping is first validated through the `package-receipt/v2`
  JSON boundary before that binding is applied.
- **Provider execution envelopes:** `ProviderExecutionRequest` records a
  candidate-, scenario-, provider-, safety-receipt-, and input-digest-bound
  request prepared for an external adapter. `ProviderExecutionResult` records
  that adapter's `completed`, `failed`, `blocked`, or `indeterminate`
  observation with output or evidence digests and typed blockers or errors.
  Both contracts require `ProviderIdentityV2`, reject raw payload and
  credential fields, and carry literal-false execution/privacy/cost claims.
  Optional usage metadata is an adapter-reported unit count, not billing or
  cost evidence. The SDK validates these envelopes but does not authorize or
  perform provider execution, contact a network, read credentials, evaluate an
  output, or establish provider truth. Replay provenance is optional, but when
  non-null it binds both the prior result ID and the SHA-256 of that prior
  result's complete canonical JSON envelope (UTF-8, keys sorted, compact
  separators). A result cannot reference itself as its replay source.

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

The schema registry accepts only known schema names and raises `ContractError`
for an
unknown schema or invalid payload. It adds Pydantic semantic checks for
manifest, provider identity, provider execution, private-registry preparation,
package-safety evidence, receipt, risk, security, scenario, and scorer schemas. The registered
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

`ProviderExecutionRequest` and `ProviderExecutionResult` are registered schema
families, not generic receipts. Their `schema_version` values therefore fail
closed through `parse_receipt` and must be validated by model or
`SchemaRegistry` name. Cross-envelope claims require the supplied objects:
`validate_provider_execution_request_against_safety_evidence` binds the safety
receipt identity, canonical digest, and candidate, while
`validate_provider_execution_result_against_request` binds the request digest
and duplicated request/result identities, and
`validate_provider_execution_replay_against_prior_result` binds optional replay
provenance to the supplied prior result. Standalone schema validation cannot
establish those external-object relations. Cross-envelope digests use canonical
JSON from the fully validated model's `model_dump(mode="json")`; they do not
hash an adapter's non-canonical input spelling, omitted defaults, or timestamp
offset representation. `parse_receipt` accepts only explicitly registered
receipt wire versions:
`receipt-base/v1`, package receipt v1/v2, evaluation receipt v1/v2, and
`registry-preparation/v1`, plus `package-safety-evidence/v1`. A prepared
registry artifact maps to the generic
`pass` status while preserving `artifact_status="prepared"`; a blocked artifact
remains blocked. Parsing validates the versioned registry schema and does not
reinterpret older receipt payloads. A reviewed-no-issue safety artifact maps
to generic `pass`; the other three
safety states map to generic `blocked` while remaining available through
`artifact_status`. This mapping does not imply that an adapter ran or that a
package is generally safe. An unknown future or foreign `schema_version`
fails with the typed
`unsupported_receipt_family` error instead of being interpreted through the
generic base receipt schema. Missing or non-string versions fail with
`invalid_receipt_schema_version`.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
