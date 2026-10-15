"""Small JSON-only entry point for bounded trusted grading subprocesses.

The worker runs trusted grader/interpreter code. Candidate source is read by the
restricted interpreter inside that trusted code and is never native-executed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from benchmark.harness_eval import grade_workspace
from benchmark.pristine_grading import REPO_ROOT, TASK_POLICIES

_MAX_INPUT_BYTES = 16 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024


def _read_request(stream: Any) -> dict[str, Any]:
    raw = stream.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError("request_too_large")
    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict) or set(request) != {"workspace", "task", "artifact_dir"}:
        raise ValueError("invalid_request_schema")
    task = request["task"]
    if not isinstance(task, str) or task not in TASK_POLICIES:
        raise ValueError("invalid_task")
    workspace = request["workspace"]
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise ValueError("invalid_workspace_path")
    artifact_dir = request["artifact_dir"]
    if artifact_dir is not None and (
        not isinstance(artifact_dir, str) or not Path(artifact_dir).is_absolute()
    ):
        raise ValueError("invalid_artifact_path")
    return request


def main() -> int:
    try:
        request = _read_request(sys.stdin)
        task = request["task"]
        fixture = (REPO_ROOT / TASK_POLICIES[task]["fixture"]).resolve(strict=True)
        workspace = Path(request["workspace"]).resolve(strict=True)
        artifact_value = request["artifact_dir"]
        artifact_dir = Path(artifact_value).resolve(strict=False) if artifact_value else None
        if not workspace.is_dir() or (artifact_dir is not None and not artifact_dir.is_dir()):
            raise ValueError("workspace_or_artifact_not_directory")
        result = grade_workspace(workspace, fixture, task, artifact_dir)
        envelope = {"status": "ok", "result": result}
    except BaseException as exc:
        envelope = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:512],
        }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_OUTPUT_BYTES:
        encoded = json.dumps(
            {"status": "error", "error_type": "OutputLimit", "error": "grade_result_too_large"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
