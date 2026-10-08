"""Revalidate actual package safety evidence before accessing execution adapters.

This binding check assesses supplied artifacts, not scanner execution or reviewer
authenticity. Capability-specific screening remains a separate required lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import JsonValue, ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.models.pre_execution_safety import PreExecutionSafetyEvidence
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.safety import PackageSafetyBlocker, PackageSafetyEvidenceReceipt


@dataclass(frozen=True, slots=True)
class SelectedCaseExecutionInput:
    """Host input and actual safety artifacts; construction does not grant admission."""

    payload: JsonValue
    safety_evidence: object


def _blocker(code: str) -> PackageSafetyBlocker:
    return PackageSafetyBlocker(code=code, message="Execution requires current bound package safety evidence.")


def assess_pre_execution_safety(
    request: ProviderExecutionRequest,
    evidence: object,
    *,
    checked_at: datetime | None = None,
    max_age_seconds: int = 3600,
    package_root: Path | None = None,
) -> PackageSafetyBlocker | None:
    """Reject missing, contradictory or stale artifacts without touching adapters.

    The host owns the clock and freshness budget; neither comes from the supplied
    artifact. A successful binding is not complete security admission on its own.
    """

    if evidence is None:
        return _blocker("package_safety_evidence_required")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400:
        return _blocker("invalid_safety_freshness_policy")
    now = datetime.now(UTC) if checked_at is None else checked_at
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _blocker("invalid_safety_check_time")
    try:
        request = ProviderExecutionRequest.model_validate(request.model_dump(mode="json"))
        if request.status != "prepared":
            return _blocker("provider_request_blocked")
        parsed = PreExecutionSafetyEvidence.model_validate(evidence)
        parsed.safety_receipt.validate_against_package_receipt(parsed.package_receipt)
        request.validate_against_package_safety_evidence(parsed.safety_receipt)
    except (AttributeError, TypeError, ValueError, ValidationError, PydanticSerializationError):
        return _blocker("invalid_package_safety_evidence")
    if parsed.safety_receipt.observed_at < parsed.package_receipt.finished_at:
        return _blocker("package_safety_evidence_predates_build")
    blocker = _review_recency_blocker(parsed.safety_receipt, now, max_age_seconds)
    if blocker is not None or package_root is None:
        return blocker
    from skills_sdk.validation.security_screening import screen_package_security

    observed = screen_package_security(package_root, parsed.package_receipt)
    if isinstance(observed, PackageSafetyBlocker):
        return observed
    if observed != parsed.screening:
        return _blocker("security_screening_mismatch")
    return None


def _review_recency_blocker(
    receipt: PackageSafetyEvidenceReceipt, checked_at: datetime, max_age_seconds: int
) -> PackageSafetyBlocker | None:
    if receipt.status != "reviewed_no_issue" or receipt.reviewer.method == "metadata":
        return _blocker("package_safety_review_required")
    if receipt.observed_at > checked_at:
        return _blocker("package_safety_evidence_future")
    if checked_at - receipt.observed_at > timedelta(seconds=max_age_seconds):
        return _blocker("package_safety_evidence_stale")
    return None
