"""Bounded final-batch regressions for whole-plugin workflow consumers."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from test_plugin_quality import _plugin

from skills_sdk.cli import plugin_quality as route
from skills_sdk.evaluation import plugin_quality as service
from skills_sdk.models.content_review import CONTENT_REVIEW_ASSESSMENT_MAX_BYTES, ContentReviewAssessment


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
