"""Read-only coverage auditing against the package's ten active scenarios."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.evaluation.quality import (
    _document_cases,
    _load_evals_payload,
    _release_sets,
    _select_release_cases,
    assess_scenario_quality,
)
from skills_sdk.models.coverage import ScenarioCoveragePlan, ScenarioCoverageResult
from skills_sdk.models.scenario_quality import ScenarioQualityFinding, ScenarioQualityReceiptV2
from skills_sdk.validation import validate_skill_package


def _finding(code: str, message: str) -> ScenarioQualityFinding:
    return ScenarioQualityFinding(code=code, message=message)


def _active_ids(
    root: Path, revision: str, quality: ScenarioQualityReceiptV2, findings: list[ScenarioQualityFinding]
) -> tuple[str, ...]:
    validation = validate_skill_package(root, source_revision=revision)
    if validation.status != "pass" or validation.candidate != quality.candidate:
        findings.append(_finding("candidate_changed", "candidate changed after scenario quality assessment"))
        return ()
    manifest = next(item for item in validation.files if item.path == "references/evals.yaml")
    payload = _load_evals_payload(root, manifest.sha256, findings)
    cases = _document_cases(payload, validation.candidate.package_id, findings)
    if not isinstance(payload, Mapping):
        return ()
    sets = _release_sets(payload, findings, active_v2=True, selected_set_id=quality.scenario_set_id)
    selected = _select_release_cases(cases, sets, quality.scenario_set_id, findings)
    return tuple(str(case["id"]) for case in selected if isinstance(case, Mapping))


def assess_scenario_coverage(
    package_root: Path, *, source_revision: str, scenario_set_id: str, coverage_plan: object
) -> ScenarioCoverageResult:
    """Audit caller-declared claims and gaps; never execute or approve a judge."""
    quality = assess_scenario_quality(
        package_root, source_revision=source_revision, scenario_set_id=scenario_set_id, contract_version="v2"
    )
    if not isinstance(quality, ScenarioQualityReceiptV2):
        raise TypeError("v2 quality assessment required")
    findings = list(quality.findings)
    plan: ScenarioCoveragePlan | None = None
    try:
        raw = (
            coverage_plan.model_dump(mode="json", warnings="error")
            if isinstance(coverage_plan, ScenarioCoveragePlan)
            else coverage_plan
        )
        plan = ScenarioCoveragePlan.model_validate(raw)
    except (ValidationError, ValueError, TypeError, RecursionError, PydanticSerializationError):
        findings.append(_finding("invalid_coverage_plan", "coverage plan must match the closed versioned contract"))
    active_ids = _active_ids(package_root, source_revision, quality, findings) if quality.status == "pass" else ()
    if plan is not None:
        if plan.candidate != quality.candidate or plan.scenario_set_id != quality.scenario_set_id:
            findings.append(
                _finding("coverage_identity_mismatch", "coverage plan must bind the current candidate and set")
            )
        if active_ids:
            findings.extend(plan.audit(active_ids))
    if active_ids:
        final = validate_skill_package(package_root, source_revision=source_revision)
        if final.status != "pass" or final.candidate != quality.candidate:
            findings.append(_finding("candidate_changed", "candidate changed during coverage assessment"))
    findings.sort(key=lambda item: (item.code, item.message))
    return ScenarioCoverageResult(
        candidate=quality.candidate,
        scenario_set_id=quality.scenario_set_id,
        status="blocked" if findings else "pass",
        quality=quality,
        plan=plan,
        active_case_ids=active_ids,
        open_gap_ids=tuple(sorted(gap.id for gap in plan.gaps)) if plan else (),
        coverage_complete=not findings and bool(plan) and not plan.gaps,
        findings=tuple(findings),
    )
