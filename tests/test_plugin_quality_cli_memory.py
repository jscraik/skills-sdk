"""Resource proof for long permitted strings at the CLI materialisation boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from skills_sdk.cli import plugin_quality as route
from skills_sdk.evaluation import plugin_quality as service


@pytest.mark.parametrize("name", ["request", "assessments", "presentation_request"])
@pytest.mark.parametrize(
    "payload", [b"[]", b'["fixture"]', b"null", b"true", b"false", b"42", b'"fixture"', b" \t\r\n", b"", b" \t\r\n []"]
)
def test_non_object_inputs_stop_before_decoder(
    tmp_path: Path, name: str, payload: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """All three file inputs reject impossible roots before allocating decoded values."""
    from skills_sdk.cli.main import _reject_duplicate_members

    decode = json.loads
    calls: list[str] = []

    def bounded_decode(text: str, **kwargs: object) -> object:
        assert text == "{}", "non-object input reached decoder"
        calls.append(text)
        return decode(text, **kwargs)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("non-object input reached service")

    monkeypatch.setattr(route.json, "loads", bounded_decode)
    monkeypatch.setattr(service, "check_plugin_quality", unexpected_service)
    arguments = Namespace(
        plugin_root=tmp_path,
        request=Path("request"),
        assessments=Path("assessments"),
        presentation_request=Path("presentation_request"),
        json_output=True,
    )
    assert (
        route.run(arguments, lambda path, **limit: payload if path.name == name else b"{}", _reject_duplicate_members)
        == 2
    )
    assert len(calls) == ["request", "assessments", "presentation_request"].index(name)
    result = decode(capsys.readouterr().out)
    assert result["blocker"]["code"] == "plugin_quality_input_invalid"
    assert result["request"] is None and not result["children"]


@pytest.mark.parametrize("prefix", ["", " ", "\t\r\n "])
def test_object_root_keeps_normal_decoder_checks(prefix: str) -> None:
    """Valid objects retain nested arrays and grammar/duplicate validation."""
    from skills_sdk.cli.main import _reject_duplicate_members

    assert route._load_json(
        lambda path, **limit: (prefix + '{"nested":[1,"fixture",null]}').encode(),
        Path("fixture"),
        _reject_duplicate_members,
        {},
    ) == {"nested": [1, "fixture", None]}
    for malformed in ('{"a":1,"a":2}', '{"a":}', '{"a":1,}'):
        with pytest.raises(ValueError):
            route._load_json(
                lambda path, wire=prefix + malformed, **limit: wire.encode(),
                Path("fixture"),
                _reject_duplicate_members,
                {},
            )


@pytest.mark.parametrize("payload", [b'"\\q"', b"[tru]", b"[1,]", b'{"a":1,"a":2}'])
def test_bounded_malformed_json_is_rejected_before_service(
    tmp_path: Path, payload: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real JSON grammar and duplicate-member rejection follow the resource scan."""
    from skills_sdk.cli.main import _reject_duplicate_members

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("malformed input reached the quality service")

    monkeypatch.setattr(service, "check_plugin_quality", unexpected_service)
    arguments = Namespace(
        plugin_root=tmp_path, request=Path("r"), assessments=None, presentation_request=None, json_output=True
    )
    assert route.run(arguments, lambda path, **limit: payload, _reject_duplicate_members) == 2
    assert json.loads(capsys.readouterr().out)["blocker"]["code"] == "plugin_quality_input_invalid"


def test_long_json_string_scan_does_not_amplify_peak_memory() -> None:
    """A bounded subprocess exposes per-character regex allocations before JSON decoding."""
    program = """
import json
import resource
import sys
from skills_sdk.cli.plugin_quality import _scan_json_structure
text = json.dumps({"evidence": "x" * 2_097_152})
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
_scan_json_structure(text)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({"growth": (after - before) * unit}))
"""
    result = subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(result.stdout)["growth"] < 32 * 1_048_576
