"""Portable path primitives shared by public contracts."""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath

from skills_sdk.core.errors import ContractError

# Unicode 15.0 Cc/Cf ranges. Astral alternatives match whole code points in
# Python and JavaScript regex engines without requiring Unicode property syntax.
PORTABLE_PATH_CONTROL_PATTERN = (
    r"[\u0000-\u001f\u007f-\u009f\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890-\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]|"
    "\U000110bd|\U000110cd|\U00013430|\U00013431|\U00013432|\U00013433|\U00013434|\U00013435|"
    "\U00013436|\U00013437|\U00013438|\U00013439|\U0001343a|\U0001343b|\U0001343c|\U0001343d|"
    "\U0001343e|\U0001343f|\U0001bca0|\U0001bca1|\U0001bca2|\U0001bca3|\U0001d173|\U0001d174|"
    "\U0001d175|\U0001d176|\U0001d177|\U0001d178|\U0001d179|\U0001d17a|\U000e0001|\U000e0020|"
    "\U000e0021|\U000e0022|\U000e0023|\U000e0024|\U000e0025|\U000e0026|\U000e0027|\U000e0028|"
    "\U000e0029|\U000e002a|\U000e002b|\U000e002c|\U000e002d|\U000e002e|\U000e002f|\U000e0030|"
    "\U000e0031|\U000e0032|\U000e0033|\U000e0034|\U000e0035|\U000e0036|\U000e0037|\U000e0038|"
    "\U000e0039|\U000e003a|\U000e003b|\U000e003c|\U000e003d|\U000e003e|\U000e003f|\U000e0040|"
    "\U000e0041|\U000e0042|\U000e0043|\U000e0044|\U000e0045|\U000e0046|\U000e0047|\U000e0048|"
    "\U000e0049|\U000e004a|\U000e004b|\U000e004c|\U000e004d|\U000e004e|\U000e004f|\U000e0050|"
    "\U000e0051|\U000e0052|\U000e0053|\U000e0054|\U000e0055|\U000e0056|\U000e0057|\U000e0058|"
    "\U000e0059|\U000e005a|\U000e005b|\U000e005c|\U000e005d|\U000e005e|\U000e005f|\U000e0060|"
    "\U000e0061|\U000e0062|\U000e0063|\U000e0064|\U000e0065|\U000e0066|\U000e0067|\U000e0068|"
    "\U000e0069|\U000e006a|\U000e006b|\U000e006c|\U000e006d|\U000e006e|\U000e006f|\U000e0070|"
    "\U000e0071|\U000e0072|\U000e0073|\U000e0074|\U000e0075|\U000e0076|\U000e0077|\U000e0078|"
    "\U000e0079|\U000e007a|\U000e007b|\U000e007c|\U000e007d|\U000e007e|\U000e007f"
)

_EXCLUDED_REFERENCE_TERMS = ("eval", "scorer", "rubric", "calibration", "heldout", "held-out", "hidden")


def require_portable_relative_path(value: str) -> PurePosixPath:
    """Return a normalized relative POSIX path or raise a typed error."""

    if (
        not value
        or not value.strip()
        or "\\" in value
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        raise ContractError("invalid_portable_path", "path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ContractError("invalid_portable_path", "path must be relative and cannot escape its root")
    normalized = path.as_posix()
    if normalized != value or normalized in {".", ""}:
        raise ContractError("invalid_portable_path", "path must already be normalized")
    return path


def require_matched_reference_path(value: str, selected_skill_paths: tuple[str, ...]) -> PurePosixPath:
    """Keep matched plan and runtime reference selection under one portable rule."""
    path = require_portable_relative_path(value)
    if path.parts[0] == "skills" and "/".join(path.parts[:2]) not in selected_skill_paths:
        raise ValueError("matched references within skills must belong to a selected child")
    if path.suffix.casefold() not in {".md", ".markdown"} or any(
        term in part.casefold() for part in path.parts for term in _EXCLUDED_REFERENCE_TERMS
    ):
        raise ValueError("matched context excludes hidden evaluation inputs and non-Markdown references")
    if value in {f"{child}/SKILL.md" for child in selected_skill_paths}:
        raise ValueError("matched references must not duplicate automatic selected entrypoints")
    return path
