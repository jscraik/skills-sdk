"""Terminal-safe rendering for human-readable CLI output."""

from __future__ import annotations

import unicodedata
from typing import TextIO


def _visible_escape(character: str) -> str:
    """Render one nonprintable code point as an ASCII escape."""
    codepoint = ord(character)
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"


def terminal_safe_text(value: object) -> str:
    """Preserve printable text while exposing terminal-active characters."""
    return "".join(
        character
        if character.isprintable() and unicodedata.category(character) not in {"Cc", "Cf"}
        else _visible_escape(character)
        for character in str(value)
    )


def print_human(value: object, *, file: TextIO | None = None) -> None:
    """Print one display-safe human-output line."""
    print(terminal_safe_text(value), file=file)
