"""Real subprocess boundaries for the optional Codex judge integration."""

import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest

from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import SelectedCaseJudgeInput
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings, _discard_to_eof, _run


def _executable(root: Path, behavior: str) -> Path:
    executable = root / "codex-fixture"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,json,time\n"
        "if '--version' in sys.argv:\n print('codex-cli 0.153.4'); sys.exit(0)\n"
        "data=json.load(sys.stdin)\n" + behavior + "\n"
    )
    executable.chmod(0o755)
    return executable


def _events(score: float = 0.9, ids: tuple[str, ...] = ("scope",)) -> str:
    verdict = {"score": score, "satisfied_assertion_ids": list(ids), "rationale": "Specific fixture evidence."}
    return "\n".join(
        json.dumps(event)
        for event in (
            {"type": "thread.started", "thread_id": "fixture"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(verdict)}},
            {"type": "turn.completed", "usage": {}},
        )
    )


@pytest.mark.parametrize("name", ["café", "文档"])
def test_mcp_overrides_reject_non_ascii_bare_keys(name: str) -> None:
    """Unsupported TOML bare keys must fail before executable configuration."""
    with pytest.raises(ValueError):
        CodexJudgeSettings("model", "0.153.4", (name,))


@pytest.mark.parametrize("field", ["task", "response", "rubric", "assertion", "judge_output"])
def test_invalid_utf8_is_a_typed_blocker_before_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Malformed private text must not reach a subprocess or raw diagnostic."""
    from skills_sdk.providers import codex_judge

    async def forbidden(*args: object) -> bytes:
        pytest.fail("invalid Unicode reached process")

    monkeypatch.setattr(codex_judge, "_run", forbidden)
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    malformed = chr(0xD800)
    with pytest.raises(ContractError) as raised:
        adapter = CodexJudgeAdapter(
            executable,
            tmp_path,
            CodexJudgeSettings("model", "0.153.4", ()),
            malformed if field == "rubric" else "Rubric",
            retain_result=_retain_noop,
        )
        if field == "judge_output":
            from test_live_selected_case import _setup

            package = tmp_path / "candidate"
            package.mkdir()
            definition, _payload, request, _events_seen = _setup(package)
            inputs = SelectedCaseJudgeInput(
                request, malformed, "0" * 64, definition.assertion_contract_sha256, definition.semantic_assertions
            )
            asyncio.run(adapter.judge(inputs))
        else:
            asyncio.run(
                adapter.assess(
                    malformed if field == "task" else "Task",
                    malformed if field == "response" else "Response",
                    (("scope", malformed if field == "assertion" else "Scope"),),
                )
            )
    assert raised.value.code == "codex_judge_input_invalid"
    assert malformed not in str(raised.value)


async def _retain_noop(ref: str, data: bytes) -> None:
    return None


def test_observation_repr_does_not_disclose_private_rationale(tmp_path: Path) -> None:
    """Model explanations may repeat private inputs and must stay out of repr."""
    private = "private-fixture-rationale"
    events = _events().replace("Specific fixture evidence.", private)
    executable = _executable(tmp_path, f"print({events!r})")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    observation = asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert observation.rationale == private
    assert private not in repr(observation)


@pytest.mark.parametrize("missing", ["executable", "parent"])
def test_missing_trusted_paths_have_safe_constructor_errors(tmp_path: Path, missing: str) -> None:
    """Missing host configuration must not disclose absolute paths in diagnostics."""
    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    absent = tmp_path / "private-missing-path"
    with pytest.raises(ValueError) as raised:
        CodexJudgeAdapter(
            absent if missing == "executable" else executable,
            absent if missing == "parent" else tmp_path,
            CodexJudgeSettings("model", "0.153.4", ()),
            "Rubric",
        )
    assert str(tmp_path) not in str(raised.value)
    assert raised.value.__cause__ is None


def test_blank_rationale_is_rejected_before_observation(tmp_path: Path) -> None:
    """A whitespace-only explanation cannot become retained judge evidence."""
    events = _events().replace("Specific fixture evidence.", "   ")
    executable = _executable(tmp_path, f"print({events!r})")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError):
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert adapter.last_observation is None


def test_real_subprocess_judgment_binds_prompt_and_cleans_scratch(tmp_path: Path) -> None:
    """The production path sends no labels and consumes actual process output."""
    checks = (
        "assert 'expected_label' not in str(data)\n"
        "assert '--sandbox' in sys.argv and 'read-only' in sys.argv\n"
        "assert 'mcp_servers.docs.enabled=false' in sys.argv\n"
        "assert 'features.shell_tool=false' in sys.argv\n"
        "assert 'gpt-6.1-sol' in sys.argv\n"
    )
    executable = _executable(tmp_path, checks + "print(" + repr(_events()) + ")")
    settings = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ("docs",))
    adapter = CodexJudgeAdapter(executable, tmp_path, settings, "Frozen rubric")
    result = asyncio.run(adapter.assess("Task facts", "Review response", (("scope", "Retain scope"),)))
    assert result.score == 0.9 and result.satisfied_assertion_ids == ("scope",)
    assert len(result.prompt_sha256) == len(result.event_sha256) == 64
    assert not list(tmp_path.glob("sdk-judge-*"))
    assert settings.public_settings()["temperature"] is None
    assert adapter.parameters == settings.calibration_parameters()
    assert adapter.parameters.temperature is None
    asyncio.run(adapter.cleanup())
    with pytest.raises(ContractError, match="closed"):
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("sys.exit(3)", "codex_judge_process_failed"),
        ("print(" + repr(_events(ids=("foreign",))) + ")", "codex_judge_assertions"),
        ("print(" + repr(_events(ids=("scope", "scope"))) + ")", "codex_judge_assertions"),
        ("print('{}')", "codex_judge_protocol_invalid"),
        ("print(json.dumps({'type':'thread.started'}))", "codex_judge_incomplete"),
        ("print(json.dumps({'type':'turn.failed'}))", "codex_judge_turn_failed"),
        ("print(json.dumps({'type':'item.completed','item':{'type':'command_execution'}}))", "codex_judge_tool_use"),
        ("sys.stderr.write('x'*70000)", "codex_judge_output_limit"),
        ("sys.stdout.write('x'*3000000)", "codex_judge_output_limit"),
    ],
)
def test_failed_or_foreign_output_never_becomes_judge_evidence(tmp_path: Path, body: str, code: str) -> None:
    """Process, resource, protocol and assertion failures retain their boundary."""
    executable = _executable(tmp_path, body)
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == code
    assert adapter.last_observation is None
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_version_drift_rejects_before_model_invocation(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "raise AssertionError('must not invoke')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.3", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_version_drift"


def test_nonexecutable_and_removed_programs_return_typed_startup_failure(tmp_path: Path) -> None:
    """An unusable trusted program cannot leak an OSError or its host path."""
    executable = _executable(tmp_path, "raise AssertionError('must not invoke')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    for removed in (False, True):
        if removed:
            executable.unlink()
        else:
            executable.chmod(0o644)
        with pytest.raises(ContractError) as raised:
            asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
        assert raised.value.code == "codex_judge_start_failed"
        assert str(tmp_path) not in str(raised.value)
        assert not list(tmp_path.glob("sdk-judge-*"))


def test_invalid_version_bytes_are_a_typed_drift_blocker(tmp_path: Path) -> None:
    """Version comparison is exact bytes; incompatible output is never decoded."""
    executable = tmp_path / "invalid-version"
    executable.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write(bytes([255]))\n")
    executable.chmod(0o755)
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_version_drift"


def test_primary_process_failure_survives_cleanup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cleanup diagnostics supplement rather than replace the original failure."""
    from skills_sdk.providers import codex_judge

    async def failed_drain(stream: asyncio.StreamReader) -> None:
        raise OSError("fixture drain failure")

    monkeypatch.setattr(codex_judge, "_discard_to_eof", failed_drain)
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", "raise SystemExit(7)"), tmp_path, b"", 5))
    assert raised.value.code == "codex_judge_process_failed"
    assert raised.value.details[0].exit_code == 7
    assert raised.value.details[1].code == "codex_judge_cleanup_failed"


def test_cleanup_deadline_returns_a_typed_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cleanup deadline must not leak a raw timeout across the adapter boundary."""

    async def expired(awaitable: object, timeout: float) -> object:
        assert timeout == 5
        awaitable.cancel()
        await asyncio.gather(awaitable, return_exceptions=True)
        raise TimeoutError

    executable = _executable(tmp_path, "raise AssertionError('not reached')")
    monkeypatch.setattr(asyncio, "wait_for", expired)
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_cleanup_timeout"


def test_timeout_reaps_child_and_cleans_work_directory(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "time.sleep(20)")
    settings = CodexJudgeSettings("gpt-6.1-sol", "0.153.4", (), timeout_seconds=1)
    adapter = CodexJudgeAdapter(executable, tmp_path, settings, "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_timeout"
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_startup_diagnostics_are_drained_before_stdin(tmp_path: Path) -> None:
    """A noisy child must read a large prompt without a false pipe deadlock."""
    script = (
        "import sys; sys.stderr.write('x'*60000); sys.stderr.flush(); data=sys.stdin.buffer.read(); print(len(data))"
    )
    output = asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"x" * 65536, 5))
    assert output.strip() == b"65536"


def test_timeout_cleans_launcher_descendants_that_keep_output_pipes_open(tmp_path: Path) -> None:
    """A successful launcher exit must not leave its native child running."""
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess,sys,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid))"
    )
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"", 1))
    assert raised.value.code == "codex_judge_timeout"
    pid = int(marker.read_text())
    try:
        for _ in range(200):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if sys.platform == "linux":
                with suppress(FileNotFoundError):
                    state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
                    if state == "Z":
                        break
            time.sleep(0.01)
        else:
            pytest.fail("launcher descendant survived cleanup")
    finally:
        with suppress(ProcessLookupError):
            os.kill(pid, 9)


def test_cleanup_discards_large_residual_pipe_without_retaining_output() -> None:
    """Cleanup must consume residual diagnostics rather than hit a second cap."""

    async def drain() -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"x" * 300000)
        stream.feed_eof()
        await _discard_to_eof(stream)
        assert stream.at_eof()

    asyncio.run(drain())


def test_invalid_controls_and_oversized_input_do_not_start_process(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ("name.enabled=true",))
    executable = _executable(tmp_path, "raise AssertionError('must not invoke')")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("x" * 65537, "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_input_limit"


def test_settings_snapshot_rejects_forgery_and_preserves_applied_identity(tmp_path: Path) -> None:
    """Reported parameters must describe the frozen arguments, not mutable caller state."""
    for model, names in ((" padded ", ()), ("model", ("docs", "docs"))):
        with pytest.raises(ValueError):
            CodexJudgeSettings(model, "0.153.4", names)
    settings = CodexJudgeSettings("fixture-model", "0.153.4", ())
    executable = _executable(tmp_path, "print(" + repr(_events()) + ")")
    adapter = CodexJudgeAdapter(executable, tmp_path, settings, "Rubric")
    object.__setattr__(settings, "model", "changed-model")
    assert adapter.identity.model_id == "fixture-model"
    assert adapter.parameters.model == "fixture-model"
    object.__setattr__(settings, "timeout_seconds", True)
    with pytest.raises(ValueError):
        CodexJudgeAdapter(executable, tmp_path, settings, "Rubric")


@pytest.mark.parametrize("retention_kind", ["function", "object"])
def test_selected_case_protocol_binds_actual_output_and_assertions(tmp_path: Path, retention_kind: str) -> None:
    """The live integration emits the existing public selected-case evidence."""
    from test_live_selected_case import _setup

    package = tmp_path / "candidate"
    package.mkdir()
    definition, _payload, request, _events_seen = _setup(package)
    executable = _executable(tmp_path, "print(" + repr(_events(ids=definition.semantic_signal_ids)) + ")")
    retained: dict[str, bytes] = {}

    async def retain(ref: str, data: bytes) -> None:
        retained[ref] = data

    class Store:
        async def __call__(self, ref: str, data: bytes) -> None:
            retained[ref] = data

    adapter = CodexJudgeAdapter(
        executable,
        tmp_path,
        CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()),
        "Rubric",
        retain_result=retain if retention_kind == "function" else Store(),
    )
    response = "Actual controlled response"
    inputs = SelectedCaseJudgeInput(
        request,
        response,
        hashlib.sha256(response.encode()).hexdigest(),
        definition.assertion_contract_sha256,
        definition.semantic_assertions,
    )
    evidence = asyncio.run(adapter.judge(inputs))
    assert evidence.candidate == request.candidate
    assert evidence.output_sha256 == inputs.output_sha256
    assert evidence.assertion_contract_sha256 == definition.assertion_contract_sha256
    assert evidence.satisfied_assertion_ids == definition.semantic_signal_ids
    assert evidence.judge == adapter.identity
    assert evidence.evidence_refs == ("judge-results/" + evidence.judge_result_sha256,)
    artifact = retained[evidence.evidence_refs[0]]
    assert hashlib.sha256(artifact).hexdigest() == evidence.judge_result_sha256
    assert json.loads(artifact)["rationale"] == "Specific fixture evidence."
    asyncio.run(adapter.cleanup())
    assert not list(tmp_path.glob("sdk-judge-*")) and retained[evidence.evidence_refs[0]] == artifact


@pytest.mark.parametrize(
    "malformed",
    [
        "weaker",
        "extra_field",
        "mapping",
        "numeric_id",
        "numeric_type",
        "list",
        "numeric_term",
        "empty",
        "unknown_type",
        "extra_all_of",
        "any_of",
        "duplicate_id",
        "blank_id",
        "private_id",
    ],
)
def test_assertion_digest_mismatch_rejects_before_any_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    from test_live_selected_case import _setup

    from skills_sdk.providers import codex_judge

    package = tmp_path / "candidate"
    package.mkdir()
    definition, _payload, request, _events_seen = _setup(package)
    response = "Actual response"
    inputs = SelectedCaseJudgeInput(
        request,
        response,
        hashlib.sha256(response.encode()).hexdigest(),
        definition.assertion_contract_sha256,
        definition.semantic_assertions,
    )
    executable = _executable(tmp_path, "raise AssertionError('must not invoke')")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric", retain_result=_retain_noop
    )

    async def forbidden(*args: object) -> bytes:
        pytest.fail("assertion mismatch reached executable")

    monkeypatch.setattr(codex_judge, "_run", forbidden)
    if malformed not in {"weaker", "extra_field"}:
        field, value = {
            "mapping": (2, {"unbound": "instruction"}),
            "numeric_id": (0, 7),
            "numeric_type": (1, 7),
            "list": (2, ["term"]),
            "numeric_term": (2, (7,)),
            "empty": (2, ()),
            "unknown_type": (1, "unknown"),
            "extra_all_of": (2, ("first", "second")),
            "any_of": (3, ("alternative",)),
            "duplicate_id": (0, inputs.assertions[1][0]),
            "blank_id": (0, " "),
            "private_id": (0, str(tmp_path / "private")),
        }[malformed]
        first = list(inputs.assertions[0])
        first[field] = value
        changed_assertions = (tuple(first), *inputs.assertions[1:])
        contract = [
            {"id": item[0], "type": item[1], "all_of": item[2], "any_of": item[3]} for item in changed_assertions
        ]
        inputs = replace(
            inputs, assertions=changed_assertions, assertion_contract_sha256=codex_judge.canonical_json_sha256(contract)
        )
    with pytest.raises(ContractError) as raised:
        changed = (
            inputs.assertions[:1]
            if malformed == "weaker"
            else tuple((*item, "unbound instruction") for item in inputs.assertions)
            if malformed == "extra_field"
            else inputs.assertions
        )
        asyncio.run(adapter.judge(replace(inputs, assertions=changed)))
    assert raised.value.code == "codex_judge_assertion_contract_drift"


def test_selected_case_requires_successful_host_retention(tmp_path: Path) -> None:
    from test_live_selected_case import _setup

    package = tmp_path / "candidate"
    package.mkdir()
    definition, _payload, request, _events_seen = _setup(package)
    response = "Actual response"
    inputs = SelectedCaseJudgeInput(
        request,
        response,
        hashlib.sha256(response.encode()).hexdigest(),
        definition.assertion_contract_sha256,
        definition.semantic_assertions,
    )
    executable = _executable(tmp_path, "print(" + repr(_events(ids=definition.semantic_signal_ids)) + ")")
    settings = CodexJudgeSettings("model", "0.153.4", ())
    with pytest.raises(ContractError) as missing:
        asyncio.run(CodexJudgeAdapter(executable, tmp_path, settings, "Rubric").judge(inputs))
    assert missing.value.code == "codex_judge_retention_required"

    async def failed(ref: str, data: bytes) -> None:
        raise OSError("private host storage failure")

    with pytest.raises(ContractError) as failure:
        asyncio.run(CodexJudgeAdapter(executable, tmp_path, settings, "Rubric", retain_result=failed).judge(inputs))
    assert failure.value.code == "codex_judge_retention_failed"
    assert "private host" not in str(failure.value)


def test_retention_is_async_and_obeys_enclosing_deadline(tmp_path: Path) -> None:
    """A waiting host store must not stall cancellation or emit evidence."""
    from test_live_selected_case import _setup

    package = tmp_path / "candidate"
    package.mkdir()
    definition, _payload, request, _events_seen = _setup(package)
    response = "Actual response"
    inputs = SelectedCaseJudgeInput(
        request,
        response,
        hashlib.sha256(response.encode()).hexdigest(),
        definition.assertion_contract_sha256,
        definition.semantic_assertions,
    )
    executable = _executable(tmp_path, "print(" + repr(_events(ids=definition.semantic_signal_ids)) + ")")
    with pytest.raises(ValueError, match="async host callback"):
        CodexJudgeAdapter(
            executable,
            tmp_path,
            CodexJudgeSettings("model", "0.153.4", ()),
            "Rubric",
            retain_result=lambda ref, data: None,
        )

    async def exercise() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def retain(ref: str, data: bytes) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        adapter = CodexJudgeAdapter(
            executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric", retain_result=retain
        )
        task = asyncio.create_task(adapter.judge(inputs))
        try:
            await asyncio.wait_for(started.wait(), 2)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.05)
            assert cancelled.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_version_failure_retains_safe_diagnostic(tmp_path: Path) -> None:
    executable = tmp_path / "bad-version"
    executable.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('private startup'); sys.exit(7)\n")
    executable.chmod(0o755)
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError):
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert adapter.last_failure is not None and adapter.last_failure.exit_code == 7


def test_version_probe_and_execution_share_the_requested_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup cannot exceed or reset a short requested native execution budget."""
    from skills_sdk.providers import codex_judge

    calls: list[float] = []

    async def controlled(argv: tuple[str, ...], root: Path, payload: bytes, seconds: float) -> bytes:
        calls.append(seconds)
        assert 0 < seconds <= 1
        if "--version" in argv:
            await asyncio.sleep(0.02)
            return b"codex-cli 0.153.4"
        assert seconds < calls[0]
        return _events().encode()

    monkeypatch.setattr(codex_judge, "_run", controlled)
    executable = _executable(tmp_path, "raise AssertionError('controlled path only')")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", (), timeout_seconds=1), "Rubric"
    )
    result = asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert result.score == 0.9 and len(calls) == 2


def test_hanging_version_probe_respects_short_native_budget(tmp_path: Path) -> None:
    """A stalled startup cannot silently use the separate ten-second cap."""
    executable = tmp_path / "hanging-version"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    executable.chmod(0o755)
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", (), timeout_seconds=1), "Rubric"
    )
    started = time.monotonic()
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_timeout"
    assert time.monotonic() - started < 4
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_exhausted_startup_budget_prevents_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful startup cleanup can exhaust the budget before any second process."""
    from skills_sdk.providers import codex_judge

    calls: list[tuple[str, ...]] = []

    async def startup_with_slow_cleanup(argv: tuple[str, ...], root: Path, payload: bytes, seconds: float) -> bytes:
        calls.append(argv)
        assert "--version" in argv, "exhausted budget reached model execution"
        await asyncio.sleep(1.01)
        return b"codex-cli 0.153.4"

    monkeypatch.setattr(codex_judge, "_run", startup_with_slow_cleanup)
    executable = _executable(tmp_path, "raise AssertionError('controlled path only')")
    adapter = CodexJudgeAdapter(
        executable, tmp_path, CodexJudgeSettings("model", "0.153.4", (), timeout_seconds=1), "Rubric"
    )
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_timeout" and len(calls) == 1


def test_overlapping_assessment_is_rejected_without_replacing_active_state(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "time.sleep(0.2); print(" + repr(_events()) + ")")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")

    async def overlap() -> None:
        first = asyncio.create_task(adapter.assess("First", "Response", (("scope", "Scope"),)))
        await asyncio.sleep(0)
        with pytest.raises(ContractError) as raised:
            await adapter.assess("Second", "Response", (("scope", "Scope"),))
        assert raised.value.code == "codex_judge_busy"
        observed = await first
        assert adapter.last_observation == observed

    asyncio.run(overlap())


def test_selected_case_outer_deadline_remains_authoritative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A native120s upper bound never relaxes the engine's tighter overall budget."""
    from test_live_selected_case import _Provider, _safety_for, _setup

    from skills_sdk.evaluation import live_selected_case
    from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput

    package = tmp_path / "candidate"
    package.mkdir()
    definition, payload, request, events = _setup(package)
    executable = _executable(
        tmp_path, "time.sleep(2); print(" + repr(_events(ids=definition.semantic_signal_ids)) + ")"
    )
    adapter = CodexJudgeAdapter(
        executable,
        tmp_path,
        CodexJudgeSettings("model", "0.153.4", ()),
        "Rubric",
        retain_result=_retain_noop,
    )
    assert live_selected_case.DEFAULT_PROVIDER_CALL_LIMITS.overall_seconds == 30
    monkeypatch.setattr(
        live_selected_case,
        "DEFAULT_PROVIDER_CALL_LIMITS",
        replace(live_selected_case.DEFAULT_PROVIDER_CALL_LIMITS, overall_seconds=0.05),
    )
    receipt = asyncio.run(
        live_selected_case.execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            adapter,
        )
    )
    assert receipt.status == "blocked"
    assert receipt.case_results[0].blocker.code == "judge_timeout"
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_selected_case_service_retains_auditable_result(tmp_path: Path) -> None:
    """The actual provider-then-judge seam returns passing, retained evidence."""
    from test_live_selected_case import _Provider, _safety_for, _setup

    from skills_sdk.evaluation.live_selected_case import execute_selected_case_with_judge
    from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput

    package = tmp_path / "candidate"
    package.mkdir()
    definition, payload, request, events = _setup(package)
    executable = _executable(tmp_path, "print(" + repr(_events(ids=definition.semantic_signal_ids)) + ")")
    retained: dict[str, bytes] = {}

    async def retain(ref: str, data: bytes) -> None:
        retained[ref] = data

    adapter = CodexJudgeAdapter(
        executable,
        tmp_path,
        CodexJudgeSettings("model", "0.153.4", ()),
        "Rubric",
        retain_result=retain,
    )
    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request)),
            _Provider(request, events),
            adapter,
        )
    )
    assert receipt.status == "pass" and len(retained) == 1
    ref, data = next(iter(retained.items()))
    assert ref == "judge-results/" + hashlib.sha256(data).hexdigest()
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_early_exit_preserves_safe_diagnostic_without_leaking_stderr(tmp_path: Path) -> None:
    """A child rejecting startup before reading stdin retains cause and exit code."""
    script = (
        "import sys; sys.stderr.write('failed to initialize in-process app-server client: '"
        "'secret-token=fixture-sensitive-value'); sys.exit(7)"
    )
    with pytest.raises(ContractError) as raised:
        asyncio.run(_run((sys.executable, "-c", script), tmp_path, b"x" * 65536, 5))
    error = raised.value
    assert error.code == "codex_judge_process_failed"
    diagnostic = error.details[0]
    assert diagnostic.exit_code == 7
    assert diagnostic.category == "app_server_initialization"
    assert diagnostic.stderr_bytes > 0 and len(diagnostic.stderr_sha256) == 64
    assert "secret-token" not in repr(error.details) and "fixture-sensitive-value" not in repr(error.details)


def test_adapter_retains_failed_invocation_diagnostic_and_cleans_scratch(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "sys.stderr.write('private model failure'); sys.exit(9)")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError):
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert adapter.last_failure.exit_code == 9
    assert adapter.last_failure.category == "unknown_process_failure"
    assert adapter.last_observation is None
    assert not list(tmp_path.glob("sdk-judge-*"))


def test_backend_schema_rejection_remains_a_typed_unaccepted_result(tmp_path: Path) -> None:
    """Controlled proof does not assume backend schema acceptance."""
    executable = _executable(tmp_path, "sys.stderr.write('invalid schema'); sys.exit(3)")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("model", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_process_failed"
    assert adapter.last_failure.category == "output_schema_rejected"
    assert adapter.last_observation is None


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        "[]",
        '{"type":"item.completed","item":null}',
        '{"type":"item.completed","item":{"type":"agent_message"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":7}}',
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}})
        + '\n{"type":"turn.completed"}',
        '{"type":"turn.completed","type":"thread.started"}',
        '{"type":"unknown.tool.event"}\n' + _events(),
        _events() + '\n{"type":"thread.started"}',
    ],
)
def test_malformed_events_are_typed_protocol_blockers(tmp_path: Path, raw: str) -> None:
    """Untrusted output cannot leak parser exceptions or raw private payloads."""
    executable = _executable(tmp_path, "print(" + repr(raw) + ")")
    adapter = CodexJudgeAdapter(executable, tmp_path, CodexJudgeSettings("gpt-6.1-sol", "0.153.4", ()), "Rubric")
    with pytest.raises(ContractError) as raised:
        asyncio.run(adapter.assess("Task", "Response", (("scope", "Scope"),)))
    assert raised.value.code == "codex_judge_protocol_invalid"
    assert adapter.last_observation is None
    assert not list(tmp_path.glob("sdk-judge-*"))
