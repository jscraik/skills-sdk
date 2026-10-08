from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import yaml

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation import (
    SelectedCaseDefinition,
    SuppliedTextProviderAdapter,
    execute_selected_case,
    load_selected_case,
)
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import EvaluationMode
from skills_sdk.models.pre_execution_safety import PreExecutionSafetyEvidence
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence
from skills_sdk.providers import ProviderAdapterComplete, ProviderAdapterFailure
from tests.safety_execution_fixtures import safety_for_package
from tests.test_provider_execution_contracts import _request

REVISION = "1" * 40


def _case(case_id: str, modes: list[str], *, edge: bool = False) -> dict[str, object]:
    """Build one package-local selected-case fixture."""
    acceptance: list[dict[str, object]] = [
        {"type": "expected_signal", "value": "Bound semantic evidence."},
    ]
    if edge:
        acceptance.append({"type": "not_contains", "value": "safe without evidence"})
    else:
        acceptance.append(
            {
                "type": "semantic_requirements",
                "requirements": [{"id": "preserve_behavior", "all_of": ["behavior"]}],
            }
        )
    return {
        "id": case_id,
        "category": "edge" if edge else "happy",
        "prompt": "Return a bounded review note.",
        "eval_modes": modes,
        "deterministic_checks": {"forbidden_commands": ["rm -rf"]},
        "acceptance": acceptance,
    }


def _skill(root: Path) -> Path:
    """Create a minimal valid skill package with selected cases."""
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: simplify\ndescription: Preserve behavior during cleanup.\n---\n",
        encoding="utf-8",
    )
    references = root / "references"
    references.mkdir()
    payload = {
        "schema_version": "2.0",
        "skill_name": "simplify",
        "cases": [
            _case("happy-diff", ["smoke", "release"]),
            _case("edge-empty-diff", ["release"], edge=True),
        ],
    }
    (references / "evals.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return root


def _prepared_request(definition: SelectedCaseDefinition, input_payload: object) -> ProviderExecutionRequest:
    """Build a provider request bound to a selected-case definition."""
    scenario_set = definition.scenario_set
    payload = _request()
    payload.update(
        candidate=scenario_set.candidate.model_dump(mode="json"),
        scenario_set_id=scenario_set.scenario_set_id,
        case_id=scenario_set.cases[0].case_id,
        input_sha256=canonical_json_sha256(input_payload),
        prepared_at=datetime.now(UTC).isoformat(),
    )
    request = ProviderExecutionRequest.model_validate(payload)
    safety = _safety_for(definition, request)
    payload.update(
        package_safety_receipt_id=safety.safety_receipt.receipt_id,
        package_safety_receipt_sha256=canonical_json_sha256(safety.safety_receipt.model_dump(mode="json")),
    )
    return ProviderExecutionRequest.model_validate(payload)


def _safety_for(definition: SelectedCaseDefinition, request: ProviderExecutionRequest) -> PreExecutionSafetyEvidence:
    """Observe actual fixture source with an explicit synthetic review."""
    return safety_for_package(definition._package_root, REVISION, request.prepared_at)


def _adapter(request: ProviderExecutionRequest, output: str) -> SuppliedTextProviderAdapter:
    """Build a controlled supplied-text adapter for a request."""
    descriptor = TextProviderAdapterDescriptor(provider=request.provider, mode="complete")
    return SuppliedTextProviderAdapter(descriptor, output, ("evidence/provider-output.json",))


class _FailingAdapter:
    def __init__(self, request: ProviderExecutionRequest) -> None:
        """Bind the failing adapter to the request provider."""
        self.descriptor = TextProviderAdapterDescriptor(provider=request.provider, mode="complete")

    async def complete(self, request: ProviderExecutionRequest, input_payload: object) -> ProviderAdapterComplete:
        """Raise a typed retryable provider failure."""
        del request, input_payload
        raise ProviderAdapterFailure(
            code="rate_limited",
            category="provider",
            retryable=True,
            evidence_refs=("provider/rate-limit.json",),
        )

    async def cleanup(self) -> None:
        """Complete the adapter protocol's no-op cleanup."""
        return None


def _evidence(
    definition: SelectedCaseDefinition,
    request: ProviderExecutionRequest,
    output: str,
) -> SelectedCaseJudgeEvidence:
    """Build judge evidence bound to the selected output and assertions."""
    return SelectedCaseJudgeEvidence(
        candidate=definition.scenario_set.candidate,
        scenario_set_id=definition.scenario_set.scenario_set_id,
        case_id=definition.scenario_set.cases[0].case_id,
        provider=request.provider,
        assertion_contract_sha256=definition.assertion_contract_sha256,
        judge=request.provider,
        satisfied_assertion_ids=definition.semantic_signal_ids,
        evidence_refs=("evidence/assertion-review.json", f"judge-results/{'c' * 64}"),
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        judge_result_sha256="c" * 64,
    )


def test_release_case_executes_supplied_adapter_and_bound_assertion_evidence(tmp_path: Path) -> None:
    """Execute a release case with evidence bound to provider output."""
    definition = load_selected_case(
        _skill(tmp_path / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    input_payload = {"prompt": definition.scenario_set.cases[0].prompt}
    output = "Revert the loop and preserve behavior with focused tests."
    request = _prepared_request(definition, input_payload)

    receipt = asyncio.run(
        execute_selected_case(
            definition,
            request,
            SelectedCaseExecutionInput(input_payload, _safety_for(definition, request)),
            _adapter(request, output),
            _evidence(definition, request, output),
        )
    )

    assert receipt.status == "pass"
    assert receipt.provider == request.provider
    assert receipt.case_results[0].observation_sha256 == hashlib.sha256(output.encode()).hexdigest()


def test_edge_case_rejects_smoke_but_accepts_release(tmp_path: Path) -> None:
    """Restrict an edge case to its declared release mode."""
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected_case_mode_mismatch"):
        load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="smoke")

    selected = load_selected_case(package, source_revision=REVISION, case_id="edge-empty-diff", mode="release")
    assert selected.scenario_set.cases[0].case_id == "edge-empty-diff"


@pytest.mark.parametrize("mode", ["release/x", [], {}])
def test_loader_rejects_runtime_mode_outside_public_literals(tmp_path: Path, mode: object) -> None:
    """Reject runtime modes outside the selected-case public literals."""
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected case mode is unsupported"):
        load_selected_case(
            package,
            source_revision=REVISION,
            case_id="happy-diff",
            mode=cast(EvaluationMode, mode),
        )


def test_standard_mode_is_not_accepted_by_selected_case_contract(tmp_path: Path) -> None:
    """Reject the legacy standard mode at the selected-case boundary."""
    with pytest.raises(ContractError, match="selected case mode is unsupported"):
        load_selected_case(
            _skill(tmp_path / "simplify"),
            source_revision=REVISION,
            case_id="happy-diff",
            mode=cast(EvaluationMode, "standard"),
        )


def test_eval_definitions_require_utf8(tmp_path: Path) -> None:
    """Reject evaluation definitions that are not UTF-8 encoded."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    evals.write_bytes(evals.read_text(encoding="utf-8").encode("utf-16"))
    with pytest.raises(ContractError, match="invalid_eval_definitions"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deterministic_checks", ["rm -rf"]),
        ("forbidden_commands", "rm -rf"),
        ("forbidden_commands", [""]),
    ],
)
def test_malformed_deterministic_check_shapes_return_typed_contract_error(
    tmp_path: Path, field: str, value: object
) -> None:
    """Return a typed error for malformed deterministic check shapes."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    if field == "deterministic_checks":
        case[field] = value
    else:
        case["deterministic_checks"][field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="invalid_selected_case"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_acceptance_assertions_reject_undeclared_fields(tmp_path: Path) -> None:
    """Reject undeclared fields in acceptance assertions."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"][0]["extra"] = "ignored"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="acceptance assertions contain unsupported fields"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("command", ["ghp_secret_marker", str(Path("/").joinpath("Users", "private", "tool"))])
def test_private_forbidden_commands_are_rejected(tmp_path: Path, command: str) -> None:
    """Reject forbidden-command declarations containing private values."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["deterministic_checks"]["forbidden_commands"] = [command]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="forbidden_commands must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_case_id_must_match_provider_execution_syntax(tmp_path: Path) -> None:
    """Require case identifiers to match provider execution syntax."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["id"] = "happy case"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case id must use provider execution id syntax"):
        load_selected_case(package, source_revision=REVISION, case_id="happy case", mode="release")


@pytest.mark.parametrize("case_id", [True, [], {}])
def test_case_id_requires_text_before_selection(tmp_path: Path, case_id: object) -> None:
    """Require a textual case identifier before selecting a case."""
    package = _skill(tmp_path / "simplify")

    with pytest.raises(ContractError, match="selected case id must use provider execution id syntax"):
        load_selected_case(
            package,
            source_revision=REVISION,
            case_id=cast(str, case_id),
            mode="release",
        )


def test_case_id_must_not_contain_private_values(tmp_path: Path) -> None:
    """Reject selected-case identifiers containing private values."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["id"] = "ghp_secret_marker"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case id must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="ghp_secret_marker", mode="release")


@pytest.mark.parametrize("category", [[], {}])
def test_category_requires_text_before_membership_checks(tmp_path: Path, category: object) -> None:
    """Require textual categories before category normalization."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["category"] = category
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="selected case category must be text"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_duplicate_semantic_requirement_ids_are_rejected(tmp_path: Path) -> None:
    """Reject duplicate semantic requirement identifiers."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"][1]["requirements"].append(
        {"id": "preserve_behavior", "all_of": ["separate evidence"]}
    )
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="semantic requirement ids must be unique"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize(("field", "value"), [("all_of", []), ("all_of", ""), ("all_of", False)])
def test_present_semantic_term_fields_must_be_non_empty_lists(tmp_path: Path, field: str, value: object) -> None:
    """Require present semantic term fields to be non-empty lists."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    requirement = payload["cases"][0]["acceptance"][1]["requirements"][0]
    requirement["any_of"] = ["behavior"]
    requirement[field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="semantic requirements require stable terms"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_semantic_requirements_reject_undeclared_fields(tmp_path: Path) -> None:
    """Reject undeclared fields in semantic requirements."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"][1]["requirements"][0]["extra"] = "ignored"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="semantic requirements contain unsupported fields"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_deterministic_assertion_values_are_rejected(tmp_path: Path, value: str) -> None:
    """Reject empty deterministic assertion values."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["cases"][0]["acceptance"] = [{"type": "contains", "value": value}]
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match="deterministic assertions require non-empty values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", "1.0", "unsupported_evals_schema"),
        ("skill_name", "another-skill", "skill_name_mismatch"),
    ],
)
def test_eval_definitions_must_bind_the_candidate(tmp_path: Path, field: str, value: str, error: str) -> None:
    """Require evaluation definitions to bind the validated candidate."""
    package = _skill(tmp_path / "simplify")
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload[field] = value
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError, match=error):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")


def test_provider_incompatible_candidate_id_is_rejected_during_loading(tmp_path: Path) -> None:
    """Reject candidate identifiers incompatible with provider contracts."""
    package = _skill(tmp_path / "bearer-token")
    (package / "SKILL.md").write_text(
        "---\nname: bearer-token\ndescription: Preserve behavior during cleanup.\n---\n", encoding="utf-8"
    )
    evals = package / "references" / "evals.yaml"
    payload = yaml.safe_load(evals.read_text(encoding="utf-8"))
    payload["skill_name"] = "bearer-token"
    evals.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ContractError, match="candidate package id must not contain private values"):
        load_selected_case(package, source_revision=REVISION, case_id="happy-diff", mode="release")
