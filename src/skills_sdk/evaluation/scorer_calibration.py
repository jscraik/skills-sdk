"""Read-only assessment of candidate-bound held-out scorer artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

from skills_sdk.evaluation.scorer_artifacts import read_candidate_artifact
from skills_sdk.models.scenario_quality import ScenarioQualityFinding
from skills_sdk.models.scorer_quality import (
    ScorerCalibrationAppliedPolicy,
    ScorerCalibrationMetrics,
    ScorerCalibrationRates,
    ScorerCalibrationReceipt,
    ScorerJudgeParameters,
)
from skills_sdk.models.validation import SkillPackageValidation
from skills_sdk.validation import validate_skill_package

_BUNDLE = "references/scorer-calibration/"
_MANIFEST = _BUNDLE + "manifest.json"
_LIMITS = {
    "minimum_examples": (1, 1),
    "minimum_true_positives": (1, 1),
    "minimum_true_negatives": (1, 1),
    "max_false_positives": (0, 0),
    "max_false_negatives": (0, 0),
}
_MANIFEST_FIELDS = {
    "schema_version",
    "scorer_id",
    "scorer_version_or_digest",
    "prompt_version",
    "threshold",
    "split",
    "parameters",
    "examples_path",
    "raw_artifacts_dir",
    *_LIMITS,
}
_PARAMETER_FIELDS = {"model", "temperature", "trial_count"}


def _finding(code: str, message: str, path: str = _MANIFEST) -> ScenarioQualityFinding:
    return ScenarioQualityFinding(code=code, message=message, evidence_refs=(path,))


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


def _json_object(payload: bytes) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_member")
            result[key] = value
        return result

    try:
        loaded = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    except RecursionError as exc:
        raise ValueError("json_nesting_exceeded") from exc
    if not isinstance(loaded, dict):
        raise ValueError("json_root_not_object")
    return loaded


def _bundle_path(value: object, default: str) -> str:
    raw = default if value is None else value
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("invalid_bundle_path")
    path = Path(raw)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise ValueError("invalid_bundle_path")
    return _BUNDLE + path.as_posix()


def _manifest_findings(manifest: Mapping[str, object]) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    if set(manifest) - _MANIFEST_FIELDS:
        findings.append(_finding("unknown_calibration_bundle_field", "calibration bundle has unsupported fields"))
    if manifest.get("schema_version") != "skills-sdk.scorer-calibration-bundle.v1":
        findings.append(_finding("calibration_bundle_schema_version", "unsupported calibration bundle schema"))
    if manifest.get("split") != "held_out":
        findings.append(_finding("calibration_split_held_out", "calibration examples must be held out"))
    for field in ("scorer_id", "scorer_version_or_digest", "prompt_version"):
        if not _text(manifest.get(field)):
            findings.append(_finding(f"{field}_present", f"{field} must be non-empty text"))
    threshold = _number(manifest.get("threshold"))
    if threshold is None or not 0 < threshold <= 1:
        findings.append(_finding("threshold_valid", "threshold must be a number in (0, 1]"))
    parameters = manifest.get("parameters")
    if isinstance(parameters, Mapping) and set(parameters) != _PARAMETER_FIELDS:
        findings.append(
            _finding(
                "judge_parameters_fields", "judge parameters must contain exactly model, temperature, and trial_count"
            )
        )
    if (
        not isinstance(parameters, Mapping)
        or not _text(parameters.get("model"))
        or (
            _number(parameters.get("temperature")) is None
            or not isinstance(parameters.get("trial_count"), int)
            or isinstance(parameters.get("trial_count"), bool)
            or parameters["trial_count"] < 1
        )
    ):
        findings.append(_finding("judge_parameters_present", "model, temperature, and trial_count are required"))
    for field, (default, minimum) in _LIMITS.items():
        raw = manifest.get(field, default)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < minimum:
            findings.append(_finding(field, f"{field} must be an integer at least {minimum}"))
    return findings


def _read_examples(
    root: Path, validation: SkillPackageValidation, path: str
) -> tuple[list[dict[str, object]], list[ScenarioQualityFinding]]:
    rows: list[dict[str, object]] = []
    findings: list[ScenarioQualityFinding] = []
    try:
        payload = read_candidate_artifact(root, validation, path).decode("utf-8")
        for line_number, line in enumerate(payload.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(_json_object(line.encode("utf-8")))
            except (UnicodeError, ValueError) as exc:
                findings.append(
                    _finding("calibration_examples_parse", f"line {line_number}: {type(exc).__name__}", path)
                )
                break
    except (OSError, UnicodeError, ValueError) as exc:
        findings.append(_finding("calibration_examples_parse", f"cannot load examples: {type(exc).__name__}", path))
    return rows, findings


def _row_findings(row: Mapping[str, object], path: str) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    if not _text(row.get("id")) or not _text(row.get("probe_type")) or not _text(row.get("raw_artifact")):
        findings.append(_finding("calibration_example_shape", "example needs id, probe_type, and raw_artifact", path))
    expected = row.get("expected_label")
    predicted = row.get("predicted_label")
    if (
        not isinstance(expected, str)
        or expected not in {"pass", "fail"}
        or (not isinstance(predicted, str) or predicted not in {"pass", "fail"})
    ):
        findings.append(_finding("calibration_example_shape", "example labels must be pass or fail", path))
    score = _number(row.get("score"))
    if score is None or not 0 <= score <= 1:
        findings.append(_finding("calibration_example_shape", "example score must be in [0, 1]", path))
    return findings


def _matrix(rows: list[dict[str, object]]) -> ScorerCalibrationMetrics:
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for row in rows:
        expected = row.get("expected_label")
        predicted = row.get("predicted_label")
        if not isinstance(expected, str) or not isinstance(predicted, str):
            continue
        key = {
            ("pass", "pass"): "tp",
            ("fail", "fail"): "tn",
            ("fail", "pass"): "fp",
            ("pass", "fail"): "fn",
        }.get((expected, predicted))
        if key is not None:
            counts[key] += 1
    return ScorerCalibrationMetrics(**counts)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _metrics(matrix: ScorerCalibrationMetrics) -> ScorerCalibrationRates:
    return ScorerCalibrationRates(
        tpr=_ratio(matrix.tp, matrix.tp + matrix.fn),
        tnr=_ratio(matrix.tn, matrix.tn + matrix.fp),
        precision=_ratio(matrix.tp, matrix.tp + matrix.fp),
        accuracy=_ratio(matrix.tp + matrix.tn, matrix.tp + matrix.tn + matrix.fp + matrix.fn),
    )


def _duplicate_findings(rows: list[dict[str, object]], examples_path: str) -> list[ScenarioQualityFinding]:
    identifiers = [value.strip() for row in rows if isinstance((value := row.get("id")), str) and value.strip()]
    raw_paths = [row.get("raw_artifact") for row in rows if _text(row.get("raw_artifact"))]
    if len(identifiers) != len(set(identifiers)) or len(raw_paths) != len(set(raw_paths)):
        return [
            _finding("duplicate_calibration_example", "held-out ids and raw artifacts must be unique", examples_path)
        ]
    return []


def _artifact_findings(
    root: Path,
    validation: SkillPackageValidation,
    rows: list[dict[str, object]],
    manifest: Mapping[str, object],
    examples_path: str,
    raw_dir: str,
) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    threshold = _number(manifest.get("threshold"))
    for row in rows:
        findings.extend(_row_findings(row, examples_path))
        score = _number(row.get("score"))
        if (
            threshold is not None
            and score is not None
            and (row.get("predicted_label") != ("pass" if score >= threshold else "fail"))
        ):
            findings.append(
                _finding("score_threshold_consistent", "prediction conflicts with threshold", examples_path)
            )
        try:
            path = _bundle_path(row.get("raw_artifact"), "")
            if not path.startswith(raw_dir + "/"):
                raise ValueError("raw_artifact_outside_declared_dir")
            raw = _json_object(read_candidate_artifact(root, validation, path))
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append(
                _finding("raw_artifacts_present", f"raw artifact unavailable: {type(exc).__name__}", examples_path)
            )
            continue
        if (
            _number(raw.get("score")) is None
            or any(raw.get(field) != row.get(field) for field in ("id", "predicted_label", "score"))
            or (raw.get("scorer_id") != manifest.get("scorer_id"))
        ):
            findings.append(_finding("raw_artifacts_match_examples", "raw artifact does not match example", path))
    return findings


def _coverage_findings(
    manifest: Mapping[str, object], rows: list[dict[str, object]], matrix: ScorerCalibrationMetrics
) -> list[ScenarioQualityFinding]:
    findings: list[ScenarioQualityFinding] = []
    observed = {
        "minimum_examples": len(rows),
        "minimum_true_positives": matrix.tp,
        "minimum_true_negatives": matrix.tn,
        "max_false_positives": matrix.fp,
        "max_false_negatives": matrix.fn,
    }
    codes = {
        "minimum_examples": "held_out_example_count",
        "minimum_true_positives": "true_positive_coverage",
        "minimum_true_negatives": "true_negative_coverage",
        "max_false_positives": "false_positive_limit",
        "max_false_negatives": "false_negative_limit",
    }
    for key, (default, _) in _LIMITS.items():
        limit = manifest.get(key, default)
        if not isinstance(limit, int) or isinstance(limit, bool):
            continue
        failing = observed[key] > limit if key.startswith("max_") else observed[key] < limit
        if failing:
            findings.append(_finding(codes[key], f"{key} limit is not met"))
    return findings


def _applied_policy(manifest: Mapping[str, object]) -> ScorerCalibrationAppliedPolicy | None:
    threshold = _number(manifest.get("threshold"))
    if threshold is None or not 0 < threshold <= 1:
        return None
    limits: dict[str, int] = {}
    for field, (default, minimum) in _LIMITS.items():
        value = manifest.get(field, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            return None
        limits[field] = value
    return ScorerCalibrationAppliedPolicy(threshold=threshold, **limits)


def _parameters(manifest: Mapping[str, object]) -> ScorerJudgeParameters | None:
    raw = manifest.get("parameters")
    if not isinstance(raw, Mapping) or set(raw) != _PARAMETER_FIELDS:
        return None
    model = raw.get("model")
    temperature = _number(raw.get("temperature"))
    trial_count = raw.get("trial_count")
    if (
        not isinstance(model, str)
        or not model.strip()
        or temperature is None
        or not isinstance(trial_count, int)
        or (isinstance(trial_count, bool) or trial_count < 1)
    ):
        return None
    return ScorerJudgeParameters(model=model, temperature=temperature, trial_count=trial_count)


def assess_scorer_calibration(package_root: Path, *, source_revision: str) -> ScorerCalibrationReceipt:
    """Assess supplied held-out artifacts; this function never executes a judge."""
    validation = validate_skill_package(package_root, source_revision=source_revision)
    findings = [
        ScenarioQualityFinding(code=item.code, message=item.message, evidence_refs=item.evidence_refs)
        for item in validation.findings
        if item.severity == "blocker"
    ]
    manifest: dict[str, object] = {}
    rows: list[dict[str, object]] = []
    if validation.status == "pass":
        try:
            manifest = _json_object(read_candidate_artifact(package_root, validation, _MANIFEST))
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append(_finding("calibration_bundle_parse", f"cannot load bundle: {type(exc).__name__}"))
        findings.extend(_manifest_findings(manifest))
        try:
            examples_path = _bundle_path(manifest.get("examples_path"), "examples.jsonl")
            raw_dir = _bundle_path(manifest.get("raw_artifacts_dir"), "raw")
            rows, parse_findings = _read_examples(package_root, validation, examples_path)
            findings.extend(parse_findings)
            duplicates = _duplicate_findings(rows, examples_path)
            findings.extend(duplicates)
            if not duplicates:
                findings.extend(_artifact_findings(package_root, validation, rows, manifest, examples_path, raw_dir))
        except ValueError:
            findings.append(_finding("calibration_examples_parse", "examples path is unsafe"))
    matrix = _matrix(rows)
    findings.extend(_coverage_findings(manifest, rows, matrix))
    if validation.status == "pass":
        from skills_sdk.evaluation.scorer_quality import assess_scorer_quality

        declared = assess_scorer_quality(package_root, source_revision=source_revision)
        if (
            declared.status != "pass"
            or declared.candidate != validation.candidate
            or (
                manifest.get("scorer_id") != declared.scorer_id
                or manifest.get("scorer_version_or_digest") != declared.scorer_version_or_digest
                or _number(manifest.get("threshold")) != declared.pass_threshold
            )
        ):
            findings.append(
                _finding("scorer_identity_mismatch", "held-out bundle must match valid scorer declarations")
            )
    return ScorerCalibrationReceipt(
        candidate=validation.candidate,
        status="blocked" if findings else "pass",
        scorer_id=str(manifest.get("scorer_id") or ""),
        scorer_version_or_digest=str(manifest.get("scorer_version_or_digest") or ""),
        prompt_version=str(manifest.get("prompt_version") or ""),
        parameters=_parameters(manifest),
        example_count=len(rows),
        effective_policy=_applied_policy(manifest),
        confusion_matrix=matrix,
        metrics=_metrics(matrix),
        findings=tuple(findings),
    )
