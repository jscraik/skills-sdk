"""Terminal-control regression coverage for human CLI renderers."""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

from skills_sdk.cli import plugin as plugin_cli
from skills_sdk.cli.display import terminal_safe_text
from skills_sdk.cli.main import _print_result, main
from skills_sdk.validation import runtime_copy

REVISION = "1" * 40


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("\x1b[31m", r"\x1b[31m"),
        ("\x9b31m", r"\x9b31m"),
        ("\x9c", r"\x9c"),
        ("\x1b]52;c;payload\x07", r"\x1b]52;c;payload\x07"),
        ("\x1b]8;;target\x1b\\label", r"\x1b]8;;target\x1b\label"),
        ("column\tvalue", r"column\x09value"),
        ("left\u202eright", r"left\u202eright"),
        ("left\u2066right", r"left\u2066right"),
        ("line\u2028break", r"line\u2028break"),
    ],
)
def test_terminal_safe_text_uses_visible_escapes(value: str, expected: str) -> None:
    assert terminal_safe_text(value) == expected


def test_terminal_safe_text_preserves_printable_unicode() -> None:
    value = "résumé/指南-🙂.md"

    assert terminal_safe_text(value) == value


def test_finding_human_output_escapes_message_and_evidence(capsys: pytest.CaptureFixture[str]) -> None:
    finding = SimpleNamespace(
        code="unsafe_path",
        message="crafted\x1b]52;c;payload\x07",
        evidence_refs=("assets/\u202eicon.txt",),
    )
    result = SimpleNamespace(candidate=None, status="blocked", findings=(finding,))

    _print_result("validate", result, json_output=False)

    output = capsys.readouterr().out
    assert "\x1b" not in output and "\x07" not in output and "\u202e" not in output
    assert r"crafted\x1b]52;c;payload\x07" in output
    assert r"assets/\u202eicon.txt" in output


def test_json_output_preserves_original_strings(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {"message": "crafted\x1b]52;c;payload\x07", "path": "assets/\u202eicon.txt"}
    result = SimpleNamespace(model_dump=lambda *, mode: payload)

    _print_result("validate", result, json_output=True)

    output = capsys.readouterr().out
    assert "\x1b" not in output and "\x07" not in output and "\u202e" not in output
    assert "\\u001b" in output and "\\u0007" in output and "\\u202e" in output
    assert json.loads(output) == payload


def test_compare_copy_human_output_escapes_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    validation = SimpleNamespace(findings=())
    comparison = SimpleNamespace(
        status="drift",
        source=validation,
        runtime=validation,
        different_paths=("assets/\x1b[31micon.txt",),
    )
    monkeypatch.setattr(runtime_copy, "compare_runtime_copy", lambda *_args: comparison)

    assert main(["compare-copy", "source", "runtime", "--source-revision", REVISION]) == 2

    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert r"different: assets/\x1b[31micon.txt" in output


def test_plugin_human_output_escapes_child_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    child_validation = SimpleNamespace(status="blocked", findings=())
    result = SimpleNamespace(
        status="blocked",
        findings=(),
        skills=(SimpleNamespace(path="skills/child\u202e", validation=child_validation),),
    )
    monkeypatch.setattr(plugin_cli, "_validation_result", lambda *_args: result)

    status = plugin_cli.run_plugin_validation(Namespace(json_output=False), lambda _path: b"", dict)

    output = capsys.readouterr().out
    assert status == 2
    assert "\u202e" not in output
    assert r"skills/child\u202e: blocked" in output
