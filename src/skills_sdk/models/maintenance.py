"""Platform-neutral public result contracts for host maintenance workflows."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    StringConstraints,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue

from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath
from skills_sdk.models.validation import SkillPackageValidation


def _reject_blocker_code_line_breaks(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("blocker code must not contain line breaks")
    return value


MaintenanceBlockerCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9_]+$"),
    AfterValidator(_reject_blocker_code_line_breaks),
    Field(json_schema_extra={"not": {"pattern": r"[\r\n]"}}),
]


def _validate_artifact_name(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("artifact name must be one non-empty path component")
    return value


ArtifactName = Annotated[
    str,
    AfterValidator(_validate_artifact_name),
    Field(
        min_length=1,
        json_schema_extra={
            "pattern": r"^[^/\\]+$",
            "not": {"anyOf": [{"enum": [".", ".."]}, {"pattern": r"\u0000"}]},
        },
    ),
]


class EntrypointMaintenanceBlocker(BaseModel):
    """Stable public reason that maintenance did not complete."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    code: MaintenanceBlockerCode
    message: NonEmptyText


class EntrypointMaintenanceResult(BaseModel):
    """Versioned result for preview and explicitly authorized maintenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["entrypoint-maintenance-result/v1"] = "entrypoint-maintenance-result/v1"
    status: Literal["matching", "repairable", "repaired", "blocked", "indeterminate"]
    blocker: EntrypointMaintenanceBlocker | None = None
    backup_name: ArtifactName | None = None
    recovery_name: ArtifactName | None = None

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        if self.status in {"matching", "repairable"} and any(
            value is not None for value in (self.blocker, self.backup_name, self.recovery_name)
        ):
            raise ValueError("preview success must not carry failure or recovery evidence")
        if self.status == "repaired" and (self.blocker is not None or self.backup_name is None):
            raise ValueError("repaired maintenance requires a backup and no blocker")
        if self.status == "blocked" and (self.blocker is None or self.recovery_name is not None):
            raise ValueError("blocked maintenance requires blocker evidence and no recovery name")
        if self.status == "indeterminate" and (
            self.blocker is None or self.backup_name is None or self.recovery_name is None
        ):
            raise ValueError("indeterminate maintenance requires blocker, backup, and recovery evidence")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        schema = handler(core_schema)
        schema["allOf"] = [
            {
                "if": {"properties": {"status": {"const": status}}},
                "then": constraint,
            }
            for status, constraint in {
                "matching": {
                    "properties": {name: {"type": "null"} for name in ("blocker", "backup_name", "recovery_name")}
                },
                "repairable": {
                    "properties": {name: {"type": "null"} for name in ("blocker", "backup_name", "recovery_name")}
                },
                "repaired": {
                    "required": ["backup_name"],
                    "properties": {"blocker": {"type": "null"}, "backup_name": {"type": "string"}},
                },
                "blocked": {
                    "required": ["blocker"],
                    "properties": {
                        "blocker": {"type": "object"},
                        "backup_name": {"type": ["string", "null"]},
                        "recovery_name": {"type": "null"},
                    },
                },
                "indeterminate": {
                    "required": ["blocker", "backup_name", "recovery_name"],
                    "properties": {
                        "blocker": {"type": "object"},
                        "backup_name": {"type": "string"},
                        "recovery_name": {"type": "string"},
                    },
                },
            }.items()
        ]
        return schema


class RuntimeCopyComparison(BaseModel):
    """Local comparison, not installation, activation, or admission evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["runtime-copy-comparison/v1"] = "runtime-copy-comparison/v1"
    status: Literal["pass", "drift", "blocked"]
    source: SkillPackageValidation
    runtime: SkillPackageValidation
    different_paths: tuple[PortablePath, ...]

    @model_validator(mode="after")
    def status_matches_evidence(self) -> Self:
        for path in self.different_paths:
            require_portable_relative_path(path)
        if tuple(sorted(set(self.different_paths))) != self.different_paths:
            raise ValueError("comparison paths must be sorted and unique")
        validations_pass = self.source.status == self.runtime.status == "pass"
        if self.status == "pass" and (not validations_pass or self.different_paths):
            raise ValueError("passing comparison requires passing validation and no differences")
        if self.status == "drift" and (not validations_pass or not self.different_paths):
            raise ValueError("drift comparison requires passing validation and differences")
        if self.status == "blocked" and validations_pass:
            raise ValueError("blocked comparison requires failed source or runtime validation")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        schema = handler(core_schema)
        passed = {"properties": {"status": {"const": "pass"}}}
        valid_copies = {
            "source": {"properties": {"status": {"const": "pass"}}},
            "runtime": {"properties": {"status": {"const": "pass"}}},
        }
        schema["allOf"] = [
            {
                "if": passed,
                "then": {"properties": {"different_paths": {"maxItems": 0}, **valid_copies}},
            },
            {
                "if": {"properties": {"status": {"const": "drift"}}},
                "then": {"properties": {"different_paths": {"minItems": 1}, **valid_copies}},
            },
            {
                "if": {"properties": {"status": {"const": "blocked"}}},
                "then": {
                    "anyOf": [
                        {"properties": {"source": {"properties": {"status": {"not": {"const": "pass"}}}}}},
                        {"properties": {"runtime": {"properties": {"status": {"not": {"const": "pass"}}}}}},
                    ]
                },
            },
        ]
        return schema


__all__ = ["EntrypointMaintenanceBlocker", "EntrypointMaintenanceResult", "RuntimeCopyComparison"]
