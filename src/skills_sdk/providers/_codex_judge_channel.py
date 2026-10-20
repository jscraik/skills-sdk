"""Bounded private protocol for the native judge's owned supervisor."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import BinaryIO

from skills_sdk.core.errors import ContractError

_HELPER_PATH = Path(__file__).with_name("_codex_judge_supervisor.py")


class JudgeSupervisor:
    """Own control endpoints without signalling a cached process identity."""

    def __init__(self) -> None:
        self.control: int | None = None
        self.transport: asyncio.ReadTransport | None = None
        self.pipe: BinaryIO | None = None
        self.reader = asyncio.StreamReader(limit=128)
        self.frames: list[str] = []

    async def launch(self, argv: tuple[str, ...], cwd: Path) -> asyncio.subprocess.Process:
        """Give private descriptors only to the trusted standalone anchor."""
        control_read = status_read = status_write = None
        launched = False
        try:
            control_read, self.control = os.pipe()
            status_read, status_write = os.pipe()
            self.pipe = os.fdopen(status_read, "rb", buffering=0)
            status_read = None
            self.transport, _protocol = await asyncio.get_running_loop().connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(self.reader), self.pipe
            )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(_HELPER_PATH),
                str(control_read),
                str(status_write),
                *argv,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(control_read, status_write),
            )
            launched = True
            return process
        finally:
            for descriptor in (control_read, status_read, status_write):
                if descriptor is not None:
                    os.close(descriptor)
            if not launched:
                error = sys.exception()
                for release in (self.stop, self.close):
                    try:
                        release()
                    except OSError:
                        if error is None:
                            raise
                        error.add_note("codex_judge_cleanup_failed")

    def stop(self) -> None:
        """Release control once; EOF asks the live anchor to stop its own group."""
        descriptor, self.control = self.control, None
        if descriptor is not None:
            os.close(descriptor)

    def close(self) -> None:
        """Release the status pipe after bounded readers have finished."""
        if self.transport is not None:
            self.transport.close()
        elif self.pipe is not None:
            self.pipe.close()

    async def frame(self) -> str:
        """Accept only small ASCII frames from the isolated supervisor."""
        try:
            raw = await self.reader.readuntil(b"\n")
            if len(raw) > 128 or len(self.frames) >= 2:
                raise ValueError("supervisor frame limit")
            prefix = b"sdk-judge-supervisor/v1 "
            if not raw.startswith(prefix):
                raise ValueError("supervisor version")
            value = raw[len(prefix) : -1].decode("ascii")
            if value != "stopping" and value != "start_failed":
                code = value.removeprefix("exit ")
                if not value.startswith("exit ") or str(int(code)) != code or not -255 <= int(code) <= 255:
                    raise ValueError("supervisor exit code")
            self.frames.append(value)
            return value
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            raise ContractError("codex_judge_protocol_invalid", "Judge supervisor returned invalid status") from None

    async def exit_code(self) -> int:
        """Require target completion rather than inferring it from anchor exit."""
        value = await self.frame()
        if value == "start_failed":
            raise ContractError("codex_judge_start_failed", "Codex judge process could not start")
        if not value.startswith("exit "):
            raise ContractError("codex_judge_process_failed", "Judge supervisor stopped before completion")
        return int(value[5:])

    async def verify_stop(self) -> None:
        """Require the owned anchor's stop frame and reject extra status."""
        while "stopping" not in self.frames:
            await self.frame()
        if self.frames.count("stopping") != 1 or await self.reader.read(1):
            raise ContractError("codex_judge_cleanup_failed", "Judge supervisor cleanup could not be verified")
