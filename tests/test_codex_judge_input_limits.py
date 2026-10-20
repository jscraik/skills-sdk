"""Early input-size rejection for native Codex judge entrypoints."""

import asyncio
from pathlib import Path

import pytest
from test_codex_judge import _events, _executable, _retain_noop

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings


@pytest.mark.parametrize(
    "field", ["task", "response", "assertion_id", "assertion_text", "assertion_count", "aggregate"]
)
def test_oversized_prompt_is_rejected_before_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Oversize private fields and collections never reach the JSON allocator."""
    from skills_sdk.providers import codex_judge

    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    task, response, assertions = "Task", "Response", (("scope", "Scope"),)
    oversized = "x" * 65537
    if field == "task":
        task = oversized
    elif field == "response":
        response = oversized
    elif field == "assertion_id":
        assertions = ((oversized, "Scope"),)
    elif field == "assertion_text":
        assertions = (("scope", oversized),)
    elif field == "assertion_count":
        assertions = tuple((f"assertion_{index}", "") for index in range(8193))
    else:
        task, response, assertions = "a" * 30000, "b" * 30000, (("scope", "c" * 6000),)

    def forbidden(*args: object, **kwargs: object) -> str:
        pytest.fail("oversize input reached JSON serialization")

    monkeypatch.setattr(codex_judge.json, "dumps", forbidden)
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess(task, response, assertions))
    assert raised.value.code == "codex_judge_input_limit"


def test_near_limit_prompt_and_encoded_overflow_keep_distinct_outcomes(tmp_path: Path) -> None:
    """The raw preflight preserves valid inputs without replacing byte limits."""
    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    assert asyncio.run(adapter.assess("a" * 64000, "Response", (("scope", "Scope"),))).score == 0.9
    for value in ("é" * 32768, "\n" * 33000):
        with pytest.raises(ContractError) as raised:
            asyncio.run(adapter.assess(value, "Response", (("scope", "Scope"),)))
        assert raised.value.code == "codex_judge_input_limit"


@pytest.mark.parametrize("field", ["output", "assertions", "terms", "term_size", "aggregate"])
def test_selected_case_preflight_runs_before_encoding_and_contract_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """The higher-level seam cannot hash or copy oversized forged input trees."""
    from test_live_selected_case import _setup

    from skills_sdk.providers import codex_judge

    package = tmp_path / "candidate"
    package.mkdir()
    definition, _payload, request, _events_seen = _setup(package)
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric", retain_result=_retain_noop
    )
    output, assertions = "Response", definition.semantic_assertions
    if field == "output":
        output = "x" * 65537
    elif field == "assertions":
        assertions = tuple((f"signal_{index}", "semantic_requirements", ("x",), ()) for index in range(65537))
    elif field == "terms":
        assertions = (("scope", "semantic_requirements", ("",) * 65537, ()),)
    elif field == "term_size":
        assertions = (("scope", "semantic_requirements", ("x" * 65537,), ()),)
    else:
        output, assertions = "x" * 33000, (("scope", "semantic_requirements", ("x" * 33000,), ()),)
    inputs = SelectedCaseJudgeInput(request, output, "0" * 64, definition.assertion_contract_sha256, assertions)

    def forbidden(*args: object, **kwargs: object) -> bytes:
        pytest.fail("oversize selected-case input reached encoding")

    monkeypatch.setattr(codex_judge, "_utf8", forbidden)
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.judge(inputs))
    assert raised.value.code == "codex_judge_input_limit"


def test_rubric_raw_limit_precedes_encoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Construction cannot allocate an encoded copy of an oversized rubric."""
    from skills_sdk.providers import codex_judge

    executable = _executable(tmp_path, "raise AssertionError('not reached')")

    def forbidden(*args: object) -> bytes:
        pytest.fail("oversize rubric reached encoding")

    monkeypatch.setattr(codex_judge, "_utf8", forbidden)
    with pytest.raises(ValueError):
        CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "x" * 32001)
