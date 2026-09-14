"""Read-only quality assessment for package-local scenario definitions."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

from skills_sdk.models.scenario_quality import (
    ScenarioQualityAppliedPolicy,
    ScenarioQualityFinding,
    ScenarioQualityReceipt,
)
from skills_sdk.models.validation import SkillPackageValidation
from skills_sdk.validation import validate_skill_package

_EVALS_PATH = "references/evals.yaml"
_MAX_EVALS_BYTES = 1_048_576
_MAX_YAML_NODES = 20_000
_CASE_FIELDS = {
    "id",
    "name",
    "category",
    "task",
    "given",
    "should",
    "realistic",
    "why_realistic",
    "unit",
    "actual_artifact",
    "expected_artifact",
    "reproduce",
    "deterministic_checks",
    "eval_modes",
    "smoke_mode",
    "should_trigger",
    "prepend_skill",
    "claim_ids",
    "prompt",
    "acceptance",
    "output_contract",
}
_TOP_FIELDS = {"schema_version", "skill_name", "scorer_quality", "claims", "release_scenario_sets", "cases"}
_ASSERTION_TYPES = {
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "skill_selected",
    "skill_not_selected",
    "expected_signal",
    "semantic_requirements",
    "discovery_question",
    "text_field_equals",
    "text_field_in",
    "text_field_present",
    "text_field_absent",
    "must_not",
}
_FIELD_ASSERTIONS = {"text_field_equals", "text_field_in", "text_field_present"}
_ASSERTION_FIELDS = {
    "contains": {"type", "value"},
    "not_contains": {"type", "value"},
    "regex": {"type", "value"},
    "not_regex": {"type", "value"},
    "skill_selected": {"type", "expected_skill"},
    "skill_not_selected": {"type", "expected_skill"},
    "expected_signal": {"type", "value"},
    "semantic_requirements": {"type", "requirements"},
    "discovery_question": {"type", "value"},
    "text_field_equals": {"type", "field", "value"},
    "text_field_in": {"type", "field", "values"},
    "text_field_present": {"type", "field"},
    "text_field_absent": {"type", "field"},
    "must_not": {"type", "value"},
}


@dataclass(frozen=True, slots=True)
class ScenarioQualityPolicy:
    minimum_release_cases: int = 5
    target_release_cases: int = 8
    maximum_release_cases: int = 10
    minimum_pressure_or_regression: int = 1
    minimum_negative_or_edge: int = 1

    def __post_init__(self) -> None:
        if (
            self.minimum_release_cases,
            self.target_release_cases,
            self.maximum_release_cases,
            self.minimum_pressure_or_regression,
            self.minimum_negative_or_edge,
        ) != (5, 8, 10, 1, 1):
            raise ValueError("scenario-quality/v1 uses the fixed portable 5/8/10 and 1/1 release policy")


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
        return cast(yaml.Node, super().compose_node(parent, index))


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


def _capture_evals(root: Path, expected_sha256: str) -> bytes:
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    refs_fd = -1
    file_fd = -1
    try:
        refs_fd = os.open("references", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        file_fd = os.open("evals.yaml", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=refs_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("invalid_evals_file_type")
        if before.st_size > _MAX_EVALS_BYTES:
            raise ValueError("evals_file_too_large")
        chunks: list[bytes] = []
        captured = 0
        while captured <= _MAX_EVALS_BYTES:
            chunk = os.read(file_fd, min(65_536, _MAX_EVALS_BYTES + 1 - captured))
            if not chunk:
                break
            chunks.append(chunk)
            captured += len(chunk)
        payload = b"".join(chunks)
        if len(payload) > _MAX_EVALS_BYTES:
            raise ValueError("evals_file_too_large")
        after = os.fstat(file_fd)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("evals_source_changed")
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("evals_source_changed")
        return payload
    finally:
        for descriptor in (file_fd, refs_fd, root_fd):
            if descriptor >= 0:
                os.close(descriptor)


def _finding(code: str, message: str, case_id: str | None = None) -> ScenarioQualityFinding:
    return ScenarioQualityFinding(code=code, message=message, case_id=case_id, evidence_refs=(_EVALS_PATH,))


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _assertion_valid(assertion: Mapping[object, object]) -> bool:
    assertion_type = assertion.get("type")
    allowed_fields = _ASSERTION_FIELDS.get(str(assertion_type))
    if allowed_fields is None or set(assertion) - allowed_fields:
        return False
    if assertion_type in {
        "contains",
        "not_contains",
        "regex",
        "not_regex",
        "expected_signal",
        "discovery_question",
        "must_not",
    }:
        value = assertion.get("value")
        if not _text(value):
            return False
        if assertion_type in {"regex", "not_regex"}:
            try:
                re.compile(cast(str, value))
            except re.error:
                return False
        return True
    if assertion_type in {"skill_selected", "skill_not_selected"}:
        return _text(assertion.get("expected_skill"))
    if assertion_type == "text_field_equals":
        return _text(assertion.get("field")) and _text(assertion.get("value"))
    if assertion_type == "text_field_in":
        return _text(assertion.get("field")) and _text_list(assertion.get("values"))
    if assertion_type in {"text_field_present", "text_field_absent"}:
        return _text(assertion.get("field"))
    if assertion_type == "semantic_requirements":
        requirements = assertion.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            return False
        return all(
            isinstance(requirement, Mapping)
            and not (set(requirement) - {"id", "all_of", "any_of"})
            and _text(requirement.get("id"))
            and (_text_list(requirement.get("all_of")) or _text_list(requirement.get("any_of")))
            and (requirement.get("all_of") is None or _text_list(requirement.get("all_of")))
            and (requirement.get("any_of") is None or _text_list(requirement.get("any_of")))
            for requirement in requirements
        )
    return False


def _case_findings(case: object) -> list[ScenarioQualityFinding]:
    if not isinstance(case, Mapping):
        return [_finding("invalid_scenario_case", "scenario cases must be mappings")]
    raw_case_id = case.get("id")
    case_id = cast(str, raw_case_id) if _text(raw_case_id) else None
    findings: list[ScenarioQualityFinding] = []
    unsupported = sorted(set(case) - _CASE_FIELDS)
    if unsupported:
        findings.append(
            _finding("unsupported_scenario_field", f"unsupported scenario fields: {', '.join(unsupported)}", case_id)
        )
    for field in ("id", "category", "unit", "given", "should", "why_realistic", "prompt", "reproduce"):
        if not _text(case.get(field)):
            findings.append(_finding("missing_scenario_field", f"scenario requires non-empty {field}", case_id))
    if case.get("realistic") is not True:
        findings.append(_finding("scenario_not_realistic", "scenario realistic must be true", case_id))
    for field in ("name", "task", "actual_artifact", "expected_artifact"):
        if field in case and not _text(case.get(field)):
            findings.append(_finding("invalid_scenario_field", f"scenario {field} must be non-empty text", case_id))
    for field in ("smoke_mode", "should_trigger", "prepend_skill"):
        if field in case and not isinstance(case.get(field), bool):
            findings.append(_finding("invalid_scenario_field", f"scenario {field} must be boolean", case_id))
    if "claim_ids" in case and not _text_list(case.get("claim_ids")):
        findings.append(_finding("invalid_scenario_field", "scenario claim_ids must contain text IDs", case_id))
    modes = case.get("eval_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(mode, str) or mode not in {"smoke", "release"} for mode in modes)
    ):
        findings.append(_finding("invalid_eval_modes", "eval_modes must contain smoke or release", case_id))
    checks = case.get("deterministic_checks")
    forbidden = checks.get("forbidden_commands") if isinstance(checks, Mapping) else None
    if not isinstance(forbidden, list) or any(not _text(command) for command in forbidden):
        findings.append(_finding("missing_deterministic_checks", "scenario requires forbidden_commands", case_id))
    acceptance = case.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        findings.append(_finding("missing_acceptance", "scenario requires acceptance assertions", case_id))
        acceptance = []
    field_assertions: set[str] = set()
    for assertion in acceptance:
        assertion_type = assertion.get("type") if isinstance(assertion, Mapping) else None
        if not isinstance(assertion_type, str) or assertion_type not in _ASSERTION_TYPES:
            findings.append(
                _finding("unsupported_acceptance_assertion", "acceptance assertion type is unsupported", case_id)
            )
            continue
        if not _assertion_valid(assertion):
            findings.append(
                _finding("invalid_acceptance_assertion", "acceptance assertion payload is invalid", case_id)
            )
            continue
        if assertion["type"] in _FIELD_ASSERTIONS:
            field_assertions.add(str(assertion["field"]))
    output_contract = case.get("output_contract")
    if output_contract is not None:
        required = output_contract.get("required_fields") if isinstance(output_contract, Mapping) else None
        if (
            not isinstance(output_contract, Mapping)
            or set(output_contract) - {"required_fields"}
            or not isinstance(required, list)
            or not required
            or any(not _text(item) for item in required)
        ):
            findings.append(
                _finding("invalid_output_contract", "output_contract requires non-empty required_fields", case_id)
            )
        else:
            for field in required:
                if field not in field_assertions:
                    findings.append(
                        _finding(
                            "missing_field_assertion",
                            f"required output field lacks field-aware proof: {field}",
                            case_id,
                        )
                    )
    return findings


def _blocked_validation_receipt(
    validation: SkillPackageValidation,
    scenario_set_id: str | None,
    effective_policy: ScenarioQualityAppliedPolicy,
) -> ScenarioQualityReceipt:
    findings = tuple(
        ScenarioQualityFinding(code=item.code, message=item.message, evidence_refs=item.evidence_refs)
        for item in validation.findings
    )
    return ScenarioQualityReceipt(
        candidate=validation.candidate,
        scenario_set_id=scenario_set_id,
        scope="release" if scenario_set_id else "all",
        status="blocked",
        scenario_count=0,
        effective_policy=effective_policy,
        findings=findings,
    )


def _document_cases(
    payload: object,
    package_id: str,
    findings: list[ScenarioQualityFinding],
) -> list[object]:
    if not isinstance(payload, Mapping):
        findings.append(_finding("invalid_evals_document", "evals.yaml must contain a mapping"))
        return []
    unsupported = sorted(set(payload) - _TOP_FIELDS)
    if unsupported:
        findings.append(_finding("unsupported_evals_field", f"unsupported eval fields: {', '.join(unsupported)}"))
    if payload.get("schema_version") != "2.0":
        findings.append(_finding("unsupported_evals_schema", "evals.yaml schema_version must be 2.0"))
    if payload.get("skill_name") != package_id:
        findings.append(_finding("skill_name_mismatch", "evals.yaml skill_name must match the candidate"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        findings.append(_finding("missing_scenarios", "evals.yaml requires a non-empty cases list"))
        return []
    return list(raw_cases)


def _load_evals_payload(
    package_root: Path,
    expected_sha256: str,
    findings: list[ScenarioQualityFinding],
) -> object:
    try:
        raw = _capture_evals(package_root, expected_sha256)
        return yaml.load(raw.decode("utf-8"), Loader=_ClosedLoader)
    except UnicodeDecodeError:
        findings.append(_finding("invalid_evals_utf8", "evals.yaml must be UTF-8"))
    except ValueError as error:
        code = (
            str(error)
            if str(error) in {"evals_file_too_large", "evals_source_changed", "invalid_evals_file_type"}
            else "invalid_evals_yaml"
        )
        findings.append(_finding(code, f"evals.yaml could not be safely loaded: {type(error).__name__}"))
    except (OSError, RecursionError, TypeError, yaml.YAMLError) as error:
        findings.append(
            _finding("invalid_evals_yaml", f"evals.yaml could not be safely loaded: {type(error).__name__}")
        )
    return None


def _release_sets(
    payload: Mapping[object, object], findings: list[ScenarioQualityFinding]
) -> list[Mapping[object, object]]:
    raw_sets = payload.get("release_scenario_sets")
    if raw_sets is None:
        return []
    if not isinstance(raw_sets, list):
        findings.append(_finding("invalid_scenario_set", "release scenario sets must be a list"))
        return []
    if not raw_sets:
        findings.append(_finding("invalid_scenario_set", "release scenario sets must not be empty"))
        return []
    valid_sets: list[Mapping[object, object]] = []
    identifiers: list[str] = []
    for item in raw_sets:
        if not isinstance(item, Mapping) or not _text(item.get("id")):
            findings.append(_finding("invalid_scenario_set", "release scenario set identifiers must be non-empty text"))
            continue
        groups = item.get("groups")
        if (
            not isinstance(groups, Mapping)
            or not groups
            or not all(
                isinstance(values, list) and bool(values) and all(_text(value) for value in values)
                for values in groups.values()
            )
        ):
            findings.append(_finding("invalid_scenario_set", "release scenario set groups must contain text IDs"))
            continue
        identifier = cast(str, item["id"])
        if identifier != identifier.strip():
            findings.append(
                _finding(
                    "invalid_scenario_set", "release scenario set identifiers must not have surrounding whitespace"
                )
            )
            continue
        identifiers.append(identifier)
        valid_sets.append(item)
    if len(identifiers) != len(set(identifiers)):
        findings.append(_finding("invalid_scenario_set", "release scenario set identifiers must be unique"))
        return []
    return valid_sets


def assess_scenario_quality(
    package_root: Path,
    *,
    source_revision: str,
    scenario_set_id: str | None = None,
    policy: ScenarioQualityPolicy | None = None,
) -> ScenarioQualityReceipt:
    active_policy = policy or ScenarioQualityPolicy()
    effective_policy = ScenarioQualityAppliedPolicy(
        minimum_release_cases=active_policy.minimum_release_cases,
        target_release_cases=active_policy.target_release_cases,
        maximum_release_cases=active_policy.maximum_release_cases,
        minimum_pressure_or_regression=active_policy.minimum_pressure_or_regression,
        minimum_negative_or_edge=active_policy.minimum_negative_or_edge,
    )
    selector_invalid = scenario_set_id is not None and (
        not _text(scenario_set_id) or scenario_set_id != scenario_set_id.strip()
    )
    valid_scenario_set_id = scenario_set_id if not selector_invalid else None
    validation = validate_skill_package(package_root, source_revision=source_revision)
    if validation.candidate is None or validation.status == "blocked":
        return _blocked_validation_receipt(validation, valid_scenario_set_id, effective_policy)
    manifest = next((item for item in validation.files if item.path == _EVALS_PATH), None)
    findings: list[ScenarioQualityFinding] = []
    payload: object = None
    payload_loaded = False
    if selector_invalid:
        findings.append(_finding("invalid_scenario_set", "scenario set identifier must be non-empty text"))
    elif manifest is None:
        findings.append(_finding("missing_evals_yaml", "package requires references/evals.yaml"))
    else:
        before_load_findings = len(findings)
        payload = _load_evals_payload(package_root, manifest.sha256, findings)
        payload_loaded = len(findings) == before_load_findings
    cases = _document_cases(payload, validation.candidate.package_id, findings) if payload_loaded else []
    release_sets = _release_sets(payload, findings) if isinstance(payload, Mapping) else []
    raw_ids = [case.get("id") for case in cases if isinstance(case, Mapping) and _text(case.get("id"))]
    if len(raw_ids) != len(set(raw_ids)):
        findings.append(_finding("duplicate_scenario_id", "scenario ids must be unique"))
    selected = cases
    scope: Literal["all", "release"] = "release" if valid_scenario_set_id else "all"
    if valid_scenario_set_id and isinstance(payload, Mapping):
        selected_ids: list[str] | None = None
        matching_sets = [item for item in release_sets if item.get("id") == valid_scenario_set_id]
        if len(matching_sets) == 1:
            groups = cast(Mapping[object, object], matching_sets[0]["groups"])
            selected_ids = [cast(str, value) for values in groups.values() for value in cast(list[object], values)]
        if not selected_ids:
            findings.append(_finding("invalid_scenario_set", "selected release scenario set is missing or empty"))
            selected = []
        else:
            by_id = {case["id"]: case for case in cases if isinstance(case, Mapping) and _text(case.get("id"))}
            unknown = [item for item in selected_ids if item not in by_id]
            if unknown:
                findings.append(
                    _finding("unknown_scenario_id", f"release scenario set contains unknown ids: {', '.join(unknown)}")
                )
            selected = [by_id[item] for item in selected_ids if item in by_id]
    selected_ids = [case.get("id") for case in selected if isinstance(case, Mapping) and _text(case.get("id"))]
    if len(selected_ids) != len(set(selected_ids)):
        findings.append(_finding("duplicate_scenario_id", "scenario ids must be unique"))
    for case in selected:
        findings.extend(_case_findings(case))
    pressure_or_regression_count = 0
    negative_or_edge_count = 0
    if scope == "release":
        categories = [str(case.get("category")) for case in selected if isinstance(case, Mapping)]
        pressure_or_regression_count = sum(value in {"pressure", "regression"} for value in categories)
        negative_or_edge_count = sum(value in {"negative", "edge"} for value in categories)
        for case in selected:
            modes = case.get("eval_modes") if isinstance(case, Mapping) else None
            if isinstance(case, Mapping) and (
                not isinstance(modes, list)
                or any(not isinstance(mode, str) for mode in modes)
                or "release" not in modes
            ):
                findings.append(
                    _finding(
                        "release_case_not_eligible",
                        "release scenario set cases must include release in eval_modes",
                        str(case.get("id") or "") or None,
                    )
                )
        if len(selected) < active_policy.minimum_release_cases:
            findings.append(
                _finding(
                    "release_case_floor",
                    f"release scenario set requires at least {active_policy.minimum_release_cases} cases",
                )
            )
        if len(selected) > active_policy.maximum_release_cases:
            findings.append(
                _finding(
                    "release_case_ceiling",
                    f"release scenario set permits at most {active_policy.maximum_release_cases} cases",
                )
            )
        if pressure_or_regression_count < active_policy.minimum_pressure_or_regression:
            findings.append(
                _finding("release_pressure_floor", "release scenario set requires pressure or regression coverage")
            )
        if negative_or_edge_count < active_policy.minimum_negative_or_edge:
            findings.append(
                _finding("release_negative_floor", "release scenario set requires negative or edge coverage")
            )
    findings.sort(key=lambda item: (item.case_id or "", item.code, item.message))
    return ScenarioQualityReceipt(
        candidate=validation.candidate,
        scenario_set_id=valid_scenario_set_id,
        scope=scope,
        status="blocked" if findings else "pass",
        scenario_count=len(selected),
        pressure_or_regression_count=pressure_or_regression_count,
        negative_or_edge_count=negative_or_edge_count,
        effective_policy=effective_policy,
        findings=tuple(findings),
    )


__all__ = ["ScenarioQualityPolicy", "assess_scenario_quality"]
