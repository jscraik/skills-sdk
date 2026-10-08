"""Installed safety API/CLI proof using explicitly synthetic offline evidence."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import skills_sdk
from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation import SuppliedTextProviderAdapter, execute_selected_case, load_selected_case
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.models.pre_execution_safety import PreExecutionSafetyEvidence
from skills_sdk.models.provider_call import TextProviderAdapterDescriptor
from skills_sdk.models.provider_execution import ProviderExecutionRequest
from skills_sdk.models.selected_case import SelectedCaseJudgeEvidence


def prepare(root: Path) -> None:
    """Prepare disposable input before entering the installed-only environment."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_selected_case_evaluation import REVISION, _adapter, _evidence, _prepared_request, _safety_for, _skill

    root.mkdir()
    definition = load_selected_case(
        _skill(root / "simplify"), source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    payload = {"prompt": definition.scenario_set.cases[0].prompt}
    request = _prepared_request(definition, payload)
    output = "Preserve behavior with focused validation."
    context = {
        "request": request.model_dump(mode="json"),
        "safety_evidence": _safety_for(definition, request).model_dump(mode="json"),
        "input_payload": payload,
        "adapter": {
            "descriptor": _adapter(request, output).descriptor.model_dump(mode="json"),
            "output_text": output,
            "evidence_refs": ["evidence/provider-output.json"],
        },
        "assertion_evidence": _evidence(definition, request, output).model_dump(mode="json"),
    }
    (root / "host-input.json").write_text(json.dumps(context), encoding="utf-8")


class ObservedAdapter:
    """Count metadata reads to prove a rejected package cannot touch the adapter."""

    def __init__(self, descriptor: TextProviderAdapterDescriptor, output: str, refs: tuple[str, ...]) -> None:
        """Compose the immutable supplied adapter without mutating its contract."""
        self._adapter = SuppliedTextProviderAdapter(descriptor, output, refs)
        self.reads = 0

    @property
    def descriptor(self) -> TextProviderAdapterDescriptor:
        """Observe access to host-controlled metadata."""
        self.reads += 1
        return self._adapter.descriptor

    async def complete(self, request: ProviderExecutionRequest, payload: object) -> object:
        """Return controlled fixture output with no external execution."""
        return await self._adapter.complete(request, payload)

    async def cleanup(self) -> None:
        """Delegate the fixture's bounded cleanup."""
        await self._adapter.cleanup()


def _api(root: Path, context: dict[str, object]) -> None:
    """Prove installed acceptance, zero-access rejection, and recovery."""
    definition = load_selected_case(root / "simplify", source_revision="1" * 40, case_id="happy-diff", mode="release")
    request = ProviderExecutionRequest.model_validate(context["request"])
    data = context["adapter"]
    assert isinstance(data, dict)
    adapter = ObservedAdapter(
        TextProviderAdapterDescriptor.model_validate(data["descriptor"]),
        data["output_text"],
        ("evidence/provider-output.json",),
    )
    adapter.reads = 0
    assertion = SelectedCaseJudgeEvidence.model_validate(context["assertion_evidence"])
    blocked = asyncio.run(execute_selected_case(definition, request, context["input_payload"], adapter, assertion))
    assert blocked.status == "blocked" and adapter.reads == 0
    assert blocked.case_results[0].blocker.code == "package_safety_evidence_required"
    safety = PreExecutionSafetyEvidence.model_validate(context["safety_evidence"])
    recovered = asyncio.run(
        execute_selected_case(
            definition, request, SelectedCaseExecutionInput(context["input_payload"], safety), adapter, assertion
        )
    )
    assert recovered.status == "pass" and recovered.candidate == request.candidate and adapter.reads > 0


def _cli(root: Path) -> tuple[int, dict[str, object]]:
    """Invoke only the installed CLI with controlled supplied text."""
    executable = Path(sys.executable).with_name("skills-sdk.exe" if sys.platform == "win32" else "skills-sdk")
    result = subprocess.run(
        [
            str(executable),
            "eval",
            "selected-case",
            str(root / "simplify"),
            "--source-revision",
            "1" * 40,
            "--case",
            "happy-diff",
            "--mode",
            "release",
            "--host-input",
            str(root / "host-input.json"),
            "--json",
            "--robot",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def _schema(context: dict[str, object]) -> None:
    """Prove the installed resource rejects invalid checklist shapes and text."""
    schema = SchemaRegistry().load("pre-execution-safety-evidence.v1")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    accepted = context["safety_evidence"]
    validator.validate(accepted)
    for change in (
        "empty",
        "duplicate",
        "reordered",
        "evidence_duplicate",
        "private",
        "blank",
        *(chr(code) for code in range(28, 32)),
        "\u0085",
    ):
        payload = deepcopy(accepted)
        checks = payload["checklist"]
        if change == "empty":
            checks.clear()
        elif change == "duplicate":
            checks[1] = deepcopy(checks[0])
        elif change == "reordered":
            checks[0], checks[1] = checks[1], checks[0]
        elif change == "evidence_duplicate":
            checks[0]["evidence_ids"] *= 2
        elif change == "private":
            checks[0]["rationale"] = "token=private-fixture"
        else:
            checks[0]["rationale"] = "   " if change == "blank" else change
        for reference in payload["safety_receipt"]["evidence"]:
            if reference["evidence_id"] == "capability-checklist":
                reference["sha256"] = canonical_json_sha256({"version": payload["checklist_version"], "checks": checks})
        assert list(validator.iter_errors(payload)), change
        try:
            PreExecutionSafetyEvidence.model_validate(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"installed model accepted invalid checklist: {change!r}")
    validator.validate(accepted)
    assert schema["x-skills-sdk-semantic-validator"]["required_for"]
    print("installed standalone safety schema rejection and recovery: pass")


def check(root: Path) -> None:
    """Check wheel provenance and both entrypoints without repository fixture imports."""
    assert "site-packages" in str(Path(skills_sdk.__file__).resolve())
    assert "pytest" not in sys.modules
    path = root / "host-input.json"
    context = json.loads(path.read_text(encoding="utf-8"))
    _schema(context)
    _api(root, context)
    code, accepted = _cli(root)
    assert code == 0 and accepted["status"] == "pass"
    path.write_text(json.dumps({**context, "safety_evidence": None}), encoding="utf-8")
    code, blocked = _cli(root)
    assert code == 2 and blocked["status"] == "blocked"
    assert blocked["case_results"][0]["blocker"]["code"] == "package_safety_evidence_required"
    path.write_text(json.dumps(context), encoding="utf-8")
    code, recovered = _cli(root)
    assert code == 0 and recovered["status"] == "pass" and recovered["candidate"] == accepted["candidate"]
    assert not any("agent_skills" in name or "skills_foundry" in name for name in sys.modules)
    print("installed safety API/CLI acceptance, rejection, recovery and zero-access rejection: pass")


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "--prepare":
        prepare(Path(directory).resolve())
    elif mode == "--check":
        check(Path(directory).resolve())
    else:
        raise ValueError("select --prepare or --check")
