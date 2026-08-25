from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.models.risk import RiskClassification, SecurityScreeningResult

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "risk-security"


def test_risk_fixture_requires_receipt_for_elevated_tier() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    risk = RiskClassification.model_validate(payload)
    assert risk.receipt_required is True
    assert set(risk.sensor_ids) == {"source-scan", "schema-check"}


@pytest.mark.parametrize(
    "filename, expected",
    [("security-pass.json", "pass"), ("security-review.json", "needs_review"), ("security-blocked.json", "blocked")],
)
def test_security_screening_fixtures_are_explicit(filename: str, expected: str) -> None:
    payload = json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    result = SecurityScreeningResult.model_validate(payload)
    assert result.status == expected
    assert result.mutation_performed is False


def test_pass_screening_cannot_hide_a_warning() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"] = [
        {
            "code": "secret_like",
            "category": "secret",
            "severity": "warning",
            "message": "review required",
            "evidence_refs": ["tests/fixtures/risk-security/SKILL.md"],
        }
    ]
    with pytest.raises(ValidationError, match="pass screening"):
        SecurityScreeningResult.model_validate(payload)


def test_duplicate_sensor_ids_are_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][1]["id"] = payload["sensors"][0]["id"]
    with pytest.raises(ValidationError, match="sensor ids"):
        RiskClassification.model_validate(payload)
