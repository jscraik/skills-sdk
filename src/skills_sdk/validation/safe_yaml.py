"""Bounded YAML loader shared by source screening and scenario validation."""

from __future__ import annotations

from typing import cast

import yaml

_MAX_YAML_NODES = 20_000
_MAX_YAML_DEPTH = 128


class _ClosedLoader(yaml.SafeLoader):
    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise yaml.constructor.ConstructorError(
                None, None, "YAML aliases are not supported", self.peek_event().start_mark
            )
        self._node_count = getattr(self, "_node_count", 0) + 1
        if self._node_count > _MAX_YAML_NODES:
            raise yaml.constructor.ConstructorError(
                None, None, "YAML node limit exceeded", self.peek_event().start_mark
            )
        depth = getattr(self, "_node_depth", 0) + 1
        if depth > _MAX_YAML_DEPTH:
            raise yaml.constructor.ConstructorError(
                None, None, "YAML nesting limit exceeded", self.peek_event().start_mark
            )
        self._node_depth = depth
        try:
            return cast(yaml.Node, super().compose_node(parent, index))
        finally:
            self._node_depth = depth - 1


def _mapping(loader: _ClosedLoader, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                None, None, "YAML mapping keys must be strings", key_node.start_mark
            )
        if key in result:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate YAML key: {key}", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_ClosedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
