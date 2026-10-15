from __future__ import annotations

import json
import os
import shutil
import socket
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
    _validate_runtime_tree,
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
    (workspace / "delete-me.txt").write_text("seed-file", encoding="utf-8")
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
        "os.unlink('/workspace/delete-me.txt')\n"
        f"report['parent_root_denied'] = denied('/proc/1/root/etc/passwd') and denied('/proc/1/root{host_marker}')\n"
        "try: os.listdir('/proc/1/fd'); report['pid1_fds_denied'] = False\n"
        "except OSError: report['pid1_fds_denied'] = True\n"
        "report['runtime_ro_denied'] = write_denied('/fixture/readonly.txt')\n"
        "open('/workspace/report.json', 'w').write(json.dumps(report, sort_keys=True))\n"
        "os.chmod('/workspace/report.json', 0o640)\n"
        "print('bounded-agent-output')\n",
        encoding="utf-8",
    )
    spec = SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/agent.py"),
        workspace=workspace,
        workspace_exports=("report.json", "result.txt", "delete-me.txt"),
        runtime_ro=(*python_runtime(), RuntimeBind(runtime_marker, PurePosixPath("/fixture/readonly.txt"))),
        limits=ResourceLimits(output_bytes=4096),
    )

    result = SandboxSupervisor().run(spec)

    assert result.infrastructure_error is None, result
    assert result.returncode == 0
    assert result.cleanup_verified is True
    assert result.timed_out is False
    assert result.workspace_outputs["result.txt"] == b"candidate-output"
    assert result.workspace_output_modes["report.json"] == 0o640
    assert result.workspace_output_modes["result.txt"] == 0o644
    assert "delete-me.txt" not in result.workspace_outputs
    assert "delete-me.txt" not in result.workspace_output_modes
    assert (workspace / "delete-me.txt").read_text(encoding="utf-8") == "seed-file"
    assert result.workspace_audit["complete"] is True
    assert result.workspace_audit["missing_exports"] == ["delete-me.txt"]
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
    assert result.resource_evidence["cgroup_usage_sample_interval_seconds"] == 1.0
    assert result.resource_evidence["cgroup_usage_samples"]
    assert "memory.current" in result.resource_evidence["cgroup_usage_samples"][0]


def test_model_broker_roundtrip_uses_only_fake_loopback_endpoint(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    server, worker = start_fake_endpoint()
    try:
        workspace = tmp_path / "broker-seed"
        workspace.mkdir()
        transcript_dir = tmp_path / "observer"
        transcript_dir.mkdir(mode=0o700)
        transcript_dir.chmod(0o700)
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
            broker_transcript_dir=transcript_dir,
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
    assert result.broker_transcript_evidence["enabled"] is True
    assert result.broker_transcript_evidence["complete"] is True
    assert result.broker_transcript_evidence["completed_requests"] == 1
    transcript = json.loads((transcript_dir / "transcript.jsonl").read_text(encoding="utf-8"))
    assert transcript["model_id"] == "fake-model"
    assert transcript["request_to_upstream_first_response_byte_seconds"] is not None
    assert transcript["request_to_first_response_chunk_seconds"] is not None
    assert (transcript_dir / transcript["files"]["client_request"]["name"]).read_bytes()
    upstream_request = (transcript_dir / transcript["files"]["upstream_request"]["name"]).read_bytes()
    assert json.loads(upstream_request)["messages"][0]["content"] == "fixture only"
    upstream_response = (transcript_dir / transcript["files"]["upstream_response"]["name"]).read_bytes()
    assert b"fake-provider-ok" in upstream_response
    assert b"Authorization" not in (transcript_dir / "transcript.jsonl").read_bytes()


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


def test_runtime_directory_with_unix_socket_is_rejected_before_candidate_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "socket-probe-workspace"
    workspace.mkdir()
    (workspace / "agent.py").write_text(
        "import socket\n"
        "sock = socket.socket(socket.AF_UNIX)\n"
        "sock.connect('/fixture/host-listener.sock')\n"
        "sock.sendall(b'fixture-sentinel')\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime-with-socket"
    runtime.mkdir()
    listener_path = runtime / "host-listener.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(listener_path))
    listener.listen(1)
    listener.settimeout(0.1)
    try:
        result = SandboxSupervisor().run(SandboxSpec(
            argv=("/usr/bin/python3.12", "/workspace/agent.py"),
            workspace=workspace,
            runtime_ro=(RuntimeBind(runtime, PurePosixPath("/fixture")),),
        ))
        assert result.infrastructure_error == "invalid_spec:ValueError"
        with pytest.raises(socket.timeout):
            listener.accept()
    finally:
        listener.close()


def test_runtime_directory_with_fifo_is_rejected(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime-with-fifo"
    runtime.mkdir()
    os.mkfifo(runtime / "control.fifo")
    workspace = tmp_path / "fifo-probe-workspace"
    workspace.mkdir()
    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/true",),
        workspace=workspace,
        runtime_ro=(RuntimeBind(runtime, PurePosixPath("/fixture")),),
    ))
    assert result.infrastructure_error == "invalid_spec:ValueError"


def test_runtime_dependency_symlinks_can_be_confined_to_the_bind_source(tmp_path: Path) -> None:
    runtime = tmp_path / "provider-cache"
    target = runtime / "pkg" / "index.js"
    target.parent.mkdir(parents=True)
    target.write_text("fixture module", encoding="utf-8")
    bin_dir = runtime / ".bin"
    bin_dir.mkdir()
    os.symlink("../pkg/index.js", bin_dir / "in-tree")

    _validate_runtime_tree(runtime, symlinks_within_source=True)

    os.symlink("../../outside.txt", bin_dir / "escape")
    with pytest.raises(ValueError, match="escapes its source tree"):
        _validate_runtime_tree(runtime, symlinks_within_source=True)


def test_workspace_audit_reports_protected_changes_and_new_paths(tmp_path: Path) -> None:
    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")
    workspace = tmp_path / "audit-seed"
    workspace.mkdir()
    (workspace / "TASK.md").write_text("protected task", encoding="utf-8")
    (workspace / "protected.txt").write_text("protected fixture", encoding="utf-8")
    (workspace / "agent.py").write_text(
        "import os\n"
        "open('/workspace/TASK.md','w').write('changed')\n"
        "os.unlink('/workspace/protected.txt')\n"
        "open('/workspace/extra.py','w').write('candidate-created')\n"
        "open('/workspace/result.txt','w').write('allowed-export')\n",
        encoding="utf-8",
    )
    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/agent.py"),
        workspace=workspace,
        workspace_exports=("result.txt",),
        runtime_ro=python_runtime(),
    ))
    assert result.infrastructure_error is None, result
    audit = result.workspace_audit
    assert audit["complete"] is True
    assert any(item["path"] == "TASK.md" for item in audit["protected_changed"])
    assert audit["protected_missing"] == ["protected.txt"]
    extra = next(item for item in audit["unauthorized_extra_paths"] if item["path"] == "extra.py")
    assert extra["size"] == len("candidate-created")
    assert "sha256" not in extra
    assert "extra.py" in {item["path"] for item in audit["final_inventory"]}
