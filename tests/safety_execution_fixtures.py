"""Synthetic, explicit review evidence for controlled execution tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.packaging import PackageReceiptV2
from skills_sdk.models.pre_execution_safety import SAFETY_CHECK_IDS, CapabilitySafetyReview, PreExecutionSafetyEvidence
from skills_sdk.models.risk import SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt
from skills_sdk.packaging import build_skill_package
from skills_sdk.validation.security_screening import screen_package_security


def synthetic_safety_evidence(
    package_receipt: PackageReceiptV2, screening: SecurityScreeningResult, observed_at: datetime
) -> PreExecutionSafetyEvidence:
    """Explicit fixture review of all six categories, not a production admission helper."""
    checks = tuple(
        CapabilitySafetyReview(
            check_id=check_id,
            status="reviewed_no_issue",
            rationale="Controlled fixture review covers this capability.",
            evidence_ids=("review-report",),
        )
        for check_id in SAFETY_CHECK_IDS
    )
    digests = {
        "review-report": "c" * 64,
        "static-screening": canonical_json_sha256(screening.model_dump(mode="json")),
        "capability-checklist": canonical_json_sha256(
            {
                "version": "sdk-capability-checklist/v1",
                "checks": [item.model_dump(mode="json") for item in checks],
            }
        ),
    }
    safety = PackageSafetyEvidenceReceipt.model_validate(
        {
            "schema_version": "package-safety-evidence/v1",
            "receipt_id": "fixture-safety-review",
            "candidate": package_receipt.candidate,
            "lane": "safety_review",
            "input_receipt_id": package_receipt.receipt_id,
            "package_digest": package_receipt.package_digest,
            "reviewer": {"adapter_id": "review/fixture", "adapter_version_or_digest": "v1", "method": "manual_review"},
            "status": "reviewed_no_issue",
            "observed_at": observed_at.isoformat(),
            "evidence": [
                {"evidence_id": key, "kind": "manual_review", "ref": f"evidence/{key}.json", "sha256": digest}
                for key, digest in digests.items()
            ],
        }
    )
    return PreExecutionSafetyEvidence(
        package_receipt=package_receipt,
        safety_receipt=safety,
        screening=screening,
        checklist=checks,
    )


def safety_for_package(package_root: Path, source_revision: str, observed_at: datetime) -> PreExecutionSafetyEvidence:
    """Capture and review only the disposable source fixture supplied by a test."""
    upstream = build_skill_package(package_root, source_revision=source_revision, clock=lambda: observed_at)
    screening = screen_package_security(package_root, upstream)
    if not isinstance(screening, SecurityScreeningResult):
        raise ValueError("fixture must have valid bound source")
    return synthetic_safety_evidence(upstream, screening, observed_at)
