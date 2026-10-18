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
