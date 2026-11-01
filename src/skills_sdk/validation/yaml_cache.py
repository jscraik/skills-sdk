"""Operation-owned reuse of closed YAML parsing, never source or safety verdicts."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date

import yaml

from skills_sdk.validation.safe_yaml import _ClosedLoader

_MAX_ENTRIES = 32
_MAX_INPUT_BYTES = 65_536
_MAX_RETAINED_BYTES = 2 * 1024 * 1024


def _owner() -> tuple[int, object]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


def _policy() -> tuple[object, ...]:
    from skills_sdk.validation import safe_yaml

    return (
        _ClosedLoader,
        safe_yaml._MAX_YAML_NODES,
        safe_yaml._MAX_YAML_DEPTH,
        tuple(_ClosedLoader.yaml_constructors.items()),
        tuple(_ClosedLoader.yaml_multi_constructors.items()),
        tuple((key, tuple(value)) for key, value in _ClosedLoader.yaml_implicit_resolvers.items()),
        tuple(_ClosedLoader.yaml_path_resolvers.items()),
    )


def _retained_size(value: object, remaining: int, depth: int = 0) -> int:
    """Count supported parsed objects conservatively, including repeated references."""
    if depth > 128:
        return remaining + 1
    size = sys.getsizeof(value)
    if size > remaining:
        return size
    if type(value) in (str, bytes, bool, int, float, type(None), date):
        return size
    if type(value) is dict:
        members = (part for pair in value.items() for part in pair)
    elif type(value) in (list, tuple, set):
        members = iter(value)
    else:
        return remaining + 1
    for member in members:
        size += _retained_size(member, remaining - size, depth + 1)
        if size > remaining:
            break
    return size


class _YamlCache:
    def __init__(self) -> None:
        self.owner: tuple[int, object] | None = _owner()
        self.active = True
        self.entries: OrderedDict[str, tuple[object, int]] = OrderedDict()
        self.retained_bytes = 0
        self.policy = _policy()

    def clear(self) -> None:
        self.entries.clear()
        self.retained_bytes = 0

    def load(self, text: str) -> object:
        policy = _policy()
        if policy != self.policy:
            self.clear()
            self.policy = policy
        if text in self.entries:
            self.entries.move_to_end(text)
            return deepcopy(self.entries[text][0])
        parsed = yaml.load(text, Loader=_ClosedLoader)
        # Include the source, parsed tree and conservative per-entry bookkeeping.
        size = sys.getsizeof(text) + 1024
        size += _retained_size(parsed, _MAX_RETAINED_BYTES - size)
        if size <= _MAX_RETAINED_BYTES:
            while self.entries and (
                len(self.entries) >= _MAX_ENTRIES or self.retained_bytes + size > _MAX_RETAINED_BYTES
            ):
                _, (_, removed) = self.entries.popitem(last=False)
                self.retained_bytes -= removed
            self.entries[text] = (deepcopy(parsed), size)
            self.retained_bytes += size
        return parsed


_CURRENT: ContextVar[_YamlCache | None] = ContextVar("sdk_yaml_operation", default=None)


@contextmanager
def yaml_parse_scope() -> Iterator[None]:
    """Own one parse cache and release retained input on every exit path."""
    cache = _YamlCache()
    token = _CURRENT.set(cache)
    try:
        yield
    finally:
        cache.active = False
        cache.clear()
        cache.owner = None
        cache.policy = ()
        _CURRENT.reset(token)


def load_closed_yaml(text: str) -> object:
    """Parse exact current text; only the owning operation may reuse its result."""
    cache = _CURRENT.get()
    if (
        cache is None
        or not cache.active
        or cache.owner != _owner()
        or type(text) is not str
        or len(text) > _MAX_INPUT_BYTES
        or len(text.encode("utf-8", errors="surrogatepass")) > _MAX_INPUT_BYTES
    ):
        return yaml.load(text, Loader=_ClosedLoader)
    return cache.load(text)
