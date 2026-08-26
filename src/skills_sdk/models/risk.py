"""Portable risk-sensor and security-screening contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity


class RiskSensor(_ContractModel):
    """One selected or available sensor in a candidate risk plan."""

    id: NonEmptyText
    placement: Literal["source", "schema", "static", "runtime_adapter", "external_adapter", "preview"]
    required: bool
    cost: Literal["low", "medium", "high"]
    blocking_behavior: Literal["block", "warn", "advisory", "skip_optional"]
    status: Literal["selected", "available_not_run", "skipped_optional", "blocked"]
    receipt_required: bool


class RiskClassification(_ContractModel):
    """Candidate-bound risk posture with explicit sensor coverage."""

    schema_version: Literal["risk-classification/v1"] = "risk-classification/v1"
    candidate: PackageCandidateIdentity
    source_kind: Literal["docs_only", "referenced", "scripted", "external", "placeholder"]
    risk_tier: Literal["low", "medium", "high", "privileged", "published"]
    probability: Literal["low", "medium", "high", "unknown"]
    impact: Literal["low", "medium", "high", "unknown"]
    detectability: Literal["low", "medium", "high", "unknown"]
    cost: Literal["low", "medium", "high"]
    blocking_behavior: Literal["block", "warn", "advisory", "skip_optional"]
    receipt_required: bool
    sensor_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    sensors: tuple[RiskSensor, ...] = Field(min_length=1)
    acceptance_trace: tuple[NonEmptyText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sensors_cover_classification(self) -> RiskClassification:
        ids = tuple(sensor.id for sensor in self.sensors)
        if len(ids) != len(set(ids)):
            raise ValueError("risk sensor ids must be unique")
        if len(self.sensor_ids) != len(set(self.sensor_ids)):
            raise ValueError("sensor_ids must be unique")
        if set(self.sensor_ids) != set(ids):
            raise ValueError("sensor_ids must match the declared sensors")
        if any(
            sensor.required
            and (sensor.status == "skipped_optional" or sensor.blocking_behavior == "skip_optional")
            for sensor in self.sensors
        ):
            raise ValueError("required sensors cannot use optional skip states")
        if not self.receipt_required and any(
            sensor.status == "selected" and sensor.receipt_required for sensor in self.sensors
        ):
            raise ValueError("selected sensors requiring receipts need a classification receipt")
        if self.risk_tier in {"high", "privileged", "published"} and not self.receipt_required:
            raise ValueError("elevated risk tiers require a receipt")
        return self


class SecurityFinding(_ContractModel):
    """Redacted finding metadata; raw secret values never enter the contract."""

    code: NonEmptyText
    category: Literal["secret", "unsafe_path", "external_service", "license", "mcp_auth", "dependency"]
    severity: Literal["info", "warning", "blocker"]
    message: NonEmptyText
    evidence_refs: tuple[PortablePath, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values


class SecurityScreeningResult(_ContractModel):
    """Candidate-bound secret and unsafe-package screening result."""

    schema_version: Literal["security-screening/v1"] = "security-screening/v1"
    candidate: PackageCandidateIdentity
    status: Literal["pass", "needs_review", "blocked"]
    scanned_paths: tuple[PortablePath, ...] = Field(min_length=1)
    findings: tuple[SecurityFinding, ...] = ()
    mutation_performed: Literal[False] = False

    @field_validator("scanned_paths")
    @classmethod
    def scanned_paths_must_be_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            require_portable_relative_path(value)
        return values

    @model_validator(mode="after")
    def status_matches_findings(self) -> SecurityScreeningResult:
        severities = {finding.severity for finding in self.findings}
        if self.status == "pass" and severities - {"info"}:
            raise ValueError("pass screening cannot contain warning or blocker findings")
        if self.status == "needs_review":
            if "blocker" in severities:
                raise ValueError("needs_review screening cannot contain a blocker finding")
            if "warning" not in severities:
                raise ValueError("needs_review screening requires a warning finding")
        if self.status == "blocked" and "blocker" not in severities:
            raise ValueError("blocked screening requires a blocker finding")
        codes = [finding.code for finding in self.findings]
        if len(codes) != len(set(codes)):
            raise ValueError("security finding codes must be unique")
        return self


__all__ = ["RiskClassification", "RiskSensor", "SecurityFinding", "SecurityScreeningResult"]
