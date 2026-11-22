"""Standalone schema and runtime parity for terminal-active portable paths."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import PORTABLE_PATH_CONTROL_PATTERN, require_portable_relative_path
from skills_sdk.core.schema_registry import SCHEMA_NAMES, SchemaRegistry

FROZEN_PATH_SCHEMAS = frozenset({"scenario-observation.v1", "scenario-case-result.v1", "evaluation-receipt.v1"})


def _path_patterns(node: Any) -> list[str]:
    if isinstance(node, dict):
        pattern = node.get("pattern")
        own = [pattern] if isinstance(pattern, str) and "(?![^/]*:)" in pattern else []
        return own + [pattern for value in node.values() for pattern in _path_patterns(value)]
    if isinstance(node, list):
        return [pattern for value in node for pattern in _path_patterns(value)]
    return []


def test_schema_control_pattern_matches_pinned_unicode_categories() -> None:
    pattern = re.compile(PORTABLE_PATH_CONTROL_PATTERN)
    actual = {codepoint for codepoint in range(0x110000) if pattern.fullmatch(chr(codepoint))}
    expected = {codepoint for codepoint in range(0x110000) if unicodedata.category(chr(codepoint)) in {"Cc", "Cf"}}

    assert actual == expected


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_NAMES - FROZEN_PATH_SCHEMAS))
def test_standalone_portable_path_patterns_reject_controls(schema_name: str) -> None:
    schema = SchemaRegistry().load(schema_name)
    for pattern in _path_patterns(schema):
        validator = Draft202012Validator({"type": "string", "pattern": pattern})
        for character in ("\x00", "\x07", "\x1b", "\x85", "\u00ad", "\u202e", "\U00013430", "\U000e007f"):
            assert not validator.is_valid(f"evidence/{character}receipt.json"), (schema_name, repr(character))
        for value in ("références/指南-🙂.md", "evidence/𐀀.json"):
            assert validator.is_valid(value), schema_name
            assert require_portable_relative_path(value).as_posix() == value


def _legacy_payloads(path: str) -> dict[str, dict[str, Any]]:
    candidate = {"package_id": "synthetic-skill", "source_revision": "1" * 40, "content_sha256": "a" * 64}
    common = {
        "candidate": candidate,
        "scenario_set_id": "synthetic",
        "case_id": "case",
        "runner_id": "test",
        "runner_version_or_digest": "v1",
        "evidence_refs": [path],
    }
    observation = {
        **common,
        "schema_version": "scenario-observation/v1",
        "status": "completed",
        "output_sha256": "b" * 64,
    }
    result = {
        **common,
        "schema_version": "scenario-case-result/v1",
        "status": "pass",
        "observation_sha256": "b" * 64,
    }
    receipt = {
        "schema_version": "evaluation-receipt/v1",
        "receipt_id": "synthetic-1",
        "candidate": candidate,
        "lane": "evaluation",
        "scenario_set_id": "synthetic",
        "status": "pass",
        "score": 1.0,
        "case_results": [result],
        "scorer": {
            "schema_version": "scorer-profile/v1",
            "candidate": candidate,
            "scorer_id": "synthetic",
            "scorer_type": "deterministic",
            "version_or_digest": "v1",
            "pass_threshold": 1.0,
            "deterministic_checks_first": True,
            "calibration_required": False,
        },
    }
    return {"scenario-observation.v1": observation, "scenario-case-result.v1": result, "evaluation-receipt.v1": receipt}


@pytest.mark.parametrize("schema_name", sorted(FROZEN_PATH_SCHEMAS))
@pytest.mark.parametrize("character", ["\x07", "\u202e", "\U000e007f"])
def test_frozen_schema_acceptance_does_not_waive_runtime_safety(schema_name: str, character: str) -> None:
    registry = SchemaRegistry()
    schema = registry.load(schema_name)
    payload = _legacy_payloads(f"evidence/{character}receipt.json")[schema_name]

    assert _path_patterns(schema)
    assert Draft202012Validator(schema).is_valid(payload)
    with pytest.raises(ContractError):
        registry.validate(schema_name, payload)
    registry.validate(schema_name, _legacy_payloads("références/指南-🙂.md")[schema_name])
