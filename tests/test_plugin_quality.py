"""Whole-plugin binding, first-stop behavior and recovery through public composition."""

from __future__ import annotations

import asyncio
import json
import shutil
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_plugin_presentation import _image, _manifest
from test_plugin_presentation import _request as presentation_request
from test_quality_workflow import _assessment, _package_path, _request

from skills_sdk.cli import plugin_quality as route
from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import check_plugin_quality
from skills_sdk.evaluation import plugin_quality as service_module
from skills_sdk.models.plugin import PluginValidationPolicy
from skills_sdk.models.plugin_quality import (
    PluginQualityRequest,
    PluginQualityResult,
    bounded_json_size,
)
from skills_sdk.models.quality_workflow import LocalCheckResultV2
from skills_sdk.validation.plugin_package import validate_plugin_package

REVISION = "1" * 40


def _plugin(root: Path) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    """Compose real synthetic child quality and image services without external adapters."""
    request = _request(root)
    source = _package_path(root)
    plugin = root / "plugin"
    child = plugin / "skills" / source.name
    child.parent.mkdir(parents=True)
    shutil.move(source, child)
    _image(plugin / "assets" / "icon.png")
    _manifest(plugin, {"logo": "./assets/icon.png", "composerIcon": "./assets/icon.png", "description": "Fixture"})
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest.update(version="1.0.0", description="Synthetic fixture.")
    (plugin / "plugin.json").write_text(json.dumps(manifest))
    capture = validate_plugin_package(
        plugin, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    path = "skills/" + source.name
    payload = {
        "candidate": capture.candidate.model_dump(mode="json"),
        "mode_manifest_sha256": capture.mode_manifest_sha256,
        "children": [{"path": path, "request": request}],
    }
    return plugin, payload, {path: _assessment(child)}, presentation_request(plugin)


def test_plugin_quality_accepts_missing_approval_blocks_and_corrected_input_recovers(tmp_path: Path) -> None:
    """All child checks alone cannot clear whole-plugin presentation or release."""
    root, request, assessments, presentation = _plugin(tmp_path)
    blocked = asyncio.run(check_plugin_quality(root, request, assessments=assessments))
    assert blocked.blocker.code == "plugin_quality_presentation_missing"
    assert blocked.children[0].status == "local_checks_passed"
    passed = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert passed.status == "local_checks_passed"
    assert passed.final_capture == passed.initial_capture
    assert passed.release_ready is passed.evaluation_executed is passed.mutation_performed is False
    registry = SchemaRegistry()
    payload = passed.model_dump(mode="json")
    registry.validate("plugin-quality.v1", payload)
    assert Draft202012Validator(registry.load("plugin-quality.v1")).is_valid(payload)
    for field, value in (("children", []), ("final_capture", None), ("presentation", None)):
        with pytest.raises(ContractError):
            registry.validate("plugin-quality.v1", {**payload, field: value})


@pytest.mark.parametrize("defect", ["mode", "child", "extra-child", "mcp", "symlink"])
def test_root_drift_or_uncovered_components_stop_before_child_checks(tmp_path: Path, defect: str) -> None:
    """Whole-plugin binding includes mode-only drift, complete membership and unsafe source."""
    root, request, assessments, presentation = _plugin(tmp_path)
    if defect == "mode":
        (root / "assets" / "icon.png").chmod(0o755)
    elif defect == "child":
        (root / "skills" / request["children"][0]["path"].split("/")[1] / "SKILL.md").write_text("changed")
    elif defect == "extra-child":
        extra = root / "skills" / "extra"
        extra.mkdir()
        (extra / "SKILL.md").write_text("---\nname: extra\ndescription: Review examples.\n---\n# Extra\n")
    elif defect == "mcp":
        (root / "mcp.json").write_text("{}")
    else:
        (root / "linked").symlink_to(root / "plugin.json")
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.blocker.code == "plugin_quality_root_mismatch"
    assert result.children == ()


def test_child_blocker_retains_actual_stage_and_rejects_false_success(tmp_path: Path) -> None:
    """Missing review stops at content review without a presentation success claim."""
    root, request, _assessments, presentation = _plugin(tmp_path)
    result = asyncio.run(check_plugin_quality(root, request, presentation_request=presentation))
    assert result.blocker.code == "plugin_quality_child_blocked"
    assert result.children[0].blocked_stage == "content-review"
    assert result.presentation is None
    with pytest.raises(ValidationError):
        PluginQualityResult.model_validate(result.model_copy(update={"status": "local_checks_passed", "blocker": None}))


def test_request_schema_and_forged_nested_child_are_revalidated(tmp_path: Path) -> None:
    """Unknown fields, traversal and forged nested intent cannot select unsupported operations."""
    _root, payload, _assessments, _presentation = _plugin(tmp_path)
    request = PluginQualityRequest.model_validate(payload)
    SchemaRegistry().validate("plugin-quality-request.v1", request.model_dump(mode="json"))
    child = request.children[0]
    for forged in (
        child.model_copy(update={"path": "../escape"}),
        child.model_copy(update={"request": child.request.model_copy(update={"intent": "update"})}),
    ):
        with pytest.raises(ValidationError):
            PluginQualityRequest.model_validate(request.model_copy(update={"children": (forged,)}))


def test_cli_accepts_blocks_and_recovers_with_json_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Exercise the actual route and duplicate-member rejection on bounded file ingress."""
    root, request, assessments, presentation = _plugin(tmp_path)
    paths = []
    for name, payload in (("request", request), ("assessments", assessments), ("presentation", presentation)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(payload))
        paths.append(path)
    command = ["check-plugin-quality", str(root), "--request", str(paths[0]), "--assessments", str(paths[1]), "--json"]
    assert main(command) == 2
    assert json.loads(capsys.readouterr().out)["blocker"]["code"] == "plugin_quality_presentation_missing"
    complete = [*command, "--presentation-request", str(paths[2])]
    assert main(complete) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "local_checks_passed"
    paths[0].write_text('{"candidate": {}, "candidate": {}}')
    assert main(complete) == 2
    assert json.loads(capsys.readouterr().out)["blocker"]["code"] == "plugin_quality_input_invalid"


@pytest.mark.parametrize("field", ["image", "settings"])
def test_passing_presentation_cannot_describe_foreign_bytes(tmp_path: Path, field: str) -> None:
    """Self-consistent presentation assertions still need the root's actual digests."""
    root, request, assessments, presentation = _plugin(tmp_path)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    ).model_dump(mode="json")
    selected = result["presentation"]
    if field == "image":
        selected["images"][0]["sha256"] = "f" * 64
        selected["images"][0]["approval"]["image_sha256"] = "f" * 64
    else:
        selected["openai_settings_sha256"] = "f" * 64
        selected["copy_approval"]["openai_settings_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="captured"):
        PluginQualityResult.model_validate(result)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", result)


def test_result_cannot_bypass_skill_only_profile(tmp_path: Path) -> None:
    """Direct result and schema-registry validation retain the service's MCP boundary."""
    root, request, assessments, presentation = _plugin(tmp_path)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    ).model_dump(mode="json")
    (root / "mcp.json").write_text("{}")
    capture = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    result["request"].update(
        candidate=capture.candidate.model_dump(mode="json"), mode_manifest_sha256=capture.mode_manifest_sha256
    )
    result["initial_capture"] = result["final_capture"] = capture.model_dump(mode="json")
    from skills_sdk.validation.plugin_presentation import check_plugin_presentation

    result["presentation"] = check_plugin_presentation(
        root, source_revision=REVISION, request=presentation_request(root)
    ).model_dump(mode="json")
    assert result["presentation"]["status"] == "pass"
    with pytest.raises(ValidationError, match="skill-only"):
        PluginQualityResult.model_validate(result)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", result)


@pytest.mark.parametrize("supplied_first", [False, True])
def test_multiple_children_stop_before_second_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supplied_first: bool
) -> None:
    """The first blocked child stops composition and preserves the bounded passing prefix."""
    from skills_sdk.evaluation import plugin_quality

    root, request, assessments, _presentation = _plugin(tmp_path)
    source = root / request["children"][0]["path"]
    extra = root / "skills" / "zz-extra"
    shutil.copytree(source, extra)
    text = (extra / "SKILL.md").read_text().replace("name: " + source.name, "name: zz-extra")
    (extra / "SKILL.md").write_text(text)
    capture = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    assert capture.status == "pass"
    extra_request = json.loads(json.dumps(request["children"][0]["request"]))
    candidate = capture.skills[1].validation.candidate.model_dump(mode="json")
    extra_request["candidate"] = extra_request["coverage_plan"]["candidate"] = candidate
    request["children"].append({"path": "skills/zz-extra", "request": extra_request})
    request.update(
        candidate=capture.candidate.model_dump(mode="json"), mode_manifest_sha256=capture.mode_manifest_sha256
    )
    calls = []
    actual = plugin_quality.check_local_quality

    async def observe(path: Path, selected: object, **kwargs: object) -> LocalCheckResultV2:
        """Observe real child service calls without substituting their receipts."""
        calls.append(path)
        return await actual(path, selected, **kwargs)

    monkeypatch.setattr(plugin_quality, "check_local_quality", observe)
    result = asyncio.run(check_plugin_quality(root, request, assessments=assessments if supplied_first else None))
    assert len(result.children) == len(calls) == (2 if supplied_first else 1)
    assert result.children[-1].blocked_stage == ("scenario-coverage" if supplied_first else "content-review")
    if supplied_first:
        from skills_sdk.models import plugin_quality as model

        assessment = result.children[0].stages[-1].receipt.assessment.model_dump(mode="json")
        size = bounded_json_size({request["children"][0]["path"]: assessment}, 10**9)
        monkeypatch.setattr(model, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", size - 1)
        with pytest.raises(ValidationError, match="aggregate"):
            PluginQualityResult.model_validate(result)
        monkeypatch.setattr(model, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", size)
        assert PluginQualityResult.model_validate(result) == result


def _tree_state(root: Path) -> dict[str, tuple[int, bytes]]:
    """Capture every regular file's mode and bytes to prove read-only composition."""
    return {
        str(path.relative_to(root)): (path.stat().st_mode, path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_composition_never_writes_into_the_plugin_source(tmp_path: Path) -> None:
    """Passing and blocked runs leave source bytes, modes and entries unchanged."""
    root, request, assessments, presentation = _plugin(tmp_path)
    before = _tree_state(root)
    asyncio.run(check_plugin_quality(root, request, assessments=assessments))
    asyncio.run(check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation))
    assert _tree_state(root) == before


@pytest.mark.parametrize("defect", ["unknown", "duplicate", "reordered", "wrong-revision"])
def test_raw_requests_with_unbound_children_are_rejected_at_the_boundary(tmp_path: Path, defect: str) -> None:
    """Raw mappings cannot add, repeat, reorder or re-version child evidence."""
    root, request, assessments, _presentation = _plugin(tmp_path)
    child = request["children"][0]
    selected = json.loads(json.dumps(request))
    if defect == "unknown":
        selected["unsupported"] = True
    elif defect == "duplicate":
        selected["children"] = [child, child]
    elif defect == "reordered":
        selected["children"] = [{**child, "path": "skills/zz"}, child]
    else:
        selected["children"][0]["request"]["candidate"]["source_revision"] = "2" * 40
    with pytest.raises(ValidationError):
        PluginQualityRequest.model_validate(selected)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality-request.v1", selected)
    result = asyncio.run(check_plugin_quality(root, selected, assessments=assessments))
    assert result.blocker.code == "plugin_quality_request_invalid"
    assert result.children == () and result.initial_capture is None


def test_assessments_for_unrequested_children_are_rejected(tmp_path: Path) -> None:
    """Supplied reviews cannot name a child that the request did not select."""
    root, request, assessments, presentation = _plugin(tmp_path)
    foreign = {**assessments, "skills/unrequested": next(iter(assessments.values()))}
    result = asyncio.run(check_plugin_quality(root, request, assessments=foreign, presentation_request=presentation))
    assert result.blocker.code == "plugin_quality_assessments_invalid"
    assert result.children == ()
    recovered = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


def test_source_drift_before_initial_capture_is_rejected_and_restoration_recovers(tmp_path: Path) -> None:
    """Drift before the initial capture blocks; restoring original source recovers."""
    root, request, assessments, presentation = _plugin(tmp_path)
    (root / "assets" / "extra.txt").write_text("late")
    stale = asyncio.run(check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation))
    assert stale.blocker.code == "plugin_quality_root_mismatch"
    assert stale.children == ()
    (root / "assets" / "extra.txt").unlink()
    fresh = asyncio.run(check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation))
    assert fresh.status == "local_checks_passed"


def test_change_at_final_capture_is_rejected_and_restoration_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent source edit cannot turn completed child evidence into plugin success."""
    from skills_sdk.evaluation import plugin_quality

    root, request, assessments, presentation = _plugin(tmp_path)
    capture = plugin_quality.validate_plugin_package
    calls = 0
    changed = root / "assets" / "concurrent.txt"

    def observe(path: Path, *, source_revision: str, policy: PluginValidationPolicy) -> object:
        """Simulate another writer immediately before the service's final recapture."""
        nonlocal calls
        calls += 1
        if calls == 2:
            changed.write_text("concurrent edit", encoding="utf-8")
        return capture(path, source_revision=source_revision, policy=policy)

    monkeypatch.setattr(plugin_quality, "validate_plugin_package", observe)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert calls == 2 and result.blocker.code == "plugin_quality_source_changed"
    assert result.initial_capture != result.final_capture
    assert result.release_ready is result.execution_authorized is False
    changed.unlink()
    monkeypatch.setattr(plugin_quality, "validate_plugin_package", capture)
    recovered = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize("flag", ["mutation_performed", "evaluation_executed", "execution_authorized", "release_ready"])
def test_authority_flags_require_literal_false_for_raw_and_copied_results(tmp_path: Path, flag: str) -> None:
    """Model boundaries must reject numeric substitutes that the packaged schema rejects."""
    root, request, assessments, presentation = _plugin(tmp_path)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert PluginQualityResult.model_validate(result) == result
    raw = {**result.model_dump(mode="json"), flag: 0}
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)
    for forged in (raw, result.model_copy(update={flag: 0})):
        with pytest.raises(ValidationError):
            PluginQualityResult.model_validate(forged)


def test_success_schema_requires_evidence_while_neighbours_validate(tmp_path: Path) -> None:
    """The packaged schema rejects evidence-free success and keeps real results valid."""
    schema = json.loads(Path("src/skills_sdk/schemas/plugin-quality.v1.schema.json").read_text())
    validator = Draft202012Validator(schema)
    root, request, assessments, presentation = _plugin(tmp_path)
    passed = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    blocked = asyncio.run(check_plugin_quality(root, request, assessments=assessments))
    for result in (passed, blocked):
        assert not list(validator.iter_errors(result.model_dump(mode="json")))
    assert list(validator.iter_errors({"schema_version": "plugin-quality/v1", "status": "local_checks_passed"}))
    partial = {**passed.model_dump(mode="json"), "final_capture": None}
    assert list(validator.iter_errors(partial))
    assert list(validator.iter_errors({"schema_version": "plugin-quality/v1", "status": "blocked"}))


def test_blocker_codes_must_match_retained_stage_evidence(tmp_path: Path) -> None:
    """A passing envelope cannot be relabelled and source_changed needs a differing final capture."""
    root, request, assessments, presentation = _plugin(tmp_path)
    passed = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    blocker = {"code": "plugin_quality_root_mismatch", "message": "forged"}
    raw = {**passed.model_dump(mode="json"), "status": "blocked", "blocker": blocker}
    with pytest.raises(ValidationError):
        PluginQualityResult.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)
    changed = {**raw, "blocker": {**blocker, "code": "plugin_quality_source_changed"}}
    with pytest.raises(ValidationError):
        PluginQualityResult.model_validate(changed)
    unknown = {**raw, "blocker": {**blocker, "code": "plugin_quality_unknown"}}
    with pytest.raises(ValidationError):
        PluginQualityResult.model_validate(unknown)
    live = asyncio.run(check_plugin_quality(root, request, assessments=assessments))
    assert live.blocker.code == "plugin_quality_presentation_missing"
    assert PluginQualityResult.model_validate(live.model_dump(mode="json")) == live


def test_aggregate_assessment_budget_blocks_before_children_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A small patched budget proves the bound without allocating bulk evidence."""
    from skills_sdk.evaluation import plugin_quality

    root, request, assessments, presentation = _plugin(tmp_path)
    monkeypatch.setattr(plugin_quality, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", 64)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.blocker.code == "plugin_quality_assessments_invalid" and result.children == ()
    monkeypatch.undo()
    recovered = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


def test_aggregate_assessment_budget_counts_the_enclosing_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Values that fit alone but not inside the compact mapping block; the exact boundary passes."""
    from skills_sdk.evaluation import plugin_quality
    from skills_sdk.models.content_review import ContentReviewAssessment

    root, request, assessments, presentation = _plugin(tmp_path)
    assessments = {
        key: ContentReviewAssessment.model_validate(value).model_dump(mode="json") for key, value in assessments.items()
    }
    ((key, value),) = assessments.items()
    value_size = bounded_json_size(value, 10**9)
    full_size = len(json.dumps(assessments, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
    assert full_size > value_size
    for budget, code in (
        (value_size, "plugin_quality_assessments_invalid"),
        (full_size - 1, "plugin_quality_assessments_invalid"),
    ):
        monkeypatch.setattr(plugin_quality, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", budget)
        blocked = asyncio.run(
            check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
        )
        assert blocked.blocker.code == code and blocked.children == ()
    monkeypatch.setattr(plugin_quality, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", full_size)
    accepted = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert accepted.status == "local_checks_passed"
    monkeypatch.undo()
    assert key in assessments


def test_cyclic_and_non_dict_assessments_are_rejected(tmp_path: Path) -> None:
    """Concrete dict is the documented boundary; cycles and read-only mappings block."""
    from types import MappingProxyType

    root, request, assessments, presentation = _plugin(tmp_path)
    key = next(iter(assessments))
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    for bad in (MappingProxyType(assessments), {key: cycle}):
        result = asyncio.run(check_plugin_quality(root, request, assessments=bad, presentation_request=presentation))
        assert result.blocker.code == "plugin_quality_assessments_invalid"


@pytest.mark.parametrize("value", [{"text": '\u0000\n"\\é' * 1000}, [12345678901234567890, -1.25e100, True, None], {}])
def test_assessment_budget_counts_actual_json_bytes(value: object) -> None:
    """Escapes and large numbers cannot undercount the aggregate admission boundary."""
    size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    assert bounded_json_size(value, size) == size
    with pytest.raises(ValueError):
        bounded_json_size(value, size - 1)


def test_cli_reads_assessment_bundle_with_contract_budget(tmp_path: Path) -> None:
    """Only the assessment bundle receives the larger no-follow read limit."""
    from types import SimpleNamespace

    from skills_sdk.cli.plugin_quality import run
    from skills_sdk.models.plugin_quality import PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES

    limits: dict[str, object] = {}

    def read(path: Path, **kwargs: object) -> bytes:
        limits[path.name] = kwargs.get("max_bytes")
        return b"{}"

    arguments = SimpleNamespace(
        plugin_root=tmp_path,
        request=Path("request.json"),
        assessments=Path("assessments.json"),
        presentation_request=Path("presentation.json"),
        json_output=True,
    )
    run(arguments, read, lambda pairs: dict(pairs))
    assert limits == {
        "request.json": None,
        "assessments.json": PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES,
        "presentation.json": None,
    }


def _passed(tmp_path: Path) -> tuple[Path, dict[str, object], PluginQualityResult]:
    """Run the real passing composition once for forged-envelope fixtures."""
    root, request, assessments, presentation = _plugin(tmp_path)
    result = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.status == "local_checks_passed"
    return root, request, result


def _padded(request: dict[str, object], defect: str) -> dict[str, object]:
    """Return a copy of a raw request with one identity or digest padded."""
    forged = json.loads(json.dumps(request))
    child = forged["children"][0]["request"]["candidate"]
    if defect == "mode":
        forged["mode_manifest_sha256"] = " " + forged["mode_manifest_sha256"]
    elif defect.startswith("child."):
        child[defect.split(".")[1]] += " "
    else:
        forged["candidate"][defect] += " "
    return forged


@pytest.mark.parametrize(
    "defect",
    [
        "package_id",
        "source_revision",
        "content_sha256",
        "mode",
        "child.package_id",
        "child.source_revision",
        "child.content_sha256",
    ],
)
def test_padded_request_identity_is_rejected_by_every_boundary(
    tmp_path: Path, defect: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Padding fails the model, schema, copied typed request and fresh service alike."""
    root, request, assessments, presentation = _plugin(tmp_path)
    forged = _padded(request, defect)
    with pytest.raises(ValidationError):
        PluginQualityRequest.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality-request.v1", forged)
    blocked = asyncio.run(
        check_plugin_quality(root, forged, assessments=assessments, presentation_request=presentation)
    )
    assert blocked.blocker.code == "plugin_quality_request_invalid" and blocked.children == ()
    assert str(root) not in blocked.blocker.message
    typed = PluginQualityRequest.model_validate(request)
    if defect == "mode":
        copied = typed.model_copy(update={"mode_manifest_sha256": forged["mode_manifest_sha256"]})
    elif defect.startswith("child."):
        key = defect.split(".")[1]
        child = typed.children[0]
        candidate = child.request.candidate.model_copy(update={key: forged["children"][0]["request"]["candidate"][key]})
        changed = child.model_copy(update={"request": child.request.model_copy(update={"candidate": candidate})})
        copied = typed.model_copy(update={"children": (changed,)})
    else:
        candidate = typed.candidate.model_copy(update={defect: forged["candidate"][defect]})
        copied = typed.model_copy(update={"candidate": candidate})
    for invalid in (copied, PluginQualityRequest.model_construct(**forged)):
        with pytest.raises(ValidationError):
            PluginQualityRequest.model_validate(invalid)
    request_path = tmp_path / "padded-request.json"
    request_path.write_text(json.dumps(forged))
    assert main(["check-plugin-quality", str(root), "--request", str(request_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["blocker"]["code"] == "plugin_quality_request_invalid"
    recovered = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


def test_padded_result_identity_is_rejected(tmp_path: Path) -> None:
    """A retained envelope cannot smuggle padded identity past the stripping model config."""
    _root, _request, passed = _passed(tmp_path)
    raw = passed.model_dump(mode="json")
    raw["request"]["mode_manifest_sha256"] = raw["request"]["mode_manifest_sha256"] + " "
    with pytest.raises(ValidationError):
        PluginQualityResult.model_validate(raw)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)


def _foreign(root: Path, defect: str) -> dict[str, object]:
    """Capture a genuinely valid tree for another plugin name or source revision."""
    policy = PluginValidationPolicy(require_version=True, require_description=True)
    revision = "2" * 40 if defect == "revision" else REVISION
    if defect == "package":
        other = root.parent / "other-plugin"
        shutil.copytree(root, other)
        manifest = json.loads((other / "plugin.json").read_text())
        manifest["name"] = "other-plugin"
        (other / "plugin.json").write_text(json.dumps(manifest))
        root = other
    capture = validate_plugin_package(root, source_revision=revision, policy=policy)
    assert capture.status == "pass" and capture.candidate is not None
    return capture.model_dump(mode="json")


@pytest.mark.parametrize("defect", ["package", "revision"])
def test_source_changed_requires_the_selected_package_and_revision(tmp_path: Path, defect: str) -> None:
    """Foreign valid recaptures are rejected while content, mode and unresolved changes stay valid."""
    root, _request, passed = _passed(tmp_path)
    raw = passed.model_dump(mode="json")
    blocker = {"code": "plugin_quality_source_changed", "message": "changed"}
    (root / "assets" / "late.txt").write_text("late")
    from skills_sdk.validation.plugin_package import validate_plugin_package as capture_again

    changed = capture_again(
        root,
        source_revision=REVISION,
        policy=PluginValidationPolicy(require_version=True, require_description=True),
    ).model_dump(mode="json")
    valid = {**raw, "status": "blocked", "final_capture": changed, "blocker": blocker}
    assert PluginQualityResult.model_validate(valid).blocker.code == "plugin_quality_source_changed"
    SchemaRegistry().validate("plugin-quality.v1", valid)
    foreign = {**valid, "final_capture": _foreign(root, defect)}
    typed = PluginQualityResult.model_validate(valid)
    assert foreign["final_capture"]["candidate"] != changed["candidate"]
    for forged in (foreign, typed.model_copy(update={"final_capture": foreign["final_capture"]})):
        with pytest.raises(ValidationError):
            PluginQualityResult.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", foreign)
    (root / "linked").symlink_to(root / "plugin.json")
    blocked_capture = capture_again(
        root,
        source_revision=REVISION,
        policy=PluginValidationPolicy(require_version=True, require_description=True),
    )
    assert blocked_capture.status == "blocked" and blocked_capture.candidate is None
    unresolved = {**valid, "final_capture": blocked_capture.model_dump(mode="json")}
    accepted = PluginQualityResult.model_validate(unresolved)
    assert accepted.final_capture.candidate is None


def test_retained_assessment_aggregate_is_reapplied_to_supplied_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lowered budget rejects forged pass and partial envelopes; the exact boundary recovers."""
    from skills_sdk.models import plugin_quality as model

    _root, _request, passed = _passed(tmp_path)
    retained = {
        child.path: stage.receipt.assessment.model_dump(mode="json")
        for child, result in zip(passed.request.children, passed.children, strict=True)
        for stage in result.stages
        if stage.name == "content-review"
    }
    size = bounded_json_size(retained, 10**9)
    raw = passed.model_dump(mode="json")
    partial = {**raw, "status": "blocked", "final_capture": None, "presentation": None}
    partial["blocker"] = {"code": "plugin_quality_presentation_missing", "message": "missing"}
    monkeypatch.setattr(model, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", size - 1)
    for forged in (raw, partial, passed.model_copy(update={"status": "local_checks_passed"})):
        with pytest.raises(ValidationError, match="aggregate"):
            PluginQualityResult.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)
    monkeypatch.setattr(model, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", size)
    assert PluginQualityResult.model_validate(raw) == passed
    assert PluginQualityResult.model_validate(partial).blocker.code == "plugin_quality_presentation_missing"
    SchemaRegistry().validate("plugin-quality.v1", raw)


def test_service_blocks_approvals_that_omit_a_declared_image_and_recovers(tmp_path: Path) -> None:
    """The fresh service derives declared images from captured settings; hash-only receipts cannot."""
    root, request, assessments, _presentation = _plugin(tmp_path)
    _image(root / "assets" / "dark.png")
    manifest = json.loads((root / "plugin.json").read_text())
    settings = manifest["extensions"]["com.openai"]["interface"]
    settings["logoDark"] = "./assets/dark.png"
    (root / "plugin.json").write_text(json.dumps(manifest))
    capture = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    request.update(
        candidate=capture.candidate.model_dump(mode="json"), mode_manifest_sha256=capture.mode_manifest_sha256
    )
    incomplete = presentation_request(root)
    assert len(incomplete["image_approvals"]) == 1
    blocked = asyncio.run(check_plugin_quality(root, request, assessments=assessments, presentation_request=incomplete))
    assert blocked.blocker.code == "plugin_quality_presentation_blocked"
    assert blocked.presentation.status == "blocked" and blocked.presentation.images == ()
    assert str(root) not in blocked.model_dump_json()
    complete = json.loads(json.dumps(incomplete))
    dark = json.loads(json.dumps(complete["image_approvals"][0]))
    dark["image_path"] = "assets/dark.png"
    dark["image_sha256"] = __import__("hashlib").sha256((root / "assets" / "dark.png").read_bytes()).hexdigest()
    complete["image_approvals"].append(dark)
    passed = asyncio.run(check_plugin_quality(root, request, assessments=assessments, presentation_request=complete))
    assert passed.status == "local_checks_passed"
    assert {image.path for image in passed.presentation.images} == {"assets/icon.png", "assets/dark.png"}


@pytest.mark.parametrize("field", ["settings", "image"])
def test_source_changed_retains_presentation_bound_to_initial_capture(tmp_path: Path, field: str) -> None:
    """A passed presentation remains consistent with the initial capture after later drift."""
    root, _request, passed = _passed(tmp_path)
    (root / "assets" / "icon.png").chmod(0o755)
    changed = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    raw = passed.model_dump(mode="json")
    raw.update(status="blocked", final_capture=changed.model_dump(mode="json"))
    raw["blocker"] = {"code": "plugin_quality_source_changed", "message": "mode drift"}
    valid = PluginQualityResult.model_validate(raw)
    SchemaRegistry().validate("plugin-quality.v1", raw)
    selected = raw["presentation"]
    if field == "settings":
        selected["openai_settings_sha256"] = "f" * 64
        selected["copy_approval"]["openai_settings_sha256"] = "f" * 64
    else:
        selected["images"][0]["sha256"] = "f" * 64
        selected["images"][0]["approval"]["image_sha256"] = "f" * 64
    for forged in (raw, valid.model_copy(update={"presentation": selected})):
        with pytest.raises(ValidationError, match="captured"):
            PluginQualityResult.model_validate(forged)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)


def test_normalized_assessment_budget_stops_before_child_checks_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw defaults cannot make retained evidence overflow and escape as an exception."""
    from skills_sdk.evaluation import plugin_quality as service
    from skills_sdk.models import plugin_quality as model
    from skills_sdk.models.content_review import ContentReviewAssessment

    root, request, assessments, presentation = _plugin(tmp_path)
    normalized = {
        key: ContentReviewAssessment.model_validate(value).model_dump(mode="json") for key, value in assessments.items()
    }
    raw_size = bounded_json_size(assessments, 10**9)
    size = bounded_json_size(normalized, 10**9)
    assert size > raw_size
    for module in (service, model):
        monkeypatch.setattr(module, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", raw_size)
    for supplied_presentation in (None, presentation):
        blocked = asyncio.run(
            check_plugin_quality(root, request, assessments=assessments, presentation_request=supplied_presentation)
        )
        assert blocked.blocker.code == "plugin_quality_assessments_invalid" and blocked.children == ()
    for module in (service, model):
        monkeypatch.setattr(module, "PLUGIN_QUALITY_ASSESSMENT_BUNDLE_MAX_BYTES", size)
    recovered = asyncio.run(
        check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


@pytest.mark.parametrize("payload", [b"[[[[[]]]]]", b"[1,2,3,4,5,6]", b'"x', b"[1]]", b"\xff"])
def test_cli_structural_scan_rejects_before_materialization(
    tmp_path: Path, payload: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lowered limits and malformed JSON block before json.loads or the service runs."""
    monkeypatch.setattr(route, "_MAX_JSON_DEPTH", 4)
    monkeypatch.setattr(route, "_MAX_JSON_NODES", 5)
    reached: list[str] = []
    real_loads = json.loads
    monkeypatch.setattr(route.json, "loads", lambda *a, **k: reached.append("loads"))
    monkeypatch.setattr(service_module, "check_plugin_quality", lambda *a, **k: reached.append("service"))
    arguments = {"plugin_root": tmp_path, "request": Path("r"), "assessments": None, "presentation_request": None}
    route.run(Namespace(**arguments, json_output=True), lambda path, **kw: payload, dict)
    assert reached == []
    assert real_loads(capsys.readouterr().out)["blocker"]["code"] == "plugin_quality_input_invalid"


def test_cli_structural_scan_admits_valid_neighbours() -> None:
    """Large strings and escaped delimiters stay accepted."""
    route._scan_json_structure(json.dumps({"a": "x" * 2_000_000, "s": 'q } ] "', "b": [1, None, {"c": 1.5}]}))


def _child_errors(name: str, child: object) -> list[object]:
    schema = SchemaRegistry().load(name)
    node = schema["$defs"]["PluginQualityChild"] | {"$defs": schema["$defs"]}
    return list(Draft202012Validator(node).iter_errors(child))


@pytest.mark.parametrize("path", ["", " ", "../escape", "skills/a/b", "/skills/a", "skills\\a", "skills/a\nb", "a/b"])
def test_child_selector_rejects_invalid_and_accepts_direct_paths(tmp_path: Path, path: str) -> None:
    """Model, packaged schemas, registry and public service require a direct skills/<name>."""
    root, payload, found, shown = _plugin(tmp_path)
    children: Any = payload["children"]
    forged = {**payload, "children": [{**children[0], "path": path}]}
    with pytest.raises(ValidationError):
        PluginQualityRequest.model_validate(forged)
    assert all(_child_errors(n, forged["children"][0]) for n in ("plugin-quality-request.v1", "plugin-quality.v1"))
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality-request.v1", forged)
    blocked = asyncio.run(check_plugin_quality(root, forged, assessments=found, presentation_request=shown))
    assert blocked.blocker is not None and blocked.blocker.code == "plugin_quality_request_invalid"
    for direct in ("skills/ordinary", "skills/café-技能"):
        for n in ("plugin-quality-request.v1", "plugin-quality.v1"):
            assert not _child_errors(n, {**children[0], "path": direct})
