# Python API

The public API is the typed contract layer under `skills_sdk`. The top-level
package exports the inventory, risk, evaluation, and provider execution
contracts listed in its `__all__`. Import family-specific contracts such as
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
  `NormalizedPackage`. Use `intake_skill_package` with a
  `SkillPackageIntakeContext` to structurally validate and normalize a local
  standalone-skill directory. The service derives candidate-bound provenance
  from the validated bytes and preserves the caller's explicit identity,
  provenance, rights, and owner-continuity checks in a
  `SkillPackageIntakeReceipt`. It does not copy source, execute package code,
  access a network, establish ownership or rights truth, or admit a package to
  Foundry. Archive intake remains a separate composition boundary.
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
  that adapter's externally observed `completed`, `failed`, `blocked`, or
  `indeterminate` result with output or evidence digests and typed blockers or
  errors. The SDK locally validates this evidence envelope; it does not prove
  that the external provider actually produced the reported outcome.
  Both contracts require `ProviderIdentityV2`, reject raw payload and
  credential fields, and carry literal-false execution/privacy/cost claims.
  A prepared request must bind supplied `reviewed_no_issue` package-safety
  evidence; other safety states cannot authorize preparation. A bound result
  cannot start before its request was prepared. These cross-envelope relations
  require the supplied receipt or request and are enforced by the named
  `SchemaRegistry` binding methods rather than standalone Draft validation.
  Optional usage metadata is an adapter-reported unit count, not billing or
  cost evidence. The SDK validates these envelopes but does not authorize or
  perform provider execution, contact a network, read credentials, evaluate an
  output, or establish provider truth. Replay provenance is optional, but when
  non-null it binds both the prior result ID and the SHA-256 of that prior
  result's complete canonical JSON envelope (UTF-8, keys sorted, compact
  separators). A result cannot reference itself as its replay source.
- **Runtime-lock planning:** `RuntimeLock` (`runtime-lock/v1`) describes
  candidate-bound intended state for a logical user or project target. Each
  entry binds package and candidate identity, version, package digest, registry
  identity, package and preparation receipt IDs, and an ordered digest inventory
  of portable relative files. `InstallPlan` (`install-plan/v1`) describes a
  deterministic `install`, `update`, or `no_change` transition, or a typed
  blocked result. The planner rejects a registry receipt whose
  `input_receipt_id` does not identify the exact package receipt, carries the
  current lock digest as its rollback identity, and always reports
  `mutation_performed: false`. These contracts do not prove an apply attempt,
  rollback, journal, race-safe host mutation, discovery, activation, or runtime
  outcome. A future host adapter must emit those evidence families separately
  without putting absolute paths, credentials, raw logs, or environment state
  into portable core contracts.
- **Runtime execution evidence:** `InstallationResult`, `RollbackJournal`,
  `RollbackOutcome`, `DiscoveryObservation`, `ActivationObservation`, and
  `RuntimeOutcomeReceipt` are additive, adapter-supplied v1 families. They bind
  the exact candidate, package digest, plan, logical target, adapter identity,
  timestamps, and digest-only evidence while keeping installation, rollback,
  discovery, activation, and runtime outcome distinct. Explicit
  `validate_against_*` methods prove cross-receipt equality; standalone Draft
  validation remains structural for those cross-object relations. The SDK does
  not resolve host paths, copy files, invoke a runtime, activate a skill, or
  claim evaluation quality, safety, cost, persistence, or usability.
  Every receipt-shaped runtime observation requires its literal `lane` field;
  omission fails through Pydantic, `SchemaRegistry`, and generic receipt
  parsing rather than reaching an untyped mapping lookup.
  Optional provider-result and evaluation-receipt references are not proof by
  presence alone: callers must use `validate_against_provider_result` and
  `validate_against_evaluation_receipt` to verify the referenced ID, canonical
  digest, and candidate identity.
  `InstallationResult.operation` preserves the planned `install`, `update`, or
  `no_change` transition in the standalone observation. Pydantic and
  `SchemaRegistry` enforce its lock-digest and mutation semantics; Draft
  2020-12 enforces the operation-to-mutation rule, while equality between lock
  digest fields remains a semantic check.

## Read-only intake

Run this example from the repository root with the pinned environment:

```bash
mise exec -- uv run --frozen python - <<'PY'
from pathlib import Path

from pydantic import ValidationError

from skills_sdk.intake import intake_skill_package
from skills_sdk.models import SkillPackageIntakeContext

# Synthetic fixture assertions: replace these with the caller's real evidence.
payload = {
    "source_repository": "jscraik/skills-sdk",
    "source_revision": "1" * 40,
    "source_path": "tests/fixtures/synthetic-skill",
    "source_kind": "git",
    "owner": {
        "owner": "sdk-tests",
        "maintainer": "sdk-tests",
        "ownership_state": "canonical",
        "rights": {
            "basis": "authored",
            "license": "Apache-2.0",
            "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
        },
    },
    "checks": {
        "identity": True,
        "provenance": True,
        "rights": True,
        "owner_unchanged": True,
    },
}
context = SkillPackageIntakeContext.model_validate(payload)
for package_root in (Path(context.source_path), Path("pyproject.toml")):
    receipt = intake_skill_package(package_root, context)
    if receipt.status == "normalized":
        print("normalized:", receipt.candidate.package_id)
        print("decision:", receipt.decision.decision.value)
    else:
        print("blocked:", receipt.blocker.code)
        for finding in receipt.validation.findings:
            print(finding.code, finding.evidence_refs)

# Invalid context fails before the service runs; it produces no receipt.
try:
    SkillPackageIntakeContext.model_validate({**payload, "source_revision": "invalid"})
except ValidationError:
    print("invalid context: ValidationError")
PY
```

The fixture directory produces `normalized`; the regular file
`pyproject.toml` produces a typed package-root blocker. Invalid context raises
`pydantic.ValidationError` before package inspection. A normalized receipt
can still contain a `block` or `needs_owner_decision` decision when supplied
checks are false: normalization does not establish admission or rights truth.
Inspect both status and decision. The synthetic revision above demonstrates
the contract's format; production callers must supply the actual source revision.

The service is always read-only, so it needs no dry-run flag or filesystem
rollback. It does not copy, execute, install, or publish the package. Validate
serialized intake receipts with
`SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))` to enforce
structural and model-level bindings. The context schema is registered as
`skill-package-intake-context.v1`; neither family is supported by the generic
`parse_receipt` function.

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
package-safety evidence, runtime lock, installation plan, runtime execution
evidence, receipt, risk, security, scenario, and scorer schemas. The registered
`package-identity.v1` and inventory schemas receive structural validation only;
they do not receive model-level semantic checks. The packaged candidate,
skill-identity, plugin-identity, source, owner, normalized-package, and legacy `intake-decision.v1`
schemas are not registered with
`SchemaRegistry`; when those families need structural validation, load their
packaged JSON Schema resource with a Draft 2020-12 validator configured with
`jsonschema.FormatChecker()` so `date-time` and other declared formats are
asserted, then call the
corresponding Pydantic model explicitly (for example,
`PackageInventoryRecord.model_validate(payload)` for an inventory record).
The new `skill-package-intake.v1` and
`skill-package-intake-context.v1` families are registered as described above.
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
offset representation. Replay digests apply that same rule to the validated
prior result model. `parse_receipt` accepts only explicitly registered
receipt wire versions:
`receipt-base/v1`, package receipt v1/v2, evaluation receipt v1/v2, and
`registry-preparation/v1`, `package-safety-evidence/v1`,
`installation-result/v1`, `rollback-outcome/v1`,
`discovery-observation/v1`, `activation-observation/v1`, and
`runtime-outcome/v1`. A prepared
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

`runtime-lock/v1` and `install-plan/v1` are registered for structural and
Pydantic semantic validation but are not generic receipts: generic receipt
parsing must not reinterpret intended runtime state or a non-mutating plan as
evidence that installation occurred.

The package's `__all__` exports and the versioned files under
`src/skills_sdk/schemas/` are the compatibility surface. Add a focused test
and update the schema when changing a public contract.
