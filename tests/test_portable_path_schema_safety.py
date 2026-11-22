"""Standalone schema and runtime parity for terminal-active portable paths."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.paths import PORTABLE_PATH_CONTROL_PATTERN, require_portable_relative_path
from skills_sdk.core.schema_registry import SCHEMA_NAMES, SchemaRegistry


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


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_NAMES))
def test_standalone_portable_path_patterns_reject_controls(schema_name: str) -> None:
    schema = SchemaRegistry().load(schema_name)
    for pattern in _path_patterns(schema):
        validator = Draft202012Validator({"type": "string", "pattern": pattern})
        for character in ("\x00", "\x07", "\x1b", "\x85", "\u00ad", "\u202e", "\U00013430", "\U000e007f"):
            assert not validator.is_valid(f"evidence/{character}receipt.json"), (schema_name, repr(character))
        for value in ("références/指南-🙂.md", "evidence/𐀀.json"):
            assert validator.is_valid(value), schema_name
            assert require_portable_relative_path(value).as_posix() == value
