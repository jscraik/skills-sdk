"""Installed advisory CLI skip and controlled provider proof; no live FM calls."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models import FMAdvisoryRequest
from skills_sdk.providers import fm_advisory


def _request() -> dict[str, object]:
    return {
        "candidate": {"package_id": "fixture", "source_revision": "1" * 40, "content_sha256": "a" * 64},
        "kind": "contradiction",
        "assertion": "The sources must be consistent.",
        "required_context": ["description", "instructions"],
        "documents": [
            {"document_id": "description", "role": "specification", "text": "Read only."},
            {"document_id": "instructions", "role": "response", "text": "Overwrite the original."},
        ],
    }


async def _controlled(argv: tuple[str, ...], cwd: Path, payload: bytes, seconds: float) -> bytes:
    if argv[1] == "config":
        return b"(none)"
    assert json.loads(payload)["source_atoms"]
    return json.dumps(
        {
            "status": "judged",
            "critique": "The instructions change a file despite read-only scope.",
            "result": "Fail",
            "specification_evidence_ids": ["S1"],
            "response_evidence_ids": ["R1"],
        }
    ).encode()


def main() -> None:
    """Run the installed executable with missing context, then controlled API."""
    with TemporaryDirectory(prefix="sdk-fm-installed-") as folder:
        root = Path(folder).resolve()
        executable = Path(sys.executable).with_name("skills-sdk")
        request = _request() | {"required_context": ["description", "instructions", "policy"]}
        path = root / "request.json"
        path.write_text(json.dumps(request))
        done = subprocess.run(
            [str(executable), "advise-fm", "--request", str(path), "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert done.returncode == 0, (done.stdout, done.stderr)
        result = json.loads(done.stdout)
        assert result["status"] == "skipped" and result["missing_context_ids"] == ["policy"]
        assert result["generation_attempted"] is False and result["acceptance_authorized"] is False
        SchemaRegistry().validate("fm-advisory.v1", result)
        with (
            patch.object(fm_advisory, "_availability", return_value=None),
            patch.object(fm_advisory, "_run", _controlled),
        ):
            observed = asyncio.run(fm_advisory.advise_with_fm(FMAdvisoryRequest.model_validate(_request())))
        assert observed.status == "completed" and observed.judgement == "finding"
        assert observed.acceptance_authorized is False
        SchemaRegistry().validate("fm-advisory.v1", observed.model_dump(mode="json"))
    print("installed FM advisory: skip and controlled finding pass; no acceptance decision or live model call")


if __name__ == "__main__":
    main()
