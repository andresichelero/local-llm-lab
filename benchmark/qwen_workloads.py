"""Common controlled tool harness for quantization selection, not native CLI scores.

Reuses the audited practical task seeds and isolated graders. Model tools never
receive acceptance code. These six development tasks are deliberately familiar;
they are not the fresh final confirmation set.
"""

from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from benchmark import practical_tasks_v2 as tasks
from benchmark.qwen_optimization import fingerprint, write_json

TASK_MAP = {
    "python_fix": "B1",
    "javascript_fix": "B2",
    "authored_tests": "M1",
    "mcp": "C2",
    "continuation": "D1",
    "tool_recovery": "M2",
}
LAB = Path("/home/foxtrot/local-llm-benchmark")
PROTECTED = {"TASK.md", "tests/test_existing.py", "tests/test_existing.test.js"}


class ModelBehaviorFailure(ValueError):
    pass


def safe_path(root, value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("path must stay inside /workspace")
    if any(
        p.startswith(".env") or p in {".ssh", ".aws"} or p.endswith((".key", ".pem"))
        for p in path.parts
    ):
        raise ValueError("secret-like paths are unavailable")
    target = Path(root).joinpath(*path.parts)
    for item in (target, *target.parents):
        if item == Path(root).parent:
            break
        if item.is_symlink():
            raise ValueError("symlinks are unavailable")
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("path escapes workspace")
    return target


def _function(name, description, properties, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


class WorkspaceTools:
    def __init__(self, task, workspace):
        self.task, self.workspace = task, Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.count, self.test_runs = 0, []
        self.started = time.monotonic()
        self.bridge = None
        self.mcp_tools = {}
        self.events = []
        self.schemas = [
            _function(
                "read",
                "Read a paginated UTF-8 workspace file. Use next_offset until null. Paths are relative to /workspace.",
                {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12000},
                },
                ("path",),
            ),
            _function(
                "write",
                "Write a complete UTF-8 workspace file; existing public tests are protected.",
                {"path": {"type": "string"}, "content": {"type": "string"}},
                ("path", "content"),
            ),
            _function("list", "List workspace files.", {}),
            _function(
                "run_tests",
                "Run the public and your authored tests in an isolated workspace. No command argument.",
                {},
            ),
        ]
        if task in {"C2", "M2"}:
            from benchmark.practical_mcp_bridge import McpBridge

            self.bridge = McpBridge(
                task, journal_path=self.workspace.parent / "mcp-journal.json"
            )
            self.bridge.start()
            tools = self.rpc("tools/list", {})["result"]["tools"]
            self.mcp_tools = {item["name"]: item for item in tools}
            self.schemas += [
                {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item.get("description", ""),
                        "parameters": item["inputSchema"],
                    },
                }
                for item in tools
            ]

    def rpc(self, method, params):
        from benchmark.practical_mcp_bridge import _frame_body, _frame_header

        with _socket_pair() as pair:
            left, right = pair
            self.bridge.dispatch(
                left,
                {
                    "jsonrpc": "2.0",
                    "id": len(self.events) + 1,
                    "method": method,
                    "params": params,
                },
            )
            return json.loads(_frame_body(right, _frame_header(right), 4 * 1024**2))

    def call(self, name, arguments):
        if time.monotonic() - self.started >= 1800:
            from benchmark.qwen_engines import ModelBudgetExceeded

            raise ModelBudgetExceeded("absolute task wall budget exhausted")
        self.count += 1
        if self.count > 240:
            raise ValueError("tool budget exhausted")
        if name == "list":
            return {
                "files": sorted(
                    str(p.relative_to(self.workspace))
                    for p in self.workspace.rglob("*")
                    if p.is_file() and not p.is_symlink()
                )[:1000]
            }
        if name == "read":
            path = safe_path(self.workspace, arguments["path"])
            if path.stat().st_size > 128 * 1024:
                raise ValueError("file exceeds read limit")
            content = path.read_text()
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 6000)
            if (
                type(offset) is not int
                or type(limit) is not int
                or offset < 0
                or not 1 <= limit <= 12000
            ):
                raise ValueError("invalid page bounds")
            return {
                "content": content[offset : offset + limit],
                "total_chars": len(content),
                "next_offset": offset + limit
                if offset + limit < len(content)
                else None,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        if name == "write":
            name = arguments["path"]
            if name in PROTECTED or name.startswith("agent-manual/"):
                raise ValueError("protected workspace file")
            path = safe_path(self.workspace, name)
            content = arguments["content"]
            if not isinstance(content, str) or len(content.encode()) > 128 * 1024:
                raise ValueError("file exceeds write limit")
            files = [p for p in self.workspace.rglob("*") if p.is_file()]
            if (
                len(files) >= 1000
                or sum(p.stat().st_size for p in files) + len(content.encode())
                > 8 * 1024**2
            ):
                raise ValueError("workspace quota exhausted")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return {
                "written": name,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        if name == "run_tests":
            from benchmark.campaign_readiness import _runtime_binds
            from benchmark.linux_sandbox import (
                ResourceLimits,
                RuntimeBind,
                SandboxSpec,
                SandboxSupervisor,
            )

            language = tasks.TASK_SPECS[self.task]["language"]
            if language == "mcp":
                return {
                    "error": "MCP task: inspect tool receipts and create the requested JSON artifact"
                }
            binds = list(_runtime_binds())
            if language == "javascript":
                node = (
                    LAB
                    / "envs/qwen-harness-refresh-20261025/runtimes/node-v24.22.1-linux-x64"
                )
                binds.append(RuntimeBind(node, "/opt/node"))
                command = ("/opt/node/bin/node", "--test")
            else:
                command = (
                    "/usr/bin/python3.12",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test*.py",
                )
            result = SandboxSupervisor().run(
                SandboxSpec(
                    argv=command,
                    workspace=self.workspace,
                    runtime_ro=tuple(binds),
                    limits=ResourceLimits(
                        memory_bytes=512 * 1024**2,
                        swap_bytes=128 * 1024**2,
                        wall_seconds=180,
                        cpu_seconds=150,
                    ),
                )
            )
            if result.infrastructure_error or not result.cleanup_verified:
                raise RuntimeError(
                    "test tool infrastructure: " + str(result.infrastructure_error)
                )
            row = {
                "returncode": result.returncode,
                "output": result.output.decode(errors="replace")[-12000:],
                "timed_out": result.timed_out,
            }
            self.test_runs.append(row)
            return row
        if name in self.mcp_tools:
            response = self.rpc("tools/call", {"name": name, "arguments": arguments})
            self.events.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "result": response.get("result"),
                    "isError": bool(
                        response.get("error")
                        or response.get("result", {}).get("isError")
                    ),
                }
            )
            return response
        raise ValueError("unknown tool: " + name)

    def close(self):
        return self.bridge.close() if self.bridge else None


class _socket_pair:
    def __enter__(self):
        self.pair = socket.socketpair()
        for sock in self.pair:
            sock.settimeout(15)
        return self.pair

    def __exit__(self, *args):
        for sock in self.pair:
            sock.close()


def run_development(client, category, output):
    from benchmark.practical_runtime_v2 import _grader_result, _phase_grade

    task = TASK_MAP[category]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    contract = (
        tasks.M1_INDEPENDENT_CONTRACT if task == "M1" else tasks.HISTORICAL_CONTRACT
    )
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="qwen-development-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        prompt = tasks.seed_task(
            task, workspace, with_skills=False, task_contract_id=contract
        )
        tools = WorkspaceTools(task, workspace)
        messages = [
            {
                "role": "system",
                "content": "Use the actual advertised tools only. All paths are relative to /workspace. "
                "Use list/read/write/run_tests; no shell tool is available. Existing public tests are protected. "
                "Add meaningful tests for code tasks. Do not claim completion before checking artifacts. "
                "Budgets: 120 generations, 240 tools, 30 minutes for the complete episode.",
            },
            {"role": "user", "content": prompt},
        ]
        phase_grades = []
        instructions = list(messages)
        compacted = 0
        seen = {}
        finished = False
        try:
            for phase in range(1, tasks.TASK_SPECS[task]["phases"] + 1):
                if phase > 1:
                    followup = {"role": "user", "content": tasks.followup_prompt(task)}
                    messages.append(followup)
                    instructions.append(followup)
                while True:
                    context = getattr(client, "context_tokens", 16384)
                    reserve = getattr(client, "max_tokens", 4096)
                    if len(json.dumps(messages)) > max(
                        4096, (context - reserve - 1024) * 2
                    ):
                        if compacted >= 8:
                            from benchmark.qwen_engines import ModelBudgetExceeded

                            raise ModelBudgetExceeded("compaction budget exhausted")
                        checkpoint = client.chat(
                            messages
                            + [
                                {
                                    "role": "user",
                                    "content": "Produce a concise checkpoint for continuing this same task. Preserve requirements, "
                                    "current files, test results, exact MCP cursors/versions/receipts and unresolved errors. "
                                    "Do not call tools or claim unobserved success. Code can be reread from files.",
                                }
                            ],
                            tools=tools.schemas,
                            kind="compaction",
                            allow_tools=False,
                        )
                        summary = checkpoint["choices"][0]["message"]
                        if summary.get("tool_calls") or not summary.get("content"):
                            raise ModelBehaviorFailure(
                                "compaction did not produce a usable text checkpoint"
                            )
                        compacted += 1
                        write_json(output / f"compaction-{compacted}.json", checkpoint)
                        messages = list(instructions) + [
                            {
                                "role": "user",
                                "content": "Resume the same authorized task from this checkpoint; reread TASK.md and current source "
                                "before edits. The hidden checks have not run.\n"
                                + summary["content"],
                            }
                        ]
                    response = client.chat(messages, tools=tools.schemas)
                    message = response["choices"][0]["message"]
                    # Preserve raw reasoning in transcripts, not in earlier turns.
                    message.pop("reasoning_content", None)
                    messages.append(message)
                    calls = message.get("tool_calls") or []
                    if not calls:
                        finished = (
                            response["choices"][0].get("finish_reason") != "length"
                        )
                        break
                    for call in calls:
                        if tools.count >= 240:
                            from benchmark.qwen_engines import ModelBudgetExceeded

                            raise ModelBudgetExceeded("tool budget exhausted")
                        previous_count = tools.count
                        try:
                            arguments = json.loads(call["function"]["arguments"])
                            value = tools.call(call["function"]["name"], arguments)
                        except (ValueError, KeyError, OSError, TypeError) as exc:
                            value = {"error": f"{type(exc).__name__}: {exc}"}
                        if tools.count == previous_count:
                            tools.count += 1  # Malformed attempted tool calls still consume budget.
                        progress = {
                            str(p.relative_to(workspace)): hashlib.sha256(
                                p.read_bytes()
                            ).hexdigest()
                            for p in workspace.rglob("*")
                            if p.is_file() and not p.is_symlink()
                        }
                        signature = fingerprint(
                            {
                                "call": call["function"],
                                "result": value,
                                "workspace": progress,
                            }
                        )
                        seen[signature] = seen.get(signature, 0) + 1
                        if seen[signature] >= 6:
                            raise ModelBehaviorFailure(
                                "repeated tool result without observable progress"
                            )
                        text = json.dumps(value, ensure_ascii=False)
                        if seen[signature] == 3:
                            text += "\nRepeated unchanged result: change the approach or finish with the limitation."
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": text,
                            }
                        )
                        write_json(output / "messages.json", messages)
                snapshot = output / f"phase-{phase}.zip"
                with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(workspace.rglob("*")):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, str(path.relative_to(workspace)))
                if tasks.TASK_SPECS[task]["language"] != "mcp":
                    verdict = _phase_grade(
                        task,
                        phase,
                        snapshot,
                        lab=LAB,
                        mcp_events=[],
                        task_contract_id=contract,
                    )
                    from benchmark.practical_test_quality import (
                        assess_authored_regression,
                    )

                    verdict["authored_test_quality"] = assess_authored_regression(
                        task, snapshot, lab=LAB, candidate=verdict.get("authored_tests")
                    )
                    phase_grades.append(verdict)
                if not finished:
                    break
        finally:
            journal = tools.close()
            if journal:
                write_json(output / "mcp-journal.json", journal)
            write_json(output / "messages.json", messages)
            write_json(
                output / "episode-progress.json",
                {
                    "seconds": time.monotonic() - started,
                    "calls": client.calls,
                    "tools": tools.count,
                },
            )
        if journal and (journal.get("fault") or not journal.get("clean_close")):
            raise RuntimeError("trusted MCP channel fault; see mcp-journal.json")
        if tasks.TASK_SPECS[task]["language"] == "mcp":
            verdict = _grader_result(
                task,
                1,
                workspace,
                lab=LAB,
                mcp_events=tools.events,
                task_contract_id=contract,
                mcp_journal=journal,
            )
            phase_grades.append({"hidden": verdict})
        if any(
            g.get("hidden", {}).get("infrastructure")
            or g.get("hidden", {}).get("contract_invalid")
            or g.get("authored_tests", {}).get("infrastructure")
            for g in phase_grades
        ):
            raise RuntimeError("development grader infrastructure failed")
        correct = len(phase_grades) == tasks.TASK_SPECS[task]["phases"] and all(
            g.get("hidden", {}).get("passed") for g in phase_grades
        )
        is_mcp = tasks.TASK_SPECS[task]["language"] == "mcp"
        authored = is_mcp or all(
            g.get("authored_tests", {}).get("passed")
            and g.get("authored_tests", {}).get("additional_count", 0) > 0
            and g.get("authored_test_quality", {}).get("quality")
            == "regression_detected"
            for g in phase_grades
        )
        tested = is_mcp or any(
            r.get("returncode") == 0 and not r.get("timed_out") for r in tools.test_runs
        )
        result = {
            "status": "complete"
            if correct and authored and tested and finished
            else "model_failure",
            "functional_correct": correct,
            "full_completion": bool(correct and authored and tested and finished),
            "task": task,
            "category": category,
            "seconds": time.monotonic() - started,
            "calls": client.calls,
            "tools": tools.count,
            "grades": phase_grades,
            "harness": "controlled-quantization-selection; not native CLI",
        }
        write_json(output / "result.json", result)
        return result
