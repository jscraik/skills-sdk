"""Bounded rendering for untrusted identifiers retained in diagnostics."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable

from skills_sdk.models.safety import _public_text_is_redaction_safe

_MAX_IDENTIFIER_DIAGNOSTIC_CHARS = 4096
_REDACTED_IDENTIFIER = "<redacted identifier>"


def _visible_escape(character: str) -> str:
    codepoint = ord(character)
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"


def _visible_identifier(value: str) -> str:
    return "".join(
        character
        if character.isprintable() and unicodedata.category(character) not in {"Cc", "Cf"}
        else _visible_escape(character)
        for character in value
    )


def _render_identifier(value: str) -> str:
    public_value = value if _public_text_is_redaction_safe(value) else _REDACTED_IDENTIFIER
    return json.dumps(_visible_identifier(public_value), ensure_ascii=True)


def render_untrusted_identifiers(values: Iterable[str]) -> str:
    """Return a bounded JSON-style list without retaining active or private text."""
    rendered = tuple(_render_identifier(value) for value in values)
    parts: list[str] = []
    rendered_length = 2
    for index, item in enumerate(rendered):
        item_length = len(item) + (2 if parts else 0)
        if rendered_length + item_length <= _MAX_IDENTIFIER_DIAGNOSTIC_CHARS:
            parts.append(item)
            rendered_length += item_length
            continue
        omitted = len(rendered) - index
        marker = json.dumps(f"<{omitted} identifiers omitted>")
        while parts and rendered_length + len(marker) + 2 > _MAX_IDENTIFIER_DIAGNOSTIC_CHARS:
            removed = parts.pop()
            rendered_length -= len(removed) + (2 if parts else 0)
            omitted += 1
            marker = json.dumps(f"<{omitted} identifiers omitted>")
        parts.append(marker)
        break
    return "[" + ", ".join(parts) + "]"


def safe_diagnostic_identifier(value: str) -> str | None:
    """Retain a short ordinary identifier for attribution, otherwise omit it."""
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded) > _MAX_IDENTIFIER_DIAGNOSTIC_CHARS or not _public_text_is_redaction_safe(value):
        return None
    return value if _visible_identifier(value) == value else None


__all__ = ["render_untrusted_identifiers", "safe_diagnostic_identifier"]
