"""Bounded cleanup for subprocesses started in their own process group."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any


class ProcessGroupStopError(RuntimeError):
    """Raised when the caller cannot establish that a child process group stopped."""


def stop_process_group(
    process: subprocess.Popen[Any],
    *,
    grace_seconds: float = 0.5,
    poll_seconds: float = 0.02,
) -> int:
    """Stop the process group created for ``process`` and reap its leader.

    Callers must launch the process with ``start_new_session=True``. On POSIX the
    leader PID is then also the process-group ID, so cleanup cannot target an
    unrelated process. Windows has no equivalent group-wide termination here;
    the leader is stopped and the caller is told that descendant cleanup is
    unverified.
    """
    pid = process.pid
    if os.name != "posix":
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise ProcessGroupStopError("process-group cleanup is unavailable on this platform")

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return process.wait()
    except OSError as exc:
        raise ProcessGroupStopError("could not signal owned process group") from exc

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return process.wait()
        except OSError as exc:
            raise ProcessGroupStopError("could not inspect owned process group") from exc
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise ProcessGroupStopError("could not force-stop owned process group") from exc
    return process.wait()
