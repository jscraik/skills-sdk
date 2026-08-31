"""Portable runtime-lock and non-mutating installation-plan contracts."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText, PortablePath, Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.packaging import ReceiptId
from skills_sdk.models.registry import RegistryIdentity, RegistryPreparationBlocker

RuntimeIdentifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
_CREDENTIAL_PREFIXES = ("aiza", "akia", "bearer", "ghp_", "github_pat_", "hf_", "sk-", "xoxb-", "xoxp-")
_CREDENTIAL_PATTERN = re.compile(
    rf"(?:^|[^A-Za-z0-9])(?:{'|'.join(re.escape(prefix) for prefix in _CREDENTIAL_PREFIXES)}|"
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:client|access)[_-]?(?:secret|token|key(?:[_-]?id)?)|"
    r"(?:(?:ssh_)?private[_-]?key|api[_-]?key|credential|password|secret|token)"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"[\"']?[\s\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*[:=])",
    re.IGNORECASE | re.ASCII,
)
_MACHINE_PATH_PATTERN = re.compile(
    r"(?:[fF][iI][lL][eE]:)/+|(?:^|[^A-Za-z0-9])\$[A-Za-z_][A-Za-z0-9_]*/|"
    r"(?:[A-Za-z0-9._-]+\\)+[A-Za-z0-9._-]+|(?:^|[^A-Za-z0-9])\\|(?:^|[^A-Za-z0-9/])/(?!/)|"
    r"(?:^|[^A-Za-z0-9/])/(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|[Pp][rR][iI][vV][aA][tT][eE]|"
    r"[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9.:/])(?:[A-Za-z0-9._-]+/)+(?:[Uu][sS][eE][rR][sS]|[Hh][oO][mM][eE]|"
    r"[Pp][rR][iI][vV][aA][tT][eE]|[Tt][mM][pP]|[Ww][oO][rR][kK][sS][pP][aA][cC][eE]|"
    r"[Vv][aA][rR]/[Ff][oO][lL][dD][eE][rR][sS]|[Rr][Oo][Oo][Tt])/|"
    r"(?:^|[^A-Za-z0-9])[A-Za-z]:"
)


def lifecycle_text_is_public_safe(value: str) -> bool:
    """Return whether lifecycle public text avoids secret and host-path shapes."""

    return _CREDENTIAL_PATTERN.search(value) is None and _MACHINE_PATH_PATTERN.search(value) is None


def _require_public_text(value: str, field: str) -> str:
    if not lifecycle_text_is_public_safe(value):
        raise ValueError(f"{field} must not contain credential-shaped or machine-path values")
    return value


def _require_public_portable_text(value: str, field: str) -> str:
    require_portable_relative_path(value)
    return _require_public_text(value, field)


def _plan_id(payload: object) -> str:
    return f"install-plan-{canonical_json_sha256(payload)[:24]}"


class RuntimeTarget(_ContractModel):
    """Logical destination resolved only by a future host adapter."""

    scope: Literal["user", "project"]
    target_id: RuntimeIdentifier

    @field_validator("target_id")
    @classmethod
    def target_id_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "runtime target identity")


class RuntimeFile(_ContractModel):
    """Expected package-relative file identity in an intended projection."""

    path: PortablePath
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def path_must_be_portable(cls, value: str) -> str:
        return _require_public_portable_text(value, "runtime file path")


class RuntimeLockEntry(_ContractModel):
    """One candidate-bound intended runtime package entry."""

    package_name: RuntimeIdentifier
    version: NonEmptyText
    candidate: PackageCandidateIdentity
    package_digest: Sha256
    registry: RegistryIdentity
    package_receipt_id: ReceiptId
    registry_preparation_receipt_id: ReceiptId
    target: RuntimeTarget
    files: tuple[RuntimeFile, ...] = Field(min_length=1)

    @field_validator("package_name", "version")
    @classmethod
    def package_identity_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "runtime package identity")

    @model_validator(mode="after")
    def identity_and_files_are_consistent(self) -> RuntimeLockEntry:
        if self.package_name != self.candidate.package_id:
            raise ValueError("runtime lock package name must match candidate package_id")
        paths = tuple(item.path for item in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("runtime lock file paths must be unique")
        return self


class RuntimeLock(_ContractModel):
    """Portable intended runtime state; a future host adapter owns persistence."""

    schema_version: Literal["runtime-lock/v1"] = "runtime-lock/v1"
    entries: tuple[RuntimeLockEntry, ...] = ()

    @model_validator(mode="after")
    def entries_are_unique(self) -> RuntimeLock:
        keys = tuple((entry.target.scope, entry.target.target_id, entry.package_name) for entry in self.entries)
        if len(keys) != len(set(keys)):
            raise ValueError("runtime lock entries must be unique by target and package")
        return self


class InstallPlan(_ContractModel):
    """Deterministic proposed runtime-lock transition that performs no mutation."""

    schema_version: Literal["install-plan/v1"] = "install-plan/v1"
    plan_id: ReceiptId
    candidate: PackageCandidateIdentity | None = None
    package_name: RuntimeIdentifier
    version: NonEmptyText
    package_digest: Sha256 | None = None
    package_receipt_id: ReceiptId
    status: Literal["planned", "blocked"]
    operation: Literal["install", "update", "no_change"] | None = None
    target: RuntimeTarget
    registry: RegistryIdentity
    registry_preparation_receipt_id: ReceiptId
    registry_input_receipt_id: ReceiptId
    current_lock_sha256: Sha256
    rollback_lock_sha256: Sha256
    proposed_lock_sha256: Sha256 | None = None
    proposed_entry: RuntimeLockEntry | None = None
    evidence: tuple[PortablePath, ...] = Field(min_length=1)
    blocker: RegistryPreparationBlocker | None = None
    mutation_performed: Literal[False] = False

    @field_validator("package_name", "version")
    @classmethod
    def package_identity_must_be_public_safe(cls, value: str) -> str:
        return _require_public_text(value, "install plan package identity")

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_unique_and_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("install plan evidence paths must be unique")
        return tuple(_require_public_portable_text(value, "install plan evidence") for value in values)

    @model_validator(mode="after")
    def status_matches_transition(self) -> InstallPlan:
        if self.rollback_lock_sha256 != self.current_lock_sha256:
            raise ValueError("install plan rollback identity must match the current lock")
        if self.status == "planned":
            if self.registry_input_receipt_id != self.package_receipt_id:
                raise ValueError("planned install registry input must match the package receipt")
            self._validate_planned_state()
        elif self.operation is not None or self.proposed_lock_sha256 is not None or self.proposed_entry is not None:
            raise ValueError("blocked install plan cannot claim a proposed transition")
        elif self.blocker is None:
            raise ValueError("blocked install plan requires a blocker")
        elif (
            not lifecycle_text_is_public_safe(self.blocker.code)
            or not lifecycle_text_is_public_safe(self.blocker.message)
            or any(not lifecycle_text_is_public_safe(ref) for ref in self.blocker.evidence_refs)
        ):
            raise ValueError("install plan blocker must not contain credential-shaped or machine-path values")
        if self.plan_id != _plan_id(self._identity_payload()):
            raise ValueError("install plan id must bind the complete emitted plan identity")
        return self

    def _identity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate": self.candidate.model_dump(mode="json") if self.candidate else None,
            "package_name": self.package_name,
            "version": self.version,
            "package_digest": self.package_digest,
            "package_receipt_id": self.package_receipt_id,
            "registry": self.registry.model_dump(mode="json"),
            "registry_preparation_receipt_id": self.registry_preparation_receipt_id,
            "registry_input_receipt_id": self.registry_input_receipt_id,
            "current_lock_sha256": self.current_lock_sha256,
            "rollback_lock_sha256": self.rollback_lock_sha256,
            "target": self.target.model_dump(mode="json"),
            "status": self.status,
            "evidence": self.evidence,
        }
        if self.status == "planned":
            payload.update(
                operation=self.operation,
                proposed_lock_sha256=self.proposed_lock_sha256,
                proposed_entry=self.proposed_entry.model_dump(mode="json") if self.proposed_entry else None,
            )
        else:
            payload["blocker"] = self.blocker.model_dump(mode="json") if self.blocker else None
        return payload

    def _validate_planned_state(self) -> None:
        if self.candidate is None or self.package_digest is None:
            raise ValueError("planned install requires candidate and package digest")
        if self.operation is None or self.proposed_lock_sha256 is None or self.proposed_entry is None:
            raise ValueError("planned install requires operation, proposed lock, and entry")
        if self.proposed_entry.candidate != self.candidate or self.proposed_entry.target != self.target:
            raise ValueError("install plan and runtime entry must bind the same candidate and target")
        if self.proposed_entry.package_digest != self.package_digest:
            raise ValueError("install plan and runtime entry must bind the same package digest")
        if self.proposed_entry.package_name != self.package_name or self.package_name != self.candidate.package_id:
            raise ValueError("install plan and runtime entry must bind the same package name")
        if self.proposed_entry.version != self.version:
            raise ValueError("install plan and runtime entry must bind the same version")
        if self.proposed_entry.package_receipt_id != self.package_receipt_id:
            raise ValueError("install plan and runtime entry must bind the same package receipt")
        if self.proposed_entry.registry_preparation_receipt_id != self.registry_preparation_receipt_id:
            raise ValueError("install plan and runtime entry must bind the same registry preparation receipt")
        if self.proposed_entry.registry != self.registry:
            raise ValueError("install plan and runtime entry must bind the same registry")
        if self.blocker is not None:
            raise ValueError("planned install cannot contain a blocker")


__all__ = [
    "InstallPlan",
    "RuntimeFile",
    "RuntimeLock",
    "RuntimeLockEntry",
    "RuntimeTarget",
    "lifecycle_text_is_public_safe",
]
