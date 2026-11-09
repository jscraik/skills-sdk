"""Opt-in advisory command kept outside the acceptance command dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from skills_sdk.models.advisory import FMAdvisoryRequest


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register explicit invocation; no validation or release route enables it."""
    parser = commands.add_parser("advise-fm", help="optional Apple on-device advisory; never SDK acceptance")
    parser.add_argument("--request", type=Path, required=True, help="explicit fm-advisory-request/v1 JSON snapshot")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", dest="json_output")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate advisory request member")
        result[key] = value
    return result


def run(arguments: argparse.Namespace, read_context: Callable[[Path], bytes]) -> int:
    """Return advisory JSON independently of validation/build acceptance."""
    from skills_sdk.providers.fm_advisory import advise_with_fm

    try:
        payload = read_context(arguments.request)
        if len(payload) > 16384:
            raise ValueError("advisory input limit")
        request = FMAdvisoryRequest.model_validate(json.loads(payload, object_pairs_hook=_unique))
        result = asyncio.run(advise_with_fm(request, timeout_seconds=arguments.timeout_seconds))
    except (OSError, ValueError, ValidationError, UnicodeError, RecursionError):
        if arguments.json_output:
            print(
                json.dumps(
                    {"error": "invalid_advisory_request", "advisory_only": True, "acceptance_authorized": False},
                    sort_keys=True,
                )
            )
        else:
            print("advise-fm: invalid request (no SDK acceptance decision)")
        return 2
    if arguments.json_output:
        print(result.model_dump_json())
    else:
        detail = result.judgement or result.reason
        print(f"advise-fm: {result.status} ({detail}); advisory only")
        if result.explanation:
            print(f"  {result.explanation}")
        if result.missing_context_ids:
            print(f"  Missing context: {', '.join(result.missing_context_ids)}")
    if result.status == "unavailable":
        return 3
    return 2 if result.status == "error" else 0
