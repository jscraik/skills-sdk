"""Bounded deterministic work for selected-case evaluation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_selected_case_evaluation import REVISION, _prepared_request, _skill

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.selected_case import execute_selected_case, load_selected_case


@pytest.mark.parametrize("count,accepted", [(127, True), (128, False)])
def test_selected_case_bounds_deterministic_pattern_count(tmp_path: Path, count: int, accepted: bool) -> None:
    """Cap repeated output scans while admitting the boundary neighbor."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"].extend(
        {"type": "contains", "value": f"pattern-{index}"} for index in range(count)
    )
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    if accepted:
        assert load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
    else:
        with pytest.raises(ContractError, match="invalid_selected_case"):
            load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_forged_selected_case_cannot_exceed_deterministic_pattern_bytes(tmp_path: Path) -> None:
    """Reapply the scan-size bound at execution after definition mutation."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, input_payload)
    forged = replace(
        definition,
        semantic_assertions=definition.semantic_assertions[:-1],
        deterministic_assertions=((definition.semantic_assertions[-1][0], "contains", "x" * 16_385),),
    )

    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(execute_selected_case(forged, request, input_payload, None, None))


@pytest.mark.parametrize("field", ["acceptance", "forbidden_commands"])
def test_selected_case_rejects_unencodable_deterministic_patterns(tmp_path: Path, field: str) -> None:
    """Return a typed loader error for a YAML-escaped lone surrogate."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    if field == "acceptance":
        payload["cases"][0]["acceptance"].append({"type": "contains", "value": "\ud800"})
    else:
        payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = ["\ud800"]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
