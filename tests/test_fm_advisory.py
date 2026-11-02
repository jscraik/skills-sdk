"""Advisory findings never grant or deny SDK acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.cli.main import main
from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.advisory import FMAdvisoryRequest, FMAdvisoryResult
from skills_sdk.packaging.manifest import build_skill_package
from skills_sdk.providers import fm_advisory
from skills_sdk.providers.fm_advisory import advise_with_fm
from skills_sdk.validation import validate_skill_package


def request_data() -> dict[str, object]:
    """Use synthetic snapshots with an explicit caller-supplied identity."""
    return {
        "schema_version": "fm-advisory-request/v1",
        "candidate": {"package_id": "example", "source_revision": "1" * 40, "content_sha256": "a" * 64},
        "kind": "contradiction",
        "assertion": "The description and instructions must be consistent.",
        "required_context": ["description", "instructions"],
        "documents": [
            {"document_id": "description", "role": "specification", "text": "Read files only."},
            {"document_id": "instructions", "role": "response", "text": "Overwrite the original file."},
        ],
    }


def _verdict(result: str = "Fail") -> bytes:
    return json.dumps(
        {
            "status": "judged",
            "critique": "The instructions require changing a file despite read-only scope.",
            "result": result,
            "specification_evidence_ids": ["S1"],
            "response_evidence_ids": ["R1"],
        }
    ).encode()


def _driver(monkeypatch: pytest.MonkeyPatch, output: bytes) -> list[tuple[str, ...]]:
    calls = []

    async def run(argv: tuple[str, ...], cwd: Path, payload: bytes, seconds: float) -> bytes:
        calls.append(argv)
        assert 0 < seconds <= 30
        if argv[1] == "config":
            assert payload == b""
            return b"(none)\n"
        assert argv[:6] == ("/usr/bin/fm", "respond", "--model", "system", "--no-stream", "--greedy")
        assert "source_atoms" in json.loads(payload)
        assert json.loads((cwd / "schema.json").read_text())["anyOf"]
        return output

    monkeypatch.setattr(fm_advisory, "_availability", lambda: None)
    monkeypatch.setattr(fm_advisory, "_run", run)
    return calls


@pytest.mark.parametrize("verdict,judgement", [("Pass", "no_finding"), ("Fail", "finding")])
def test_valid_advisory_is_bound_but_never_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    verdict: str,
    judgement: str,
) -> None:
    calls = _driver(monkeypatch, _verdict(verdict))
    request = FMAdvisoryRequest.model_validate(request_data())
    result = asyncio.run(advise_with_fm(request))
    assert result.status == "completed" and result.judgement == judgement
    assert result.advisory_only is True and result.acceptance_authorized is False
    assert result.source_binding == "caller_supplied" and result.candidate == request.candidate
    assert result.evidence[0].line_sha256 == hashlib.sha256(b"Read files only.").hexdigest()
    assert len(calls) == 2
    assert "Read files only." not in result.model_dump_json()
    SchemaRegistry().validate("fm-advisory-request.v1", request.model_dump(mode="json"))
    SchemaRegistry().validate("fm-advisory.v1", result.model_dump(mode="json"))


def test_missing_required_context_skips_before_any_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        raise AssertionError("missing context must not even query availability")

    monkeypatch.setattr(fm_advisory, "_availability", forbidden)
    data = request_data()
    data["required_context"] = ["description", "instructions", "policy"]
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(data)))
    assert result.status == "skipped" and result.missing_context_ids == ("policy",)
    assert result.generation_attempted is False and result.judgement is None
    SchemaRegistry().validate("fm-advisory.v1", result.model_dump(mode="json"))


def test_missing_source_role_also_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _driver(monkeypatch, _verdict())
    data = request_data()
    data["documents"] = []
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(data)))
    assert result.status == "skipped" and {"role-specification", "role-response"}.issubset(result.missing_context_ids)
    assert calls == []


def test_model_abstention_is_not_a_binary_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _driver(
        monkeypatch,
        json.dumps(
            {
                "status": "needs_context",
                "critique": "The expected value was not supplied.",
                "missing_context": "The expected value.",
            }
        ).encode(),
    )
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.judgement == "insufficient_evidence" and not result.evidence
    assert result.acceptance_authorized is False


@pytest.mark.parametrize(
    "alteration",
    [
        {"response_evidence_ids": ["R99"]},
        {"response_evidence_ids": ["S1"]},
        {"specification_evidence_ids": ["S1", "S1"]},
        {"response_evidence_ids": []},
        {"extra": "ignored"},
        {"critique": ""},
        {"critique": "credential: private-value"},
        {"result": "Approved"},
        {"status": "needs_context"},
    ],
)
def test_invalid_model_output_has_no_judgement(
    monkeypatch: pytest.MonkeyPatch,
    alteration: dict[str, object],
) -> None:
    raw = json.loads(_verdict()) | alteration
    _driver(monkeypatch, json.dumps(raw).encode())
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.status == "error" and result.reason == "invalid_model_output"
    assert result.judgement is None and result.explanation is None and result.evidence == ()
    assert "private-value" not in result.model_dump_json()


@pytest.mark.parametrize(
    "output", [b'{"status":"judged","status":"needs_context"}', b"NaN", b"1e999", b"{", b"x" * 65537, b"\xff"]
)
def test_malformed_or_oversized_output_is_typed_error(monkeypatch: pytest.MonkeyPatch, output: bytes) -> None:
    _driver(monkeypatch, output)
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.status == "error" and result.judgement is None


def test_custom_provider_is_refused_without_sending_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def configured(argv: tuple[str, ...], cwd: Path, payload: bytes, seconds: float) -> bytes:
        calls.append(argv)
        assert not payload
        return b"configured-provider"

    monkeypatch.setattr(fm_advisory, "_availability", lambda: None)
    monkeypatch.setattr(fm_advisory, "_run", configured)
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.status == "unavailable" and result.reason == "custom_provider_configured"
    assert result.generation_attempted is False and len(calls) == 1


@pytest.mark.parametrize("reason", ["unsupported_platform", "fm_unavailable"])
def test_unavailable_host_is_explicit(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    calls = _driver(monkeypatch, _verdict())
    monkeypatch.setattr(fm_advisory, "_availability", lambda: reason)
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.status == "unavailable" and not calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("documents", [request_data()["documents"][0]] * 2),
        ("required_context", ["description", "description"]),
        ("assertion", " "),
        ("assertion", "x" * 2001),
    ],
)
def test_invalid_input_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        FMAdvisoryRequest.model_validate(request_data() | {field: value})


def test_forged_request_and_nested_document_are_revalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _driver(monkeypatch, _verdict())
    request = FMAdvisoryRequest.model_validate(request_data())
    nested = request.documents[0].model_copy(update={"text": " "})
    forged = request.model_copy(update={"documents": (nested, request.documents[1])})
    with pytest.raises(ValidationError):
        asyncio.run(advise_with_fm(forged))
    assert not calls


@pytest.mark.parametrize("seconds", [True, float("nan"), float("inf"), 0, 31])
def test_invalid_timeout_never_starts_model(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    calls = _driver(monkeypatch, _verdict())
    with pytest.raises(ValueError):
        asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data()), timeout_seconds=seconds))
    assert not calls


@pytest.mark.parametrize("verdict", ["Pass", "Fail"])
def test_cli_finding_and_no_finding_are_both_advisory_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verdict: str,
) -> None:
    _driver(monkeypatch, _verdict(verdict))
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request_data()))
    assert main(["advise-fm", "--request", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["acceptance_authorized"] is False
    with pytest.raises(ContractError):
        SchemaRegistry().validate("package-receipt.v2", data)


def test_advisory_does_not_change_validation_or_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _driver(monkeypatch, _verdict())
    root = tmp_path / "example"
    root.mkdir()
    skill = root / "SKILL.md"
    skill.write_text("---\nname: example\ndescription: Inspect a source snapshot.\n---\nRead only.\n")
    before = skill.read_bytes()
    validation = validate_skill_package(root, source_revision="1" * 40)
    request = FMAdvisoryRequest.model_validate(
        request_data() | {"candidate": validation.candidate.model_dump(mode="json")}
    )
    assert asyncio.run(advise_with_fm(request)).judgement == "finding"
    assert validate_skill_package(root, source_revision="1" * 40) == validation
    assert build_skill_package(root, source_revision="1" * 40).status == "built"
    assert skill.read_bytes() == before


def test_result_cannot_claim_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    _driver(monkeypatch, _verdict())
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    for updates in (
        {"acceptance_authorized": True},
        {"acceptance_authorized": 0},
        {"advisory_only": 1},
        {"status": "skipped"},
        {"generation_attempted": False},
    ):
        with pytest.raises(ValidationError):
            FMAdvisoryResult.model_validate(result.model_dump(mode="json") | updates)


@pytest.mark.parametrize("payload", ['{"kind":"semantic","kind":"contradiction"}', "{", "x" * 16385])
def test_cli_rejects_bad_request_before_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: str,
) -> None:
    calls = _driver(monkeypatch, _verdict())
    path = tmp_path / "bad.json"
    path.write_text(payload)
    assert main(["advise-fm", "--request", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_advisory_request"
    assert not calls


def test_request_source_line_budget_is_enforced() -> None:
    data = request_data()
    data["documents"][0]["text"] = "x\n" * 129
    with pytest.raises(ValidationError, match="128 source lines"):
        FMAdvisoryRequest.model_validate(data)


class _CleanupFailure:
    def __init__(self, root: Path) -> None:
        self.root = root

    def __enter__(self) -> str:
        return str(self.root)

    def __exit__(self, kind: object, error: object, trace: object) -> None:
        raise OSError("controlled cleanup failure")


def test_cleanup_failure_preserves_generation_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = _driver(monkeypatch, _verdict())
    monkeypatch.setattr(fm_advisory, "TemporaryDirectory", lambda **kwargs: _CleanupFailure(tmp_path))
    result = asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert result.status == "error" and result.reason == "execution_failed"
    assert result.generation_attempted is True and result.judgement is None and len(calls) == 2


def test_cleanup_failure_does_not_swallow_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def cancelled(argv: tuple[str, ...], cwd: Path, payload: bytes, seconds: float) -> bytes:
        if argv[1] == "config":
            return b"(none)"
        raise asyncio.CancelledError

    monkeypatch.setattr(fm_advisory, "_run", cancelled)
    monkeypatch.setattr(fm_advisory, "_availability", lambda: None)
    monkeypatch.setattr(fm_advisory, "TemporaryDirectory", lambda **kwargs: _CleanupFailure(tmp_path))
    with pytest.raises(asyncio.CancelledError) as raised:
        asyncio.run(advise_with_fm(FMAdvisoryRequest.model_validate(request_data())))
    assert "fm_advisory_cleanup_failed" in raised.value.__notes__


def test_text_cli_never_prints_model_terminal_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = json.loads(_verdict()) | {"critique": "before\x1b]52;c;dGVzdA==\x07after"}
    _driver(monkeypatch, json.dumps(raw).encode())
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request_data()))
    assert main(["advise-fm", "--request", str(path)]) == 2
    output = capsys.readouterr().out
    assert "\x1b" not in output and "\x07" not in output and "dGVzdA" not in output
