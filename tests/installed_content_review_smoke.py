"""Wheel-only content-review evidence and controlled offline callback proof."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import subprocess
import sys
import time
from collections import UserDict
from multiprocessing.connection import Connection
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

from pydantic import ValidationError

import skills_sdk
from skills_sdk.cli.main import _UnsupportedContextRead
from skills_sdk.cli.main import main as cli_main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import ContentReviewInput, execute_content_review
from skills_sdk.evaluation import content_review as review_module
from skills_sdk.models import ContentReviewAssessment, ContentReviewExecutionResult, ContentReviewResult
from skills_sdk.models.safety import PackageSafetyReviewer
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity
from skills_sdk.validation import assess_content_review


class FixtureReviewer:
    """Test-only semantic comparison of this script's two known descriptions."""

    reviewer = PackageSafetyReviewer(adapter_id="smoke-review", adapter_version_or_digest="1", method="static_analysis")

    async def review(self, inputs: ContentReviewInput) -> object:
        document = next(item for item in inputs.documents if item.path == "SKILL.md")
        references = [item for item in inputs.documents if item.path.startswith("references/")]
        mismatch = b"Deletes production" in document.content
        return {
            "candidate": inputs.candidate.model_dump(mode="json"),
            "reviewer": self.reviewer.model_dump(mode="json"),
            "evidence": [
                {
                    "evidence_id": "entry" if item.path == "SKILL.md" else "guide",
                    "kind": "static_analysis",
                    "ref": item.path,
                    "sha256": item.sha256,
                }
                for item in [document, *references]
            ],
            "items": [
                {
                    "dimension": dimension,
                    "path": "SKILL.md",
                    "status": "finding" if dimension == "description" and mismatch else "clear",
                    "rationale": "Known fixture comparison completed.",
                    "evidence_ids": ["entry"],
                }
                for dimension in ("description", "progressive_disclosure")
            ]
            + [
                {
                    "dimension": "reference",
                    "path": item.path,
                    "status": "clear",
                    "rationale": "Known fixture reference captured.",
                    "evidence_ids": ["guide"],
                }
                for item in references
            ],
        }


class MetadataFailureReviewer(FixtureReviewer):
    @property
    def reviewer(self) -> PackageSafetyReviewer:
        raise RuntimeError("private metadata diagnostic")


class BlockingReviewer(FixtureReviewer):
    def __init__(self, started: Path) -> None:
        self.started = started

    async def review(self, inputs: ContentReviewInput) -> object:
        self.started.write_text(str(time.monotonic()))
        while True:
            time.sleep(60)


class SlowStartingBlockingReviewer(BlockingReviewer):
    @property
    def reviewer(self) -> PackageSafetyReviewer:
        time.sleep(4)
        return FixtureReviewer.reviewer


class CompletedReviewer(FixtureReviewer):
    def __init__(self, finished: Path, duration: float, fail: bool = False) -> None:
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


def _assert_delayed_observation(root: Path) -> None:
    original_read = review_module._read_worker
    for duration, fail, code in (
        (0.05, False, None),
        (0.5, False, "content_review_timeout"),
        (0.05, True, "content_review_adapter_failed"),
        (0.5, True, "content_review_timeout"),
    ):
        finished = root.parent / f"finished-{duration}-{fail}"

        async def delayed_read(
            channel: review_module.socket.socket, finished: Path = finished
        ) -> review_module._WorkerObservation:
            async with asyncio.timeout(10):
                while not finished.exists():
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)
            return await original_read(channel)

        existing = {child.pid for child in review_module.multiprocessing.active_children()}
        with (
            patch.object(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.2),
            patch.object(review_module, "_read_worker", delayed_read),
        ):
            result = asyncio.run(
                execute_content_review(
                    root, source_revision="1" * 40, adapter=CompletedReviewer(finished, duration, fail)
                )
            )
        assert result.status == ("blocked" if code else "pass") and result.adapter_invoked is True
        if code:
            assert result.findings[0].code == code
        assert "private callback" not in result.model_dump_json()
        assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer())).status == "pass"
    )


def _assert_deadline_and_byte_text(root: Path, assessment: ContentReviewAssessment) -> None:
    malformed = assessment.model_dump(mode="python")
    malformed["items"][0]["rationale"] = b"Known fixture comparison completed."
    _assert_contract_rejects(ContentReviewAssessment, "content-review-assessment.v1", malformed)
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    malformed = assessment.model_dump(mode="python")
    forged = assessment.evidence[0].model_copy(update={"sha256": "invalid"})
    malformed["evidence"] = (item for item in (forged, *assessment.evidence[1:]))
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    for adapter_type in (BlockingReviewer, SlowStartingBlockingReviewer):
        marker = root.parent / "callback-started"
        existing = {child.pid for child in review_module.multiprocessing.active_children()}
        with patch.object(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.2):
            timed_out = asyncio.run(
                execute_content_review(root, source_revision="1" * 40, adapter=adapter_type(marker))
            )
            finished = time.monotonic()
        # Startup has its own budget; measure only callback observation and cleanup.
        assert finished - float(marker.read_text()) < 3
        assert timed_out.status == "blocked" and timed_out.adapter_invoked is True
        assert timed_out.findings[0].code == "content_review_timeout"
        assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer())).status == "pass"
    )


class FailingAssessmentSerializer(ContentReviewAssessment):
    dump_error: ClassVar[type[Exception]] = RuntimeError

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise self.dump_error("private serializer diagnostic")


class OrdinarySerializerError(Exception):
    """Caller-defined failure outside built-in exception families."""


class TypedReviewer(FixtureReviewer):
    def __init__(self, canonical: bool) -> None:
        self.canonical = canonical

    async def review(self, inputs: ContentReviewInput) -> object:
        model = ContentReviewAssessment if self.canonical else FailingAssessmentSerializer
        return model.model_validate(await super().review(inputs))


class NestedSerializerFailure(PackageSafetyReviewer):
    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise OSError("private nested serializer diagnostic")


class OrdinaryTransferFailure(Exception):
    """Caller-defined ordinary transfer failure."""


class CustomTransferFailureReviewer:
    def __reduce_ex__(self, protocol: int) -> object:
        raise OrdinaryTransferFailure("private transfer diagnostic")


class OversizedMetadataReviewer(FixtureReviewer):
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    @property
    def reviewer(self) -> PackageSafetyReviewer:
        review_module._REVIEW_OUTPUT_LIMIT = 256
        return PackageSafetyReviewer(adapter_id="a" * 300, adapter_version_or_digest="1", method="static_analysis")

    async def review(self, inputs: ContentReviewInput) -> object:
        self.marker.write_text("invoked")
        return await super().review(inputs)


def _assert_host_boundary_recovery(root: Path, assessment: ContentReviewAssessment) -> None:
    malformed = assessment.model_dump(mode="json")
    malformed["reviewer"] = NestedSerializerFailure.model_validate(malformed["reviewer"])
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=malformed)
    assert rejected.findings[0].code == "invalid_content_review"
    assert "private nested serializer" not in rejected.model_dump_json()
    marker = root.parent / "metadata-callback"
    existing = {child.pid for child in review_module.multiprocessing.active_children()}
    for adapter, code in (
        (CustomTransferFailureReviewer(), "unsupported_content_review_isolation"),
        (OversizedMetadataReviewer(marker), "content_review_output_limit"),
    ):
        result = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=adapter))
        assert result.findings[0].code == code and result.adapter_invoked is False
        assert "private transfer" not in result.model_dump_json() and not marker.exists()
        assert {child.pid for child in review_module.multiprocessing.active_children()} == existing
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer())).status == "pass"
    )


def _assert_assessment_size_recovery(root: Path, assessment: ContentReviewAssessment) -> None:
    path = root.parent / "large-review.json"
    data = assessment.model_dump(mode="json")
    command = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        "review-content",
        str(root),
        "--source-revision",
        "1" * 40,
        "--assessment",
        str(path),
        "--json",
    ]
    for repetitions, expected, code in ((90_000, 0, None), (650_000, 2, "content_review_input_limit"), (1, 0, None)):
        data["items"][0]["rationale"] = "Known review. " * repetitions
        path.write_text(json.dumps(data))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == expected and "Traceback" not in result.stderr
        payload = json.loads(result.stdout)
        if code:
            assert payload["code"] == code
        else:
            assert payload["status"] == "pass"
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"


def _assert_contract_rejects(
    model: type[ContentReviewResult] | type[ContentReviewExecutionResult] | type[ContentReviewAssessment],
    schema: str,
    data: object,
) -> None:
    try:
        model.model_validate(data)
    except ValidationError:
        pass
    else:
        raise AssertionError("malformed content-review proof accepted")
    try:
        SchemaRegistry().validate(schema, data)
    except ContractError:
        pass
    else:
        raise AssertionError("malformed content-review proof accepted by registry")


def _assert_contract_boundaries(root: Path, assessment: ContentReviewAssessment) -> None:
    malformed = assessment.model_dump(mode="json")
    malformed["reviewer"] = assessment.reviewer.model_copy(update={"method": "invalid"})
    _assert_contract_rejects(ContentReviewAssessment, "content-review-assessment.v1", malformed)
    finding = SkillPackageFinding(
        code="fixture_blocked", severity=ValidationSeverity.BLOCKER, message="Blocked fixture"
    )
    blocked = {"candidate": None, "status": "blocked", "findings": [finding.model_dump(mode="json")]}
    _assert_contract_rejects(ContentReviewResult, "content-review.v1", {**blocked, "promotion_authorized": 0})
    _assert_contract_rejects(
        ContentReviewExecutionResult, "content-review-execution.v1", {**blocked, "adapter_invoked": "false"}
    )
    _assert_contract_rejects(
        ContentReviewExecutionResult, "content-review-execution.v1", {**blocked, "adapter_invoked": True}
    )
    for error in (RuntimeError, OSError, OrdinarySerializerError):
        FailingAssessmentSerializer.dump_error = error
        failing = FailingAssessmentSerializer.model_validate(assessment.model_dump(mode="json"))
        rejected = assess_content_review(root, source_revision="1" * 40, assessment=failing)
        assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
        assert "private serializer" not in rejected.model_dump_json()
    metadata = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=MetadataFailureReviewer()))
    assert metadata.findings[0].code == "invalid_content_review_adapter" and metadata.adapter_invoked is False
    assert "private metadata" not in metadata.model_dump_json()
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"
    rejected_worker = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=TypedReviewer(False)))
    assert rejected_worker.findings[0].code == "invalid_content_review" and rejected_worker.adapter_invoked is True
    assert "private serializer" not in rejected_worker.model_dump_json()
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=TypedReviewer(True))).status
        == "pass"
    )
    recovered = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer()))
    assert recovered.status == "pass" and recovered.adapter_invoked is True
    _assert_new_receipt_invariants(root, assessment, recovered)


def _assert_new_receipt_invariants(
    root: Path, assessment: ContentReviewAssessment, execution: ContentReviewExecutionResult
) -> None:
    malformed = execution.model_dump(mode="json")
    malformed["status"] = "blocked"
    malformed["adapter_invoked"] = False
    blocker = SkillPackageFinding(
        code="fixture_blocked", severity=ValidationSeverity.BLOCKER, message="Blocked fixture"
    )
    malformed["findings"] = [blocker.model_dump(mode="json")]
    _assert_contract_rejects(ContentReviewExecutionResult, "content-review-execution.v1", malformed)
    for model, schema in (
        (ContentReviewResult, "content-review.v1"),
        (ContentReviewExecutionResult, "content-review-execution.v1"),
    ):
        warning_only = {
            "candidate": None,
            "status": "blocked",
            "findings": [{**blocker.model_dump(mode="json"), "severity": "warning"}],
        }
        _assert_contract_rejects(model, schema, warning_only)
        corrected = {**warning_only, "findings": [blocker.model_dump(mode="json")]}
        model.model_validate(corrected)
        SchemaRegistry().validate(schema, corrected)
        references = (value for value in (b"docs/a.md",))
        streaming_finding = {**blocker.model_dump(mode="python"), "evidence_refs": references}
        malformed = {**corrected, "findings": [streaming_finding]}
        _assert_contract_rejects(model, schema, malformed)
        assert list(references) == [b"docs/a.md"]
        for materialized in (["docs/a.md"], ("docs/a.md",)):
            recovered_finding = {**blocker.model_dump(mode="python"), "evidence_refs": materialized}
            recovered = {**corrected, "findings": [recovered_finding]}
            assert model.model_validate(recovered).findings[0].evidence_refs == ("docs/a.md",)
            SchemaRegistry().validate(schema, recovered)
    streaming = assessment.model_dump(mode="json")
    iterator = iter(streaming["items"])
    streaming["items"] = iterator
    _assert_contract_rejects(ContentReviewAssessment, "content-review-assessment.v1", streaming)
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=streaming)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert list(iterator) == assessment.model_dump(mode="json")["items"]
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"
    SchemaRegistry().validate("content-review-execution.v1", execution.model_dump(mode="json"))


def _assert_reference_binding(root: Path, cwd: Path, assessment: ContentReviewAssessment) -> None:
    malformed = assessment.model_dump(mode="json")
    malformed["evidence"] = [item for item in malformed["evidence"] if item["ref"] == "SKILL.md"]
    malformed["items"][-1]["evidence_ids"] = ["entry"]
    try:
        ContentReviewAssessment.model_validate(malformed)
    except ValidationError:
        pass
    else:
        raise AssertionError("cross-file evidence accepted by direct model")
    try:
        SchemaRegistry().validate("content-review-assessment.v1", malformed)
    except ContractError:
        pass
    else:
        raise AssertionError("cross-file evidence accepted by registry")
    result = assess_content_review(root, source_revision="1" * 40, assessment=malformed)
    assert result.status == "blocked" and result.findings[0].code == "invalid_content_review"
    path = cwd / "borrowed-evidence.json"
    path.write_text(json.dumps(malformed))
    command = [
        sys.executable,
        "-m",
        "skills_sdk.cli.main",
        "review-content",
        str(root),
        "--source-revision",
        "1" * 40,
        "--assessment",
        str(path),
    ]
    for json_output in (False, True):
        process = subprocess.run(
            [*command, "--json"] if json_output else command, cwd=cwd, capture_output=True, text=True, check=False
        )
        assert process.returncode == 2, process.stderr
        assert "invalid_content_review" in process.stdout and "Traceback" not in process.stderr


def _assert_mapping_and_finding_recovery(root: Path, assessment: ContentReviewAssessment) -> None:
    malformed = assessment.model_dump(mode="json")
    malformed["candidate"] = UserDict(
        {**malformed["candidate"], "package_id": assessment.candidate.package_id.encode()}
    )
    _assert_contract_rejects(ContentReviewAssessment, "content-review-assessment.v1", malformed)
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=malformed)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    finding = SkillPackageFinding(
        code="fixture_blocked", severity=ValidationSeverity.BLOCKER, message="Blocked fixture"
    )
    for model, schema in (
        (ContentReviewResult, "content-review.v1"),
        (ContentReviewExecutionResult, "content-review-execution.v1"),
    ):
        payload = {
            "candidate": None,
            "status": "blocked",
            "findings": (finding.model_copy(update={"code": "INVALID"}),),
        }
        _assert_contract_rejects(model, schema, payload)
        corrected = {**payload, "findings": (finding,)}
        model.model_validate(corrected)
        SchemaRegistry().validate(schema, model.model_validate(corrected).model_dump(mode="json"))
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"


def _daemon_review(root: Path, channel: Connection) -> None:
    result = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer()))
    channel.send((result.status, result.adapter_invoked, result.findings[0].code))
    channel.close()


def _assert_daemon_recovery(root: Path) -> None:
    context = review_module.multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(target=_daemon_review, args=(root, child), daemon=True)
    try:
        worker.start()
        child.close()
        assert parent.poll(30), "daemon blocker did not return"
        assert parent.recv() == ("blocked", False, "unsupported_content_review_isolation")
        worker.join(5)
        assert worker.exitcode == 0
    finally:
        parent.close()
        child.close()
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        worker.close()
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer())).status == "pass"
    )


def main() -> int:
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-content-review-") as directory:
        cwd = Path(directory).resolve()
        root = cwd / "review-smoke"
        root.mkdir()
        (root / "references").mkdir()
        (root / "references/guide.md").write_text("# Supplied fixture guide\nRead examples only.\n")
        skill = root / "SKILL.md"
        template = (
            "---\nname: review-smoke\ndescription: {description}\n---\n# Read examples\nOnly read supplied examples.\n"
        )
        for description, expected in (("Deletes production", "blocked"), ("Reads supplied examples", "pass")):
            skill.write_text(template.format(description=description))
            original = skill.read_bytes()
            result = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer()))
            assert result.status == expected
            assert result.adapter_invoked is True
            assert result.review is not None and result.review.assessment is not None
            _assert_reference_binding(root, cwd, result.review.assessment)
            assessment = cwd / "assessment.json"
            assessment.write_text(result.review.assessment.model_dump_json())
            if expected == "pass":
                _assert_deadline_and_byte_text(root, result.review.assessment)
                _assert_delayed_observation(root)
                _assert_unsupported_read_recovery(root, assessment)
                _assert_contract_boundaries(root, result.review.assessment)
                _assert_host_boundary_recovery(root, result.review.assessment)
                _assert_assessment_size_recovery(root, result.review.assessment)
                _assert_mapping_and_finding_recovery(root, result.review.assessment)
                _assert_daemon_recovery(root)
            command = [
                sys.executable,
                "-m",
                "skills_sdk.cli.main",
                "review-content",
                str(root),
                "--source-revision",
                "1" * 40,
                "--assessment",
                str(assessment),
            ]
            for json_output in (False, True):
                process = subprocess.run(
                    [*command, "--json"] if json_output else command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert process.returncode == (0 if expected == "pass" else 2), process.stderr
                assert "Traceback" not in process.stderr
                if json_output:
                    assert json.loads(process.stdout)["status"] == expected
                else:
                    assert process.stdout.startswith(f"review-content: {expected} (")
                assert skill.read_bytes() == original
    print("installed content-review API, offline adapter and supplied CLI: pass")
    return 0


def _assert_unsupported_read_recovery(root: Path, assessment: Path) -> None:
    command = ["review-content", str(root), "--source-revision", "1" * 40, "--assessment", str(assessment)]
    for json_output in (False, True):
        arguments = [*command, "--json"] if json_output else command
        captured = io.StringIO()
        with (
            patch("skills_sdk.cli.main._read_intake_context", side_effect=_UnsupportedContextRead("unavailable")),
            contextlib.redirect_stdout(captured),
        ):
            assert cli_main(arguments) == 2
        if json_output:
            blocker = json.loads(captured.getvalue())
            assert blocker["code"] == "unsupported_context_read"
            SchemaRegistry().validate("blocker.v1", blocker)
        else:
            assert "unsupported_context_read" in captured.getvalue()
        recovered = io.StringIO()
        with contextlib.redirect_stdout(recovered):
            assert cli_main(arguments) == 0
        if json_output:
            assert json.loads(recovered.getvalue())["status"] == "pass"
        else:
            assert recovered.getvalue().startswith("review-content: pass (")


if __name__ == "__main__":
    raise SystemExit(main())
