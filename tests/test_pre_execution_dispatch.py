"""Missing and forged safety evidence must stop before adapter property access."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from test_live_selected_case import _Judge, _Provider, _setup
from test_selected_case_evaluation import _evidence, _safety_for

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.evaluation import execute_selected_case, execute_selected_case_with_judge
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.safety import PackageSafetyEvidenceReceipt


class _ObservedProvider(_Provider):
    @property
    def descriptor(self) -> TextProviderAdapterDescriptor:
        self.events.append("provider_descriptor")
        return self._descriptor

    @descriptor.setter
    def descriptor(self, value: TextProviderAdapterDescriptor) -> None:
        self._descriptor = value


class _ObservedJudge(_Judge):
    @property
    def identity(self) -> ProviderIdentityV2:
        self.events.append("judge_identity")
        return self._identity

    @identity.setter
    def identity(self, value: ProviderIdentityV2) -> None:
        self._identity = value


@pytest.mark.parametrize("lane", ["supplied", "live-judge"])
@pytest.mark.parametrize("mutation", ["missing", "wrong-upstream", "stale", "future", "incomplete-checklist"])
def test_safety_rejections_precede_all_adapter_properties_and_recover(tmp_path: Path, lane: str, mutation: str) -> None:
    definition, payload, request, events = _setup(tmp_path)
    evidence = _safety_for(definition, request)
    broken = evidence.model_dump(mode="json")
    changed_request = request
    if mutation == "wrong-upstream":
        broken["safety_receipt"]["input_receipt_id"] = "other-upstream"
    elif mutation in {"stale", "future"}:
        seconds = -7200 if mutation == "stale" else 7200
        broken["safety_receipt"]["observed_at"] = (request.prepared_at + timedelta(seconds=seconds)).isoformat()
        normalized = PackageSafetyEvidenceReceipt.model_validate(broken["safety_receipt"]).model_dump(mode="json")
        changed_request = request.model_copy(
            update={"package_safety_receipt_sha256": canonical_json_sha256(normalized)}
        )
    elif mutation == "incomplete-checklist":
        broken["checklist"].pop()
    provider = _ObservedProvider(request, events)
    judge = _ObservedJudge(request.provider, events)
    supplied = None if mutation == "missing" else broken
    if lane == "supplied":
        receipt = asyncio.run(
            execute_selected_case(
                definition,
                changed_request,
                SelectedCaseExecutionInput(payload, supplied),
                provider,
                _evidence(definition, request, "behavior preserved"),
            )
        )
    else:
        receipt = asyncio.run(
            execute_selected_case_with_judge(
                definition,
                changed_request,
                SelectedCaseExecutionInput(payload, supplied),
                provider,
                judge,
            )
        )
    assert receipt.status == "blocked"
    assert events == []
    if lane == "supplied":
        recovered = asyncio.run(
            execute_selected_case(
                definition,
                request,
                SelectedCaseExecutionInput(payload, evidence),
                provider,
                _evidence(definition, request, "behavior preserved"),
            )
        )
    else:
        recovered = asyncio.run(
            execute_selected_case_with_judge(
                definition,
                request,
                SelectedCaseExecutionInput(payload, evidence),
                provider,
                judge,
            )
        )
    assert recovered.status == "pass"
    assert "provider_descriptor" in events and "provider" in events
    if lane == "live-judge":
        assert "judge_identity" in events and "judge" in events


@pytest.mark.parametrize("lane", ["supplied", "live-judge"])
def test_id_only_old_request_cannot_dispatch(tmp_path: Path, lane: str) -> None:
    definition, payload, request, events = _setup(tmp_path)
    provider = _ObservedProvider(request, events)
    if lane == "supplied":
        receipt = asyncio.run(
            execute_selected_case(
                definition, request, payload, provider, _evidence(definition, request, "behavior preserved")
            )
        )
    else:
        receipt = asyncio.run(
            execute_selected_case_with_judge(
                definition, request, payload, provider, _ObservedJudge(request.provider, events)
            )
        )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker.code == "package_safety_evidence_required"
    assert events == []
