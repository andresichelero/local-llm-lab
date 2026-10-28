"""Local fake-provider handshake through an isolated native CLI; no LLM is run."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path
import tempfile
from typing import Any

from benchmark.campaign_readiness import _runtime_binds
from benchmark.linux_sandbox import (
    McpPolicy,
    ResourceLimits,
    RuntimeBind,
    SandboxSpec,
    SandboxSupervisor,
    _validate_runtime_binds,
)
from benchmark.model_broker import BrokerPolicy
from benchmark.practical_mcp_bridge import McpBridge
from benchmark.practical_policy import BudgetPolicy
from benchmark.qwen_harness_adapters import prepare_adapter
from benchmark.qwen_native_runtime import stage_native_runtime


class FakeLocalModel:
    def __init__(self, mcp: bool):
        self.requests = []
        self.mcp = mcp
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "local-qwen"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                request = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                )
                outer.requests.append(request)
                tools = request.get("tools") or []
                prior_tool = any(
                    m.get("role") == "tool" for m in request.get("messages", [])
                )
                mcp_tool = next(
                    (
                        t
                        for t in tools
                        if outer.mcp
                        and (t.get("function") or {})
                        .get("name", "")
                        .endswith("list_issues")
                    ),
                    None,
                )
                if mcp_tool and not prior_tool:
                    schema = mcp_tool["function"]["parameters"]
                    args = {}
                    for key in schema.get("required", []):
                        definition = schema["properties"][key]
                        args[key] = (
                            None
                            if key == "cursor"
                            else (
                                2
                                if definition["type"] == "integer"
                                else []
                                if definition["type"] == "array"
                                else False
                                if definition["type"] == "boolean"
                                else "SMOKE"
                            )
                        )
                    choice = {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "smoke-call",
                                    "type": "function",
                                    "function": {
                                        "name": mcp_tool["function"]["name"],
                                        "arguments": json.dumps(
                                            args, separators=(",", ":")
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                else:
                    choice = {
                        "message": {"role": "assistant", "content": "QWEN-LOCAL-SMOKE"},
                        "finish_reason": "stop",
                    }
                body = json.dumps(
                    {
                        "choices": [choice],
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": 8,
                            "total_tokens": 28,
                        },
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def smoke_adapter(
    harness: str, install_state: dict[str, Any], *, with_mcp: bool = False
) -> dict[str, Any]:
    fake = FakeLocalModel(with_mcp)
    mcp_port = 18889 if with_mcp else None
    bridge = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="qwen-native-smoke-", dir="/tmp"
        ) as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("offline native provider smoke\n")
            fake_broker = root / "fake-broker"
            fake_broker.mkdir(mode=0o700)
            port = 18887
            adapter = prepare_adapter(
                harness,
                install_state,
                model_alias="local-qwen",
                endpoint_port=port,
                prompt="Reply exactly QWEN-LOCAL-SMOKE. Do not edit files or call tools.",
                workspace="/workspace",
                mcp_port=mcp_port,
            )
            if adapter["status"] != "ready" or (
                with_mcp and not adapter.get("mcp_supported")
            ):
                return {
                    "status": "blocked",
                    "reason": adapter.get("reason") or adapter.get("mcp_reason"),
                }
            adapter.update(
                workspace="/workspace",
                evidence_dir="/workspace",
                model_alias="local-qwen",
                gateway_port=port,
                output_cap=8192,
                generation={
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "min_p": 0.0,
                    "presence_penalty": 0.0,
                    "max_tokens": 8192,
                    "seed": 101,
                },
            )
            repo_root = Path(__file__).resolve().parents[1]
            native_runtime = stage_native_runtime(root, repo_root, adapter)
            binds = [RuntimeBind(native_runtime, "/opt/qwen-native")]
            binds.extend(_runtime_binds())
            binds.extend(
                RuntimeBind(Path(src).resolve(), target)
                for src, target in adapter["runtime_ro"]
            )
            try:
                _validate_runtime_binds(tuple(binds))
            except (OSError, ValueError) as exc:
                return {
                    "status": "failed",
                    "mcp": with_mcp,
                    "model_calls": 0,
                    "mcp_call_recorded": None,
                    "sandbox_external_egress_unavailable": None,
                    "cleanup_verified": True,
                    "error": f"invalid_spec:{type(exc).__name__}",
                    "diagnostics": {"bind_validation_error": str(exc)[:240]},
                }
            if with_mcp:
                bridge = McpBridge("C2", journal_path=root / "fake-mcp-journal.json")
            spec = SandboxSpec(
                argv=(
                    "/usr/bin/python3.12",
                    "-B",
                    "-I",
                    "/opt/qwen-native/qwen_native_driver.py",
                    "/opt/qwen-native/adapter.json",
                ),
                workspace=workspace,
                workspace_exports=("native-cli.stdout.txt",),
                runtime_ro=tuple(binds),
                env={"PYTHONDONTWRITEBYTECODE": "1"},
                limits=ResourceLimits(
                    memory_bytes=1024 * 1024 * 1024,
                    swap_bytes=128 * 1024**2,
                    cpu_seconds=90,
                    wall_seconds=180,
                    output_bytes=2 * 1024**2,
                    workspace_bytes=64 * 1024**2,
                    scratch_bytes=64 * 1024**2,
                ),
                broker=BrokerPolicy(
                    upstream_port=fake.server.server_address[1],
                    adapter_port=18888,
                    model_allowlist=("local-qwen",),
                    output_token_cap=8192,
                    max_requests=129,
                    frozen_generation={
                        "temperature": 0.6,
                        "top_p": 0.95,
                        "min_p": 0.0,
                        "presence_penalty": 0.0,
                        "max_tokens": 8192,
                        "seed": 101,
                    },
                    request_limits=BudgetPolicy(
                        main=120, wall_seconds=1800, title=1, compaction=8, metadata=20
                    ).as_dict(),
                    unclassified_request_category="main",
                ),
                broker_transcript_dir=fake_broker,
                mcp=McpPolicy(18889) if bridge else None,
                mcp_bridge=bridge,
            )
            result = SandboxSupervisor().run(spec)
            if bridge and not bridge.closed:
                journal = bridge.close()
            elif bridge:
                journal = bridge.close()
            else:
                journal = None
            output = result.output.decode("utf-8", errors="replace")
            candidate_output = result.workspace_outputs.get(
                "native-cli.stdout.txt", b""
            ).decode("utf-8", errors="replace")
            packets = [
                line[len("QWEN_NATIVE_EPISODE:") :]
                for line in output.splitlines()
                if line.startswith("QWEN_NATIVE_EPISODE:")
            ]
            report = json.loads(packets[0]) if len(packets) == 1 else None
            mcp_ok = (
                bool(
                    journal
                    and journal.get("clean_close")
                    and any(
                        r.get("method") == "tools/call"
                        for r in journal.get("records", [])
                    )
                )
                if with_mcp
                else None
            )
            passed = bool(
                not result.infrastructure_error
                and result.cleanup_verified
                and result.network_evidence.get("external_egress_unavailable") is True
                and report
                and report["returncode"] == 0
                and fake.requests
                and (not with_mcp or mcp_ok)
            )
            return {
                "status": "pass" if passed else "failed",
                "mcp": with_mcp,
                "model_calls": len(fake.requests),
                "mcp_call_recorded": mcp_ok,
                "sandbox_external_egress_unavailable": result.network_evidence.get(
                    "external_egress_unavailable"
                ),
                "cleanup_verified": result.cleanup_verified,
                "error": None
                if passed
                else (result.infrastructure_error or output[-1000:]),
                "diagnostics": None
                if passed
                else {
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                    "infrastructure_error": result.infrastructure_error,
                    "namespace": dict(result.namespace_evidence),
                    "network": dict(result.network_evidence),
                    "file_evidence": {
                        key: result.file_evidence.get(key)
                        for key in (
                            "root_read_only",
                            "workspace_writable",
                            "workspace_noexec",
                            "workspace_tmpfs_bounded",
                            "runtime_read_only",
                            "scratch_writable",
                        )
                    },
                    "broker_events": [event.__dict__ for event in result.broker_events],
                    "candidate_output_tail": candidate_output[-2500:],
                    "output_tail": output[-2000:],
                },
            }
    finally:
        if bridge and not bridge.closed:
            bridge.close()
        fake.close()
