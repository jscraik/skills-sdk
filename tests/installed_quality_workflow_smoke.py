"""Installed API/CLI proof with repository fixtures prepared in a separate process."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import skills_sdk
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import ContentReviewInput, check_local_quality
from skills_sdk.models import LocalCheckResultV2, PackageSafetyReviewer


class FixtureReviewer:
    """Execute a synthetic callback; never claim general semantic accuracy."""

    reviewer = PackageSafetyReviewer(adapter_id="fixture-review", adapter_version_or_digest="1", method="manual_review")

    def __init__(self, assessment: dict[str, object]) -> None:
        self.assessment = assessment

    async def review(self, inputs: ContentReviewInput) -> object:
        assert self.assessment["candidate"] == inputs.candidate.model_dump(mode="json")
        return self.assessment


def prepare(root: Path) -> None:
    """Use the existing test fixture only before entering the installed environment."""
    from test_quality_workflow import _assessment, _package_path, _request

    root.mkdir()
    request = _request(root)
    package = _package_path(root)
    (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (root / "assessment.json").write_text(json.dumps(_assessment(package)), encoding="utf-8")


def _cli(root: Path) -> tuple[int, dict[str, object]]:
    command = [
        str(Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")),
        "check-quality",
        str(root / "synthetic-skill"),
        "--request",
        str(root / "request.json"),
        "--assessment",
        str(root / "assessment.json"),
        "--json",
        "--robot",
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def _api(root: Path, request: dict[str, object], assessment: dict[str, object]) -> None:
    package = root / "synthetic-skill"
    for intent in ("create", "external-check", "update"):
        selected = {**request, "intent": intent}
        baseline = None
        if intent == "update":
            selected["update_baseline"] = request["candidate"]
            baseline = package
        result = asyncio.run(check_local_quality(package, selected, baseline_root=baseline, assessment=assessment))
        assert result.status == "local_checks_passed"
        SchemaRegistry().validate("local-check.v2", result.model_dump(mode="json"))
    rejected = asyncio.run(check_local_quality(package, request, assessment={}))
    assert rejected.blocked_stage == "content-review"
    recovered = asyncio.run(check_local_quality(package, request, assessment=assessment))
    assert recovered.status == "local_checks_passed" and recovered.stages[:-1] == rejected.stages[:-1]
    observed = asyncio.run(
        check_local_quality(
            package,
            {**request, "content_review_mode": "observed"},
            adapter=FixtureReviewer(assessment),
        )
    )
    assert observed.status == "local_checks_passed" and observed.stages[-1].receipt.adapter_invoked
    assert observed.evaluation_executed is False and observed.promotion_authorized is False


def check(root: Path) -> None:
    """Prove installed provenance, rejection and exact recovery with no source imports."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert "pytest" not in sys.modules
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    assessment_path = root / "assessment.json"
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    _api(root, request, assessment)
    code, accepted = _cli(root)
    assert code == 0 and accepted["status"] == "local_checks_passed"
    LocalCheckResultV2.model_validate(accepted)
    assessment_path.write_text("{}", encoding="utf-8")
    code, blocked = _cli(root)
    assert code == 2 and blocked["blocked_stage"] == "content-review"
    SchemaRegistry().validate("local-check.v2", blocked)
    assessment_path.write_text(json.dumps(assessment), encoding="utf-8")
    assert _cli(root) == (0, accepted)
    assert not any("agent_skills" in name or "skills_foundry" in name for name in sys.modules)
    print("installed local quality API/CLI acceptance, rejection, recovery and callback: pass")


def main() -> int:
    mode, directory = sys.argv[1:]
    root = Path(directory).resolve()
    if mode == "--prepare":
        prepare(root)
    elif mode == "--check":
        check(root)
    else:
        raise ValueError("select --prepare or --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
