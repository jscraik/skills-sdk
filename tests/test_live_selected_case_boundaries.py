"""Cross-boundary provider and judge receipt regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_live_selected_case import _Judge, _Provider, _setup

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import execute_selected_case_with_judge
from skills_sdk.models.evaluation_v2 import ScenarioSetV2
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.providers import ProviderAdapterComplete


def test_judge_failure_names_bound_judge_runner(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)
    judge_identity = request.provider.model_copy(update={"adapter_id": "different-judge"})
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _Provider(request, events), _Judge(judge_identity, events, failure=True)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "judge_execution_failed"
    assert receipt.case_results[0].runner_id == "different-judge"


def test_provider_valid_internal_request_mutation_cannot_pass(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _ValidMutatingProvider(_Provider):
        async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
            replacement = request.provider.model_copy(update={"model_id": "different-model"})
            object.__setattr__(request, "provider", replacement)
            return await super().complete(request, input_payload)

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _ValidMutatingProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "selected_case_request_mutated"
    assert events == ["provider", "provider_cleanup"]


def test_definition_serializer_failure_is_typed_before_dispatch(tmp_path: Path) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _UnserializableScenarioSet(ScenarioSetV2):
        def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise KeyError("private serializer failure")

    forged_set = _UnserializableScenarioSet.model_construct(**definition.scenario_set.model_dump(mode="python"))
    forged_definition = replace(definition, scenario_set=forged_set)
    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        asyncio.run(
            execute_selected_case_with_judge(
                forged_definition, request, payload, _Provider(request, events), _Judge(request.provider, events)
            )
        )
    assert events == []


@pytest.mark.parametrize("malformed_code", ["provider timeout", 42])
def test_host_contract_error_code_is_normalized_after_cleanup(tmp_path: Path, malformed_code: object) -> None:
    definition, payload, request, events = _setup(tmp_path)

    class _MalformedErrorProvider(_Provider):
        async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
            del request, input_payload
            self.events.append("provider")
            raise ContractError(cast(str, malformed_code), "private host failure")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition, request, payload, _MalformedErrorProvider(request, events), _Judge(request.provider, events)
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker is not None
    assert receipt.case_results[0].blocker.code == "invalid_provider_error_code"
    assert events == ["provider", "provider_cleanup"]
