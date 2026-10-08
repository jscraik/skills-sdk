"""Actual trusted offline callback proof, not generic semantic-accuracy proof."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import content_review as review_module
from skills_sdk.evaluation.content_review import ContentReviewInput, execute_content_review
from skills_sdk.models.content_review import CONTENT_REVIEW_ASSESSMENT_MAX_BYTES, ContentReviewAssessment
from skills_sdk.models.safety import PackageSafetyReviewer

REVISION = "1" * 40


class OrdinaryTransferFailure(Exception):
    """An arbitrary caller-defined pickling failure."""


class CustomTransferFailureReviewer:
    def __reduce_ex__(self, protocol: int) -> object:
        raise OrdinaryTransferFailure("private transfer diagnostic")


def test_custom_transfer_failure_is_typed_and_recovers(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    result = asyncio.run(
        execute_content_review(root, source_revision=REVISION, adapter=CustomTransferFailureReviewer())
    )
    assert result.findings[0].code == "unsupported_content_review_isolation" and result.adapter_invoked is False
    assert "private transfer" not in result.model_dump_json()
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class OversizedMetadataReviewer:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    @property
    def reviewer(self) -> PackageSafetyReviewer:
        review_module._REVIEW_WIRE_LIMIT = 256
        return PackageSafetyReviewer(adapter_id="a" * 300, adapter_version_or_digest="1", method="static_analysis")

    async def review(self, inputs: ContentReviewInput) -> object:
        self.marker.write_text("invoked")
        return await FixtureReviewer().review(inputs)


def test_oversized_reviewer_metadata_never_invokes_callback(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    marker = tmp_path / "callback-started"
    adapter = OversizedMetadataReviewer(marker)
    result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    assert result.findings[0].code == "content_review_output_limit" and result.adapter_invoked is False
    assert not marker.exists()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


def test_daemon_spawn_context_blocks_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    with monkeypatch.context() as context:
        context.setitem(review_module.multiprocessing.current_process()._config, "daemon", True)
        result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer()))
    assert result.status == "blocked" and result.adapter_invoked is False
    assert result.findings[0].code == "unsupported_content_review_isolation"
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class BlockingReviewer:
    reviewer = PackageSafetyReviewer(
        adapter_id="fixture-review", adapter_version_or_digest="1", method="static_analysis"
    )

    def __init__(self, started: Path) -> None:
        self.started = started

    async def review(self, inputs: ContentReviewInput) -> object:
        self.started.write_text(str(time.monotonic()))
        time.sleep(2)
        return await FixtureReviewer().review(inputs)


class SlowStartingBlockingReviewer(BlockingReviewer):
    @property
    def reviewer(self) -> PackageSafetyReviewer:
        time.sleep(2)
        return BlockingReviewer.reviewer


@pytest.mark.parametrize("adapter_type", [BlockingReviewer, SlowStartingBlockingReviewer])
def test_blocking_callback_exceeding_deadline_blocks_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adapter_type: type[BlockingReviewer]
) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    started = tmp_path / "callback-started"
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    with monkeypatch.context() as context:
        context.setattr(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.2, raising=False)
        rejected = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter_type(started)))
        finished = time.monotonic()
    # Exclude interpreter startup and metadata discovery from the callback deadline.
    assert finished - float(started.read_text()) < 1.5
    assert rejected.status == "blocked" and rejected.adapter_invoked is True
    assert rejected.findings[0].code == "content_review_timeout"
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class FixtureReviewer:
    """Test-only review of one known semantic mismatch in supplied fixture bytes."""

    reviewer = PackageSafetyReviewer(
        adapter_id="fixture-review", adapter_version_or_digest="1", method="static_analysis"
    )

    def __init__(self) -> None:
        self.calls = 0

    async def review(self, inputs: ContentReviewInput) -> object:
        self.calls += 1
        documents = {item.path: item for item in inputs.documents}
        mismatch = b"Deletes production" in documents["SKILL.md"].content
        paths = [("description", "SKILL.md"), ("progressive_disclosure", "SKILL.md")]
        paths.extend(("reference", path) for path in documents if path.startswith("references/"))
        return {
            "candidate": inputs.candidate.model_dump(mode="json"),
            "reviewer": self.reviewer.model_dump(mode="json"),
            "evidence": [
                {
                    "evidence_id": "entry",
                    "kind": "static_analysis",
                    "ref": "SKILL.md",
                    "sha256": documents["SKILL.md"].sha256,
                }
            ],
            "items": [
                {
                    "dimension": dimension,
                    "path": path,
                    "status": "finding" if dimension == "description" and mismatch else "clear",
                    "rationale": "Known fixture comparison completed.",
                    "evidence_ids": ["entry"],
                }
                for dimension, path in paths
            ],
        }


class LargeAssessmentReviewer(FixtureReviewer):
    def __init__(self, unit: str) -> None:
        super().__init__()
        self.unit = unit

    async def review(self, inputs: ContentReviewInput) -> object:
        data = await super().review(inputs)
        assessment = ContentReviewAssessment.model_validate(data)
        baseline = len(assessment.model_dump_json().encode("utf-8"))
        original = assessment.items[0].rationale
        available = CONTENT_REVIEW_ASSESSMENT_MAX_BYTES - baseline + len(original.encode("utf-8"))
        count, remainder = divmod(available, len(self.unit.encode("utf-8")))
        item = assessment.items[0].model_copy(update={"rationale": self.unit * count + "x" * remainder})
        assessment = ContentReviewAssessment.model_validate(
            assessment.model_copy(update={"items": (item, *assessment.items[1:])})
        )
        assert len(assessment.model_dump_json().encode("utf-8")) == CONTENT_REVIEW_ASSESSMENT_MAX_BYTES
        return assessment


@pytest.mark.parametrize("unit", ["x ", "é "])
def test_public_assessment_limit_fits_worker_wire_and_recovers(tmp_path: Path, unit: str) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=LargeAssessmentReviewer(unit)))
    assert result.status == "pass", result.findings
    assert result.adapter_invoked is True
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class StartupDelayReviewer(FixtureReviewer):
    def __init__(self, finished: Path, fail: bool = False) -> None:
        super().__init__()
        self.finished = finished
        self.fail = fail

    @property
    def reviewer(self) -> PackageSafetyReviewer:
        time.sleep(0.5)
        self.finished.write_text("metadata completed")
        if self.fail:
            raise OSError("private startup diagnostic")
        return FixtureReviewer.reviewer


@pytest.mark.parametrize("fail", [False, True])
def test_delayed_parent_observation_preserves_startup_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    finished = tmp_path / "startup-finished"
    original_read = review_module._read_worker

    async def delayed_read(
        channel: review_module.socket.socket, launched_at: float
    ) -> review_module._WorkerObservation:
        async with asyncio.timeout(10):
            while not finished.exists():
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        return await original_read(channel, launched_at)

    with monkeypatch.context() as context:
        context.setattr(review_module, "_REVIEW_STARTUP_TIMEOUT_SECONDS", 0.2)
        context.setattr(review_module, "_read_worker", delayed_read)
        result = asyncio.run(
            execute_content_review(root, source_revision=REVISION, adapter=StartupDelayReviewer(finished, fail))
        )
    assert result.status == "blocked" and result.findings[0].code == "content_review_timeout"
    assert result.adapter_invoked is (not fail)
    assert "private startup" not in result.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class CompletedReviewer(FixtureReviewer):
    def __init__(self, finished: Path, duration: float, fail: bool = False) -> None:
        super().__init__()
        self.finished = finished
        self.duration = duration
        self.fail = fail

    async def review(self, inputs: ContentReviewInput) -> object:
        await asyncio.sleep(self.duration)
        result = await super().review(inputs)
        self.finished.write_text("finished")
        if self.fail:
            raise OSError("private callback diagnostic")
        return result


class NonCanonicalAssessment(ContentReviewAssessment):
    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise OSError("private serializer diagnostic")


class TypedReviewer(FixtureReviewer):
    def __init__(self, canonical: bool) -> None:
        super().__init__()
        self.canonical = canonical

    async def review(self, inputs: ContentReviewInput) -> object:
        model = ContentReviewAssessment if self.canonical else NonCanonicalAssessment
        return model.model_validate(await super().review(inputs))


def test_worker_rejects_custom_serializers_and_accepts_canonical_model(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    rejected = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=TypedReviewer(False)))
    assert rejected.status == "blocked" and rejected.adapter_invoked is True
    assert rejected.findings[0].code == "invalid_content_review"
    assert "private serializer" not in rejected.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=TypedReviewer(True))).status
        == "pass"
    )


@pytest.mark.parametrize(
    "duration, fail, expected_code",
    [
        (0.05, False, None),
        (0.5, False, "content_review_timeout"),
        (0.05, True, "content_review_adapter_failed"),
        (0.5, True, "content_review_timeout"),
    ],
)
def test_delayed_parent_observation_preserves_callback_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duration: float, fail: bool, expected_code: str | None
) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    finished = tmp_path / "finished"
    original_read = review_module._read_worker

    async def delayed_read(
        channel: review_module.socket.socket, launched_at: float
    ) -> review_module._WorkerObservation:
        async with asyncio.timeout(10):
            while not finished.exists():
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        return await original_read(channel, launched_at)

    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    with monkeypatch.context() as context:
        context.setattr(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.2)
        context.setattr(review_module, "_read_worker", delayed_read)
        result = asyncio.run(
            execute_content_review(root, source_revision=REVISION, adapter=CompletedReviewer(finished, duration, fail))
        )
    assert result.status == ("blocked" if expected_code else "pass") and result.adapter_invoked is True
    if expected_code:
        assert result.findings[0].code == expected_code
    assert "private callback" not in result.model_dump_json()
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


def test_adapter_observes_current_bytes_and_corrected_input(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    skill = root / "SKILL.md"
    template = "---\nname: review-example\ndescription: {description}\n---\n# Read examples\nOnly read examples.\n"
    skill.write_text(template.format(description="Deletes production"))
    adapter = FixtureReviewer()
    rejected = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    assert rejected.status == "blocked"
    assert rejected.adapter_invoked is True
    assert rejected.findings[0].code == "content_review_unresolved"
    skill.write_text(template.format(description="Reads supplied examples"))
    accepted = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    assert accepted.status == "pass"
    assert accepted.adapter_invoked is True
    assert accepted.candidate != rejected.candidate
    assert accepted.assessment_sha256 is not None
    # A spawned adapter owns a private copy; receipts prove the two invocations.
    assert adapter.calls == 0
    assert "Deletes production" not in accepted.model_dump_json()
    SchemaRegistry().validate("content-review-execution.v1", accepted.model_dump(mode="json"))


def test_invalid_source_never_invokes_adapter(tmp_path: Path) -> None:
    adapter = FixtureReviewer()
    result = asyncio.run(execute_content_review(tmp_path / "absent", source_revision=REVISION, adapter=adapter))
    assert result.status == "blocked"
    assert result.adapter_invoked is False
    assert adapter.calls == 0


class FailingReviewer(FixtureReviewer):
    async def review(self, inputs: ContentReviewInput) -> object:
        raise RuntimeError("private fixture diagnostic must not escape")


class ChangingReviewer(FixtureReviewer):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    async def review(self, inputs: ContentReviewInput) -> object:
        result = await super().review(inputs)
        self.path.write_text(self.path.read_text() + "Changed after review capture.\n")
        return result


def test_candidate_drift_during_callback_blocks(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    skill = root / "SKILL.md"
    skill.write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=ChangingReviewer(skill)))
    assert result.status == "blocked"
    assert any(item.code == "content_review_candidate_changed" for item in result.findings)


def test_adapter_failure_is_redacted_and_correctable(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    rejected = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FailingReviewer()))
    assert rejected.findings[0].code == "content_review_adapter_failed"
    assert "private fixture diagnostic" not in rejected.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class WaitingReviewer(FixtureReviewer):
    def __init__(self, started: Path) -> None:
        super().__init__()
        self.started = started

    async def review(self, inputs: ContentReviewInput) -> object:
        self.started.write_text("started")
        await asyncio.Event().wait()


def test_caller_cancellation_cancels_owned_callback(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")

    async def run() -> None:
        existing = {child.pid for child in review_module.multiprocessing.active_children()}
        adapter = WaitingReviewer(tmp_path / "started")
        task = asyncio.create_task(execute_content_review(root, source_revision=REVISION, adapter=adapter))
        async with asyncio.timeout(5):
            while not adapter.started.exists():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert {child.pid for child in review_module.multiprocessing.active_children()} == existing

    asyncio.run(run())


class NeverReturningReviewer(FixtureReviewer):
    def __init__(self, started: Path) -> None:
        super().__init__()
        self.started = started

    async def review(self, inputs: ContentReviewInput) -> object:
        self.started.write_text(str(time.monotonic()))
        while True:
            time.sleep(60)


class BlockingMetadataReviewer(FixtureReviewer):
    @property
    def reviewer(self) -> PackageSafetyReviewer:
        time.sleep(60)
        return FixtureReviewer.reviewer


@pytest.mark.parametrize("adapter_type", [NeverReturningReviewer, BlockingMetadataReviewer])
def test_nonreturning_worker_is_bounded_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adapter_type: type[FixtureReviewer]
) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    monkeypatch.setattr(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(review_module, "_REVIEW_STARTUP_TIMEOUT_SECONDS", 5)
    started = tmp_path / "callback-started"
    adapter = NeverReturningReviewer(started) if adapter_type is NeverReturningReviewer else adapter_type()
    result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    finished = time.monotonic()
    if isinstance(adapter, NeverReturningReviewer):
        assert finished - float(started.read_text()) < 1.5
    else:
        assert not started.exists()
    assert result.status == "blocked" and result.findings[0].code == "content_review_timeout"
    assert result.adapter_invoked is isinstance(adapter, NeverReturningReviewer)
    assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


def test_unsupported_adapter_transfer_blocks_without_invocation_and_recovers(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    adapter = FixtureReviewer()
    adapter.untransferable = lambda: None
    result = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    assert result.status == "blocked" and result.adapter_invoked is False
    assert result.findings[0].code == "unsupported_content_review_isolation"
    assert adapter.calls == 0
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


class MalformedReviewer(FixtureReviewer):
    async def review(self, inputs: ContentReviewInput) -> object:
        return {"private": "fixture diagnostic must not escape"}


class MismatchedReviewer(FixtureReviewer):
    async def review(self, inputs: ContentReviewInput) -> object:
        result = await super().review(inputs)
        assert isinstance(result, dict)
        result["reviewer"] = PackageSafetyReviewer(
            adapter_id="different-review", adapter_version_or_digest="1", method="static_analysis"
        ).model_dump(mode="json")
        return result


class MetadataFailureReviewer(FixtureReviewer):
    def __init__(self, field: str, error: type[Exception]) -> None:
        super().__init__()
        self.field = field
        self.error = error

    def __getattribute__(self, name: str) -> object:
        if name in {"reviewer", "review"} and name == object.__getattribute__(self, "field"):
            raise object.__getattribute__(self, "error")("private metadata diagnostic")
        return object.__getattribute__(self, name)


@pytest.mark.parametrize("field", ["reviewer", "review"])
@pytest.mark.parametrize("error", [RuntimeError, KeyError])
def test_metadata_failure_is_redacted_and_recovers(tmp_path: Path, field: str, error: type[Exception]) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    rejected = asyncio.run(
        execute_content_review(root, source_revision=REVISION, adapter=MetadataFailureReviewer(field, error))
    )
    assert rejected.status == "blocked" and rejected.adapter_invoked is False
    assert rejected.findings[0].code == "invalid_content_review_adapter"
    assert "private metadata" not in rejected.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )


@pytest.mark.parametrize(
    ("adapter", "code"),
    [(MalformedReviewer(), "invalid_content_review"), (MismatchedReviewer(), "content_review_reviewer_mismatch")],
)
def test_invalid_callback_result_blocks_and_recovers(tmp_path: Path, adapter: FixtureReviewer, code: str) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")
    rejected = asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=adapter))
    assert rejected.status == "blocked"
    assert rejected.adapter_invoked is True
    assert code in {item.code for item in rejected.findings}
    assert "fixture diagnostic" not in rejected.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision=REVISION, adapter=FixtureReviewer())).status == "pass"
    )
