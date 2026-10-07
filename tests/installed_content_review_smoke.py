"""Wheel-only content-review evidence and controlled offline callback proof."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

import skills_sdk
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import ContentReviewInput, execute_content_review
from skills_sdk.models import ContentReviewAssessment
from skills_sdk.models.safety import PackageSafetyReviewer
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


if __name__ == "__main__":
    raise SystemExit(main())
