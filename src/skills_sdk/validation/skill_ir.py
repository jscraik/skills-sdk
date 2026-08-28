"""Internal standalone-skill intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError(
                "while constructing frontmatter",
                node.start_mark,
                "keys must be strings",
                key_node.start_mark,
            )
        if key in mapping:
            raise ConstructorError(
                "while constructing frontmatter",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(frozen=True, slots=True)
class SkillIR:
    """Fields derived from one parsed ``SKILL.md`` source."""

    name: str
    name_declared: bool
    version: str
    description: str
    frontmatter: dict[str, Any]
    body: str


def read_frontmatter(text: str) -> tuple[dict[str, Any], str, bool]:
    """Return strictly parsed frontmatter, body, and closure state."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip(), False
    closing_index = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if closing_index is None:
        return {}, "", False
    frontmatter_text = "\n".join(lines[1:closing_index])
    loaded = yaml.load(frontmatter_text, Loader=_UniqueKeyLoader) if frontmatter_text.strip() else {}
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise ValueError("SKILL.md frontmatter must be a string-keyed mapping")
    return loaded, "\n".join(lines[closing_index + 1 :]).strip(), True


def build_skill_ir(skill_md: Path, *, text: str) -> SkillIR:
    """Build conservative identity fields from one captured source snapshot."""

    frontmatter, body, closed = read_frontmatter(text)
    if not closed:
        raise ValueError("SKILL.md requires a closed leading frontmatter block")
    metadata = frontmatter.get("metadata")
    metadata_version = metadata.get("version") if isinstance(metadata, dict) else None
    raw_name = frontmatter.get("name")
    name_declared = isinstance(raw_name, str) and bool(raw_name.strip())
    name = str(raw_name or skill_md.parent.name).strip()
    version = str(frontmatter.get("version") or metadata_version or "0.1.0").strip()
    description_value = frontmatter.get("description")
    description = description_value.strip() if isinstance(description_value, str) else ""
    return SkillIR(
        name=name,
        name_declared=name_declared,
        version=version or "0.1.0",
        description=description,
        frontmatter=frontmatter,
        body=body,
    )


__all__: list[str] = []
