"""Read-only whole-plugin static screening and supplied safety assessment checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.models.plugin import PluginPackageValidation, PluginValidationPolicy
from skills_sdk.models.plugin_safety import PluginPreExecutionSafetyEvidence
from skills_sdk.models.risk import SecurityFinding, SecurityScreeningResult
from skills_sdk.models.safety import PackageSafetyBlocker
from skills_sdk.validation.plugin_capture import capture_plugin_source
from skills_sdk.validation.plugin_evidence import verify_plugin_package_validation
from skills_sdk.validation.security_signatures import source_security_indicators


def _blocker(code: str) -> PackageSafetyBlocker:
    """Create a typed plugin-safety blocker without retaining host paths."""
    return PackageSafetyBlocker(code=code, message="Execution requires current bound whole-plugin safety evidence.")


def _plugin_indicators(path: str, content: bytes) -> tuple[SecurityFinding, ...]:
    """Preserve child eval semantics while retaining plugin-relative evidence paths."""
    parts = path.split("/")
    scanner_path = "/".join(parts[2:]) if len(parts) > 2 and parts[0] == "skills" else path
    return tuple(
        finding.model_copy(update={"evidence_refs": (path,)})
        for finding in source_security_indicators(scanner_path, content)
    )


def _aggregate_findings(payloads: dict[str, bytes]) -> tuple[SecurityFinding, ...]:
    """Aggregate identical static indicators while retaining every captured path."""
    by_code: dict[str, SecurityFinding] = {}
    for path, content in sorted(payloads.items()):
        for finding in _plugin_indicators(path, content):
            previous = by_code.get(finding.code)
            refs = finding.evidence_refs + (previous.evidence_refs if previous else ())
            by_code[finding.code] = finding.model_copy(update={"evidence_refs": tuple(sorted(set(refs)))})
    return tuple(by_code.values())


def screen_plugin_security(
    root: Path,
    validation: object,
    *,
    policy: PluginValidationPolicy | None = None,
) -> SecurityScreeningResult | PackageSafetyBlocker:
    """Screen freshly verified complete plugin bytes without execution or mutation."""
    try:
        active = PluginValidationPolicy.model_validate(policy if policy is not None else {})
        supplied = PluginPackageValidation.model_validate(validation)
        if supplied.candidate is None:
            raise ValueError("plugin candidate is unavailable")
        verified = verify_plugin_package_validation(
            root,
            supplied,
            source_revision=supplied.candidate.source_revision,
            policy=active,
        )
        if verified.status != "pass" or verified != supplied or supplied.policy != active:
            return _blocker("plugin_security_source_changed")
        files, payloads, _directories = capture_plugin_source(root)
        if files != supplied.files:
            return _blocker("plugin_security_source_changed")
        findings = _aggregate_findings(payloads)
        result = SecurityScreeningResult(
            candidate=supplied.candidate,
            sensor_ids=("sdk-static-signature-v1",),
            status="needs_review" if findings else "pass",
            scanned_paths=tuple(item.path for item in files),
            findings=findings,
        )
        confirmed = verify_plugin_package_validation(
            root,
            supplied,
            source_revision=supplied.candidate.source_revision,
            policy=active,
        )
        if confirmed.status != "pass" or confirmed != supplied:
            return _blocker("plugin_security_source_changed")
        return result
    except (AttributeError, ContractError, OSError, TypeError, ValueError, ValidationError, RecursionError):
        return _blocker("invalid_plugin_security_source")


def assess_plugin_pre_execution_safety(
    root: Path,
    evidence: object,
    *,
    policy: PluginValidationPolicy | None = None,
    checked_at: datetime | None = None,
    max_age_seconds: int = 3600,
) -> PackageSafetyBlocker | None:
    """Assess supplied no-issue evidence against fresh complete plugin source and host time."""
    if evidence is None:
        return _blocker("plugin_safety_evidence_required")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400:
        return _blocker("invalid_plugin_safety_freshness_policy")
    now = datetime.now(UTC) if checked_at is None else checked_at
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _blocker("invalid_plugin_safety_check_time")
    try:
        parsed = PluginPreExecutionSafetyEvidence.model_validate(evidence)
    except (AttributeError, TypeError, ValueError, ValidationError, RecursionError):
        return _blocker("invalid_plugin_safety_evidence")
    observed = screen_plugin_security(root, parsed.validation, policy=policy)
    if isinstance(observed, PackageSafetyBlocker):
        return observed
    if observed != parsed.screening:
        return _blocker("plugin_security_screening_mismatch")
    if parsed.observed_at > now:
        return _blocker("plugin_safety_evidence_future")
    if now - parsed.observed_at > timedelta(seconds=max_age_seconds):
        return _blocker("plugin_safety_evidence_stale")
    return None


__all__ = ["assess_plugin_pre_execution_safety", "screen_plugin_security"]
