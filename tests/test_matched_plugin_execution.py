"""Whole-plugin matched execution rejects drift and recovers without new cases."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_matched_execution import _matched

from skills_sdk.evaluation import execute_matched_lane


@pytest.mark.parametrize("children", [2, 9])
def test_complete_plugin_executes_exactly_ten_cases(children: int, tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path, child_count=children)
    receipt = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
    assert receipt.status == "completed" and len(receipt.pairs) == 10
    assert len(receipt.plan.plugin_scope.candidate.skills) == children
    assert len(receipt.plan.plugin_scope.cases[-1].selected_skill_paths) == children
    assert len(receipt.calibrations[0].targets) == children
    assert receipt.provider_invocation_count == receipt.judge_invocation_count == 20
    assert events.count("provider") == events.count("dimensional_judge") == 20
    assert not receipt.promotion_authorized and not receipt.external_authenticity_verified


def test_missing_plugin_safety_blocks_before_callbacks_and_recovers(tmp_path: Path) -> None:
    plan, calibrations, batch, events = _matched(tmp_path)
    last = batch[-1]
    candidate = replace(last.candidate, plugin_context=replace(last.candidate.plugin_context, safety_evidence=None))
    blocked = asyncio.run(
        execute_matched_lane(plan, "local", calibrations, (*batch[:-1], replace(last, candidate=candidate)))
    )
    assert blocked.status == "blocked" and blocked.blocker.code == "matched_plugin_safety_evidence_required"
    assert blocked.provider_invocation_count == blocked.judge_invocation_count == 0 and not events
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"


@pytest.mark.parametrize("change", ["sibling", "shared", "mode", "opposite_variant"])
def test_callback_plugin_drift_blocks_then_restored_source_recovers(change: str, tmp_path: Path) -> None:
    plan, calibrations, batch, _ = _matched(tmp_path, child_count=2)
    item = batch[-1].candidate if change == "opposite_variant" else batch[0].candidate
    context = batch[0].baseline.plugin_context if change == "opposite_variant" else item.plugin_context
    relative = "skills/supplement-1/SKILL.md" if change == "sibling" else "shared.md"
    source = context.root / relative
    content, mode = source.read_bytes(), source.stat().st_mode & 0o777
    original = item.provider.complete

    async def changed(request: object, payload: object) -> object:
        result = await original(request, payload)
        if change == "mode":
            source.chmod(mode ^ 0o100)
        else:
            source.write_bytes(content + b"\nChanged plugin instructions.\n")
        return result

    item.provider.complete = changed
    try:
        blocked = asyncio.run(execute_matched_lane(plan, "local", calibrations, batch))
        assert blocked.status == "blocked" and blocked.blocker.code == "matched_plugin_source_changed"
        assert not blocked.promotion_authorized
    finally:
        source.write_bytes(content)
        source.chmod(mode)
        item.provider.complete = original
    assert asyncio.run(execute_matched_lane(plan, "local", calibrations, batch)).status == "completed"
