"""Read-only static package screening over the existing safe capture boundary."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.risk import SecurityFinding, SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.validation.security_signatures import source_security_indicators
from skills_sdk.validation.skill_package import SkillValidationPolicy, _scan_files


def screen_package_security(
    package_root: Path, package_receipt: PackageReceiptV2
) -> SecurityScreeningResult | PackageSafetyBlocker:
    """Observe actual bound bytes without scanner subprocesses or package execution."""
    try:
        receipt = PackageReceiptV2.model_validate(package_receipt.model_dump(mode="json"))
        if receipt.status != "built" or receipt.manifest is None or receipt.candidate is None:
            raise ValueError("built upstream required")
        files, capture_findings, captured = _scan_files(package_root, SkillValidationPolicy())
        if capture_findings or tuple(files) != receipt.manifest.files:
            return PackageSafetyBlocker(
                code="security_source_changed", message="Security capture must match the built package."
            )
        observations = tuple(
            finding
            for path, content in sorted(captured.items())
            for finding in source_security_indicators(path, content)
        )
        by_code: dict[str, SecurityFinding] = {}
        for finding in observations:
            previous = by_code.get(finding.code)
            by_code[finding.code] = finding.model_copy(
                update={
                    "evidence_refs": tuple(
                        sorted(set(finding.evidence_refs + (previous.evidence_refs if previous else ())))
                    )
                }
            )
        findings = tuple(by_code.values())
        return SecurityScreeningResult(
            candidate=receipt.candidate,
            sensor_ids=("sdk-static-signature-v1",),
            status="needs_review" if findings else "pass",
            scanned_paths=tuple(sorted(captured)),
            findings=findings,
        )
    except (AttributeError, TypeError, ValueError, OSError, RuntimeError, ValidationError, PydanticSerializationError):
        return PackageSafetyBlocker(
            code="invalid_security_source", message="Security capture requires a built readable package."
        )
