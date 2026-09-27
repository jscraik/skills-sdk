"""Read-only quality checks for a candidate's declared scorer metadata."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

import yaml

from skills_sdk.evaluation.quality import _TOP_FIELDS, _ClosedLoader
from skills_sdk.evaluation.scorer_artifacts import read_candidate_artifact
from skills_sdk.models.scenario_quality import ScenarioQualityFinding
from skills_sdk.models.scorer_quality import ScorerQualityReceipt
from skills_sdk.validation import validate_skill_package

_EVALS = "references/evals.yaml"
_SCORER_TYPES = {"deterministic", "llm_judge", "hybrid", "external_tessl"}
_JUDGE_TYPES = _SCORER_TYPES - {"deterministic"}
_SCOPES = {"span", "trace", "suite"}
_PROBES = {
    "obvious_correct",
    "obvious_wrong",
    "short_correct_vs_verbose_wrong",
    "rubric_copying_rejected",
    "skill_name_mention_not_enough",
    "evidence_lane_overclaim_rejected",
}
_SEGMENTS = {"category", "claim_ids", "eval_modes"}
_FIELDS = {
    "schema_version",
    "scorer_id",
    "scorer_type",
    "scope",
    "scorer_version_or_digest",
    "pass_threshold",
    "deterministic_checks_first",
    "parameters",
    "rationale_audit",
    "bias_probes",
    "segmentation_fields",
    "calibration_cases",
}


def _finding(code: str, message: str) -> ScenarioQualityFinding:
    return ScenarioQualityFinding(code=code, message=message, evidence_refs=(_EVALS,))


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) else None
    return None


def _strict_metadata(metadata: Mapping[object, object]) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    if set(metadata) - _FIELDS:
        findings.append(_finding("unknown_scorer_field", "scorer_quality contains unsupported fields"))
    if metadata.get("schema_version") != "skills-sdk.scorer-quality.v1":
        findings.append(_finding("invalid_scorer_schema", "scorer_quality schema_version is unsupported"))
    for field in ("scorer_id", "scorer_version_or_digest"):
        if not _text(metadata.get(field)):
            findings.append(_finding(f"invalid_{field}", f"{field} must be non-empty text"))
    scorer_type = metadata.get("scorer_type")
    if not isinstance(scorer_type, str) or scorer_type not in _SCORER_TYPES:
        findings.append(_finding("invalid_scorer_type", "scorer_type is unsupported"))
    scope = metadata.get("scope")
    if not isinstance(scope, str) or scope not in _SCOPES:
        findings.append(_finding("invalid_scorer_scope", "scope is unsupported"))
    threshold = _number(metadata.get("pass_threshold"))
    if threshold is None or not 0 < threshold <= 1:
        findings.append(_finding("invalid_pass_threshold", "pass_threshold must be a number in (0, 1]"))
    if metadata.get("deterministic_checks_first") is not True:
        findings.append(_finding("deterministic_checks_first", "deterministic checks must run first"))
    findings.extend(_judge_findings(metadata, scorer_type))
    findings.extend(_probe_findings(metadata))
    return findings


def _valid_parameters(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"model", "temperature", "trial_count"}
        and _text(value.get("model"))
        and _number(value.get("temperature")) is not None
        and isinstance(value.get("trial_count"), int)
        and not isinstance(value.get("trial_count"), bool)
        and value["trial_count"] >= 1
    )


def _valid_rationale(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"required", "sampled_count"}
        and isinstance(value.get("required"), bool)
        and isinstance(value.get("sampled_count"), int)
        and not isinstance(value.get("sampled_count"), bool)
        and value["sampled_count"] >= 0
    )


def _judge_findings(metadata: Mapping[object, object], scorer_type: object) -> list[ScenarioQualityFinding]:
    judge = isinstance(scorer_type, str) and scorer_type in _JUDGE_TYPES
    findings: list[ScenarioQualityFinding] = []
    parameters = metadata.get("parameters")
    if (parameters is not None or judge) and not _valid_parameters(parameters):
        findings.append(
            _finding("judge_parameters_versioned", "judge parameters need model, temperature, and trial_count")
        )
    rationale = metadata.get("rationale_audit")
    if (rationale is not None or judge) and not _valid_rationale(rationale):
        findings.append(_finding("invalid_rationale_audit", "rationale audit has invalid fields or types"))
    if judge and (not isinstance(rationale, Mapping) or rationale.get("required") is not True):
        findings.append(_finding("rationale_audit_required", "judge rationale audit must be required"))
    if judge and (
        not isinstance(rationale, Mapping)
        or not isinstance(rationale.get("sampled_count"), int)
        or isinstance(rationale.get("sampled_count"), bool)
        or rationale["sampled_count"] < 3
    ):
        findings.append(_finding("rationale_audit_sampled", "judge rationale audit needs at least three samples"))
    return findings


def _probe_findings(metadata: Mapping[object, object]) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    segments = metadata.get("segmentation_fields")
    if (
        not isinstance(segments, list)
        or not all(_text(item) and item in _SEGMENTS for item in segments)
        or (set(segments) != _SEGMENTS)
    ):
        findings.append(_finding("segmentation_fields_present", "category, claim_ids, and eval_modes are required"))
    cases = metadata.get("calibration_cases")
    if not isinstance(cases, list) or not cases:
        return [*findings, _finding("calibration_cases_present", "calibration cases are required")]
    probe_types: set[str] = set()
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping) or set(case) - {
            "id",
            "probe_type",
            "expected_score",
            "expected_label",
            "expected_direction",
        }:
            findings.append(_finding("invalid_calibration_case", "calibration case has unsupported structure"))
            continue
        probe_type = case.get("probe_type")
        case_id = case.get("id")
        if isinstance(case_id, str) and case_id.strip():
            normalized_id = case_id.strip()
            if normalized_id in case_ids:
                findings.append(_finding("duplicate_calibration_case", "calibration case ids must be unique"))
            case_ids.add(normalized_id)
        if not _text(case_id) or not isinstance(probe_type, str) or probe_type not in _PROBES:
            findings.append(
                _finding("invalid_calibration_case", "calibration case needs an id and supported probe_type")
            )
        else:
            probe_types.add(probe_type)
        if not _expected_outcome(case, _number(metadata.get("pass_threshold"))):
            findings.append(
                _finding("calibration_expected_outcomes", "each calibration case needs a typed expected outcome")
            )
    if probe_types != _PROBES:
        findings.append(_finding("calibration_probe_coverage", "all six scorer calibration probes are required"))
    bias = metadata.get("bias_probes", [])
    bias_values = bias if isinstance(bias, list) else []
    if not isinstance(bias, list) or any(
        not isinstance(item, str) or item not in {"verbosity_bias", "short_correct_vs_verbose_wrong"}
        for item in bias_values
    ):
        findings.append(_finding("invalid_bias_probes", "bias_probes contains an unsupported entry"))
    if "short_correct_vs_verbose_wrong" not in probe_types and "verbosity_bias" not in bias_values:
        findings.append(_finding("verbosity_bias_probe_present", "a verbosity-bias probe is required"))
    return findings


def _expected_outcome(case: Mapping[object, object], threshold: float | None) -> bool:
    score = case.get("expected_score")
    score_number = _number(score)
    label = case.get("expected_label")
    direction = case.get("expected_direction")
    if score is not None and (score_number is None or not 0 <= score_number <= 1):
        return False
    if label is not None and (not isinstance(label, str) or label not in {"pass", "fail"}):
        return False
    if direction is not None and direction != "short_correct_wins":
        return False
    if (
        score_number is not None
        and label is not None
        and threshold is not None
        and label != ("pass" if score_number >= threshold else "fail")
    ):
        return False
    return score is not None or label is not None or direction is not None


def assess_scorer_quality(package_root: Path, *, source_revision: str) -> ScorerQualityReceipt:
    """Assess declarations without claiming the held-out calibration ran here."""
    validation = validate_skill_package(package_root, source_revision=source_revision)
    findings = [
        ScenarioQualityFinding(code=item.code, message=item.message, evidence_refs=item.evidence_refs)
        for item in validation.findings
        if item.severity == "blocker"
    ]
    metadata: Mapping[object, object] = {}
    if validation.status == "pass":
        try:
            raw = read_candidate_artifact(package_root, validation, _EVALS)
            payload = yaml.load(raw.decode("utf-8"), Loader=_ClosedLoader)
            if isinstance(payload, Mapping):
                if set(payload) - _TOP_FIELDS:
                    findings.append(_finding("unsupported_evals_field", "evals.yaml has unsupported fields"))
                if payload.get("schema_version") != "2.0":
                    findings.append(_finding("unsupported_evals_schema", "evals.yaml schema_version must be 2.0"))
                if validation.candidate is not None and payload.get("skill_name") != validation.candidate.package_id:
                    findings.append(_finding("skill_name_mismatch", "evals.yaml skill_name must match the candidate"))
            if not isinstance(payload, Mapping) or not isinstance(payload.get("scorer_quality"), Mapping):
                findings.append(
                    _finding("scorer_quality_declared", "references/evals.yaml must declare scorer_quality")
                )
            else:
                metadata = payload["scorer_quality"]
                findings.extend(_strict_metadata(metadata))
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            findings.append(_finding("invalid_evals_yaml", f"cannot safely load scorer metadata: {type(exc).__name__}"))
    cases = metadata.get("calibration_cases")
    return ScorerQualityReceipt(
        candidate=validation.candidate,
        status="blocked" if findings else "pass",
        scorer_id=str(metadata.get("scorer_id") or ""),
        scorer_version_or_digest=str(metadata.get("scorer_version_or_digest") or ""),
        pass_threshold=(
            threshold
            if (threshold := _number(metadata.get("pass_threshold"))) is not None and 0 < threshold <= 1
            else None
        ),
        calibration_probe_count=len(cases) if isinstance(cases, list) else 0,
        findings=tuple(findings),
    )
