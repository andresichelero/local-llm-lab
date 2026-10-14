from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from benchmark.visible_feedback import collect_visible_feedback


@pytest.mark.skipif(os.name == "nt", reason="the timeout test validates POSIX process groups")
def test_timeout_stops_visible_test_descendants_before_returning(tmp_path: Path) -> None:
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

    result = collect_visible_feedback(workspace, env=env, timeout_seconds=0.2)
    time.sleep(0.9)

    assert result["timed_out"] is True
    assert not marker.exists(), "a visible-test child wrote to the workspace after feedback returned"
