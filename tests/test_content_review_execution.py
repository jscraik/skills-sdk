"""Actual trusted offline callback proof, not generic semantic-accuracy proof."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.content_review import ContentReviewInput, execute_content_review
from skills_sdk.models.safety import PackageSafetyReviewer

REVISION = "1" * 40


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
    assert adapter.calls == 2
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
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def review(self, inputs: ContentReviewInput) -> object:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


def test_caller_cancellation_cancels_owned_callback(tmp_path: Path) -> None:
    root = tmp_path / "review-example"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: review-example\ndescription: Reads examples.\n---\n# Read examples\n")

    async def run() -> None:
        adapter = WaitingReviewer()
        task = asyncio.create_task(execute_content_review(root, source_revision=REVISION, adapter=adapter))
        await asyncio.wait_for(adapter.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(adapter.cancelled.wait(), timeout=1)

    asyncio.run(run())


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
