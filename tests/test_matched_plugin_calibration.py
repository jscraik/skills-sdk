"""Plugin bundles retain exact child/assertion calibration rather than aliasing it."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_matched_calibration import DimensionJudge, _dimensions
from test_matched_comparison import _plan
from test_selected_case_evaluation import REVISION, _prepared_request, _safety_for

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.evaluation.matched_calibration import execute_matched_calibration
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import load_selected_case
from skills_sdk.models.matched_plugin_calibration import (
    MatchedCalibrationTarget,
    MatchedVariantCalibrationBundle,
    _require_plugin_calibration_bundle,
)
from skills_sdk.models.observed_calibration import ObservedCalibrationPlan
from skills_sdk.models.plugin import PLUGIN_SCHEMA_URI
from skills_sdk.validation.plugin_package import validate_plugin_package


def _bundle(root: Path) -> tuple[object, object, object, tuple[object, ...]]:
    """Observe two distinct assertion targets for one real captured child."""
    (root / "skills").mkdir()
    (root / "plugin.json").write_text(json.dumps({"$schema": PLUGIN_SCHEMA_URI, "name": "calibration"}))
    observed, frames, events = _dimensions(root / "skills")
    rubric = _plan().rubric
    receipts = [asyncio.run(execute_matched_calibration(observed, rubric, frames))]
    definition = load_selected_case(
        root / "skills/simplify", source_revision=REVISION, case_id="edge-empty-diff", mode="release"
    )
    payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, payload)
    second = ObservedCalibrationPlan.model_validate(
        dict(observed.__dict__, assertion_contract_sha256=definition.assertion_contract_sha256)
    )
    changed_frames = []
    for index, frame in enumerate(frames):
        judge = DimensionJudge(frame.judge, 4.5 if index % 2 == 0 else 0.5, events)
        judge.definition, judge.request = definition, request
        changed_frames.append(
            replace(
                frame,
                definition=definition,
                request=request,
                inputs=SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
                judge=judge,
            )
        )
    receipts.append(asyncio.run(execute_matched_calibration(second, rubric, tuple(changed_frames))))
    assert all(receipt.status == "pass" for receipt in receipts)
    plugin = validate_plugin_package(root, source_revision=REVISION)
    assert plugin.status == "pass"
    targets = tuple(
        sorted(
            (
                MatchedCalibrationTarget(
                    skill_path="skills/simplify",
                    child_candidate=receipt.calibration.plan.candidate,
                    assertion_contract_sha256=receipt.calibration.plan.assertion_contract_sha256,
                    scorer=receipt.calibration.plan.scorer,
                    receipt=receipt,
                )
                for receipt in receipts
            ),
            key=lambda item: (item.skill_path, item.assertion_contract_sha256),
        )
    )
    bundle = MatchedVariantCalibrationBundle(
        plugin_candidate=plugin.candidate,
        mode_manifest_sha256=plugin.mode_manifest_sha256,
        judge=observed.judge,
        judge_parameters=observed.parameters,
        rubric=rubric,
        targets=targets,
    )
    lane = _plan().lanes[0].model_copy(update={"judge": observed.judge, "judge_parameters": observed.parameters})
    required = tuple((item.skill_path, item.assertion_contract_sha256, item.scorer) for item in targets)
    return plugin, bundle, lane, required


def _require(plugin: object, bundle: object, lane: object, required: tuple[object, ...]) -> object:
    return _require_plugin_calibration_bundle(
        bundle, plugin, bundle.rubric, (lane, canonical_json_sha256(bundle.model_dump(mode="json"))), required
    )


def test_distinct_assertions_require_distinct_observed_targets(tmp_path: Path) -> None:
    plugin, bundle, lane, required = _bundle(tmp_path)
    assert bundle.plugin_candidate != bundle.targets[0].child_candidate
    assert _require(plugin, bundle, lane, required) == bundle
    assert MatchedVariantCalibrationBundle.model_validate_json(bundle.model_dump_json()) == bundle
    Draft202012Validator(MatchedVariantCalibrationBundle.model_json_schema()).validate(bundle.model_dump(mode="json"))
    with pytest.raises(ValueError, match="exact required"):
        _require(plugin, bundle.model_copy(update={"targets": bundle.targets[:1]}), lane, required)
    with pytest.raises(ValueError, match="exact required"):
        _require(plugin, bundle, lane, required[:1])
    assert _require(plugin, bundle, lane, (*required, required[0])) == bundle


@pytest.mark.parametrize(
    "change", ["child", "assertions", "scorer", "plugin_as_child", "duplicate", "judge", "settings", "rubric"]
)
def test_calibration_bundle_tampering_rejects_and_recovers(tmp_path: Path, change: str) -> None:
    _plugin, bundle, _lane, _required = _bundle(tmp_path)
    raw = bundle.model_dump(mode="json")
    target = raw["targets"][0]
    if change == "child":
        target["child_candidate"]["content_sha256"] = "0" * 64
    elif change == "assertions":
        target["assertion_contract_sha256"] = "0" * 64
    elif change == "scorer":
        target["scorer"]["version_or_digest"] = "different"
    elif change == "plugin_as_child":
        target["child_candidate"] = raw["plugin_candidate"]
    elif change == "duplicate":
        raw["targets"] = [target, target]
    elif change == "judge":
        raw["judge"]["adapter_version_or_digest"] = "different"
    elif change == "settings":
        raw["judge_parameters"]["temperature"] = 0.2
    else:
        raw["rubric"]["rubric_id"] = "different"
    with pytest.raises(ValidationError):
        MatchedVariantCalibrationBundle.model_validate(raw)
    with pytest.raises(ValidationError):
        MatchedVariantCalibrationBundle.model_validate_json(json.dumps(raw))
    assert MatchedVariantCalibrationBundle.model_validate(bundle) == bundle


@pytest.mark.parametrize("change", ["mode", "plugin", "digest", "missing_child", "wrong_scorer"])
def test_bundle_join_rejects_drift_and_corrected_input_recovers(tmp_path: Path, change: str) -> None:
    plugin, bundle, lane, required = _bundle(tmp_path)
    supplied, expected, targets = bundle, plugin, required
    digest = canonical_json_sha256(bundle.model_dump(mode="json"))
    if change == "mode":
        supplied = bundle.model_copy(update={"mode_manifest_sha256": "0" * 64})
    elif change == "plugin":
        supplied = bundle.model_copy(update={"plugin_candidate": bundle.targets[0].child_candidate})
    elif change == "digest":
        digest = "0" * 64
    elif change == "missing_child":
        targets = (("skills/unknown", required[0][1], required[0][2]), *required[1:])
    else:
        targets = (
            (required[0][0], required[0][1], required[0][2].model_copy(update={"version_or_digest": "different"})),
            *required[1:],
        )
    with pytest.raises(ValueError):
        _require_plugin_calibration_bundle(supplied, expected, bundle.rubric, (lane, digest), targets)
    assert _require(plugin, bundle, lane, required) == bundle
