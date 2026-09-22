"""Portable orchestration for one package-local behavioral evaluation case."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.deterministic_v2 import evaluate_scenario_set_v2
from skills_sdk.evaluation.quality import _capture_evals, _ClosedLoader
from skills_sdk.models.evaluation import ScorerProfile
from skills_sdk.models.evaluation_v2 import EvaluationReceiptV2, ScenarioCaseV2, ScenarioObservationV2, ScenarioSetV2
from skills_sdk.models.packaging import PackageManifestFile, PackageReceiptBlocker
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest, _identity_is_public
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import JsonValue, ProviderAdapterComplete, TextProviderAdapter, execute_provider_call
from skills_sdk.validation import validate_skill_package

EvaluationMode = Literal["smoke", "release"]
SemanticAssertion = tuple[str, str, tuple[str, ...], tuple[str, ...]]
_SEMANTIC_ASSERTIONS = {"discovery_question", "expected_signal", "semantic_requirements"}
_DETERMINISTIC_ASSERTIONS = {"contains", "must_not", "not_contains"}
_SUPPORTED_MODES = {"smoke", "release"}
_EXECUTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SelectedCaseDefinition:
    """Validated package-local inputs for one selected behavioral case."""

    scenario_set: ScenarioSetV2
    scorer: ScorerProfile
    semantic_assertions: tuple[SemanticAssertion, ...]
    deterministic_assertions: tuple[tuple[str, str, str], ...]

    @property
    def semantic_signal_ids(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.semantic_assertions)

    @property
    def assertion_contract_sha256(self) -> str:
        payload = [
            {"id": item[0], "type": item[1], "all_of": item[2], "any_of": item[3]} for item in self.semantic_assertions
        ]
        return canonical_json_sha256(payload)


@dataclass(frozen=True, slots=True)
class SuppliedTextProviderAdapter:
    """Controlled adapter for caller-supplied text; it performs no external I/O."""

    descriptor: TextProviderAdapterDescriptor
    text: str
    evidence_refs: tuple[str, ...]

    async def complete(
        self,
        request: ProviderExecutionRequest,
        input_payload: JsonValue,
    ) -> ProviderAdapterComplete:
        del request, input_payload
        return ProviderAdapterComplete(text=self.text, evidence_refs=self.evidence_refs)

    async def cleanup(self) -> None:
        return None


def _contract_error(code: str, message: str) -> ContractError:
    return ContractError(code=code, message=message)


def _evals_digest(validation_files: tuple[PackageManifestFile, ...]) -> str:
    for item in validation_files:
        if item.path == "references/evals.yaml":
            return item.sha256
    raise _contract_error("missing_eval_definitions", "package does not contain references/evals.yaml")


def _load_cases(package_root: Path, expected_sha256: str, package_id: str) -> list[object]:
    try:
        payload = yaml.load(_capture_evals(package_root, expected_sha256).decode("utf-8"), Loader=_ClosedLoader)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise _contract_error("invalid_eval_definitions", "package eval definitions could not be loaded") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise _contract_error("invalid_eval_definitions", "package eval definitions require a cases list")
    if payload.get("schema_version") != "2.0":
        raise _contract_error("unsupported_evals_schema", "package eval definitions require schema_version 2.0")
    if payload.get("skill_name") != package_id:
        raise _contract_error("skill_name_mismatch", "package eval definitions must match the candidate")
    return cast(list[object], payload["cases"])


def _selected_case(cases: list[object], case_id: str, mode: EvaluationMode) -> dict[str, object]:
    matches = [item for item in cases if isinstance(item, dict) and item.get("id") == case_id]
    if len(matches) != 1:
        raise _contract_error("selected_case_not_found", "selected case must exist exactly once")
    case = cast(dict[str, object], matches[0])
    modes = case.get("eval_modes")
    if not isinstance(modes, list) or mode not in modes:
        raise _contract_error("selected_case_mode_mismatch", "selected case does not declare the requested mode")
    return case


def _assertion_signals(
    case: dict[str, object],
) -> tuple[tuple[SemanticAssertion, ...], tuple[tuple[str, str, str], ...]]:
    acceptance = case.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        raise _contract_error("missing_acceptance_evidence", "selected case requires acceptance assertions")
    semantic: list[SemanticAssertion] = []
    deterministic: list[tuple[str, str, str]] = []
    for index, raw in enumerate(acceptance, start=1):
        semantic_items, deterministic_item = _assertion_signal(raw, index)
        semantic.extend(semantic_items)
        if deterministic_item is not None:
            deterministic.append(deterministic_item)
    return tuple(semantic), tuple(deterministic)


def _assertion_signal(raw: object, index: int) -> tuple[tuple[SemanticAssertion, ...], tuple[str, str, str] | None]:
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        raise _contract_error("invalid_acceptance_assertion", "acceptance assertions must be typed mappings")
    assertion_type = cast(str, raw["type"])
    allowed_fields = {"type", "requirements"} if assertion_type == "semantic_requirements" else {"type", "value"}
    if set(raw) - allowed_fields:
        raise _contract_error("invalid_acceptance_assertion", "acceptance assertions contain unsupported fields")
    prefix = f"acceptance-{index}"
    if assertion_type == "semantic_requirements":
        requirements = raw.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            raise _contract_error("invalid_acceptance_assertion", "semantic requirements must be non-empty")
        assertions = tuple(_semantic_requirement(prefix, item) for item in requirements if isinstance(item, dict))
        if len(assertions) != len(requirements):
            raise _contract_error("invalid_acceptance_assertion", "semantic requirements require stable ids")
        assertion_ids = tuple(item[0] for item in assertions)
        if len(assertion_ids) != len(set(assertion_ids)):
            raise _contract_error("invalid_acceptance_assertion", "semantic requirement ids must be unique")
        return assertions, None
    if assertion_type in _SEMANTIC_ASSERTIONS:
        value = raw.get("value")
        if not isinstance(value, str) or not value.strip():
            raise _contract_error("invalid_acceptance_assertion", "semantic assertions require expected behavior")
        return ((prefix, assertion_type, (value,), ()),), None
    if assertion_type in _DETERMINISTIC_ASSERTIONS and isinstance(raw.get("value"), str):
        value = cast(str, raw["value"])
        if not value.strip():
            raise _contract_error("invalid_acceptance_assertion", "deterministic assertions require non-empty values")
        return (), (prefix, assertion_type, value)
    raise _contract_error("unsupported_acceptance_assertion", "selected case uses an unsupported assertion type")


def _semantic_requirement(prefix: str, raw: dict[object, object]) -> SemanticAssertion:
    if set(raw) - {"id", "all_of", "any_of"}:
        raise _contract_error("invalid_acceptance_assertion", "semantic requirements contain unsupported fields")
    requirement_id = raw.get("id")
    all_of = raw.get("all_of", ())
    any_of = raw.get("any_of", ())
    if (
        not isinstance(requirement_id, str)
        or not requirement_id.strip()
        or not isinstance(all_of, (list, tuple))
        or not isinstance(any_of, (list, tuple))
        or ("all_of" in raw and not all_of)
        or ("any_of" in raw and not any_of)
        or not (*all_of, *any_of)
        or not all(isinstance(item, str) and item.strip() for item in (*all_of, *any_of))
    ):
        raise _contract_error("invalid_acceptance_assertion", "semantic requirements require stable terms")
    return (f"{prefix}-{requirement_id}", "semantic_requirements", tuple(all_of), tuple(any_of))


def _category(value: object) -> Literal["happy", "pressure", "boundary", "regression"]:
    if not isinstance(value, str):
        raise _contract_error("invalid_selected_case", "selected case category must be text")
    if value in {"happy", "pressure", "regression"}:
        return cast(Literal["happy", "pressure", "regression"], value)
    if value in {"boundary", "edge", "negative"}:
        return "boundary"
    raise _contract_error("invalid_selected_case", "selected case category is unsupported")


def load_selected_case(
    package_root: Path,
    *,
    source_revision: str,
    case_id: str,
    mode: EvaluationMode,
) -> SelectedCaseDefinition:
    """Load one validated package-local eval case without executing it."""

    if not isinstance(mode, str) or mode not in _SUPPORTED_MODES:
        raise _contract_error("invalid_selected_case", "selected case mode is unsupported")
    if not isinstance(case_id, str):
        raise _contract_error("invalid_selected_case", "selected case id must use provider execution id syntax")
    validation = validate_skill_package(package_root, source_revision=source_revision)
    if validation.status != "pass" or validation.candidate is None:
        raise _contract_error("package_validation_blocked", "selected-case evaluation requires a valid package")
    if not _identity_is_public(validation.candidate.package_id):
        raise _contract_error("invalid_selected_case", "candidate package id must not contain private values")
    case = _selected_case(
        _load_cases(package_root, _evals_digest(validation.files), validation.candidate.package_id),
        case_id,
        mode,
    )
    semantic, deterministic = _assertion_signals(case)
    raw_checks = case.get("deterministic_checks")
    if not isinstance(raw_checks, dict):
        raise _contract_error("invalid_selected_case", "deterministic_checks must be a mapping")
    raw_forbidden = raw_checks.get("forbidden_commands")
    if not isinstance(raw_forbidden, list) or not all(isinstance(item, str) and item.strip() for item in raw_forbidden):
        raise _contract_error("invalid_selected_case", "forbidden_commands must be a list of non-empty text")
    if not all(_identity_is_public(item) for item in raw_forbidden):
        raise _contract_error("invalid_selected_case", "forbidden_commands must not contain private values")
    forbidden = tuple(raw_forbidden)
    prompt = case.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise _contract_error("invalid_selected_case", "selected case requires a prompt")
    if _EXECUTION_ID_PATTERN.fullmatch(case_id) is None:
        raise _contract_error("invalid_selected_case", "selected case id must use provider execution id syntax")
    if not _identity_is_public(case_id):
        raise _contract_error("invalid_selected_case", "selected case id must not contain private values")
    semantic_ids = tuple(item[0] for item in semantic)
    selected = ScenarioCaseV2(
        case_id=case_id,
        category=_category(case.get("category")),
        prompt=prompt,
        expected_signals=(*semantic_ids, *(item[0] for item in deterministic)),
        forbidden_commands=forbidden,
        oracle="expected_signal",
    )
    scenario_set = ScenarioSetV2(
        candidate=validation.candidate,
        scenario_set_id=f"{validation.candidate.package_id}-{case_id}-{mode}",
        release=False,
        cases=(selected,),
    )
    scorer = ScorerProfile(
        candidate=validation.candidate,
        scorer_id="selected-case-deterministic-v1",
        scorer_type="deterministic",
        version_or_digest="selected-case-v1",
        pass_threshold=1.0,
        deterministic_checks_first=True,
        calibration_required=False,
    )
    return SelectedCaseDefinition(scenario_set, scorer, semantic, deterministic)


def _blocker(
    code: str, message: str, evidence_refs: tuple[str, ...] = ("references/evals.yaml",)
) -> PackageReceiptBlocker:
    return PackageReceiptBlocker(code=code, message=message, evidence_refs=evidence_refs)


def _blocked_observation(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    code: str,
    message: str,
    evidence_refs: tuple[str, ...] = ("references/evals.yaml",),
) -> ScenarioObservationV2:
    return ScenarioObservationV2(
        candidate=definition.scenario_set.candidate,
        scenario_set_id=definition.scenario_set.scenario_set_id,
        case_id=definition.scenario_set.cases[0].case_id,
        provider=request.provider,
        status="blocked",
        runner_id=request.provider.adapter_id,
        runner_version_or_digest=request.provider.adapter_version_or_digest,
        blocker=_blocker(code, message, evidence_refs),
    )


def _deterministic_signals(text: str, assertions: tuple[tuple[str, str, str], ...]) -> tuple[str, ...]:
    normalized = text.casefold()
    signals: list[str] = []
    for signal, assertion_type, expected in assertions:
        present = expected.casefold() in normalized
        passed = present if assertion_type == "contains" else not present
        if passed:
            signals.append(signal)
    return tuple(signals)


def _observed_forbidden_commands(text: str, commands: tuple[str, ...]) -> tuple[str, ...]:
    normalized = text.casefold()
    return tuple(command for command in commands if command.casefold() in normalized)


def _validated_observation(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    supplied: SelectedCaseJudgeEvidence,
    output_text: str,
    output_sha256: str,
) -> ScenarioObservationV2:
    case_id = definition.scenario_set.cases[0].case_id
    if (
        supplied.candidate != definition.scenario_set.candidate
        or supplied.scenario_set_id != definition.scenario_set.scenario_set_id
        or supplied.case_id != case_id
        or supplied.provider != request.provider
        or supplied.output_sha256 != output_sha256
        or supplied.assertion_contract_sha256 != definition.assertion_contract_sha256
    ):
        return _blocked_observation(
            definition,
            request,
            "selected_case_identity_mismatch",
            "assertion evidence does not bind the executed output",
        )
    if not set(supplied.satisfied_assertion_ids) <= set(definition.semantic_signal_ids):
        return _blocked_observation(
            definition,
            request,
            "missing_semantic_evidence",
            "semantic assertions require bound evidence",
        )
    deterministic = _deterministic_signals(output_text, definition.deterministic_assertions)
    case = definition.scenario_set.cases[0]
    judge_result_ref = f"judge-results/{supplied.judge_result_sha256}"
    evidence_refs = (
        supplied.evidence_refs
        if judge_result_ref in supplied.evidence_refs
        else (*supplied.evidence_refs, judge_result_ref)
    )
    return ScenarioObservationV2(
        candidate=supplied.candidate,
        scenario_set_id=supplied.scenario_set_id,
        case_id=supplied.case_id,
        provider=supplied.provider,
        status="completed",
        observed_signals=(*supplied.satisfied_assertion_ids, *deterministic),
        observed_commands=_observed_forbidden_commands(output_text, case.forbidden_commands),
        evidence_refs=evidence_refs,
        output_sha256=supplied.output_sha256,
        runner_id=supplied.judge.adapter_id,
        runner_version_or_digest=supplied.judge.adapter_version_or_digest,
    )


def _request_matches_definition(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
) -> bool:
    case = definition.scenario_set.cases[0]
    return (
        request.candidate == definition.scenario_set.candidate
        and request.scenario_set_id == definition.scenario_set.scenario_set_id
        and request.case_id == case.case_id
        and input_payload == {"prompt": case.prompt}
        and request.input_sha256 == canonical_json_sha256(input_payload)
    )


async def execute_selected_case(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    input_payload: JsonValue,
    adapter: TextProviderAdapter | None,
    assertion_evidence: SelectedCaseJudgeEvidence | None,
) -> EvaluationReceiptV2:
    """Execute one injected provider call and evaluate bound assertion evidence."""

    if not _request_matches_definition(definition, request, input_payload):
        observation = _blocked_observation(
            definition,
            request,
            "selected_case_request_mismatch",
            "provider request does not bind the selected case",
        )
        return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)
    if adapter is None or assertion_evidence is None:
        observation = _blocked_observation(
            definition,
            request,
            "provider_adapter_required",
            "adapter and assertion evidence are required",
        )
        return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)
    try:
        assertion_evidence = SelectedCaseJudgeEvidence.model_validate(assertion_evidence.model_dump(mode="json"))
    except (ValidationError, PydanticSerializationError):
        observation = _blocked_observation(
            definition,
            request,
            "invalid_judge_evidence",
            "assertion evidence failed boundary validation",
        )
        return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)
    outcome = await execute_provider_call(request, input_payload, adapter)
    if outcome.complete_text is None or outcome.public_result.output_sha256 is None:
        execution = outcome.public_result.execution
        failure = execution.blocker or execution.error
        failure_code = failure.code if failure is not None else "provider_output_unavailable"
        failure_refs = failure.evidence_refs if failure is not None else ("references/evals.yaml",)
        retryable = execution.error.retryable if execution.error is not None else False
        observation = _blocked_observation(
            definition,
            request,
            failure_code,
            f"provider execution {execution.status}; retryable={str(retryable).lower()}",
            failure_refs,
        )
    else:
        observation = _validated_observation(
            definition,
            request,
            assertion_evidence,
            outcome.complete_text,
            outcome.public_result.output_sha256,
        )
    return evaluate_scenario_set_v2(definition.scenario_set, (observation,), scorer=definition.scorer)


__all__ = [
    "EvaluationMode",
    "SelectedCaseDefinition",
    "SuppliedTextProviderAdapter",
    "execute_selected_case",
    "load_selected_case",
]
