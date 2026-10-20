"""Adverse input and redaction cases found by current-head review."""

import asyncio
import hashlib
from pathlib import Path

import pytest
from test_codex_judge import _events, _executable, _retain_noop
from test_live_selected_case import _setup

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings, _decode_events


@pytest.mark.parametrize("number", ["1e9999", "-1e9999"])
def test_overflowed_event_numbers_are_protocol_blockers(number: str) -> None:
    events = _events().splitlines()
    events[-1] = '{"type":"turn.completed","usage":{"tokens":' + number + "}}"
    with pytest.raises(ContractError) as raised:
        _decode_events("\n".join(events).encode(), ("scope",))
    assert raised.value.code == "codex_judge_protocol_invalid"


@pytest.mark.parametrize(
    "assertions",
    [
        (),
        ("ab",),
        (("scope", "One"), ("scope", "Two")),
        ((),),
        (("scope",),),
        (
            (
                "scope",
                (),
            ),
        ),
    ],
)
def test_invalid_direct_assertions_are_typed_before_execution(tmp_path: Path, assertions: tuple) -> None:
    executable = _executable(tmp_path, "raise AssertionError('must not execute')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", assertions))
    assert raised.value.code == "codex_judge_input_invalid"


def test_observation_representation_omits_private_assertion_ids(tmp_path: Path) -> None:
    private_id = "private-customer-assertion-id"
    events = _events(ids=(private_id,))
    executable = _executable(tmp_path, "print(" + repr(events) + ")")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    result = asyncio.run(adapter.assess("Task", "Response", ((private_id, "Scope"),)))
    assert result.satisfied_assertion_ids == (private_id,)
    assert private_id not in repr(result)


def test_finite_metadata_numbers_remain_accepted() -> None:
    events = _events().splitlines()
    events[-1] = '{"type":"turn.completed","usage":{"tokens":1e308,"tiny":1e-9999}}'
    assert _decode_events("\n".join(events).encode(), ("scope",)).score == 0.9


@pytest.mark.parametrize("number", ["1e9999", "-1e9999"])
def test_overflowed_verdict_numbers_are_protocol_blockers(number: str) -> None:
    from test_codex_judge import _events

    payload = _events().replace("0.9", number).encode()
    with pytest.raises(ContractError) as raised:
        _decode_events(payload, ("scope",))
    assert raised.value.code == "codex_judge_protocol_invalid"


@pytest.mark.parametrize("term", [chr(0xD800), chr(0xDFFF)])
def test_selected_assertion_surrogates_are_rejected_before_invocation(tmp_path: Path, term: str) -> None:
    package = tmp_path / "candidate"
    package.mkdir()
    _definition, _payload, request, _events_seen = _setup(package)
    assertions = (("scope", "semantic_requirements", (term,), ()),)
    digest = canonical_json_sha256([{"id": "scope", "type": "semantic_requirements", "all_of": (term,), "any_of": ()}])
    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric", retain_result=_retain_noop
    )
    inputs = SelectedCaseJudgeInput(request, "Response", hashlib.sha256(b"Response").hexdigest(), digest, assertions)
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.judge(inputs))
    assert raised.value.code == "codex_judge_assertion_contract_drift"


def test_valid_unicode_assertion_terms_remain_bound(tmp_path: Path) -> None:
    package = tmp_path / "candidate"
    package.mkdir()
    _definition, _payload, request, _events_seen = _setup(package)
    term = "Café 文档 ✅"
    assertions = (("scope", "semantic_requirements", (term,), ()),)
    digest = canonical_json_sha256([{"id": "scope", "type": "semantic_requirements", "all_of": (term,), "any_of": ()}])
    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric", retain_result=_retain_noop
    )
    inputs = SelectedCaseJudgeInput(request, "Response", hashlib.sha256(b"Response").hexdigest(), digest, assertions)
    evidence = asyncio.run(adapter.judge(inputs))
    assert evidence.assertion_contract_sha256 == digest
    assert evidence.satisfied_assertion_ids == ("scope",)
