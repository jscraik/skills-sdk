"""Installed optional adapter proof uses only a controlled local executable."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator, FormatChecker

from skills_sdk.core.errors import ContractError
from skills_sdk.models import CodexNativeJudgeParameters
from skills_sdk.providers.codex_judge import CodexJudgeAdapter, CodexJudgeSettings


async def _check(root: Path) -> None:
    executable = root / "fixture-judge"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,json\n"
        "if '--version' in sys.argv:\n print('codex-cli 0.153.4'); sys.exit(0)\n"
        "data=json.load(sys.stdin)\n"
        "if data['task']=='reject':\n print('[]'); sys.exit(0)\n"
        "verdict={'score':1.0,'satisfied_assertion_ids':['scope'],'rationale':'Controlled fixture.'}\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(verdict)}}))\n"
        "print(json.dumps({'type':'turn.completed'}))\n"
    )
    executable.chmod(0o755)
    settings = CodexJudgeSettings("fixture-model", "0.153.4", ())
    parameters = settings.calibration_parameters()
    assert type(parameters) is CodexNativeJudgeParameters
    schema = json.loads(
        files("skills_sdk.schemas").joinpath("codex-native-judge-parameters.v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    payload = json.loads(parameters.model_dump_json())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    assert CodexNativeJudgeParameters.model_validate(payload) == parameters
    for task in ("accepted", "reject", "corrected"):
        adapter = CodexJudgeAdapter(executable, root, settings, "Frozen rubric")
        try:
            result = await adapter.assess(task, "Response", (("scope", "Scope"),))
        except ContractError as error:
            assert task == "reject" and error.code == "codex_judge_protocol_invalid"
        else:
            assert task != "reject" and result.score == 1.0
            assert hashlib.sha256(result.result_json).hexdigest() == result.result_sha256
            assert json.loads(result.result_json)["rationale"] == "Controlled fixture."
        finally:
            await adapter.cleanup()
    assert not list(root.glob("sdk-judge-*"))


if __name__ == "__main__":
    with TemporaryDirectory(prefix="sdk-installed-judge-") as folder:
        asyncio.run(_check(Path(folder)))
    print("installed Codex judge acceptance/rejection/recovery: pass (controlled executable)")
