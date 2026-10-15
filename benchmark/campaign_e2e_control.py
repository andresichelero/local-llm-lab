"""No-model canonical trial: real client, tools, sandbox, grader and observation."""
from __future__ import annotations

import json
import shlex
import threading
import time
import traceback
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from benchmark.campaign_observer import ResourceMonitor


def _task_files() -> dict[str, str]:
    from benchmark.pristine_grading import REPO_ROOT, TASK_POLICIES

    fixture = REPO_ROOT / TASK_POLICIES["calculator_division"]["fixture"]
    source = (fixture / "src/calculator.py").read_text(encoding="utf-8")
    tests = (fixture / "tests/test_calculator.py").read_text(encoding="utf-8")
    return {
        "src/calculator.py": source + (
            "\n\ndef divide(a, b):\n"
            "    if b == 0:\n        raise ValueError('division by zero')\n"
            "    return a / b  # readiness-edit-target\n"),
        "tests/test_calculator.py": tests + (
            "\n\nfrom src.calculator import divide\n"
            "\nclass DivisionTests(unittest.TestCase):\n"
            "    def test_divide_positive(self):\n        self.assertEqual(divide(12, 3), 4)\n"
            "    def test_divide_negative(self):\n        self.assertEqual(divide(12, -3), -4)\n"
            "    def test_divide_by_zero(self):\n"
            "        with self.assertRaisesRegex(ValueError, 'division by zero'):\n"
            "            divide(1, 0)\n"),
    }


def _tool_arguments(schema: Any, name: str, step: int) -> dict[str, Any]:
    from benchmark.campaign_readiness import _schema_arguments

    arguments = _schema_arguments(schema, name)
    if name == "bash":
        if step == 0:
            code = ("import json; from pathlib import Path; data=json.loads("
                    + repr(json.dumps(_task_files()))
                    + "); [Path(p).write_text(t, encoding='utf-8') for p,t in data.items()]")
            command = "python3 -c " + shlex.quote(code)
        else:
            command = "python3 -m unittest discover -s tests -v"
        for key in arguments:
            if key.lower().replace("_", "") in {"command", "cmd", "script"}:
                arguments[key] = command
    elif name == "edit":
        for key in arguments:
            normalized = key.lower().replace("_", "")
            if normalized in {"filepath", "path", "file"}:
                arguments[key] = "/workspace/src/calculator.py"
            elif normalized in {"oldstring", "oldtext", "search"}:
                arguments[key] = "return a / b  # readiness-edit-target"
            elif normalized in {"newstring", "newtext", "content", "text"}:
                arguments[key] = "return a / b"
    return arguments


def _handler() -> type:
    from benchmark.campaign_readiness import _FakeModelHandler

    class CanonicalHandler(_FakeModelHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/chat/completions" or not 0 < length <= 2 * 1024**2:
                self.send_error(400)
                return
            payload = json.loads(self.rfile.read(length))
            server: Any = self.server
            state = server.control_state
            state["requests"] += 1
            functions = {
                tool["function"]["name"]: tool["function"]
                for tool in payload.get("tools", [])
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                and isinstance(tool["function"].get("name"), str)
            }
            message: dict[str, Any] = {"role": "assistant", "content": "Canonical fake trial complete."}
            finish = "stop"
            step = state["step"]
            if {"bash", "edit"} <= functions.keys() and step < 3:
                name = "edit" if step == 1 else "bash"
                arguments = _tool_arguments(functions[name].get("parameters", {}), name, step)
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"canonical-control-{step}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }]}
                state["step"] += 1
                finish = "tool_calls"
            body = {"id": f"canonical-fake-{state['requests']}", "object": "chat.completion",
                    "created": 0, "model": server.readiness_model,
                    "choices": [{"index": 0, "finish_reason": finish, "message": message}]}
            if payload.get("stream"):
                self._send_stream(body)
            else:
                self._send(body)

    return CanonicalHandler


def run_control(evidence_dir: Path, *, benchmark_root: Path | None = None) -> dict[str, Any]:
    """Exercise one complete measured-row path with synthetic responses only."""
    from benchmark import safe_campaign
    from benchmark.model_quality_paired import MODELS

    root = Path(benchmark_root) if benchmark_root is not None else safe_campaign.DEFAULT_BENCHMARK_ROOT
    output = Path(evidence_dir) / f"canonical-trial-{time.time_ns()}"
    output.mkdir(mode=0o700)
    server: Any = ThreadingHTTPServer(("127.0.0.1", 0), _handler())
    server.daemon_threads = True
    server.readiness_model = MODELS["qwen3.5-4b"]["alias"]
    server.readiness_state = {"models_requests": 0}
    server.control_state = {"step": 0, "requests": 0}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monitor = None
    result: dict[str, Any] = {"passed": False, "reason": "canonical_trial_not_completed"}
    try:
        monitor = ResourceMonitor.start(output / "fake-provider-resources", run_id="canonical-control",
                                        phase_id="fake_provider", agent_id="fake-http-provider")
        log = output / "fake-provider.log"
        log.write_text("Synthetic provider only; no model loaded.\n", encoding="utf-8")
        row = {"block": 1, "model": "qwen3.5-4b", "task": "calculator_division",
               "repeat": 1, "stage": "measurement"}
        record = safe_campaign._execute_task(
            row, install_root=root,
            binary=root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode",
            server_log=log, output_root=output, experiment="canonical-no-model-control",
            session_resource={"status": "running", "scope": "system_wide"},
            model_api_port=server.server_address[1],
        )
        grade = record.get("grade", {})
        records = [json.loads(line) for line in (output / "records.jsonl").read_text().splitlines()]
        passed = (record.get("strict_pass") is True and record.get("failure_category") == "passed"
                  and record.get("workflow_complete") is True and len(records) == 1
                  and grade.get("runtime_result_authenticated") is True
                  and all(grade.get(gate) is True for gate in (
                      "functional_pass", "regression_pass", "integrity_pass", "scope_pass", "workflow_pass")))
        result = {"passed": passed, "reason": "real_canonical_client_tools_tests_and_trusted_grade",
                  "record": record, "provider_requests": server.control_state["requests"],
                  "scripted_tool_steps": server.control_state["step"], "output_root": str(output)}
    except Exception as exc:
        result = {"passed": False, "reason": f"canonical_trial:{type(exc).__name__}",
                  "error": str(exc)[:500], "traceback": traceback.format_exc()[-4000:],
                  "output_root": str(output)}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if monitor is not None:
            try:
                resource = monitor.stop()
            except Exception as exc:
                resource = {"status": "unavailable", "cleanup_verified": False,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            result["resource_sampling"] = resource
            if resource.get("status") != "measured" or not resource.get("cleanup_verified"):
                result["passed"] = False
        result["fake_provider_cleanup_verified"] = not thread.is_alive()
        if thread.is_alive():
            result["passed"] = False
        result["models_loaded"] = False
        result["inference_performed"] = False
        (output / "control-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
