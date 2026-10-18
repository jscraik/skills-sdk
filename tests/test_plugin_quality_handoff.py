"""Bounded final-batch regressions for whole-plugin workflow consumers."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from test_plugin_quality import _plugin

from skills_sdk.cli import plugin_quality as route
from skills_sdk.cli.main import main
from skills_sdk.evaluation import plugin_quality as service
from skills_sdk.models.content_review import CONTENT_REVIEW_ASSESSMENT_MAX_BYTES, ContentReviewAssessment


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork boundary")
def test_warmed_workers_recover_after_process_fork() -> None:
    """A disposable subprocess proves child admission after both parent workers start."""
    script = """
import asyncio, os, select, signal, threading
from pathlib import Path
from skills_sdk.evaluation import plugin_quality as service
barrier = threading.Barrier(2)
original = service._run_plugin_quality
def warm(*args):
    barrier.wait(timeout=3)
    return service._block('plugin_quality_request_invalid')
service._run_plugin_quality = warm
async def run():
    await asyncio.gather(service.check_plugin_quality(Path('.'), {}),
                         service.check_plugin_quality(Path('.'), {}))
asyncio.run(run())
service._run_plugin_quality = original
read_fd, write_fd = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(read_fd)
    result = asyncio.run(service.check_plugin_quality(Path('.'), {}))
    os.write(write_fd, result.blocker.code.encode())
    os._exit(0)
os.close(write_fd)
ready = select.select([read_fd], [], [], 3)[0]
if not ready:
    os.kill(pid, signal.SIGKILL)
_, status = os.waitpid(pid, 0)
message = os.read(read_fd, 1024).decode()
os.close(read_fd)
assert os.waitstatus_to_exitcode(status) == 0, 'forked worker stalled'
assert message == 'plugin_quality_request_invalid'
# The parent's executor and capacity remain usable too.
assert asyncio.run(service.check_plugin_quality(Path('.'), {})).blocker.code == message
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=12, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("marker", ["api_key=synthetic-fixture-only", str(Path("/") / "Users" / "fixture" / "private")])
def test_manifest_description_is_not_emitted(tmp_path: Path, marker: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Unsafe captured metadata must stop without retaining it in API or CLI JSON."""
    from test_plugin_quality import REVISION

    from skills_sdk.models.plugin import PluginValidationPolicy
    from skills_sdk.validation.plugin_package import validate_plugin_package

    root, request, assessments, presentation = _plugin(tmp_path)
    path = root / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["description"] = marker
    path.write_text(json.dumps(manifest))
    capture = validate_plugin_package(
        root, source_revision=REVISION, policy=PluginValidationPolicy(require_version=True, require_description=True)
    )
    request["candidate"] = capture.candidate.model_dump(mode="json")
    request["mode_manifest_sha256"] = capture.mode_manifest_sha256
    result = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert marker not in result.model_dump_json()
    assert result.blocker.code == "plugin_quality_input_invalid" and result.initial_capture is None
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request))
    assert main(["check-plugin-quality", str(root), "--request", str(request_file), "--json"]) == 2
    output = capsys.readouterr().out
    assert marker not in output
    assert json.loads(output)["blocker"]["code"] == "plugin_quality_input_invalid"


@pytest.mark.parametrize("field", ["initial_capture", "final_capture"])
def test_supplied_and_late_manifest_descriptions_fail_closed(
    tmp_path: Path, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revalidated receipts and a late real source change cannot retain unsafe text."""
    from pydantic import ValidationError
    from test_plugin_quality import REVISION

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models.plugin_quality import PluginQualityResult

    root, request, assessments, presentation = _plugin(tmp_path)
    passed = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    marker = "api_key=synthetic-late-fixture"
    path = root / "plugin.json"
    original = path.read_text()
    manifest = json.loads(original)
    manifest["description"] = marker
    path.write_text(json.dumps(manifest))
    capture = service.validate_plugin_package(root, source_revision=REVISION, policy=passed.initial_capture.policy)
    raw = passed.model_dump(mode="json")
    raw.update(status="blocked", blocker={"code": "plugin_quality_source_changed", "message": "Changed."})
    if field == "initial_capture":
        raw.update(children=[], presentation=None, final_capture=None)
        raw["blocker"]["code"] = "plugin_quality_root_mismatch"
    raw[field] = capture.model_dump(mode="json")
    for value in (raw, passed.model_copy(update=raw)):
        with pytest.raises(ValidationError, match="captured descriptions"):
            PluginQualityResult.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality.v1", raw)
    path.write_text(original)
    validate = service.validate_plugin_package
    calls = 0

    def change_at_final(path: Path, *, source_revision: str, policy: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            (path / "plugin.json").write_text(json.dumps(manifest))
        return validate(path, source_revision=source_revision, policy=policy)

    monkeypatch.setattr(service, "validate_plugin_package", change_at_final)
    result = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert calls == 2 and result.blocker.code == "plugin_quality_input_invalid"
    assert marker not in result.model_dump_json() and result.initial_capture is None


@pytest.mark.parametrize("field", ["statement", "reason", "owner", "scenario_set_id", "case_id", "claim_id", "gap_id"])
def test_unsafe_coverage_text_never_enters_a_plugin_receipt(
    tmp_path: Path, field: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject synthetic sensitive text before retaining request or later blocker evidence."""
    from pydantic import ValidationError

    from skills_sdk.core.errors import ContractError
    from skills_sdk.core.schema_registry import SchemaRegistry
    from skills_sdk.models.plugin_quality import PluginQualityRequest

    root, request, assessments, presentation = _plugin(tmp_path)
    valid = PluginQualityRequest.model_validate(request)
    plan = request["children"][0]["request"]["coverage_plan"]
    marker = "api_key=synthetic-fixture-only"
    if field in {"claim_id", "gap_id"}:
        marker = "sk-synthetic-fixture"
    if field == "claim_id":
        plan["claims"][0]["id"] = marker
        plan["mappings"][0]["claim_id"] = marker
    elif field == "gap_id":
        plan["gaps"] = [{"id": marker, "reason": "Deferred fixture", "owner": "Fixture owner"}]
        plan["mappings"][0]["gap_ids"] = [marker]
    elif field == "scenario_set_id":
        plan[field] = marker
    elif field == "case_id":
        plan["mappings"][0]["case_ids"] = [marker]
    elif field == "statement":
        plan["claims"][0][field] = marker
    else:
        plan["gaps"] = [{"id": "gap-fixture", "reason": "Deferred fixture", "owner": "Fixture owner"}]
        plan["mappings"][0]["gap_ids"] = ["gap-fixture"]
        plan["gaps"][0][field] = marker
    result = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.blocker.code == "plugin_quality_request_invalid"
    assert result.request is None and marker not in result.model_dump_json()
    for value in (request, valid.model_copy(update=request)):
        with pytest.raises(ValidationError):
            PluginQualityRequest.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-quality-request.v1", request)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    assert main(["check-plugin-quality", str(root), "--request", str(path), "--json"]) == 2
    output = capsys.readouterr().out
    assert marker not in output
    assert json.loads(output)["blocker"]["code"] == "plugin_quality_request_invalid"


def test_concurrent_admission_is_bounded_until_cancelled_workers_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overflow never submits work; cancellation cannot release an active worker slot."""
    root, request, assessments, presentation = _plugin(tmp_path)
    entered = threading.Barrier(3)
    release = threading.Event()
    finished = threading.Barrier(3)

    def work(*args: object) -> object:
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        finished.wait(timeout=5)
        return service._block("plugin_quality_request_invalid")

    monkeypatch.setattr(service, "_run_plugin_quality", work)

    async def run() -> None:
        first = asyncio.create_task(service.check_plugin_quality(root, request, assessments=assessments))
        second = asyncio.create_task(service.check_plugin_quality(root, request, assessments=assessments))
        try:
            await asyncio.to_thread(entered.wait, 5)
            overflow = await service.check_plugin_quality(root, request)
            assert overflow.blocker.code == "plugin_quality_capacity_exceeded"
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (
                await service.check_plugin_quality(root, request)
            ).blocker.code == "plugin_quality_capacity_exceeded"
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 5)
            await second

    asyncio.run(run())
    monkeypatch.undo()
    recovered = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert recovered.status == "local_checks_passed"


def test_contract_sized_many_record_assessment_returns_a_result(tmp_path: Path) -> None:
    """An under-eight-MiB review cannot crash composition at a scalar-count limit."""
    root, request, assessments, presentation = _plugin(tmp_path)
    assessment = next(iter(assessments.values()))
    template = next(item for item in assessment["evidence"] if item["ref"] == "SKILL.md")
    added = [{**template, "evidence_id": f"extra-{index}"} for index in range(45_000)]
    assessment["evidence"].extend(added)
    assessment["items"][0]["evidence_ids"].extend(item["evidence_id"] for item in added)
    normalized = ContentReviewAssessment.model_validate(assessment)
    assert len(normalized.model_dump_json().encode()) < CONTENT_REVIEW_ASSESSMENT_MAX_BYTES
    result = asyncio.run(
        service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
    )
    assert result.status == "local_checks_passed"
    wire = json.dumps({f"skills/child-{index}": assessment for index in range(4)}, separators=(",", ":"))
    assert len(wire.encode()) < 32 * 1_048_576
    route._scan_json_structure(wire)


def test_source_capture_does_not_block_the_callers_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real caller continues while the first synchronous filesystem capture waits."""
    root, request, assessments, presentation = _plugin(tmp_path)
    entered, release = threading.Event(), threading.Event()
    capture = service.validate_plugin_package

    def waiting_capture(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(2), "filesystem capture blocked the caller event loop"
        return capture(*args, **kwargs)

    monkeypatch.setattr(service, "validate_plugin_package", waiting_capture)

    async def exercise() -> None:
        task = asyncio.create_task(
            service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
        )
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            if task.done():
                task.result()
            release.set()
            assert (await task).status == "local_checks_passed"
        finally:
            release.set()
            if not task.done():
                await task

    asyncio.run(exercise())


def test_whole_plugin_models_are_publicly_exported() -> None:
    """Aggregate imports expose the same canonical new-family model classes."""
    from skills_sdk.models import PluginQualityRequest, PluginQualityResult
    from skills_sdk.models.plugin_quality import PluginQualityRequest as Request
    from skills_sdk.models.plugin_quality import PluginQualityResult as Result

    assert PluginQualityRequest is Request and PluginQualityResult is Result


def test_cancellation_releases_caller_and_read_only_worker_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation does not pretend that Python can forcibly stop filesystem work."""
    root, request, assessments, presentation = _plugin(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    run = service._run_plugin_quality
    results = []

    def waiting_run(*args: object) -> object:
        entered.set()
        try:
            assert release.wait(2)
            result = run(*args)
            results.append(result)
            return result
        finally:
            finished.set()

    monkeypatch.setattr(service, "_run_plugin_quality", waiting_run)

    async def exercise() -> None:
        task = asyncio.create_task(
            service.check_plugin_quality(root, request, assessments=assessments, presentation_request=presentation)
        )
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 15)

    asyncio.run(exercise())
    assert results[0].status == "local_checks_passed" and results[0].mutation_performed is False


def test_documented_optional_inputs_retain_actual_first_stop_codes(tmp_path: Path) -> None:
    """Omitted assessments stop at the child; omitted presentation stops after passing children."""
    root, request, assessments, _presentation = _plugin(tmp_path)
    no_assessments = asyncio.run(service.check_plugin_quality(root, request))
    assert no_assessments.blocker.code == "plugin_quality_child_blocked"
    assert len(no_assessments.children) == 1 and no_assessments.children[0].status == "blocked"
    no_presentation = asyncio.run(service.check_plugin_quality(root, request, assessments=assessments))
    assert no_presentation.blocker.code == "plugin_quality_presentation_missing"
