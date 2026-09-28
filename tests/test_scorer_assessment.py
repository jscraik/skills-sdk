"""Public scorer assessment: accepted, rejected, and corrected input."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import assess_scorer_calibration, assess_scorer_quality
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.scenario_quality import ScenarioQualityFinding
from skills_sdk.models.scorer_quality import (
    ScorerCalibrationAppliedPolicy,
    ScorerCalibrationMetrics,
    ScorerCalibrationRates,
    ScorerCalibrationReceipt,
    ScorerJudgeParameters,
    ScorerQualityReceipt,
)
from skills_sdk.validation import validate_skill_package

_PROBES = (
    "obvious_correct",
    "obvious_wrong",
    "short_correct_vs_verbose_wrong",
    "rubric_copying_rejected",
    "skill_name_mention_not_enough",
    "evidence_lane_overclaim_rejected",
)
_REVISION_1 = "1" * 40
_REVISION_2 = "2" * 40


def _package(root: Path) -> Path:
    package = root / "synthetic-skill"
    references = package / "references"
    references.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: synthetic-skill\ndescription: Synthetic scorer assessment fixture.\n---\n# Synthetic Skill\n",
        encoding="utf-8",
    )
    metadata = {
        "schema_version": "skills-sdk.scorer-quality.v1",
        "scorer_id": "synthetic-skill.release-scorer",
        "scorer_type": "deterministic",
        "scope": "suite",
        "scorer_version_or_digest": "local-v1",
        "pass_threshold": 0.9,
        "deterministic_checks_first": True,
        "segmentation_fields": ["category", "claim_ids", "eval_modes"],
        "calibration_cases": [
            {"id": probe, "probe_type": probe, "expected_label": "pass" if probe == "obvious_correct" else "fail"}
            for probe in _PROBES
        ],
    }
    _evals(package, metadata)
    _bundle(package)
    return package


def _evals(package: Path, metadata: dict[str, object]) -> None:
    import yaml

    payload = {"schema_version": "2.0", "skill_name": "synthetic-skill", "scorer_quality": metadata, "cases": []}
    (package / "references" / "evals.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _bundle(package: Path, *, false_positive: bool = False) -> None:
    bundle = package / "references" / "scorer-calibration"
    raw_dir = bundle / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "skills-sdk.scorer-calibration-bundle.v1",
        "scorer_id": "synthetic-skill.release-scorer",
        "scorer_version_or_digest": "local-v1",
        "prompt_version": "local-v1",
        "threshold": 0.9,
        "split": "held_out",
        "parameters": {"model": "local-fixture", "temperature": 0, "trial_count": 1},
        "examples_path": "examples.jsonl",
        "raw_artifacts_dir": "raw",
        "minimum_examples": 2,
        "minimum_true_positives": 1,
        "minimum_true_negatives": 1,
        "max_false_positives": 0,
        "max_false_negatives": 0,
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        {
            "id": "correct",
            "probe_type": "obvious_correct",
            "expected_label": "pass",
            "predicted_label": "pass",
            "score": 1.0,
            "raw_artifact": "raw/correct.json",
        },
        {
            "id": "wrong",
            "probe_type": "obvious_wrong",
            "expected_label": "fail",
            "predicted_label": "pass" if false_positive else "fail",
            "score": 0.95 if false_positive else 0.1,
            "raw_artifact": "raw/wrong.json",
        },
    ]
    (bundle / "examples.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    for row in rows:
        raw = {key: row[key] for key in ("id", "predicted_label", "score")}
        raw["scorer_id"] = manifest["scorer_id"]
        (raw_dir / f"{row['id']}.json").write_text(json.dumps(raw), encoding="utf-8")


def _codes(receipt: ScorerQualityReceipt | ScorerCalibrationReceipt) -> set[str]:
    return {finding.code for finding in receipt.findings}


def test_accepted_candidate_bound_quality_and_held_out_artifacts(tmp_path: Path) -> None:
    package = _package(tmp_path)
    quality = assess_scorer_quality(package, source_revision=_REVISION_1)
    calibration = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert quality.status == calibration.status == "pass"
    assert quality.candidate == calibration.candidate
    assert quality.calibration_probe_count == 6
    assert quality.pass_threshold == 0.9
    assert calibration.confusion_matrix.model_dump() == {"tp": 1, "tn": 1, "fp": 0, "fn": 0}
    assert calibration.metrics.model_dump() == {"tpr": 1.0, "tnr": 1.0, "precision": 1.0, "accuracy": 1.0}
    assert calibration.parameters is not None and calibration.parameters.trial_count == 1
    assert not quality.execution_performed and not calibration.execution_performed


def test_false_positive_rejected_then_corrected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    _bundle(package, false_positive=True)
    rejected = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert rejected.status == "blocked"
    assert "false_positive_limit" in _codes(rejected)
    _bundle(package)
    recovered = assess_scorer_calibration(package, source_revision=_REVISION_2)
    assert recovered.status == "pass"
    assert recovered.candidate != rejected.candidate


@pytest.mark.parametrize("bad_field", ["unexpected", "pass_threshold"])
def test_invalid_quality_metadata_rejected_then_corrected(tmp_path: Path, bad_field: str) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    payload["scorer_quality"][bad_field] = "0.9" if bad_field == "pass_threshold" else "bad"
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    rejected = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert rejected.status == "blocked"
    payload["scorer_quality"].pop("unexpected", None)
    payload["scorer_quality"]["pass_threshold"] = 0.9
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert assess_scorer_quality(package, source_revision=_REVISION_2).status == "pass"


def test_cli_routes_are_prompt_free_and_candidate_bound(tmp_path: Path) -> None:
    package = _package(tmp_path)
    for name in ("scorer-quality", "scorer-calibration"):
        process = subprocess.run(
            [
                str(Path(sys.executable).with_name("skills-sdk")),
                "eval",
                name,
                str(package),
                "--source-revision",
                _REVISION_1,
                "--json",
                "--robot",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": ""},
        )
        assert process.returncode == 0, process.stderr
        payload = json.loads(process.stdout)
        assert payload["status"] == "pass"
        assert payload["candidate"]["package_id"] == "synthetic-skill"


def test_judge_parameters_rationale_and_schema_validation(tmp_path: Path) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    payload["scorer_quality"]["scorer_type"] = "hybrid"
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert {"judge_parameters_versioned", "rationale_audit_required"} <= _codes(blocked)
    payload["scorer_quality"]["parameters"] = {"model": "local-fixture", "temperature": 0, "trial_count": 1}
    payload["scorer_quality"]["rationale_audit"] = {"required": True, "sampled_count": 3}
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    recovered = assess_scorer_quality(package, source_revision=_REVISION_2)
    assert recovered.status == "pass"
    registry = SchemaRegistry()
    registry.validate("scorer-quality.v1", recovered.model_dump(mode="json"))


def test_present_optional_deterministic_judge_fields_still_validate(tmp_path: Path) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    payload["scorer_quality"]["parameters"] = {"model": "local", "temperature": "0", "trial_count": 1}
    payload["scorer_quality"]["rationale_audit"] = {"required": False, "sampled_count": 0, "extra": True}
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert {"judge_parameters_versioned", "invalid_rationale_audit"} <= _codes(blocked)


def test_missing_raw_artifact_and_unsafe_example_path_block(tmp_path: Path) -> None:
    package = _package(tmp_path)
    raw = package / "references" / "scorer-calibration" / "raw" / "wrong.json"
    raw.unlink()
    missing = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert "raw_artifacts_present" in _codes(missing)
    _bundle(package)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["examples_path"] = "../outside.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unsafe = assess_scorer_calibration(package, source_revision=_REVISION_2)
    assert "calibration_examples_parse" in _codes(unsafe)


def test_symlinked_manifest_blocks_without_following_it(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(outside)
    receipt = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert receipt.status == "blocked"
    assert "symlink_not_allowed" in _codes(receipt)


def test_malformed_example_and_candidate_recovery(tmp_path: Path) -> None:
    package = _package(tmp_path)
    examples = package / "references" / "scorer-calibration" / "examples.jsonl"
    examples.write_text('{"id": "broken"\n', encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert "calibration_examples_parse" in _codes(blocked)
    _bundle(package)
    recovered = assess_scorer_calibration(package, source_revision=_REVISION_2)
    assert recovered.status == "pass"
    SchemaRegistry().validate("scorer-calibration.v1", recovered.model_dump(mode="json"))


def test_duplicate_held_out_example_and_forged_pass_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    accepted = assess_scorer_calibration(package, source_revision=_REVISION_1)
    payload = accepted.model_dump(mode="json")
    payload["confusion_matrix"]["fp"] = 1
    with pytest.raises(ValidationError):
        ScorerCalibrationReceipt.model_validate(payload)
    examples = package / "references" / "scorer-calibration" / "examples.jsonl"
    rows = examples.read_text(encoding="utf-8").splitlines()
    examples.write_text("\n".join([*rows, rows[0]]) + "\n", encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_2)
    assert "duplicate_calibration_example" in _codes(blocked)


def test_whitespace_equivalent_held_out_ids_block_then_recover(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bundle = package / "references" / "scorer-calibration"
    examples = bundle / "examples.jsonl"
    rows = [json.loads(line) for line in examples.read_text(encoding="utf-8").splitlines()]
    duplicate = {**rows[0], "id": f" {rows[0]['id']} ", "raw_artifact": "raw/other.json"}
    raw = {key: duplicate[key] for key in ("id", "predicted_label", "score")}
    raw["scorer_id"] = "synthetic-skill.release-scorer"
    (bundle / "raw" / "other.json").write_text(json.dumps(raw), encoding="utf-8")
    examples.write_text("\n".join(json.dumps(row) for row in [*rows, duplicate]) + "\n", encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "duplicate_calibration_example" in _codes(blocked)
    duplicate["id"] = "distinct"
    raw["id"] = "distinct"
    (bundle / "raw" / "other.json").write_text(json.dumps(raw), encoding="utf-8")
    examples.write_text("\n".join(json.dumps(row) for row in [*rows, duplicate]) + "\n", encoding="utf-8")
    assert assess_scorer_calibration(package, source_revision=_REVISION_2).status == "pass"


def test_artifact_path_alias_blocks_before_raw_reads_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    bundle = package / "references" / "scorer-calibration"
    examples = bundle / "examples.jsonl"
    rows = [json.loads(line) for line in examples.read_text(encoding="utf-8").splitlines()]
    alias = {**rows[0], "id": "other", "raw_artifact": "raw//correct.json"}
    examples.write_text("\n".join(json.dumps(row) for row in [*rows, alias]) + "\n", encoding="utf-8")

    from skills_sdk.evaluation import scorer_calibration

    original = scorer_calibration.read_candidate_artifact
    raw_reads: list[str] = []

    def tracked(root: Path, validation: object, path: str, **kwargs: object) -> bytes:
        if "/raw/" in path:
            raw_reads.append(path)
        return original(root, validation, path, **kwargs)

    monkeypatch.setattr(scorer_calibration, "read_candidate_artifact", tracked)
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "duplicate_calibration_example" in _codes(blocked)
    assert not raw_reads
    _bundle(package)
    assert assess_scorer_calibration(package, source_revision=_REVISION_2).status == "pass"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ScorerCalibrationMetrics, {"tp": True, "tn": 1, "fp": 0, "fn": 0}),
        (
            ScorerCalibrationAppliedPolicy,
            {
                "threshold": 0.9,
                "minimum_examples": True,
                "minimum_true_positives": 1,
                "minimum_true_negatives": 1,
                "max_false_positives": 0,
                "max_false_negatives": 0,
            },
        ),
        (ScorerJudgeParameters, {"model": "local", "temperature": 0, "trial_count": True}),
        (ScorerCalibrationRates, {"tpr": True}),
        (
            ScorerQualityReceipt,
            {
                "status": "blocked",
                "findings": [{"code": "fixture", "message": "fixture"}],
                "calibration_probe_count": True,
            },
        ),
        (
            ScorerCalibrationReceipt,
            {"status": "blocked", "findings": [{"code": "fixture", "message": "fixture"}], "example_count": True},
        ),
    ],
)
def test_public_scorer_numeric_fields_reject_boolean(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("confusion_matrix", ScorerCalibrationMetrics.model_construct(tp=True, tn=True, fp=False, fn=False)),
        (
            "effective_policy",
            ScorerCalibrationAppliedPolicy.model_construct(
                threshold=0.9,
                minimum_examples=True,
                minimum_true_positives=1,
                minimum_true_negatives=1,
                max_false_positives=0,
                max_false_negatives=0,
            ),
        ),
        ("parameters", ScorerJudgeParameters.model_construct(model="local", temperature=0, trial_count=True)),
        ("metrics", ScorerCalibrationRates.model_construct(tpr=True, tnr=1.0, precision=1.0, accuracy=1.0)),
    ],
)
def test_forged_nested_calibration_model_cannot_pass(tmp_path: Path, field: str, forged: object) -> None:
    package = _package(tmp_path)
    accepted = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert accepted.status == "pass"
    payload = accepted.model_dump(mode="json")
    payload[field] = forged
    with pytest.raises(ValidationError):
        ScorerCalibrationReceipt.model_validate(payload)
    assert ScorerCalibrationReceipt.model_validate(accepted.model_dump(mode="json")) == accepted


@pytest.mark.parametrize("assess", [assess_scorer_quality, assess_scorer_calibration])
def test_forged_candidate_identity_cannot_pass_scorer_receipt(tmp_path: Path, assess: object) -> None:
    accepted = assess(_package(tmp_path), source_revision=_REVISION_1)
    assert accepted.status == "pass"
    payload = accepted.model_dump(mode="json")
    payload["candidate"] = PackageCandidateIdentity.model_construct(
        package_id="BAD", source_revision="x", content_sha256="y"
    )
    with pytest.raises(ValidationError):
        type(accepted).model_validate(payload)
    assert type(accepted).model_validate(accepted.model_dump(mode="json")) == accepted


@pytest.mark.parametrize("receipt_type", [ScorerQualityReceipt, ScorerCalibrationReceipt])
def test_forged_finding_cannot_enter_blocked_scorer_receipt(receipt_type: type) -> None:
    valid = ScenarioQualityFinding(code="fixture", message="fixture", evidence_refs=("references/evals.yaml",))
    assert receipt_type(status="blocked", findings=(valid,)).status == "blocked"
    for forged in (
        ScenarioQualityFinding.model_construct(code="BAD", message="fixture"),
        ScenarioQualityFinding.model_construct(code="fixture", message=""),
        ScenarioQualityFinding.model_construct(
            code="fixture", message="fixture", evidence_refs=(str(Path(Path.cwd().anchor, "raw.json")),)
        ),
    ):
        with pytest.raises(ValidationError):
            receipt_type(status="blocked", findings=(forged,))


@pytest.mark.parametrize(
    ("location", "constant", "expected_code"),
    [
        ("manifest.json", "NaN", "calibration_bundle_parse"),
        ("examples.jsonl", "Infinity", "calibration_examples_parse"),
        ("raw/correct.json", "-Infinity", "raw_artifacts_present"),
    ],
)
def test_nonstandard_json_constant_blocks_then_recovers(
    tmp_path: Path, location: str, constant: str, expected_code: str
) -> None:
    package = _package(tmp_path)
    bundle = package / "references" / "scorer-calibration"
    path = bundle / location
    text = path.read_text(encoding="utf-8")
    if location == "examples.jsonl":
        first, rest = text.split("\n", 1)
        text = first[:-1] + f', "supplemental": {constant}}}' + "\n" + rest
    else:
        text = text[:-1] + f', "supplemental": {constant}}}'
    path.write_text(text, encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert expected_code in _codes(blocked)
    _bundle(package)
    assert assess_scorer_calibration(package, source_revision=_REVISION_2).status == "pass"


def test_raw_artifact_reads_share_one_candidate_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    from skills_sdk.evaluation import scorer_calibration

    original_index = scorer_calibration.index_candidate_files
    original_read = scorer_calibration.read_candidate_artifact
    indexes: list[object] = []
    raw_indexes: list[object] = []

    def tracked_index(validation: object) -> object:
        index = original_index(validation)
        indexes.append(index)
        return index

    def tracked_read(root: Path, validation: object, path: str, **kwargs: object) -> bytes:
        if "/raw/" in path:
            raw_indexes.append(kwargs.get("file_index"))
        return original_read(root, validation, path, **kwargs)

    monkeypatch.setattr(scorer_calibration, "index_candidate_files", tracked_index)
    monkeypatch.setattr(scorer_calibration, "read_candidate_artifact", tracked_read)
    assert assess_scorer_calibration(package, source_revision=_REVISION_1).status == "pass"
    assert len(indexes) == 1
    assert len(raw_indexes) == 2
    assert all(index is indexes[0] for index in raw_indexes)


def test_bundle_scorer_identity_must_match_candidate_declaration(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scorer_id"] = "different-scorer"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert "scorer_identity_mismatch" in _codes(blocked)


def test_bundle_threshold_must_match_candidate_declaration(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["threshold"] = 0.99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "scorer_identity_mismatch" in _codes(blocked)


def test_duplicate_declared_probe_ids_block(tmp_path: Path) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    payload["scorer_quality"]["calibration_cases"][1]["id"] = "obvious_correct"
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "duplicate_calibration_case" in _codes(blocked)


@pytest.mark.parametrize("target", ["manifest", "examples", "raw"])
def test_deeply_nested_json_returns_typed_blocker(tmp_path: Path, target: str) -> None:
    package = _package(tmp_path)
    bundle = package / "references" / "scorer-calibration"
    nested = "[" * 20000 + "0" + "]" * 20000
    if target == "manifest":
        (bundle / "manifest.json").write_text('{"extra":' + nested + "}", encoding="utf-8")
    elif target == "examples":
        (bundle / "examples.jsonl").write_text('{"extra":' + nested + "}\n", encoding="utf-8")
    else:
        (bundle / "raw" / "correct.json").write_text('{"extra":' + nested + "}", encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    expected = {
        "manifest": "calibration_bundle_parse",
        "examples": "calibration_examples_parse",
        "raw": "raw_artifacts_present",
    }
    assert expected[target] in _codes(blocked)


def test_duplicate_rows_do_not_reread_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    examples = package / "references" / "scorer-calibration" / "examples.jsonl"
    rows = examples.read_text(encoding="utf-8").splitlines()
    examples.write_text("\n".join([*rows, *([rows[0]] * 1000)]) + "\n", encoding="utf-8")

    from skills_sdk.evaluation import scorer_calibration

    original = scorer_calibration.read_candidate_artifact
    raw_reads: list[str] = []

    def tracked(root: Path, validation: object, path: str, **kwargs: object) -> bytes:
        if "/raw/" in path:
            raw_reads.append(path)
        return original(root, validation, path, **kwargs)

    monkeypatch.setattr(scorer_calibration, "read_candidate_artifact", tracked)
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert "duplicate_calibration_example" in _codes(blocked)
    assert not raw_reads


def test_boolean_raw_score_blocks(tmp_path: Path) -> None:
    package = _package(tmp_path)
    raw_path = package / "references" / "scorer-calibration" / "raw" / "correct.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["score"] = True
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "raw_artifacts_match_examples" in _codes(blocked)


def test_declared_expected_score_and_label_must_agree(tmp_path: Path) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    case = payload["scorer_quality"]["calibration_cases"][1]
    case["expected_score"] = 0.95
    case["expected_label"] = "fail"
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "calibration_expected_outcomes" in _codes(blocked)


def test_unknown_manifest_policy_field_blocks(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["minimum_true_positive"] = 20
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "unknown_calibration_bundle_field" in _codes(blocked)


def test_unknown_nested_judge_parameter_blocks_then_recovers(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "references" / "scorer-calibration" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parameters"]["temperatur"] = 0.5
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocked = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "judge_parameters_fields" in _codes(blocked)
    del manifest["parameters"]["temperatur"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    recovered = assess_scorer_calibration(package, source_revision=_REVISION_2)
    assert recovered.status == "pass"
    assert recovered.parameters is not None and recovered.parameters.temperature == 0


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), float("-inf")])
def test_public_judge_parameters_reject_nonfinite_temperature(temperature: float) -> None:
    with pytest.raises(ValidationError):
        ScorerJudgeParameters(model="local-fixture", temperature=temperature, trial_count=1)
    accepted = ScorerJudgeParameters(model="local-fixture", temperature=0, trial_count=1)
    assert ScorerJudgeParameters.model_validate_json(accepted.model_dump_json()) == accepted


@pytest.mark.parametrize(
    ("field", "invalid", "code"),
    [
        ("schema_version", "9.0", "unsupported_evals_schema"),
        ("skill_name", "wrong-skill", "skill_name_mismatch"),
    ],
)
def test_enclosing_evals_contract_blocks_then_recovers(tmp_path: Path, field: str, invalid: str, code: str) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    original = payload[field]
    payload[field] = invalid
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    calibration = assess_scorer_calibration(package, source_revision=_REVISION_1)
    assert blocked.status == calibration.status == "blocked"
    assert code in _codes(blocked)
    payload[field] = original
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert assess_scorer_quality(package, source_revision=_REVISION_2).status == "pass"


def test_normalized_duplicate_probe_ids_block_then_recover(tmp_path: Path) -> None:
    package = _package(tmp_path)
    import yaml

    evals_path = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    cases = payload["scorer_quality"]["calibration_cases"]
    cases[1]["id"] = f" {cases[0]['id']} "
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    blocked = assess_scorer_quality(package, source_revision=_REVISION_1)
    assert blocked.status == "blocked"
    assert "duplicate_calibration_case" in _codes(blocked)
    cases[1]["id"] = "distinct-probe"
    evals_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert assess_scorer_quality(package, source_revision=_REVISION_2).status == "pass"


def test_package_validation_evidence_refs_are_preserved(tmp_path: Path) -> None:
    package = _package(tmp_path)
    assets = package / "assets"
    assets.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (assets / "linked.txt").symlink_to(outside)
    source = validate_skill_package(package, source_revision=_REVISION_1)
    original = {(item.code, item.evidence_refs) for item in source.findings if item.severity == "blocker"}
    assert original
    for receipt in (
        assess_scorer_quality(package, source_revision=_REVISION_1),
        assess_scorer_calibration(package, source_revision=_REVISION_1),
    ):
        assert original <= {(item.code, item.evidence_refs) for item in receipt.findings}
