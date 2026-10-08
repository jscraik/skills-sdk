"""Explicitly offline supplied adapters for observed calibration CLI proof."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput
    from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution
    from skills_sdk.models.observed_calibration import CalibrationJudgeVerdict, ObservedCalibrationReceipt
    from skills_sdk.models.provider import ProviderIdentityV2
    from skills_sdk.models.scorer_quality import ScorerJudgeParameters


@dataclass(frozen=True, slots=True)
class _SuppliedNumericJudge:
    """Invoke a retained fixture verdict; never claim external judge authenticity."""

    identity: ProviderIdentityV2
    parameters: ScorerJudgeParameters
    verdict: CalibrationJudgeVerdict

    async def judge(self, inputs: SelectedCaseJudgeInput) -> object:
        """Return supplied numeric evidence for the executor's binding checks."""
        del inputs
        return self.verdict

    async def cleanup(self) -> None:
        """The controlled adapter owns no external resources."""


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register a separate route without changing read-only calibration v1."""
    parser = commands.add_parser("observed-calibration", help="invoke controlled offline calibration adapters")
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--host-input", type=Path, required=True)
    parser.add_argument("--adapter-mode", choices=("supplied-offline",), required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--robot", action="store_true")


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid offline calibration input")
    return value


def _execution(arguments: argparse.Namespace, raw: object) -> CalibrationProbeExecution:
    from skills_sdk.evaluation import SuppliedTextProviderAdapter, load_selected_case
    from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution
    from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
    from skills_sdk.models.observed_calibration import CalibrationJudgeVerdict
    from skills_sdk.models.provider import ProviderIdentityV2
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
    from skills_sdk.models.provider_execution import ProviderExecutionRequest
    from skills_sdk.models.scorer_quality import ScorerJudgeParameters
    from skills_sdk.providers import JsonValue

    item = _object(raw, {"case_id", "mode", "request", "input_payload", "safety_evidence", "provider", "judge"})
    if not isinstance(item["case_id"], str) or item["mode"] not in {"smoke", "release"}:
        raise ValueError("invalid selected calibration case")
    definition = load_selected_case(
        arguments.package_root,
        source_revision=arguments.source_revision,
        case_id=item["case_id"],
        mode=item["mode"],
    )
    provider = _object(item["provider"], {"descriptor", "output_text", "evidence_refs"})
    if not isinstance(provider["output_text"], str) or not isinstance(provider["evidence_refs"], list):
        raise ValueError("invalid supplied provider")
    judge = _object(item["judge"], {"identity", "parameters", "verdict"})
    return CalibrationProbeExecution(
        definition=definition,
        request=ProviderExecutionRequest.model_validate(item["request"]),
        inputs=SelectedCaseExecutionInput(cast(JsonValue, item["input_payload"]), item["safety_evidence"]),
        provider=SuppliedTextProviderAdapter(
            TextProviderAdapterDescriptor.model_validate(provider["descriptor"]),
            provider["output_text"],
            tuple(provider["evidence_refs"]),
        ),
        judge=_SuppliedNumericJudge(
            ProviderIdentityV2.model_validate(judge["identity"]),
            ScorerJudgeParameters.model_validate(judge["parameters"]),
            CalibrationJudgeVerdict.model_validate(judge["verdict"]),
        ),
    )


def run(arguments: argparse.Namespace, read_input: Callable[[Path], bytes], pairs: Callable[..., object]) -> int:
    """Read bounded no-follow JSON and invoke only controlled supplied adapters."""
    from skills_sdk.core.errors import ContractError
    from skills_sdk.evaluation.observed_calibration import execute_scorer_calibration

    try:
        data = _object(
            json.loads(read_input(arguments.host_input).decode("utf-8"), object_pairs_hook=pairs),
            {"plan", "executions"},
        )
        if not isinstance(data["executions"], list) or not 2 <= len(data["executions"]) <= 64:
            raise ValueError("invalid calibration batch")
        executions = tuple(_execution(arguments, item) for item in data["executions"])
        receipt = asyncio.run(execute_scorer_calibration(data["plan"], executions))
    except (ContractError, OSError, RecursionError, TypeError, ValueError):
        receipt = asyncio.run(execute_scorer_calibration(None, ()))
    _emit(receipt, arguments.json_output)
    return 0 if receipt.status == "pass" else 2


def _emit(receipt: ObservedCalibrationReceipt, json_output: bool) -> None:
    if json_output:
        print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
        return
    print(f"observed-calibration: {receipt.status} (supplied-offline; no external authenticity)")
    print(f"  observed judge invocations: {receipt.judge_invocation_count}")
    if receipt.blocker is not None:
        print(f"  {receipt.blocker.code}: {receipt.blocker.message}")
