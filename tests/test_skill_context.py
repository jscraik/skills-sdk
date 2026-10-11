"""Actual provider context binding, hidden-input exclusion and recovery."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from test_live_selected_case import _Judge, _Provider, _setup
from test_selected_case_evaluation import REVISION, _prepared_request, _safety_for

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.evaluation.live_selected_case import execute_selected_case_with_judge
from skills_sdk.evaluation.pre_execution_safety import SelectedCaseExecutionInput
from skills_sdk.evaluation.selected_case import load_selected_case
from skills_sdk.evaluation.skill_context import prepare_selected_case_context
from skills_sdk.providers import ProviderAdapterComplete


class ContextProvider(_Provider):
    async def complete(self, request: object, input_payload: object) -> ProviderAdapterComplete:
        assert request.input_sha256 == canonical_json_sha256(input_payload)
        documents = input_payload["skill_context"]["documents"]
        assert [item["path"].casefold() for item in documents] == ["skill.md", "references/guide.md"]
        assert "Follow the captured reference." in documents[1]["text"]
        assert "acceptance" not in str(input_payload)
        self.events.append("context_provider")
        return ProviderAdapterComplete(text=self.text, evidence_refs=("evidence/provider-result.json",))


def _context(root: Path, reference_path: str = "references/guide.md") -> tuple[object, object, object, list[str]]:
    definition, _, _, events = _setup(root)
    (definition._package_root / reference_path).write_text("Follow the captured reference.\n", encoding="utf-8")
    definition = load_selected_case(
        definition._package_root, source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    payload = prepare_selected_case_context(definition, (reference_path,))
    return definition, payload, _prepared_request(definition, payload), events


def _run(definition: object, payload: object, request: object, events: list[str], safety: object = None) -> object:
    return asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(payload, _safety_for(definition, request) if safety is None else safety),
            ContextProvider(request, events),
            _Judge(request.provider, events),
        )
    )


def test_actual_context_is_sent_and_digest_bound(tmp_path: Path) -> None:
    definition, payload, request, events = _context(tmp_path)
    receipt = _run(definition, payload, request, events)
    assert receipt.status == "pass" and events == ["context_provider", "provider_cleanup", "judge", "judge_cleanup"]
    assert "Follow the captured reference." not in receipt.model_dump_json()


@pytest.mark.parametrize(
    "path",
    [
        "references/heldout.md",
        "references/held-out.md",
        "references/hidden.md",
        "references/HeLdOuT/guide.md",
        "references/held-out/nested/guide.md",
        "references/hidden/guide.md",
        "references/evals/guide.md",
        "references/scorer/rubric/calibration/guide.md",
    ],
)
def test_hidden_path_segments_block_context_and_callbacks_then_recover(tmp_path: Path, path: str) -> None:
    """Captured hidden documents cannot enter provider context through path selection."""
    definition, _, _, events = _context(tmp_path)
    hidden = definition._package_root / path
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text("Private held-out labels.\n", encoding="utf-8")
    definition = load_selected_case(
        definition._package_root, source_revision=REVISION, case_id="happy-diff", mode="release"
    )
    payload = prepare_selected_case_context(definition, ("references/guide.md",))
    forged = deepcopy(payload)
    forged["skill_context"]["documents"].append(
        {
            "path": path,
            "sha256": hashlib.sha256(hidden.read_bytes()).hexdigest(),
            "text": hidden.read_text(encoding="utf-8"),
        }
    )
    request = _prepared_request(definition, forged)
    with pytest.raises(ValueError, match="hidden evaluation inputs"):
        prepare_selected_case_context(definition, (path,))
    assert _run(definition, forged, request, events).status == "blocked" and not events
    assert _run(definition, payload, _prepared_request(definition, payload), events).status == "pass"


def test_uppercase_safe_markdown_is_sent_to_provider(tmp_path: Path) -> None:
    """Safe Markdown selection is case-insensitive without normalising its bound path."""
    definition, payload, request, events = _context(tmp_path, "references/guide.MD")
    assert payload["skill_context"]["documents"][1]["path"] == "references/guide.MD"
    assert _run(definition, payload, request, events).status == "pass"


@pytest.mark.parametrize("change", ["text", "digest", "candidate", "extra", "prompt"])
def test_forged_context_rejects_before_callbacks_and_recovers(tmp_path: Path, change: str) -> None:
    definition, payload, request, events = _context(tmp_path)
    forged = deepcopy(payload)
    if change == "text":
        forged["skill_context"]["documents"][0]["text"] = "Invented instructions."
    elif change == "digest":
        forged["skill_context"]["documents"][0]["sha256"] = "0" * 64
    elif change == "candidate":
        forged["skill_context"]["candidate"]["source_revision"] = "2" * 40
    elif change == "extra":
        forged["skill_context"]["hidden_labels"] = ["pass", "fail"]
    else:
        forged["prompt"] = "Different case."
    altered = request.model_copy(update={"input_sha256": canonical_json_sha256(forged)})
    assert _run(definition, forged, altered, events).status == "blocked" and not events
    assert _run(definition, payload, request, events).status == "pass"


@pytest.mark.parametrize("path", ["references/evals.yaml", "references/rubric.md", "../outside.md", "SKILL.md"])
def test_hidden_or_unsafe_reference_selection_rejects(tmp_path: Path, path: str) -> None:
    definition, _, _, _ = _context(tmp_path)
    with pytest.raises(ValueError):
        prepare_selected_case_context(definition, (path,))


def test_forged_context_never_accesses_adapter_properties(tmp_path: Path) -> None:
    definition, payload, request, _ = _context(tmp_path)
    safety = _safety_for(definition, request)
    forged = deepcopy(payload)
    forged["skill_context"]["documents"][0]["text"] = "Invented variant."
    request = request.model_copy(update={"input_sha256": canonical_json_sha256(forged)})

    class UnavailableCapabilities:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"adapter capability accessed before context rejection: {name}")

    receipt = asyncio.run(
        execute_selected_case_with_judge(
            definition,
            request,
            SelectedCaseExecutionInput(forged, safety),
            UnavailableCapabilities(),
            UnavailableCapabilities(),
        )
    )
    assert receipt.status == "blocked"


def test_changed_reference_and_symlink_block_then_source_recovers(tmp_path: Path) -> None:
    definition, payload, request, events = _context(tmp_path)
    path = definition._package_root / "references/guide.md"
    original = path.read_text(encoding="utf-8")
    safety = _safety_for(definition, request)
    path.write_text("Changed context.\n", encoding="utf-8")
    with pytest.raises(ContractError):
        prepare_selected_case_context(definition, ("references/guide.md",))
    path.write_text(original, encoding="utf-8")
    assert prepare_selected_case_context(definition, ("references/guide.md",)) == payload
    path.unlink()
    path.symlink_to(definition._package_root / "SKILL.md")
    with pytest.raises(ContractError, match="invalid_selected_case_definition"):
        _run(definition, payload, request, events, safety)
    assert not events
    path.unlink()
    path.write_text(original, encoding="utf-8")
    assert prepare_selected_case_context(definition, ("references/guide.md",)) == payload
