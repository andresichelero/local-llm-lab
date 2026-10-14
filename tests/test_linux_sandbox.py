from __future__ import annotations

import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path, PurePosixPath

import pytest

from benchmark.linux_sandbox import (
    ResourceLimits,
    RuntimeBind,
    SandboxSpec,
    SandboxSupervisor,
    new_scope_unit,
    systemd_scope_command,
)
from benchmark.model_broker import BrokerPolicy


pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="rootless Linux namespaces are required")


def python_runtime() -> tuple[RuntimeBind, ...]:
    python = Path(shutil.which("python3") or "/usr/bin/python3").resolve(strict=True)
    stdlib = Path("/usr/lib/python3.12")
    library_dir = Path("/lib/x86_64-linux-gnu").resolve(strict=True)
    loader = Path("/lib64/ld-linux-x86-64.so.2").resolve(strict=True)
    sources = [
        (python, PurePosixPath("/usr/bin/python3.12")),
        (stdlib, PurePosixPath("/usr/lib/python3.12")),
        ((library_dir / "libc.so.6").resolve(strict=True), PurePosixPath("/lib/x86_64-linux-gnu/libc.so.6")),
        ((library_dir / "libm.so.6").resolve(strict=True), PurePosixPath("/lib/x86_64-linux-gnu/libm.so.6")),
        ((library_dir / "libz.so.1").resolve(strict=True), PurePosixPath("/lib/x86_64-linux-gnu/libz.so.1")),
        ((library_dir / "libexpat.so.1").resolve(strict=True), PurePosixPath("/lib/x86_64-linux-gnu/libexpat.so.1")),
        (loader, PurePosixPath("/lib64/ld-linux-x86-64.so.2")),
    ]
    missing = [str(source) for source, _target in sources if not source.exists()]
    if missing:
        pytest.skip(f"minimal Python runtime inputs are unavailable: {missing}")
    return tuple(RuntimeBind(source, target) for source, target in sources)


class FakeEndpointHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def log_message(self, _format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).requests.append({
            "path": self.path,
            "body": json.loads(raw),
            "authorization": self.headers.get("Authorization"),
        })
        result = b'{"id":"fake","choices":[{"message":{"content":"fake-provider-ok"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


def start_fake_endpoint() -> tuple[HTTPServer, threading.Thread]:
    FakeEndpointHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), FakeEndpointHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def test_rootless_sandbox_bounds_workspace_runtime_and_parent_routes(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    workspace = tmp_path / "seed"
    workspace.mkdir()
    (workspace / "seed.txt").write_text("fixture-only", encoding="utf-8")
    host_marker = tmp_path / "parent-sentinel.txt"
    host_marker.write_text("benign-parent-sentinel", encoding="utf-8")
    runtime_marker = tmp_path / "runtime-sentinel.txt"
    runtime_marker.write_text("read-only-runtime-sentinel", encoding="utf-8")
    candidate = workspace / "agent.py"
    candidate.write_text(
        "import json, os, sys\n"
        "def denied(path):\n"
        " try: open(path, 'rb').read(16); return False\n"
        " except (OSError, PermissionError): return True\n"
        "def write_denied(path):\n"
        " try: open(path, 'ab').write(b'x'); return False\n"
        " except (OSError, PermissionError): return True\n"
        "report = {'seed': open('/workspace/seed.txt').read()}\n"
        "report['workspace_write'] = False\n"
        "try: open('/workspace/result.txt', 'w').write('candidate-output'); report['workspace_write'] = True\n"
        "except OSError: pass\n"
        f"report['parent_root_denied'] = denied('/proc/1/root/etc/passwd') and denied('/proc/1/root{host_marker}')\n"
        "try: os.listdir('/proc/1/fd'); report['pid1_fds_denied'] = False\n"
        "except OSError: report['pid1_fds_denied'] = True\n"
        "report['runtime_ro_denied'] = write_denied('/fixture/readonly.txt')\n"
        "open('/workspace/report.json', 'w').write(json.dumps(report, sort_keys=True))\n"
        "print('bounded-agent-output')\n",
        encoding="utf-8",
    )
    spec = SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/agent.py"),
        workspace=workspace,
        workspace_exports=("report.json", "result.txt"),
        runtime_ro=(*python_runtime(), RuntimeBind(runtime_marker, PurePosixPath("/fixture/readonly.txt"))),
        limits=ResourceLimits(output_bytes=4096),
    )

    result = SandboxSupervisor().run(spec)

    assert result.infrastructure_error is None, result
    assert result.returncode == 0
    assert result.cleanup_verified is True
    assert result.timed_out is False
    assert result.workspace_outputs["result.txt"] == b"candidate-output"
    report = json.loads(result.workspace_outputs["report.json"])
    assert report == {
        "parent_root_denied": True,
        "pid1_fds_denied": True,
        "runtime_ro_denied": True,
        "seed": "fixture-only",
        "workspace_write": True,
    }
    assert not (workspace / "result.txt").exists()
    assert runtime_marker.read_text(encoding="utf-8") == "read-only-runtime-sentinel"
    assert all(result.namespace_evidence["isolated"].values())
    assert result.file_evidence["root_read_only"] is True
    assert result.file_evidence["workspace_writable"] is True
    assert result.file_evidence["workspace_tmpfs_bounded"] is True
    assert result.file_evidence["runtime_read_only"] is True
    assert result.network_evidence["external_egress_unavailable"] is True
    assert result.resource_evidence["memory_max"] == str(spec.limits.memory_bytes)
    assert result.resource_evidence["memory_swap_max"] == str(spec.limits.swap_bytes)
    assert result.resource_evidence["pids_max"] == str(spec.limits.pids)
    assert result.resource_evidence["cpu_max"] == "100000 100000"
    assert result.resource_evidence["descendants_clean"] is True


def test_model_broker_roundtrip_uses_only_fake_loopback_endpoint(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    server, worker = start_fake_endpoint()
    try:
        workspace = tmp_path / "broker-seed"
        workspace.mkdir()
        script = workspace / "roundtrip.py"
        script.write_text(
            "import json, socket\n"
            "body = json.dumps({'model':'fake-model','messages':[{'role':'user','content':'fixture only'}]}, separators=(',',':')).encode()\n"
            "sock = socket.create_connection(('127.0.0.1', 18888), timeout=3)\n"
            "request = b'POST /v1/chat/completions HTTP/1.1\\r\\nHost: 127.0.0.1:18888\\r\\nConnection: close\\r\\nContent-Type: application/json\\r\\nContent-Length: ' + str(len(body)).encode() + b'\\r\\n\\r\\n' + body\n"
            "sock.sendall(request)\n"
            "response = bytearray()\n"
            "while True:\n"
            " chunk = sock.recv(4096)\n"
            " if not chunk: break\n"
            " response.extend(chunk)\n"
            "sock.close()\n"
            "assert b'fake-provider-ok' in response\n"
            "open('/workspace/roundtrip.txt','w').write('fake-only')\n"
            "print('fake-roundtrip-complete')\n",
            encoding="utf-8",
        )
        policy = BrokerPolicy(
            upstream_port=server.server_port,
            model_allowlist=("fake-model",),
            output_token_cap=16,
            frozen_generation={"temperature": 0, "seed": 1234, "max_tokens": 16},
            adapter_port=18888,
            deadline_seconds=10,
        )
        result = SandboxSupervisor().run(SandboxSpec(
            argv=("/usr/bin/python3.12", "/workspace/roundtrip.py"),
            workspace=workspace,
            workspace_exports=("roundtrip.txt",),
            runtime_ro=python_runtime(),
            broker=policy,
        ))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

    assert result.infrastructure_error is None, result
    assert result.returncode == 0
    assert result.cleanup_verified is True
    assert result.workspace_outputs["roundtrip.txt"] == b"fake-only"
    assert len(result.broker_events) == 1
    assert result.broker_events[0].model_id == "fake-model"
    assert FakeEndpointHandler.requests[0]["path"] == "/v1/chat/completions"
    forwarded = FakeEndpointHandler.requests[0]["body"]
    assert isinstance(forwarded, dict)
    assert forwarded["temperature"] == 0
    assert forwarded["seed"] == 1234
    assert forwarded["max_tokens"] == 16
    assert FakeEndpointHandler.requests[0]["authorization"] is None


def test_output_and_detached_descendant_are_bounded_and_cleaned(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    workspace = tmp_path / "output-seed"
    workspace.mkdir()
    candidate = workspace / "detached.py"
    candidate.write_text(
        "import os, time\n"
        "if os.fork() == 0: time.sleep(60); os._exit(0)\n"
        "os.write(1, b'x' * 8192)\n",
        encoding="utf-8",
    )
    limits = ResourceLimits(output_bytes=128, wall_seconds=20)
    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/detached.py"),
        workspace=workspace,
        runtime_ro=python_runtime(),
        limits=limits,
    ))
    assert result.infrastructure_error is None, result
    assert result.returncode == 0
    assert result.output_limited is True
    assert len(result.output) <= limits.output_bytes
    assert result.resource_evidence["descendants_clean"] is True
    assert result.cleanup_verified is True


def test_wall_timeout_kills_only_its_scope_and_verifies_cleanup(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    workspace = tmp_path / "timeout-seed"
    workspace.mkdir()
    (workspace / "wait.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    limits = ResourceLimits(wall_seconds=2)

    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/wait.py"),
        workspace=workspace,
        runtime_ro=python_runtime(),
        limits=limits,
    ))

    assert result.timed_out is True
    assert result.infrastructure_error == "sandbox_wall_timeout"
    assert result.cleanup_verified is True
    assert result.resource_evidence["memory.max"] == str(limits.memory_bytes)
    assert result.resource_evidence["memory.swap.max"] == str(limits.swap_bytes)


def test_tmpfs_aggregate_workspace_and_scratch_limits_are_enforced(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    workspace = tmp_path / "capacity-seed"
    workspace.mkdir()
    (workspace / "fill.py").write_text(
        "def refused(path):\n"
        " try:\n"
        "  stream = open(path, 'wb'); stream.write(b'x' * 262144); stream.flush(); stream.close(); return False\n"
        " except OSError:\n"
        "  return True\n"
        "print('capacity-bounded' if refused('/workspace/fill.bin') and refused('/scratch/fill.bin') else 'capacity-unbounded')\n",
        encoding="utf-8",
    )
    limits = ResourceLimits(
        workspace_bytes=64 * 1024,
        workspace_file_bytes=64 * 1024,
        scratch_bytes=64 * 1024,
        output_bytes=1024,
    )

    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/fill.py"),
        workspace=workspace,
        runtime_ro=python_runtime(),
        limits=limits,
    ))

    assert result.infrastructure_error is None, result
    assert result.returncode == 0
    assert b"capacity-bounded" in result.output
    assert result.file_evidence["workspace_tmpfs_bounded"] is True
    assert result.file_evidence["workspace_size_bytes"] == 64 * 1024
    assert result.file_evidence["scratch_size_bytes"] == 64 * 1024
    assert result.cleanup_verified is True


def test_scope_helper_rejects_unowned_unit_names() -> None:
    unit = new_scope_unit("trusted-grader")
    assert unit.startswith("safe-model-trusted-grader-") and unit.endswith(".scope")
    with pytest.raises(ValueError):
        systemd_scope_command(("true",), ResourceLimits(), unit="user.service")
