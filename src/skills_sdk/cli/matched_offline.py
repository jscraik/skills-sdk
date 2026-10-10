"""Explicit supplied-offline capabilities for guarded matched execution."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from skills_sdk.evaluation.matched_admission import MatchedTrialAdapters, MatchedVariantExecution
    from skills_sdk.evaluation.matched_calibration import DimensionalJudgeInput
    from skills_sdk.evaluation.matched_plugin_context import PluginExecutionContext
    from skills_sdk.models.matched_comparison import MatchedVariantJudgment
    from skills_sdk.models.provider import ProviderIdentityV2
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
    from skills_sdk.models.provider_execution import ProviderExecutionRequest
    from skills_sdk.models.scorer_quality import ScorerJudgeParameters
    from skills_sdk.providers import JsonValue, ProviderAdapterComplete
    from skills_sdk.providers.types import ProviderAdapterStreamItem


@dataclass(frozen=True, slots=True)
class _FixtureJudge:
    identity: ProviderIdentityV2
    parameters: ScorerJudgeParameters
    judgment: MatchedVariantJudgment

    async def judge(self, inputs: DimensionalJudgeInput) -> object:
        """Return explicit fixture evidence, not external model authenticity."""
        del inputs
        return self.judgment

    async def cleanup(self) -> None:
        """The fixture owns no external resources."""


@dataclass(frozen=True, slots=True)
class _FixtureProvider:
    """Expose supplied text through the descriptor-selected offline protocol."""

    descriptor: TextProviderAdapterDescriptor
    parameters: ScorerJudgeParameters
    text: str
    evidence_refs: tuple[str, ...]

    async def complete(self, request: ProviderExecutionRequest, input_payload: JsonValue) -> ProviderAdapterComplete:
        """Return supplied output without invoking an external model."""
        from skills_sdk.providers import ProviderAdapterComplete

        del request, input_payload
        return ProviderAdapterComplete(text=self.text, evidence_refs=self.evidence_refs)

    async def stream(
        self, request: ProviderExecutionRequest, input_payload: JsonValue
    ) -> AsyncIterator[ProviderAdapterStreamItem]:
        """Yield bounded Unicode chunks and terminal evidence on demand."""
        from skills_sdk.providers import DEFAULT_PROVIDER_CALL_LIMITS, ProviderAdapterChunk, ProviderAdapterTerminal

        del request, input_payload

        async def events() -> AsyncIterator[ProviderAdapterStreamItem]:
            # UTF-8 uses at most four bytes per character; do not split encoded characters.
            characters = DEFAULT_PROVIDER_CALL_LIMITS.chunk_bytes // 4
            for offset in range(0, len(self.text), characters):
                yield ProviderAdapterChunk(text=self.text[offset : offset + characters])
            yield ProviderAdapterTerminal(evidence_refs=self.evidence_refs)

        return events()

    async def cleanup(self) -> None:
        """The fixture owns no external resources."""


def add_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Require an explicit offline mode for every callback execution route."""
    for name in (
        "matched-calibration",
        "matched-local",
        "matched-cloud",
        "matched-regression",
        "matched-cloud-regression",
    ):
        parser = commands.add_parser(name, help="execute guarded supplied-offline matched callbacks")
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--adapter-mode", choices=("supplied-offline",), required=True)
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--robot", action="store_true")


def _object(raw: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("offline matched input requires exact members")
    return raw


def _plugin_context(raw: object) -> PluginExecutionContext:
    """Parse explicit host capabilities separately from portable matched receipts."""
    from skills_sdk.evaluation import PluginExecutionContext
    from skills_sdk.models import PluginPackageValidation, PluginPreExecutionSafetyEvidence, PluginValidationPolicy

    data = _object(
        raw,
        {
            "root",
            "validation",
            "driver_skill_path",
            "selected_skill_paths",
            "reference_paths",
            "policy",
            "safety_evidence",
        },
    )
    if any(type(data[key]) is not str or not data[key] for key in ("root", "driver_skill_path")):
        raise ValueError("offline plugin source selection is invalid")
    for key, maximum in (("selected_skill_paths", 9), ("reference_paths", 64)):
        if type(data[key]) is not list or len(data[key]) > maximum or any(type(path) is not str for path in data[key]):
            raise ValueError("offline plugin document selection is invalid")
    return PluginExecutionContext(
        root=Path(data["root"]),
        validation=PluginPackageValidation.model_validate(data["validation"]),
        driver_skill_path=data["driver_skill_path"],
        selected_skill_paths=tuple(data["selected_skill_paths"]),
        reference_paths=tuple(data["reference_paths"]),
        policy=PluginValidationPolicy.model_validate(data["policy"]),
        safety_evidence=PluginPreExecutionSafetyEvidence.model_validate(data["safety_evidence"]),
    )


def _variant(raw: object, *, matched: bool = False) -> MatchedVariantExecution:
    from skills_sdk.evaluation import load_selected_case
    from skills_sdk.evaluation.matched_admission import MatchedTrialAdapters, MatchedVariantExecution
    from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
    from skills_sdk.models.matched_comparison import MatchedVariantJudgment
    from skills_sdk.models.provider import ProviderIdentityV2
    from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
    from skills_sdk.models.provider_execution import ProviderExecutionRequest
    from skills_sdk.models.scorer_quality import ScorerJudgeParameters
    from skills_sdk.providers import JsonValue

    item = _object(
        raw,
        {
            "package_root",
            "source_revision",
            "case_id",
            "request",
            "input_payload",
            "safety_evidence",
            "provider",
            "judge",
        }
        | ({"plugin_context"} if matched else set()),
    )
    if any(not isinstance(item[key], str) or not item[key] for key in ("package_root", "source_revision", "case_id")):
        raise ValueError("offline matched source selection is invalid")
    definition = load_selected_case(
        Path(item["package_root"]), source_revision=item["source_revision"], case_id=item["case_id"], mode="release"
    )
    provider = _object(item["provider"], {"descriptor", "parameters", "output_text", "evidence_refs"})
    judge = _object(item["judge"], {"identity", "parameters", "judgment"})
    if not isinstance(provider["output_text"], str) or not isinstance(provider["evidence_refs"], list):
        raise ValueError("offline provider fixture is invalid")
    provider_parameters = ScorerJudgeParameters.model_validate(provider["parameters"])
    judge_parameters = ScorerJudgeParameters.model_validate(judge["parameters"])
    if matched and provider_parameters.trial_count * 20 > 128:
        raise ValueError("offline matched trial allocation exceeds the lane callback bound")

    def adapters() -> MatchedTrialAdapters:
        return MatchedTrialAdapters(
            _FixtureProvider(
                TextProviderAdapterDescriptor.model_validate(provider["descriptor"]),
                provider_parameters,
                provider["output_text"],
                tuple(provider["evidence_refs"]),
            ),
            _FixtureJudge(
                ProviderIdentityV2.model_validate(judge["identity"]),
                judge_parameters,
                MatchedVariantJudgment.model_validate(judge["judgment"]),
            ),
        )

    first = adapters()
    return MatchedVariantExecution(
        definition,
        ProviderExecutionRequest.model_validate(item["request"]),
        SelectedCaseExecutionInput(cast(JsonValue, item["input_payload"]), item["safety_evidence"]),
        first.provider,
        first.judge,
        _plugin_context(item["plugin_context"]) if matched else None,
        tuple(adapters() for _ in range(provider_parameters.trial_count - 1)) if matched else (),
    )


def _batch(raw: object) -> tuple[object, ...]:
    from skills_sdk.evaluation.matched_admission import MatchedCaseExecution

    if not isinstance(raw, list) or len(raw) != 10:
        raise ValueError("offline matched execution requires exactly ten pairs")
    pairs = tuple(_object(item, {"baseline", "candidate"}) for item in raw)
    return tuple(
        MatchedCaseExecution(_variant(pair["baseline"], matched=True), _variant(pair["candidate"], matched=True))
        for pair in pairs
    )


async def _execute(command: str, raw: object) -> object:
    from skills_sdk.evaluation import (
        execute_matched_calibration,
        execute_matched_cloud,
        execute_matched_cloud_regression,
        execute_matched_lane,
        execute_matched_regression,
    )
    from skills_sdk.evaluation.observed_calibration import CalibrationProbeExecution

    if command == "matched-calibration":
        data = _object(raw, {"plan", "rubric", "executions"})
        if not isinstance(data["executions"], list) or not 2 <= len(data["executions"]) <= 64:
            raise ValueError("offline matched calibration requires bounded probes")
        variants = tuple(_variant(item) for item in data["executions"])
        frames = tuple(
            CalibrationProbeExecution(item.definition, item.request, item.inputs, item.provider, item.judge)
            for item in variants
        )
        return await execute_matched_calibration(data["plan"], data["rubric"], frames)
    fields = {"plan", "calibrations", "executions"}
    if command == "matched-cloud":
        fields = {"handoff", "calibrations", "executions"}
    elif command in {"matched-regression", "matched-cloud-regression"}:
        fields |= {"initial", "assignments"}
    data = _object(raw, fields)
    if not isinstance(data["calibrations"], list) or len(data["calibrations"]) != 2:
        raise ValueError("both offline calibration receipts are required")
    calibrations = tuple(data["calibrations"])
    batch = _batch(data["executions"])
    if command == "matched-cloud":
        return await execute_matched_cloud(data["handoff"], calibrations, batch)
    if command in {"matched-regression", "matched-cloud-regression"}:
        if not isinstance(data["assignments"], list) or len(data["assignments"]) > 10:
            raise ValueError("offline feedback ownership is invalid")
        service = execute_matched_regression if command == "matched-regression" else execute_matched_cloud_regression
        return await service(data["initial"], tuple(data["assignments"]), data["plan"], calibrations, batch)
    return await execute_matched_lane(data["plan"], "local", calibrations, batch)


async def _invalid(command: str) -> object:
    from skills_sdk.evaluation import (
        execute_matched_calibration,
        execute_matched_cloud,
        execute_matched_cloud_regression,
        execute_matched_lane,
        execute_matched_regression,
    )

    if command == "matched-calibration":
        return await execute_matched_calibration(None, None, ())
    if command == "matched-cloud":
        return await execute_matched_cloud(None, (None, None), ())
    if command in {"matched-regression", "matched-cloud-regression"}:
        service = execute_matched_regression if command == "matched-regression" else execute_matched_cloud_regression
        return await service(None, (), None, (None, None), ())
    return await execute_matched_lane(None, "local", (None, None), ())


def run(arguments: argparse.Namespace, read_input: Callable[[Path], bytes], pairs: Callable[..., object]) -> int:
    """Observe supplied-offline callbacks and emit the service's portable receipt."""
    from skills_sdk.core.errors import ContractError

    try:
        raw = json.loads(read_input(arguments.input).decode("utf-8"), object_pairs_hook=pairs)
        receipt = asyncio.run(_execute(arguments.eval_command, raw))
    except (ContractError, OSError, RecursionError, TypeError, ValueError):
        receipt = asyncio.run(_invalid(arguments.eval_command))
    if arguments.json_output:
        print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"{arguments.eval_command}: {receipt.status} (supplied-offline callbacks; no external authenticity)")
        blocker = getattr(receipt, "blocker", None)
        if blocker is None:
            blocker = getattr(getattr(receipt, "execution", None), "blocker", None)
        if blocker is None:
            blocker = getattr(getattr(receipt, "feedback", None), "blocker", None)
        if blocker is not None:
            print(f"  {blocker.code}: {blocker.message}")
    return 0 if receipt.status in {"pass", "completed", "closed"} else 2
