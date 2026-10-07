"""Wheel-only content-review evidence and controlled offline callback proof."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import skills_sdk
from skills_sdk.evaluation import ContentReviewInput, execute_content_review
from skills_sdk.models.safety import PackageSafetyReviewer


class FixtureReviewer:
    """Test-only semantic comparison of this script's two known descriptions."""

    reviewer = PackageSafetyReviewer(adapter_id="smoke-review", adapter_version_or_digest="1", method="static_analysis")

    async def review(self, inputs: ContentReviewInput) -> object:
        document = next(item for item in inputs.documents if item.path == "SKILL.md")
        mismatch = b"Deletes production" in document.content
        return {
            "candidate": inputs.candidate.model_dump(mode="json"),
            "reviewer": self.reviewer.model_dump(mode="json"),
            "evidence": [
                {"evidence_id": "entry", "kind": "static_analysis", "ref": document.path, "sha256": document.sha256}
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
            ],
        }


def main() -> int:
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    with TemporaryDirectory(prefix="sdk-content-review-") as directory:
        cwd = Path(directory).resolve()
        root = cwd / "review-smoke"
        root.mkdir()
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
            assessment = cwd / "assessment.json"
            assessment.write_text(result.review.assessment.model_dump_json())
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "skills_sdk.cli.main",
                    "review-content",
                    str(root),
                    "--source-revision",
                    "1" * 40,
                    "--assessment",
                    str(assessment),
                    "--json",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            assert process.returncode == (0 if expected == "pass" else 2), process.stderr
            assert json.loads(process.stdout)["status"] == expected
            assert skill.read_bytes() == original
    print("installed content-review API, offline adapter and supplied CLI: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
