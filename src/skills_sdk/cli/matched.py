"""Calibration and matched evidence routes with explicit offline execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path

_MAX_MATCHED_CONTEXT_BYTES = 16 * 1_048_576


def add_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Expose non-executing evidence routes separately from adapter execution."""
    from skills_sdk.cli.matched_offline import add_parsers as add_offline_parsers
    from skills_sdk.cli.observed_calibration import add_parser as add_calibration_parser

    add_calibration_parser(commands)
    add_offline_parsers(commands)
    for name, help_text in (
        ("matched-assessment", "assess supplied paired judgments without model execution"),
        ("matched-handoff", "prepare cloud handoff from qualified local execution evidence"),
    ):
        parser = commands.add_parser(name, help=help_text)
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--robot", action="store_true")


def _read(arguments: argparse.Namespace, read_input: Callable[[Path], bytes], pairs: Callable[..., object]) -> object:
    from skills_sdk.core.errors import ContractError

    fields = {"plan", "lane", "baseline", "candidate"}
    if arguments.eval_command == "matched-handoff":
        fields = {"local", "cloud_plan"}
    try:
        raw = json.loads(read_input(arguments.input).decode("utf-8"), object_pairs_hook=pairs)
        if not isinstance(raw, dict) or set(raw) != fields:
            return None
        return raw
    except (ContractError, OSError, RecursionError, TypeError, ValueError):
        return None


def run(arguments: argparse.Namespace, read_input: Callable[[Path], bytes], pairs: Callable[..., object]) -> int:
    """Return versioned evidence or a typed blocker without discovering adapters."""
    from skills_sdk.evaluation import assess_matched_pair, prepare_matched_cloud_handoff

    raw = _read(arguments, read_input, pairs)
    data = raw if isinstance(raw, dict) else {}
    if arguments.eval_command == "matched-handoff":
        receipt = prepare_matched_cloud_handoff(data.get("local"), data.get("cloud_plan"))
        successful = receipt.status == "ready"
    else:
        receipt = assess_matched_pair(data.get("plan"), data.get("lane"), data.get("baseline"), data.get("candidate"))
        successful = receipt.status == "assessed"
    if arguments.json_output:
        print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
    else:
        print(f"{arguments.eval_command}: {receipt.status} (supplied evidence; no model execution)")
        if receipt.blocker is not None:
            print(f"  {receipt.blocker.code}: {receipt.blocker.message}")
        decision = getattr(receipt, "decision", None)
        if decision is not None:
            print(f"  decision: {decision}")
    return 0 if successful else 2


def run_evidence(arguments: argparse.Namespace, read_input: Callable[..., bytes], pairs: Callable[..., object]) -> int:
    """Dispatch explicit evidence lanes without enlarging the main CLI module."""
    if arguments.eval_command == "observed-calibration":
        from skills_sdk.cli.observed_calibration import run as run_calibration

        return run_calibration(arguments, read_input, pairs)
    read_input = partial(read_input, max_bytes=_MAX_MATCHED_CONTEXT_BYTES)
    if arguments.eval_command not in {"matched-assessment", "matched-handoff"}:
        from skills_sdk.cli.matched_offline import run as run_offline

        return run_offline(arguments, read_input, pairs)
    return run(arguments, read_input, pairs)
