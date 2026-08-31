"""Packaged JSON Schema discovery and validation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

from skills_sdk.core.errors import ContractError

type JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]
MAX_JSON_NESTING_DEPTH = 100

SCHEMA_NAMES = frozenset(
    {
        "blocker.v1",
        "package-identity.v1",
        "package-inventory-set.v1",
        "package-inventory-set.v2",
        "package-inventory.v1",
        "package-inventory.v2",
        "package-manifest.v1",
        "package-hardening.v1",
        "package-receipt.v1",
        "package-receipt.v2",
        "package-safety-evidence.v1",
        "receipt-base.v1",
        "risk-classification.v1",
        "security-screening.v1",
        "evaluation-receipt.v1",
        "evaluation-receipt.v2",
        "provider-identity.v1",
        "provider-identity.v2",
        "provider-execution-request.v1",
        "provider-execution-result.v1",
        "registry-identity.v1",
        "registry-preparation.v1",
        "registry-preparation-request.v1",
        "scenario-case-result.v1",
        "scenario-case-result.v2",
        "scenario-observation.v1",
        "scenario-observation.v2",
        "scenario-set.v1",
        "scenario-set.v2",
        "scorer-profile.v1",
        "skill-package-validation.v1",
    }
)


def _require_json_value(
    value: object,
    active_containers: set[int] | None = None,
    depth: int = 0,
) -> JsonValue:
    if depth > MAX_JSON_NESTING_DEPTH:
        raise ContractError("invalid_json_value", "schema payload exceeds the maximum JSON nesting depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("invalid_json_value", "schema payload cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ContractError("invalid_json_value", "schema payload must contain only JSON-compatible values")
    if isinstance(value, (Mapping, Sequence)):
        active = active_containers if active_containers is not None else set()
        container_id = id(value)
        if container_id in active:
            raise ContractError("invalid_json_value", "schema payload cannot contain cyclic containers")
        active.add(container_id)
        try:
            if isinstance(value, Mapping):
                if not all(isinstance(key, str) for key in value):
                    raise ContractError("invalid_json_value", "JSON object keys must be strings")
                return {str(key): _require_json_value(item, active, depth + 1) for key, item in value.items()}
            return [_require_json_value(item, active, depth + 1) for item in value]
        finally:
            active.remove(container_id)
    raise ContractError("invalid_json_value", "schema payload must contain only JSON-compatible values")


@dataclass(frozen=True, slots=True)
class SchemaRegistry:
    """Resolve only known, packaged schema versions."""

    def load(self, name: str) -> dict[str, Any]:
        if name not in SCHEMA_NAMES:
            raise ContractError("unknown_schema", f"unsupported schema: {name}")
        resource = files("skills_sdk.schemas").joinpath(f"{name}.schema.json")
        try:
            payload = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContractError("invalid_schema_resource", f"cannot load schema: {name}", (str(error),)) from error
        if not isinstance(payload, dict):
            raise ContractError("invalid_schema_resource", f"schema is not an object: {name}")
        Draft202012Validator.check_schema(payload)
        return payload

    def validate(self, name: str, payload: object) -> None:
        if name not in SCHEMA_NAMES:
            raise ContractError("unknown_schema", f"unsupported schema: {name}")
        schemas = {schema_name: self.load(schema_name) for schema_name in SCHEMA_NAMES}
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
        validator = Draft202012Validator(
            schemas[name],
            format_checker=FormatChecker(),
            registry=registry,
        )
        errors = sorted(
            validator.iter_errors(_require_json_value(payload)),
            key=lambda error: tuple(str(part) for part in error.path),
        )
        if errors:
            details = tuple(error.message for error in errors)
            raise ContractError("contract_validation_failed", f"{name} rejected the payload", details)
        self._validate_registered_model(name, payload)

    def validate_package_safety_evidence_against_package_receipt(
        self,
        payload: object,
        package_receipt: object,
    ) -> None:
        """Validate safety evidence against one supplied package-receipt/v2 object."""

        self.validate("package-safety-evidence.v1", payload)
        if isinstance(package_receipt, Mapping):
            self.validate("package-receipt.v2", package_receipt)
        try:
            from skills_sdk.models.packaging import PackageReceiptV2
            from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

            safety_receipt = PackageSafetyEvidenceReceipt.model_validate(payload)
            upstream_receipt = PackageReceiptV2.model_validate(package_receipt)
            safety_receipt.validate_against_package_receipt(upstream_receipt)
        except (ValidationError, ValueError) as error:
            raise ContractError(
                "contract_validation_failed",
                "package-safety-evidence.v1 rejected the upstream package receipt binding",
                tuple(str(item) for item in error.errors()) if isinstance(error, ValidationError) else (str(error),),
            ) from error

    def validate_provider_execution_request_against_safety_evidence(
        self,
        payload: object,
        safety_receipt: object,
    ) -> None:
        """Validate one provider request against its supplied safety receipt."""

        self.validate("provider-execution-request.v1", payload)
        self.validate("package-safety-evidence.v1", safety_receipt)
        try:
            from skills_sdk.models.provider_execution import ProviderExecutionRequest
            from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

            request = ProviderExecutionRequest.model_validate(payload)
            safety = PackageSafetyEvidenceReceipt.model_validate(safety_receipt)
            request.validate_against_package_safety_evidence(safety)
        except (ValidationError, ValueError) as error:
            raise ContractError(
                "contract_validation_failed",
                "provider-execution-request.v1 rejected the package safety evidence binding",
                tuple(str(item) for item in error.errors()) if isinstance(error, ValidationError) else (str(error),),
            ) from error

    def validate_provider_execution_result_against_request(
        self,
        payload: object,
        request_payload: object,
    ) -> None:
        """Validate one provider result against its supplied execution request."""

        self.validate("provider-execution-result.v1", payload)
        self.validate("provider-execution-request.v1", request_payload)
        try:
            from skills_sdk.models.provider_execution import ProviderExecutionRequest, ProviderExecutionResult

            result = ProviderExecutionResult.model_validate(payload)
            request = ProviderExecutionRequest.model_validate(request_payload)
            result.validate_against_request(request)
        except (ValidationError, ValueError) as error:
            raise ContractError(
                "contract_validation_failed",
                "provider-execution-result.v1 rejected the provider request binding",
                tuple(str(item) for item in error.errors()) if isinstance(error, ValidationError) else (str(error),),
            ) from error

    def validate_provider_execution_replay_against_prior_result(
        self,
        payload: object,
        replayed_payload: object,
    ) -> None:
        """Validate replay provenance against one supplied prior result."""

        self.validate("provider-execution-result.v1", payload)
        self.validate("provider-execution-result.v1", replayed_payload)
        try:
            from skills_sdk.models.provider_execution import ProviderExecutionResult

            result = ProviderExecutionResult.model_validate(payload)
            replayed_result = ProviderExecutionResult.model_validate(replayed_payload)
            result.validate_against_replayed_result(replayed_result)
        except (ValidationError, ValueError) as error:
            raise ContractError(
                "contract_validation_failed",
                "provider-execution-result.v1 rejected the replay provenance binding",
                tuple(str(item) for item in error.errors()) if isinstance(error, ValidationError) else (str(error),),
            ) from error

    @staticmethod
    def _validate_registered_model(name: str, payload: object) -> None:
        """Apply semantic invariants after structural schema validation."""

        model: type[BaseModel]
        if name == "package-inventory.v2":
            from skills_sdk.models.inventory import PackageInventoryRecordV2

            model = PackageInventoryRecordV2
        elif name == "package-inventory-set.v2":
            from skills_sdk.models.inventory import PackageInventoryV2

            model = PackageInventoryV2
        elif name == "package-manifest.v1":
            from skills_sdk.models.packaging import PackageManifest

            model = PackageManifest
        elif name == "package-hardening.v1":
            from skills_sdk.models.packaging import PackageHardeningReceipt

            model = PackageHardeningReceipt
        elif name == "package-receipt.v1":
            from skills_sdk.models.packaging import PackageReceipt

            model = PackageReceipt
        elif name == "package-receipt.v2":
            from skills_sdk.models.packaging import PackageReceiptV2

            model = PackageReceiptV2
        elif name == "risk-classification.v1":
            from skills_sdk.models.risk import RiskClassification

            model = RiskClassification
        elif name == "provider-identity.v1":
            from skills_sdk.models.provider import ProviderIdentity

            model = ProviderIdentity
        elif name == "provider-identity.v2":
            from skills_sdk.models.provider import ProviderIdentityV2

            model = ProviderIdentityV2
        elif name == "provider-execution-request.v1":
            from skills_sdk.models.provider_execution import ProviderExecutionRequest

            model = ProviderExecutionRequest
        elif name == "provider-execution-result.v1":
            from skills_sdk.models.provider_execution import ProviderExecutionResult

            model = ProviderExecutionResult
        elif name == "registry-identity.v1":
            from skills_sdk.models.registry import RegistryIdentity

            model = RegistryIdentity
        elif name == "registry-preparation.v1":
            from skills_sdk.models.registry import RegistryPreparationReceipt

            model = RegistryPreparationReceipt
        elif name == "registry-preparation-request.v1":
            from skills_sdk.models.registry import RegistryPreparationRequest

            model = RegistryPreparationRequest
        elif name == "package-safety-evidence.v1":
            from skills_sdk.models.safety import PackageSafetyEvidenceReceipt

            model = PackageSafetyEvidenceReceipt
        elif name == "security-screening.v1":
            from skills_sdk.models.risk import SecurityScreeningResult

            model = SecurityScreeningResult
        elif name == "scenario-set.v1":
            from skills_sdk.models.evaluation import ScenarioSet

            model = ScenarioSet
        elif name == "scorer-profile.v1":
            from skills_sdk.models.evaluation import ScorerProfile

            model = ScorerProfile
        elif name == "scenario-observation.v1":
            from skills_sdk.models.evaluation import ScenarioObservation

            model = ScenarioObservation
        elif name == "scenario-case-result.v1":
            from skills_sdk.models.evaluation import ScenarioCaseResult

            model = ScenarioCaseResult
        elif name == "evaluation-receipt.v1":
            from skills_sdk.models.evaluation import EvaluationReceipt

            model = EvaluationReceipt
        elif name == "scenario-set.v2":
            from skills_sdk.models.evaluation_v2 import ScenarioSetV2

            model = ScenarioSetV2
        elif name == "scenario-observation.v2":
            from skills_sdk.models.evaluation_v2 import ScenarioObservationV2

            model = ScenarioObservationV2
        elif name == "scenario-case-result.v2":
            from skills_sdk.models.evaluation_v2 import ScenarioCaseResultV2

            model = ScenarioCaseResultV2
        elif name == "evaluation-receipt.v2":
            from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2

            model = EvaluationReceiptV2
        elif name == "skill-package-validation.v1":
            from skills_sdk.models.validation import SkillPackageValidation

            model = SkillPackageValidation
        else:
            return

        try:
            model.model_validate(payload)
        except ValidationError as error:
            details = tuple(item["msg"] for item in error.errors())
            raise ContractError("contract_validation_failed", f"{name} rejected the payload", details) from error
