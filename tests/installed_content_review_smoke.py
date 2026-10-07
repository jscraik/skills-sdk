"""Wheel-only content-review evidence and controlled offline callback proof."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
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
    async def review(self, inputs: ContentReviewInput) -> object:
        time.sleep(0.02)
        return await super().review(inputs)


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
    with patch.object(review_module, "_REVIEW_TIMEOUT_SECONDS", 0.01):
        timed_out = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=BlockingReviewer()))
    assert timed_out.status == "blocked" and timed_out.adapter_invoked is True
    assert timed_out.findings[0].code == "content_review_timeout"
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"
    assert (
        asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer())).status == "pass"
    )


class FailingAssessmentSerializer(ContentReviewAssessment):
    def model_dump(self, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("private serializer diagnostic")


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
    failing = FailingAssessmentSerializer.model_validate(assessment.model_dump(mode="json"))
    rejected = assess_content_review(root, source_revision="1" * 40, assessment=failing)
    assert rejected.status == "blocked" and rejected.findings[0].code == "invalid_content_review"
    assert "private serializer" not in rejected.model_dump_json()
    metadata = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=MetadataFailureReviewer()))
    assert metadata.findings[0].code == "invalid_content_review_adapter" and metadata.adapter_invoked is False
    assert "private metadata" not in metadata.model_dump_json()
    assert assess_content_review(root, source_revision="1" * 40, assessment=assessment).status == "pass"
    recovered = asyncio.run(execute_content_review(root, source_revision="1" * 40, adapter=FixtureReviewer()))
    assert recovered.status == "pass" and recovered.adapter_invoked is True


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
                _assert_unsupported_read_recovery(root, assessment)
                _assert_contract_boundaries(root, result.review.assessment)
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
