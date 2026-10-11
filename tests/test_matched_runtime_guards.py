"""Whole-plugin guards fail closed before and around matched callbacks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_matched_execution import _matched

import skills_sdk.evaluation.matched_execution as matched_execution
import skills_sdk.evaluation.plugin_safety as plugin_safety
from skills_sdk.models.plugin_safety import PluginPreExecutionSafetyEvidence
from skills_sdk.models.safety import PackageSafetyBlocker


class _CapabilityTrap:
    """Record and reject every attempted access to an adapter capability."""

    def __init__(self, accesses: list[str]) -> None:
        object.__setattr__(self, "_accesses", accesses)

    def __getattribute__(self, name: str) -> object:
        if name == "_accesses":
            return object.__getattribute__(self, name)
        self._accesses.append(name)
        raise AssertionError(f"adapter capability was accessed: {name}")


def _replace_safety(batch: tuple[object, ...], safety: object) -> tuple[object, ...]:
    """Replace one late variant's whole-plugin safety input without touching source."""
    last = batch[-1]
    context = replace(last.candidate.plugin_context, safety_evidence=safety)
    return (*batch[:-1], replace(last, candidate=replace(last.candidate, plugin_context=context)))


def _assert_completed(plan: object, calibrations: tuple[object, object], batch: tuple[object, ...]) -> None:
    """Prove the original corrected batch remains executable after a rejection."""
    receipt = asyncio.run(matched_execution.execute_matched_lane(plan, "local", calibrations, batch))
    assert receipt.status == "completed" and len(receipt.pairs) == 20


def test_source_stale_immediately_after_preflight_never_reads_adapters_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recapture source after admission and before reading any adapter property."""
    plan, calibrations, batch, events = _matched(tmp_path)
    context = batch[0].baseline.plugin_context
    source = context.root / "shared.md"
    original_source = source.read_bytes()
    original_preflight = matched_execution.preflight_matched_lane
    accesses: list[str] = []
    first = batch[0]
    trapped = replace(
        first,
        baseline=replace(first.baseline, provider=_CapabilityTrap(accesses), judge=_CapabilityTrap(accesses)),
    )

    def stale_after_preflight(*args: object, **kwargs: object) -> object:
        result = original_preflight(*args, **kwargs)
        if result is None:
            source.write_bytes(original_source + b"\nlate drift\n")
        return result

    monkeypatch.setattr(matched_execution, "preflight_matched_lane", stale_after_preflight)
    try:
        receipt = asyncio.run(
            matched_execution.execute_matched_lane(plan, "local", calibrations, (trapped, *batch[1:]))
        )
        assert receipt.status == "blocked" and receipt.blocker.code == "matched_plugin_source_changed"
        assert receipt.provider_invocation_count == receipt.judge_invocation_count == 0
        assert not accesses and not events
    finally:
        source.write_bytes(original_source)
        monkeypatch.setattr(matched_execution, "preflight_matched_lane", original_preflight)
    _assert_completed(plan, calibrations, batch)


@pytest.mark.parametrize("shape", ["raw", "copied", "constructed"])
def test_malformed_plugin_safety_is_typed_rejection_with_zero_callbacks(shape: str, tmp_path: Path) -> None:
    """Reject malformed supplied safety consistently across all supported ingress shapes."""
    plan, calibrations, batch, events = _matched(tmp_path)
    valid = batch[-1].candidate.plugin_context.safety_evidence
    assert valid is not None
    if shape == "raw":
        malformed = valid.model_dump(mode="json")
        malformed["promotion_authorized"] = True
    elif shape == "copied":
        malformed = valid.model_copy(update={"promotion_authorized": True})
    else:
        values = {name: getattr(valid, name) for name in type(valid).model_fields}
        values["promotion_authorized"] = True
        malformed = PluginPreExecutionSafetyEvidence.model_construct(**values)

    receipt = asyncio.run(
        matched_execution.execute_matched_lane(plan, "local", calibrations, _replace_safety(batch, malformed))
    )
    assert receipt.status == "blocked" and receipt.blocker.code == "matched_plugin_safety_rejected"
    assert receipt.provider_invocation_count == receipt.judge_invocation_count == 0
    assert not events
    _assert_completed(plan, calibrations, batch)


@pytest.mark.parametrize("callback", ["provider", "judge"])
@pytest.mark.parametrize("mutation", ["source", "mode"])
def test_callback_plugin_drift_has_typed_runtime_blocker_counts_cleanup_and_recovery(
    callback: str, mutation: str, tmp_path: Path
) -> None:
    """Name source drift around either callback while preserving actual-call accounting."""
    plan, calibrations, batch, events = _matched(tmp_path)
    item = batch[0].candidate
    source = item.plugin_context.root / "shared.md"
    original_source = source.read_bytes()
    original_mode = source.stat().st_mode & 0o777
    adapter = item.provider if callback == "provider" else item.judge
    original_callback = getattr(adapter, "complete" if callback == "provider" else "judge")

    async def mutate_after_call(*args: object, **kwargs: object) -> object:
        result = await original_callback(*args, **kwargs)
        if mutation == "source":
            source.write_bytes(original_source + b"\nruntime drift\n")
        else:
            source.chmod(original_mode ^ 0o100)
        return result

    setattr(adapter, "complete" if callback == "provider" else "judge", mutate_after_call)
    try:
        receipt = asyncio.run(matched_execution.execute_matched_lane(plan, "local", calibrations, batch))
        assert receipt.status == "blocked" and receipt.blocker.code == "matched_plugin_source_changed"
        expected_judges = 1 if callback == "provider" else 2
        assert receipt.provider_invocation_count == 2 and receipt.judge_invocation_count == expected_judges
        assert events.count("provider") == events.count("provider_cleanup") == 2
        assert events.count("dimensional_judge") == events.count("dimensional_cleanup") == expected_judges
        assert not receipt.pairs
    finally:
        source.write_bytes(original_source)
        source.chmod(original_mode)
        setattr(adapter, "complete" if callback == "provider" else "judge", original_callback)
    _assert_completed(plan, calibrations, batch)


def test_safety_becoming_stale_after_preflight_is_typed_runtime_blocker_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reassess safety at runtime and distinguish changed safety from invalid admission."""
    plan, calibrations, batch, events = _matched(tmp_path)
    original_preflight = matched_execution.preflight_matched_lane
    original_assess = plugin_safety.assess_plugin_pre_execution_safety

    def stale_safety(*args: object, **kwargs: object) -> PackageSafetyBlocker:
        return PackageSafetyBlocker(
            code="plugin_safety_evidence_stale",
            message="Whole-plugin safety evidence is stale.",
        )

    def expire_after_preflight(*args: object, **kwargs: object) -> object:
        result = original_preflight(*args, **kwargs)
        if result is None:
            monkeypatch.setattr(plugin_safety, "assess_plugin_pre_execution_safety", stale_safety)
        return result

    monkeypatch.setattr(matched_execution, "preflight_matched_lane", expire_after_preflight)
    receipt = asyncio.run(matched_execution.execute_matched_lane(plan, "local", calibrations, batch))
    assert receipt.status == "blocked" and receipt.blocker.code == "matched_plugin_safety_changed"
    assert receipt.provider_invocation_count == receipt.judge_invocation_count == 0
    assert not events

    monkeypatch.setattr(plugin_safety, "assess_plugin_pre_execution_safety", original_assess)
    monkeypatch.setattr(matched_execution, "preflight_matched_lane", original_preflight)
    _assert_completed(plan, calibrations, batch)
