from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import errno
from unittest.mock import Mock, patch
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
    _bootstrap_error_code,
)
from benchmark.model_broker import BrokerPolicy
from benchmark import linux_sandbox


pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="rootless Linux namespaces are required")


def test_bootstrap_error_keeps_a_bounded_safe_error_type():
    assert _bootstrap_error_code({"error": "RuntimeError"}) == "sandbox_bootstrap_error:RuntimeError"
    assert _bootstrap_error_code({"error": "../../secret"}) == "sandbox_bootstrap_error"


def test_runtime_binds_allow_only_pinned_node_directory_under_home(tmp_path, monkeypatch):
    home = tmp_path / 'fake-home'
    node = home / 'local-llm-benchmark/runtimes/node-v22.23.3-linux-x64'
    node.mkdir(parents=True)
    (node / 'node').write_text('fixture')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    result = linux_sandbox._validate_runtime_binds((RuntimeBind(node, '/opt/node'),))
    assert result == [{'source': str(node), 'target': '/opt/node'}]
    for denied in (node.parent, home, home / 'personal'):
        denied.mkdir(exist_ok=True)
        with pytest.raises(ValueError):
            linux_sandbox._validate_runtime_binds((RuntimeBind(denied, '/opt/node'),))


def test_runtime_binds_allow_only_the_versioned_local_harness_install(tmp_path, monkeypatch):
    home=tmp_path/'hosthome'
    runtime=home/'local-llm-benchmark/envs/qwen-harness-refresh-20261025/packages/pi'
    runtime.mkdir(parents=True)
    (runtime/'pi').write_text('offline local CLI')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    approved=linux_sandbox._validate_runtime_binds((RuntimeBind(runtime,'/opt/pi'),))
    assert approved==[{'source':str(runtime),'target':'/opt/pi'}]
    parent=runtime.parent
    with pytest.raises(ValueError):
        linux_sandbox._validate_runtime_binds((RuntimeBind(parent,'/opt/packages'),))
    unmanaged=home/'local-llm-benchmark/envs/unmanaged-cli'
    unmanaged.mkdir()
    with pytest.raises(ValueError):
        linux_sandbox._validate_runtime_binds((RuntimeBind(unmanaged,'/opt/cli'),))


@pytest.mark.parametrize("control_file,error", [
    ("cgroup.events", OSError(errno.ENODEV, "synthetic cgroup teardown")),
    ("cgroup.procs", linux_sandbox.SandboxError("synthetic vanished control file")),
])
def test_cleanup_accepts_kernel_removed_scope_during_control_read(tmp_path, control_file, error) -> None:
    cgroup = tmp_path / "synthetic-owned-scope"
    cgroup.mkdir()
    process = Mock()
    process.poll.return_value = 0

    def read(directory, name):
        if name == control_file:
            directory.rmdir()
            raise error
        return "populated 0\nfrozen 0"

    with patch.object(linux_sandbox, "_read_cgroup_file", side_effect=read):
        assert linux_sandbox._cleanup_evidence(process, cgroup) is True


def test_cleanup_stays_unverified_for_live_process_populated_or_unreadable_scope(tmp_path) -> None:
    process = Mock()
    process.poll.return_value = None
    assert linux_sandbox._cleanup_evidence(process, tmp_path / "absent") is False
    process.poll.return_value = 0
    with patch.object(linux_sandbox, "_read_cgroup_file", return_value="populated 1\nfrozen 0"):
        assert linux_sandbox._cleanup_evidence(process, tmp_path) is False
    with patch.object(linux_sandbox, "_read_cgroup_file", side_effect=PermissionError("synthetic denied")):
        assert linux_sandbox._cleanup_evidence(process, tmp_path) is False
    unreadable = Mock()
    unreadable.stat.side_effect = PermissionError("synthetic denied")
    assert linux_sandbox._cleanup_evidence(process, unreadable) is False


def test_cleanup_wait_observes_teardown_without_restarting_or_accepting_timeout(tmp_path) -> None:
    process = Mock()
    with (patch.object(linux_sandbox, "_cleanup_evidence", side_effect=[False, False, True]) as check,
          patch.object(linux_sandbox.time, "sleep")):
        assert linux_sandbox._wait_for_cleanup_evidence(process, tmp_path, 1) is True
        assert check.call_count == 3
        assert all(call.args == (process, tmp_path) for call in check.call_args_list)
        process.assert_not_called()
    with patch.object(linux_sandbox, "_cleanup_evidence", return_value=False):
        assert linux_sandbox._wait_for_cleanup_evidence(process, tmp_path, 0) is False


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


# --- dedicated MCP channel contract (Task 7) ---------------------------------


def test_mcp_channel_requires_policy_and_bridge_together(tmp_path: Path) -> None:
    from benchmark.linux_sandbox import McpPolicy

    with pytest.raises(ValueError):
        SandboxSpec(argv=("python3", "-c", "pass"), workspace=tmp_path,
                    mcp=McpPolicy(port=29111))
    with pytest.raises(ValueError):
        SandboxSpec(argv=("python3", "-c", "pass"), workspace=tmp_path,
                    mcp_bridge=object())
    spec = SandboxSpec(argv=("python3", "-c", "pass"), workspace=tmp_path,
                       mcp=McpPolicy(port=29112), mcp_bridge=object())
    assert spec.mcp.port == 29112 and spec.mcp_bridge is not None


def test_mcp_port_must_be_explicit_and_distinct_from_the_broker_adapter(tmp_path: Path) -> None:
    from benchmark.linux_sandbox import McpPolicy

    for port in (0, -1, 65536, "29113"):
        with pytest.raises(ValueError):
            McpPolicy(port=port)  # type: ignore[arg-type]
    broker = BrokerPolicy(upstream_port=29999, model_allowlist=("fixture-model",))
    with pytest.raises(ValueError):
        SandboxSpec(argv=("python3", "-c", "pass"), workspace=tmp_path,
                    broker=broker, mcp=McpPolicy(port=broker.adapter_port),
                    mcp_bridge=object())
    spec = SandboxSpec(argv=("python3", "-c", "pass"), workspace=tmp_path,
                       broker=broker, mcp=McpPolicy(port=broker.adapter_port + 1),
                       mcp_bridge=object())
    assert spec.mcp.port == broker.adapter_port + 1


def test_bootstrap_config_contract_gains_the_mcp_channel_fields() -> None:
    from benchmark import sandbox_bootstrap

    base = {
        "root": "/root", "workspace": "/workspace", "runtime_binds": [],
        "argv": ["python3", "-c", "pass"], "env": {}, "limits": {},
        "exports": [], "expected_namespaces": {}, "host_uid": 0,
        "evidence_fd": -1, "broker_fd": -1, "broker": None,
        "mcp_fd": -1, "mcp": None,
    }
    sandbox_bootstrap._validate_child_request(base)  # accepted contract shape
    for extra, replacement in (("mcp_fd", None), ("mcp", None), ("nope", None)):
        broken = dict(base)
        match extra:
            case "mcp_fd":
                del broken["mcp_fd"]
            case "mcp":
                del broken["mcp"]
            case _:
                broken["nope"] = None
        with pytest.raises(sandbox_bootstrap.BootstrapError):
            sandbox_bootstrap._validate_child_request(broken)


def test_network_evidence_records_both_listeners_loopback_only() -> None:
    from benchmark import sandbox_bootstrap

    evidence = sandbox_bootstrap._network_evidence(False, True)
    assert evidence["broker_listener_loopback_only"] is False
    assert evidence["mcp_listener_loopback_only"] is True
    both = sandbox_bootstrap._network_evidence(True, True)
    assert both["broker_listener_loopback_only"] is True
    assert both["mcp_listener_loopback_only"] is True
    only_broker = sandbox_bootstrap._network_evidence(True, False)
    assert only_broker["mcp_listener_loopback_only"] is False
    # The host supervisor gate consults this key; a missing key must fail the
    # check rather than silently admitting a missing relay.
    assert "mcp_listener_loopback_only" in evidence


# --- full-circle dedicated MCP channel under the real namespace (Task 7) ------

_FULL_CIRCLE_AGENT = b"""
import json
import os
import socket
import time

port = int(os.environ["MCP_PORT"])
result = {
    "no_source": not os.path.exists("/opt/practical/practical_mcp_v2.py"),
    "no_state": not os.path.exists("/tmp/practical-mcp-state.json"),
}
sock = None
for _ in range(200):
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        break
    except OSError:
        time.sleep(0.05)
if sock is None:
    print("RESULT_JSON:" + json.dumps(result))
    raise SystemExit(0)
sock.settimeout(30)
reader = sock.makefile("rb")


def call(message):
    sock.sendall((json.dumps(message) + "\\n").encode())
    line = reader.readline()
    return json.loads(line.decode()) if line else None


init = call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}})
result["server"] = init["result"]["serverInfo"]["name"]
# Notifications are fire-and-forget on this channel: no frame comes back.
sock.sendall(b'{\"jsonrpc\": \"2.0\", \"method\": \"notifications/initialized\"}\\n')
page = call({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "list_issues", "arguments": {}}})
data = page["result"]["structuredContent"]["data"]
result["page_items"] = len(data["items"])
result["next_cursor"] = data["next_cursor"]
print("RESULT_JSON:" + json.dumps(result))
reader.close()
sock.close()
"""


def _free_loopback_port() -> int:
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def test_full_circle_mcp_channel_inside_the_real_namespace(tmp_path: Path) -> None:
    """One episode's entire dedicated channel: candidate -> namespace relay ->
    trusted host bridge -> journaled tools/call, with only the source-free
    surface visible in the sandbox and the trusted journal closing cleanly."""
    from benchmark.linux_sandbox import McpPolicy
    from benchmark.practical_mcp_bridge import McpBridge

    if not shutil.which("systemd-run") or not shutil.which("unshare"):
        pytest.skip("systemd-run or unshare is unavailable")

    port = _free_loopback_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.py").write_bytes(_FULL_CIRCLE_AGENT)
    journal_path = tmp_path / "mcp-journal.json"
    instance = McpBridge("C2", journal_path=journal_path)
    result = SandboxSupervisor().run(SandboxSpec(
        argv=("/usr/bin/python3.12", "/workspace/agent.py"),
        workspace=workspace,
        env={"MCP_PORT": str(port)},
        runtime_ro=python_runtime(),
        mcp=McpPolicy(port=port),
        mcp_bridge=instance,
    ))
    assert result.infrastructure_error is None, (
        result.infrastructure_error, result.output)
    assert result.network_evidence.get("mcp_listener_loopback_only") is True

    lines = [line for line in result.output.decode().splitlines()
             if line.startswith("RESULT_JSON:")]
    assert lines, result.output
    payload = json.loads(lines[0][len("RESULT_JSON:"):])
    # The namespace sees loopback initialization, one paged call, and none of
    # the trusted server source, fixtures, or a marshalled state file.
    assert payload == {
        "no_source": True, "no_state": True,
        "server": "practical-agent-v2", "page_items": 2, "next_cursor": "2"}

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["schema"] == "practical-mcp-journal-v1"
    assert journal["task"] == "C2"
    assert journal["clean_close"] is True and journal["fault"] is None
    requests = [record for record in journal["records"] if record["kind"] == "request"]
    assert [record["method"] for record in requests] == [
        "initialize", "notifications/initialized", "tools/call"]
    assert requests[-1]["params"] == {"name": "list_issues", "arguments": {}}
    responses = [record for record in journal["records"] if record["kind"] == "response"]
    assert [record["id"] for record in responses] == [1, 2]
    assert responses[0]["envelope"]["result"]["serverInfo"] == {
        "name": "practical-agent-v2", "version": "2.1.0"}
    page = responses[1]["envelope"]["result"]["structuredContent"]
    assert [row["id"] for row in page["data"]["items"]] == [101, 102]
    assert page["data"]["next_cursor"] == "2"
    final = journal["final_state"]
    # Raw trusted server state at close: one episode, zero writes, no leak.
    assert final["report"] is None and final["reconciliation"] is None
    assert final["get_change_reads"] == 0 and final["apply_count"] == 0
