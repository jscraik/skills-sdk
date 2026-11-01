"""Explicit, optional Apple system-model advisory; never an acceptance judge."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError
from skills_sdk.models.advisory import FMAdvisoryRequest, FMAdvisoryResult
from skills_sdk.providers import _fm_advisory_protocol as protocol
from skills_sdk.providers.codex_judge import _run

__all__ = ["advise_with_fm"]


@dataclass
class _InvocationState:
    attempted: bool = False


def _availability() -> str | None:
    if sys.platform != "darwin":
        return "unsupported_platform"
    return None if Path("/usr/bin/fm").is_file() else "fm_unavailable"


def _outcome(request: FMAdvisoryRequest, **fields: object) -> FMAdvisoryResult:
    return FMAdvisoryResult(
        candidate=request.candidate,
        request_sha256=canonical_json_sha256(request.model_dump(mode="json")),
        **fields,
    )


async def _invoke(
    request: FMAdvisoryRequest,
    cwd: Path,
    deadline: float,
    state: _InvocationState,
) -> FMAdvisoryResult:
    atoms = protocol.source_atoms(request)
    try:
        instructions, payload = protocol.prompt(request, atoms)
    except ValueError:
        return _outcome(request, status="error", reason="input_limit")
    try:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _outcome(request, status="error", reason="execution_timeout")
        provider = await _run(("/usr/bin/fm", "config", "get", "default-model-provider"), cwd, b"", remaining)
        if provider.strip() != b"(none)":
            return _outcome(request, status="unavailable", reason="custom_provider_configured")
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _outcome(request, status="error", reason="execution_timeout")
        schema = cwd / "schema.json"
        schema.write_text(json.dumps(protocol.output_schema(atoms)), encoding="utf-8")
        argv = (
            "/usr/bin/fm",
            "respond",
            "--model",
            "system",
            "--no-stream",
            "--greedy",
            "--schema",
            str(schema),
            "--instructions",
            instructions,
        )
        state.attempted = True
        output = await _run(argv, cwd, payload, remaining)
        return protocol.decode(request, atoms, output)
    except ContractError as exc:
        reason = "execution_timeout" if exc.code == "codex_judge_timeout" else "execution_failed"
        return _outcome(request, status="error", reason=reason, generation_attempted=state.attempted)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return _outcome(request, status="error", reason="invalid_model_output", generation_attempted=state.attempted)
    except OSError:
        return _outcome(request, status="error", reason="execution_failed", generation_attempted=state.attempted)


async def _generate(request: FMAdvisoryRequest, seconds: float) -> FMAdvisoryResult:
    state = _InvocationState()
    cancelled = None
    deadline = asyncio.get_running_loop().time() + seconds
    try:
        with TemporaryDirectory(prefix="skills-sdk-fm-") as directory:
            try:
                return await _invoke(request, Path(directory), deadline, state)
            except asyncio.CancelledError as exc:
                cancelled = exc
                raise
    except OSError:
        if cancelled is not None:
            cancelled.add_note("fm_advisory_cleanup_failed")
            raise cancelled from None
        return _outcome(request, status="error", reason="execution_failed", generation_attempted=state.attempted)


async def advise_with_fm(request: FMAdvisoryRequest, *, timeout_seconds: float = 30.0) -> FMAdvisoryResult:
    """Check supplied snapshots only, with no implication for SDK acceptance.

    Missing required context skips before platform checks or subprocess creation.
    Calls are explicit, bounded and local-only; cancellation propagates after the
    owned supervised process group has been cleaned up. No implicit retry runs.
    """
    request = FMAdvisoryRequest.model_validate(request.model_dump(mode="json", warnings="error"))
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
        raise ValueError("FM advisory timeout must be in (0, 30] seconds")
    missing = protocol.missing_context(request)
    if missing:
        return _outcome(request, status="skipped", reason="missing_required_context", missing_context_ids=missing)
    unavailable = _availability()
    if unavailable is not None:
        return _outcome(request, status="unavailable", reason=unavailable)
    return await _generate(request, float(timeout_seconds))
