#!/usr/bin/env python3
"""Validate that a pull-request body preserves the SDK template contract."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SECTION_RE = re.compile(r"^## (?P<title>.+?)\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^- \[[ xX]\] (?P<label>.+?)\s*$", re.MULTILINE)
FIELD_LINE_RE = re.compile(r"^- (?P<label>[^:\n]+):(?P<value>.*)$", re.MULTILINE)
STATUS_RE = re.compile(r"^\*\*\((?:pending|n\.a\.|n/a|not applicable)\)\*\*\s*", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
LOCAL_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w:/])(?:/(?:Users|home|private|tmp|var/folders|workspace)(?:/[^\s`),;]+)+|[A-Za-z]:[\\/][^\s`),;]+)"
)
COMMAND_RE = re.compile(
    r"^-\s*Command:\s*(?:`[^\n`]+`|(?=\S).*?\S)\s*->\s*"
    r"(?:(?:pass|fail)(?:\s*\([^)]+\)\.?)?|blocked\s*\([^)]+\))\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TemplateContract:
    sections: tuple[str, ...]
    checklist_items: tuple[str, ...]
    fields_by_section: dict[str, tuple[str, ...]]


def _visible(markdown: str) -> str:
    return HTML_COMMENT_RE.sub("", markdown)


def _section_blocks(markdown: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(markdown))
    return {
        match.group("title").strip(): markdown[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        ]
        for index, match in enumerate(matches)
    }


def _normalize_checklist_label(label: str) -> str:
    return STATUS_RE.sub("", label.strip()).strip()


def _template_contract(template: str) -> TemplateContract:
    visible = _visible(template)
    blocks = _section_blocks(visible)
    sections = tuple(match.group("title").strip() for match in SECTION_RE.finditer(visible))
    checklist_items = tuple(
        _normalize_checklist_label(match.group("label")) for match in CHECKBOX_RE.finditer(blocks.get("Checklist", ""))
    )
    fields_by_section = {
        section: tuple(
            match.group("label").strip()
            for match in FIELD_LINE_RE.finditer(block)
            if match.group("label").strip() != "Command"
        )
        for section, block in blocks.items()
        if section != "Checklist"
    }
    return TemplateContract(sections, checklist_items, fields_by_section)


def _field_values(block: str) -> tuple[dict[str, str], Counter[str]]:
    matches = list(FIELD_LINE_RE.finditer(block))
    values: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        label = match.group("label").strip()
        if label == "Command":
            continue
        continuation = block[match.end() : next_start].strip()
        counts[label] += 1
        values[label] = f"{match.group('value').strip()}\n{continuation}".strip()
    return values, counts


def _structure_errors(contract: TemplateContract, body: str) -> list[str]:
    visible = _visible(body)
    actual_sections = tuple(match.group("title").strip() for match in SECTION_RE.finditer(visible))
    errors: list[str] = []
    if actual_sections != contract.sections:
        errors.append(
            "PR body sections must match the template exactly: "
            f"expected={contract.sections!r} actual={actual_sections!r}"
        )
    blocks = _section_blocks(visible)
    for section, expected_fields in contract.fields_by_section.items():
        values, counts = _field_values(blocks.get(section, ""))
        errors.extend(
            f"Missing required field in ## {section}: {field}:" for field in expected_fields if counts[field] == 0
        )
        errors.extend(f"Duplicate field in ## {section}: {field}:" for field in expected_fields if counts[field] > 1)
        errors.extend(
            f"Required field in ## {section} is empty: {field}:"
            for field in expected_fields
            if field in values and not values[field]
        )
        errors.extend(f"Unexpected field in ## {section}: {field}:" for field in values if field not in expected_fields)
    actual_checklist = tuple(
        _normalize_checklist_label(match.group("label")) for match in CHECKBOX_RE.finditer(blocks.get("Checklist", ""))
    )
    if actual_checklist != contract.checklist_items:
        errors.append("Checklist item text and order must match the template exactly.")
    errors.extend(
        f"Unchecked checklist item requires an explicit Pending or N/A marker: {match.group(0).strip()}"
        for match in CHECKBOX_RE.finditer(blocks.get("Checklist", ""))
        if match.group(0).startswith("- [ ]") and not STATUS_RE.match(match.group("label"))
    )
    return errors


def _command_errors(body: str) -> list[str]:
    validation = _section_blocks(_visible(body)).get("Validation", "")
    command_lines = [line.strip() for line in validation.splitlines() if line.strip().lower().startswith("- command:")]
    if not command_lines:
        return ["Validation must include at least one Command evidence line."]
    return [f"Invalid Command evidence: {line}" for line in command_lines if COMMAND_RE.fullmatch(line) is None]


def validate_pr_body(template: str, body: str) -> list[str]:
    if not body.strip():
        return ["PR body is empty. Fill out the repository template."]
    errors = _structure_errors(_template_contract(template), body)
    errors.extend(_command_errors(body))
    errors.extend(f"Replace unresolved placeholder token: {token}" for token in PLACEHOLDER_RE.findall(_visible(body)))
    if LOCAL_ABSOLUTE_PATH_RE.search(_visible(body)):
        errors.append("PR body must not contain local absolute paths.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=Path(".github/PULL_REQUEST_TEMPLATE.md"))
    body_group = parser.add_mutually_exclusive_group()
    body_group.add_argument("--body-file", type=Path)
    body_group.add_argument("--body-env")
    args = parser.parse_args()
    body = (
        args.body_file.read_text(encoding="utf-8")
        if args.body_file
        else os.environ.get(args.body_env, "")
        if args.body_env
        else sys.stdin.read()
    )
    errors = validate_pr_body(args.template.read_text(encoding="utf-8"), body)
    if errors:
        print("PR template validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PR template validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
