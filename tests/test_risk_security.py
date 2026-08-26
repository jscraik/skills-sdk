from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.risk import RiskClassification, SecurityScreeningResult

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "risk-security"


def _schema_errors(name: str, payload: object) -> list[object]:
    schema = SchemaRegistry().load(name)
    return list(Draft202012Validator(schema).iter_errors(payload))


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
    assert result.sensor_ids
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


def test_needs_review_screening_cannot_hide_a_blocker() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-review.json").read_text(encoding="utf-8"))
    payload["findings"][0]["severity"] = "blocker"
    with pytest.raises(ValidationError, match="cannot contain a blocker"):
        SecurityScreeningResult.model_validate(payload)


def test_duplicate_sensor_ids_are_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][1]["id"] = payload["sensors"][0]["id"]
    with pytest.raises(ValidationError, match="sensor ids"):
        RiskClassification.model_validate(payload)


def test_duplicate_sensor_id_entries_are_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensor_ids"].append(payload["sensor_ids"][0])
    with pytest.raises(ValidationError, match="sensor_ids must be unique"):
        RiskClassification.model_validate(payload)


@pytest.mark.parametrize("field, value", [("status", "skipped_optional"), ("blocking_behavior", "skip_optional")])
def test_required_sensors_cannot_use_optional_skip_states(field: str, value: str) -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][0][field] = value
    with pytest.raises(ValidationError, match="required sensors"):
        RiskClassification.model_validate(payload)


def test_selected_sensor_receipt_requirement_propagates_to_low_risk() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["risk_tier"] = "low"
    payload["receipt_required"] = False
    with pytest.raises(ValidationError, match="classification receipt"):
        RiskClassification.model_validate(payload)


def test_needs_review_screening_requires_a_warning() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-review.json").read_text(encoding="utf-8"))
    payload["findings"][0]["severity"] = "info"
    with pytest.raises(ValidationError, match="requires a warning"):
        SecurityScreeningResult.model_validate(payload)


def test_duplicate_security_finding_codes_are_rejected() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"].append(dict(payload["findings"][0]))
    with pytest.raises(ValidationError, match="finding codes must be unique"):
        SecurityScreeningResult.model_validate(payload)


def test_pass_screening_without_findings_is_valid() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload.pop("findings")
    result = SecurityScreeningResult.model_validate(payload)
    assert result.findings == ()
    assert not _schema_errors("security-screening.v1", payload)


def test_security_screening_requires_unique_sensor_identity() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["sensor_ids"].append(payload["sensor_ids"][0])
    with pytest.raises(ValidationError, match="screening sensor ids must be unique"):
        SecurityScreeningResult.model_validate(payload)
    assert _schema_errors("security-screening.v1", payload)


def test_risk_schema_requires_receipt_for_elevated_tier() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["receipt_required"] = False
    assert _schema_errors("risk-classification.v1", payload)


def test_risk_schema_rejects_duplicate_sensor_id_entries() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensor_ids"].append(payload["sensor_ids"][0])
    assert _schema_errors("risk-classification.v1", payload)


def test_risk_schema_rejects_duplicate_sensor_objects() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"].append(dict(payload["sensors"][0]))
    assert _schema_errors("risk-classification.v1", payload)


def test_risk_schema_rejects_whitespace_only_acceptance_trace() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["acceptance_trace"] = [" "]
    assert _schema_errors("risk-classification.v1", payload)


@pytest.mark.parametrize("field, value", [("status", "skipped_optional"), ("blocking_behavior", "skip_optional")])
def test_risk_schema_rejects_optional_skip_for_required_sensor(field: str, value: str) -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][0][field] = value
    assert _schema_errors("risk-classification.v1", payload)


def test_risk_schema_propagates_selected_sensor_receipt_requirement() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["risk_tier"] = "low"
    payload["receipt_required"] = False
    assert _schema_errors("risk-classification.v1", payload)


@pytest.mark.parametrize(
    "filename, mutation",
    [
        ("security-pass.json", lambda payload: payload["findings"][0].update(severity="warning")),
        ("security-review.json", lambda payload: payload["findings"][0].update(severity="info")),
        ("security-blocked.json", lambda payload: payload["findings"][0].update(severity="warning")),
    ],
)
def test_security_schema_enforces_status_and_finding_severity(filename: str, mutation: object) -> None:
    payload = json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    mutation(payload)  # type: ignore[operator]
    assert _schema_errors("security-screening.v1", payload)


@pytest.mark.parametrize(
    "field, value",
    [("scanned_paths", ["/absolute/path"]), ("evidence_refs", ["../outside"]), ("scanned_paths", ["scans/"])],
)
def test_security_schema_enforces_portable_paths(field: str, value: list[str]) -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    if field == "evidence_refs":
        payload["findings"][0][field] = value
    else:
        payload[field] = value
    assert _schema_errors("security-screening.v1", payload)


@pytest.mark.parametrize("field", ["code", "message"])
def test_security_schema_rejects_whitespace_only_finding_text(field: str) -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"][0][field] = "   "
    assert _schema_errors("security-screening.v1", payload)


def test_security_schema_rejects_whitespace_only_scanned_path() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["scanned_paths"] = [" "]
    assert _schema_errors("security-screening.v1", payload)


@pytest.mark.parametrize("field", ["scanned_paths", "evidence_refs"])
@pytest.mark.parametrize("value", ["SKILL.md\n", "SKILL.md\r", "SKILL\n.md"])
def test_security_paths_reject_line_terminators(field: str, value: str) -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    if field == "evidence_refs":
        payload["findings"][0][field] = [value]
    else:
        payload[field] = [value]

    with pytest.raises(ValidationError):
        SecurityScreeningResult.model_validate(payload)
    assert _schema_errors("security-screening.v1", payload)


def test_security_schema_accepts_multiline_finding_message() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"][0]["message"] = "line one\nline two"
    assert not _schema_errors("security-screening.v1", payload)


def test_security_schema_requires_sensor_identity() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload.pop("sensor_ids")
    assert _schema_errors("security-screening.v1", payload)


def test_schema_registry_applies_risk_semantic_invariants() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensor_ids"] = ["source-scan"]
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("risk-classification.v1", payload)
    assert any("sensor_ids must match" in detail for detail in error.value.details)


def test_schema_registry_rejects_selected_sensor_receipt_mismatch() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["risk_tier"] = "low"
    payload["receipt_required"] = False
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("risk-classification.v1", payload)
    assert error.value.code == "contract_validation_failed"


def test_risk_model_rejects_untrimmed_sensor_identity() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][0]["id"] = " source-scan "
    with pytest.raises(ValidationError, match="sensor ids must already be normalized"):
        RiskClassification.model_validate(payload)


def test_risk_schema_rejects_untrimmed_sensor_identity() -> None:
    payload = json.loads((FIXTURE_ROOT / "risk.json").read_text(encoding="utf-8"))
    payload["sensors"][0]["id"] = " source-scan "
    assert _schema_errors("risk-classification.v1", payload)


def test_schema_registry_applies_security_semantic_invariants() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"][0]["severity"] = "warning"
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("security-screening.v1", payload)
    assert error.value.code == "contract_validation_failed"


def test_schema_registry_rejects_needs_review_without_warning() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-review.json").read_text(encoding="utf-8"))
    payload["findings"][0]["severity"] = "info"
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("security-screening.v1", payload)
    assert error.value.code == "contract_validation_failed"


def test_schema_registry_rejects_duplicate_finding_codes() -> None:
    payload = json.loads((FIXTURE_ROOT / "security-pass.json").read_text(encoding="utf-8"))
    payload["findings"].append(dict(payload["findings"][0]))
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("security-screening.v1", payload)
    assert any("finding codes must be unique" in detail for detail in error.value.details)
