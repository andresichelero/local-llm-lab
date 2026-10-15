from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from benchmark.process_control import stop_process_group
from benchmark import visible_feedback
from benchmark.visible_feedback import collect_visible_feedback


def test_candidate_test_execution_fails_closed_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    marker = tmp_path / "visible-child-wrote-after-timeout"
    child_code = (
        "import time\nfrom pathlib import Path\n"
        f"time.sleep(0.7)\nPath({str(marker)!r}).write_text('late')\n"
    )
    test_code = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "time.sleep(5)\n"
    )
    (tests_dir / "test_hangs.py").write_text(test_code, encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(workspace)}

    monkeypatch.setattr(visible_feedback.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("candidate code must not spawn"))
    with pytest.raises(RuntimeError, match="benchmark.safe_campaign --readiness"):
        collect_visible_feedback(workspace, env=env, timeout_seconds=0.2)
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX-specific")
def test_process_group_cleanup_stops_child_after_normal_leader_exit(tmp_path: Path) -> None:
    ready = tmp_path / "child-ready"
    marker = tmp_path / "child-wrote-after-leader-exit"
    child_code = (
        "import sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text('ready')\n"
        "time.sleep(0.8)\nPath(sys.argv[2]).write_text('late')\n"
    )
    leader_code = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}, sys.argv[1], sys.argv[2]])\n"
        "deadline=time.monotonic()+2\n"
        "while not Path(sys.argv[1]).exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", leader_code, str(ready), str(marker)],
        start_new_session=True,
    )
    assert process.wait(timeout=3) == 0

    stop_process_group(process)
    time.sleep(0.9)

    assert not marker.exists(), "a child wrote after its normally-exited leader was cleaned up"


def test_retired_visible_runner_does_not_spawn_candidate_tests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests/test_example.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(visible_feedback.subprocess, "Popen",
                        lambda *args, **kwargs: pytest.fail("candidate code must not spawn"))

    with pytest.raises(RuntimeError, match="benchmark.safe_campaign --readiness"):
        collect_visible_feedback(workspace, env={}, timeout_seconds=1)
