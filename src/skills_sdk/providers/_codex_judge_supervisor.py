"""Private standalone process-group anchor; launched with isolated Python."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from contextlib import suppress


def supervise(control: int, status: int, argv: list[str]) -> None:
    """Serialize target creation with self-owned group termination."""
    transition = threading.Lock()
    reporting = threading.Lock()
    stopping = threading.Event()

    def write_frame(frame: bytes) -> None:
        os.write(status, b"sdk-judge-supervisor/v1 " + frame + b"\n")

    def report(frame: bytes) -> None:
        with reporting:
            write_frame(frame)

    def stop() -> None:
        try:
            os.read(control, 1)
            stopping.set()
            with transition:
                if not os.getpid() == os.getpgrp() == os.getsid(0):
                    raise OSError("supervisor ownership lost")
                with reporting:
                    write_frame(b"stopping")
                    os.killpg(os.getpgrp(), signal.SIGKILL)
        except OSError:
            os._exit(125)

    reader = threading.Thread(target=stop, daemon=True)
    reader.start()
    try:
        with transition:
            if stopping.is_set():
                raise OSError("stop requested before launch")
            child = subprocess.Popen(argv, close_fds=True)
        # Only the target and its descendants may retain the data pipes.
        for descriptor in (0, 1, 2):
            os.close(descriptor)
        code = child.wait()
        report(b"exit " + str(code).encode("ascii"))
    except OSError:
        for descriptor in (0, 1, 2):
            with suppress(OSError):
                os.close(descriptor)
        report(b"start_failed")
    reader.join()


if __name__ == "__main__":
    if len(sys.argv) < 4 or not os.getpid() == os.getpgrp() == os.getsid(0):
        sys.exit(125)
    supervise(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:])
