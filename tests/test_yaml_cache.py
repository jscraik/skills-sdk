"""Parse reuse retains closed-loader rejection and operation ownership."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

from skills_sdk.validation import yaml_cache as cache_module
from skills_sdk.validation.safe_yaml import _ClosedLoader
from skills_sdk.validation.yaml_cache import load_closed_yaml, yaml_parse_scope


def _observe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = yaml.load

    def counted(text: str, Loader: object) -> object:
        calls.append(text)
        return original(text, Loader=Loader)

    monkeypatch.setattr(yaml, "load", counted)
    return calls


def test_exact_text_reuse_returns_independent_values(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    with yaml_parse_scope():
        first = load_closed_yaml("a: [one]")
        first["a"].append("changed")
        assert load_closed_yaml("a: [one]") == {"a": ["one"]}
        assert load_closed_yaml("a: [two]") == {"a": ["two"]}
    assert len(calls) == 2
    load_closed_yaml("a: [one]")
    load_closed_yaml("a: [one]")
    assert len(calls) == 4


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\na: 2",
        "a: &a [one]\nb: *a",
        "a: [unterminated",
        "1: value",
        "a: !!python/object:object {}",
        "a: " + "[" * 130 + "0" + "]" * 130,
        "a: [" + ",".join("0" for _ in range(20001)) + "]",
        "a: \ud800",
    ],
)
def test_invalid_input_is_never_cached(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    with yaml_parse_scope():
        for _ in range(2):
            with pytest.raises(yaml.YAMLError):
                load_closed_yaml(text)
        assert load_closed_yaml("a: [0]") == {"a": [0]}
    assert len(calls) == 3


def test_entry_and_byte_limits_evict_and_oversized_input_bypasses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 2)
    monkeypatch.setattr(cache_module, "_MAX_RETAINED_BYTES", 4096)
    with yaml_parse_scope():
        cache = cache_module._CURRENT.get()
        for text in ("a: 1", "a: 2", "a: 3", "a: 1"):
            load_closed_yaml(text)
        assert len(calls) == 4 and len(cache.entries) <= 2
        assert cache.retained_bytes <= 4096
        expanded = "a: [" + ",".join("word" for _ in range(200)) + "]"
        load_closed_yaml(expanded)
        load_closed_yaml(expanded)
        assert expanded not in cache.entries
        large = "a: " + "x" * 65537
        load_closed_yaml(large)
        load_closed_yaml(large)
        assert large not in cache.entries and len(calls) == 8
    assert not cache.active and not cache.entries and cache.retained_bytes == 0


def test_nested_scope_and_exception_restore_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    with yaml_parse_scope():
        outer = cache_module._CURRENT.get()
        load_closed_yaml("a: 1")
        with pytest.raises(RuntimeError), yaml_parse_scope():
            inner = cache_module._CURRENT.get()
            load_closed_yaml("a: 1")
            raise RuntimeError("stop")
        assert not inner.active and not inner.entries
        assert cache_module._CURRENT.get() is outer
        load_closed_yaml("a: 1")
    assert len(calls) == 2 and not outer.active and not outer.entries
    assert outer.owner is None and outer.policy == ()
    assert cache_module._CURRENT.get() is None


def test_byte_budget_evicts_before_entry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    monkeypatch.setattr(cache_module, "_MAX_RETAINED_BYTES", 2048)
    with yaml_parse_scope():
        for text in ("a: 1", "a: 2", "a: 1"):
            load_closed_yaml(text)
        cache = cache_module._CURRENT.get()
        assert len(cache.entries) == 1 and cache.retained_bytes <= 2048
    assert len(calls) == 3


def test_inherited_context_after_exit_is_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)

    async def child() -> None:
        await released.wait()
        inherited = cache_module._CURRENT.get()
        assert not inherited.active and inherited.owner is None and not inherited.entries
        load_closed_yaml("a: 1")
        load_closed_yaml("a: 1")

    async def run() -> None:
        with yaml_parse_scope():
            load_closed_yaml("a: 1")
            task = asyncio.create_task(child())
        released.set()
        await task

    released = asyncio.Event()
    asyncio.run(run())
    assert len(calls) == 3


def test_timestamps_bypass_retention_of_unaccounted_timezone_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _observe(monkeypatch)
    text = "a: [" + ",".join("2026-01-01T00:00:00+01:00" for _ in range(1000)) + "]"
    with yaml_parse_scope():
        assert load_closed_yaml(text) == load_closed_yaml(text)
        cache = cache_module._CURRENT.get()
        assert not cache.entries and cache.retained_bytes == 0
    assert len(calls) == 2


def test_loader_policy_change_invalidates_cached_value(monkeypatch: pytest.MonkeyPatch) -> None:
    with yaml_parse_scope():
        assert load_closed_yaml("a: 1") == {"a": 1}
        constructors = dict(_ClosedLoader.yaml_constructors)
        constructors["tag:yaml.org,2002:int"] = lambda loader, node: 99
        monkeypatch.setattr(_ClosedLoader, "yaml_constructors", constructors)
        assert load_closed_yaml("a: 1") == {"a": 99}


def test_child_tasks_threads_and_cancellation_do_not_share_retained_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _observe(monkeypatch)

    async def child() -> None:
        load_closed_yaml("a: 1")
        load_closed_yaml("a: 1")

    async def cancelled() -> None:
        with yaml_parse_scope():
            retained.append(cache_module._CURRENT.get())
            load_closed_yaml("a: 1")
            started.set()
            await asyncio.Event().wait()

    async def run() -> None:
        with yaml_parse_scope():
            load_closed_yaml("a: 1")
            await asyncio.create_task(child())
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(load_closed_yaml, "a: 1").result() == {"a": 1}
            load_closed_yaml("a: 1")
        task = asyncio.create_task(cancelled())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not retained[0].active and not retained[0].entries

    retained = []
    started = asyncio.Event()
    asyncio.run(run())
    assert len(calls) == 5
