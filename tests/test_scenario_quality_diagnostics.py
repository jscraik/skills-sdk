from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_scenario_quality import REVISION, _case, _release_set, _skill

from skills_sdk.evaluation import assess_scenario_quality


def test_yaml_field_diagnostics_escape_controls_and_redact_private_text(tmp_path: Path) -> None:
    case = _case("case\x1b[31m")
    case["line\nfield"] = True
    case["api_key=private-value"] = True
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "top\u202efield": True,
        "cases": [case],
    }

    result = assess_scenario_quality(_skill(tmp_path / "example", payload), source_revision=REVISION)

    messages = "\n".join(item.message for item in result.findings)
    assert "\x1b" not in messages and "\u202e" not in messages and "private-value" not in messages
    assert json.dumps(r"line\x0afield") in messages
    assert json.dumps(r"top\u202efield") in messages
    assert json.dumps("<redacted identifier>") in messages
    unsupported = next(item for item in result.findings if item.code == "unsupported_scenario_field")
    assert unsupported.case_id is None


def test_release_selection_diagnostic_does_not_retain_unsafe_ids(tmp_path: Path) -> None:
    cases = [_case(f"case-{index}") for index in range(8)]
    cases[6]["category"] = "pressure"
    cases[7]["category"] = "edge"
    selected_ids = [case["id"] for case in cases]
    selected_ids.extend(["missing\ncase", "api_key=private-value"])
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [_release_set(selected_ids)],
        "cases": cases,
    }

    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload), source_revision=REVISION, scenario_set_id="release"
    )

    finding = next(item for item in result.findings if item.code == "unknown_scenario_id")
    assert "\n" not in finding.message and "private-value" not in finding.message
    assert json.dumps(r"missing\x0acase") in finding.message
    assert json.dumps("<redacted identifier>") in finding.message


@pytest.mark.parametrize("unsafe_identifier", ["release\x1b]52;c;payload\x07", "api_key=private-value"])
def test_unsafe_release_set_identifiers_are_rejected_without_retention(tmp_path: Path, unsafe_identifier: str) -> None:
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [_release_set(["happy"], set_id=unsafe_identifier)],
        "cases": [_case()],
    }

    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload), source_revision=REVISION, scenario_set_id=unsafe_identifier
    )

    assert result.status == "blocked" and result.scenario_set_id is None
    assert unsafe_identifier not in "\n".join(item.message for item in result.findings)
    assert "invalid_scenario_set" in {item.code for item in result.findings}


@pytest.mark.parametrize("identifier", ["case\nforged", "api_key=private-value", "ordinary-case"])
def test_release_ineligible_case_attribution_is_safe(tmp_path: Path, identifier: str) -> None:
    case = _case(identifier)
    case["eval_modes"] = ["smoke"]
    payload = {
        "schema_version": "2.0",
        "skill_name": "example",
        "release_scenario_sets": [_release_set([identifier])],
        "cases": [case],
    }

    result = assess_scenario_quality(
        _skill(tmp_path / "example", payload), source_revision=REVISION, scenario_set_id="release"
    )

    finding = next(item for item in result.findings if item.code == "release_case_not_eligible")
    assert finding.case_id == ("ordinary-case" if identifier == "ordinary-case" else None)
    assert "private-value" not in result.model_dump_json()
