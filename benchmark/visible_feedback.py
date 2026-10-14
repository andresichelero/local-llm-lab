"""Run only agent-visible workspace tests for cascade development feedback."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal, Mapping, NotRequired, TypeGuard, TypedDict

from benchmark.process_control import stop_process_group


class VisibleDevelopmentFeedback(TypedDict):
    phase: Literal["visible_development"]
    passed: bool
    output: str
    exit_code: int | None
    timed_out: bool
    process_group_stopped: NotRequired[bool]


def is_visible_development_feedback(value: object) -> TypeGuard[VisibleDevelopmentFeedback]:
    if not isinstance(value, dict):
        return False
    required = {
        "phase",
        "passed",
        "output",
        "exit_code",
        "timed_out",
    }
    if not required.issubset(value) or value["phase"] != "visible_development":
        return False
    exit_code = value["exit_code"]
    return (
        type(value["passed"]) is bool
        and isinstance(value["output"], str)
        and (exit_code is None or type(exit_code) is int)
        and type(value["timed_out"]) is bool
    )


def collect_visible_feedback(
    workspace: Path,
    *,
    env: Mapping[str, str],
    timeout_seconds: float = 45,
) -> VisibleDevelopmentFeedback:
    """Run workspace tests only, with bounded time and caller-supplied isolated env."""
    tests_dir = workspace.resolve() / "tests"
    test_files = [path for path in tests_dir.rglob("test*.py") if path.is_file()] if tests_dir.is_dir() else []
    if not test_files:
        return {
            "phase": "visible_development",
            "passed": False,
            "output": "No visible workspace unittest files were found under tests/.",
            "exit_code": 2,
            "timed_out": False,
            "process_group_stopped": True,
        }

    process: subprocess.Popen[str] | None = None
    timed_out = False
    output = ""
    exit_code: int | None = None
    process_group_stopped = True
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=workspace.resolve(),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            output = f"{stdout}{stderr}"[-12000:]
            exit_code = process.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
            output = f"{stdout}{stderr}\nVisible workspace tests timed out."[-12000:]
        try:
            stop_process_group(process)
        except Exception:
            process_group_stopped = False
        finally:
            for capture in (process.stdout, process.stderr):
                if capture is not None:
                    capture.close()
        if not timed_out:
            exit_code = process.returncode
    except OSError as exc:
        return {
            "phase": "visible_development",
            "passed": False,
            "output": f"Visible workspace tests could not run: {exc}"[-12000:],
            "exit_code": None,
            "timed_out": False,
            "process_group_stopped": process is None,
        }

    count_match = re.search(r"Ran (\d+) tests?", output)
    test_count = int(count_match.group(1)) if count_match else 0
    return {
        "phase": "visible_development",
        "passed": exit_code == 0 and test_count > 0 and process_group_stopped and not timed_out,
        "output": output,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "process_group_stopped": process_group_stopped,
    }
