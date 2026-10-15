"""Rootless Linux namespace supervisor for untrusted native benchmark agents.

The host-side supervisor stays outside the private namespaces.  The candidate
receives only a bounded tmpfs workspace, explicit read-only runtime mounts, a
clean environment, and (optionally) the narrow loopback model adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from .model_broker import BrokerEvent, BrokerPolicy, ModelBroker


class SandboxError(RuntimeError):
    """The sandbox could not be established or its evidence was incomplete."""


_OWNED_UNIT = re.compile(r"^safe-model-(?:sandbox|trusted-grader)-[0-9a-f]{32}\.scope$")


@dataclass(frozen=True)
class ResourceLimits:
    memory_bytes: int = 2 * 1024**3
    swap_bytes: int = 512 * 1024**2
    cpu_quota_percent: int = 100
    cpu_seconds: int = 600
    pids: int = 96
    wall_seconds: int = 300
    output_bytes: int = 256 * 1024
    workspace_bytes: int = 256 * 1024**2
    workspace_files: int = 5000
    workspace_file_bytes: int = 64 * 1024**2
    scratch_bytes: int = 256 * 1024**2
    file_bytes: int = 128 * 1024**2
    open_files: int = 1024
    export_file_bytes: int = 2 * 1024**2
    export_total_bytes: int = 8 * 1024**2
    rootfs_bytes: int = 32 * 1024**2
    startup_seconds: int = 15
    stop_grace_seconds: int = 3

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not 1 <= self.cpu_quota_percent <= 800:
            raise ValueError("cpu_quota_percent must be between 1 and 800")
        if self.swap_bytes > self.memory_bytes:
            raise ValueError("swap_bytes cannot exceed memory_bytes")
        if self.export_file_bytes > self.export_total_bytes:
            raise ValueError("export_file_bytes cannot exceed export_total_bytes")
        if self.workspace_file_bytes > self.workspace_bytes:
            raise ValueError("workspace_file_bytes cannot exceed workspace_bytes")


@dataclass(frozen=True)
class RuntimeBind:
    source: Path
    target: PurePosixPath | str
    symlinks_within_source: bool = False

    def __post_init__(self) -> None:
        source = Path(self.source)
        target = PurePosixPath(self.target)
        if not target.is_absolute() or target == PurePosixPath("/") or ".." in target.parts:
            raise ValueError("runtime target must be a safe absolute path")
        if type(self.symlinks_within_source) is not bool:
            raise ValueError("symlinks_within_source must be a boolean")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True)
class SandboxSpec:
    argv: tuple[str, ...]
    workspace: Path
    workspace_exports: tuple[str, ...] = ()
    runtime_ro: tuple[RuntimeBind, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    broker: BrokerPolicy | None = None
    broker_transcript_dir: Path | None = None

    def __post_init__(self) -> None:
        argv = tuple(self.argv)
        if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise ValueError("argv must contain non-empty strings without NULs")
        exports = tuple(self.workspace_exports)
        for item in exports:
            _validate_relative_path(item)
        if len(set(exports)) != len(exports):
            raise ValueError("workspace export paths must be unique")
        binds = tuple(self.runtime_ro)
        targets = [item.target for item in binds]
        if len(set(targets)) != len(targets):
            raise ValueError("runtime bind targets must be unique")
        for left in targets:
            if any(left in right.parents or right in left.parents for right in targets if left != right):
                raise ValueError("runtime bind targets cannot overlap")
        env = dict(self.env)
        reserved = {
            "HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME", "XDG_DATA_HOME", "OPENAI_BASE_URL", "OPENAI_API_KEY",
            "OPENAI_API_TOKEN", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
        }
        for key, value in env.items():
            if (not isinstance(key, str) or not isinstance(value, str) or not key
                    or "\x00" in key or "\x00" in value or "=" in key):
                raise ValueError("env must contain valid string pairs")
            normalized_key = key.upper()
            if key in reserved or any(marker in normalized_key for marker in ("_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")):
                raise ValueError(f"env key is reserved or may carry credentials: {key}")
        workspace = Path(self.workspace)
        transcript_dir = None if self.broker_transcript_dir is None else Path(self.broker_transcript_dir)
        if transcript_dir is not None and self.broker is None:
            raise ValueError("broker transcript output requires a broker")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "workspace_exports", exports)
        object.__setattr__(self, "runtime_ro", binds)
        object.__setattr__(self, "env", MappingProxyType(env))
        object.__setattr__(self, "broker_transcript_dir", transcript_dir)


@dataclass(frozen=True)
class RunResult:
    returncode: int | None
    timed_out: bool
    cleanup_verified: bool
    output_limited: bool
    output: bytes
    workspace_outputs: Mapping[str, bytes]
    workspace_output_modes: Mapping[str, int]
    workspace_audit: Mapping[str, Any]
    namespace_evidence: Mapping[str, Any]
    file_evidence: Mapping[str, Any]
    network_evidence: Mapping[str, Any]
    resource_evidence: Mapping[str, Any]
    broker_events: tuple[BrokerEvent, ...] = ()
    broker_transcript_evidence: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    infrastructure_error: str | None = None


def _validate_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("workspace path must be a normalized relative path")
    if any(part in ("", ".") for part in path.parts):
        raise ValueError("workspace path must be normalized")
    return path


def _recv_exact(channel: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = channel.recv(length - len(result))
        if not chunk:
            raise EOFError("sandbox control channel closed")
        result.extend(chunk)
    return bytes(result)


def _send_message(channel: socket.socket, message: Mapping[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > 1024 * 1024:
        raise SandboxError("control message exceeds its limit")
    channel.sendall(struct.pack("!I", len(data)) + data)


def _recv_message(channel: socket.socket, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    size = struct.unpack("!I", _recv_exact(channel, 4))[0]
    if size > max_bytes:
        raise SandboxError("control message exceeds its limit")
    message = json.loads(_recv_exact(channel, size).decode("utf-8"))
    if not isinstance(message, dict):
        raise SandboxError("control message is not an object")
    return message


def _namespace_inodes() -> dict[str, int]:
    return {name: os.stat(f"/proc/self/ns/{name}").st_ino for name in ("user", "mnt", "pid", "net", "uts", "ipc")}


def _canonical_workspace(path: Path) -> Path:
    try:
        absolute = Path(os.path.abspath(path))
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise ValueError("workspace must be an existing directory") from exc
    repo = Path(__file__).resolve(strict=True).parents[1]
    if (resolved != absolute or not absolute.is_dir()
            or absolute == repo or repo in absolute.parents or absolute in repo.parents):
        raise ValueError("workspace must be a canonical directory without symlinks")
    return absolute


def _validate_runtime_binds(binds: tuple[RuntimeBind, ...]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for bind in binds:
        source = Path(os.path.abspath(bind.source))
        try:
            info = source.lstat()
            resolved = source.resolve(strict=True)
        except OSError as exc:
            raise ValueError("runtime bind source does not exist") from exc
        if source != resolved or not (source.is_file() or source.is_dir()):
            raise ValueError("runtime bind source must be canonical regular file or directory")
        if source == Path("/") or source == Path.home():
            raise ValueError("runtime bind cannot expose the filesystem or whole home tree")
        repo = Path(__file__).resolve(strict=True).parents[1]
        if source == repo or repo in source.parents or source in repo.parents:
            raise ValueError("runtime bind cannot expose the repository tree")
        home = Path.home()
        if home in source.parents:
            allowed_opencode = home / "local-llm-benchmark/envs/node-harnesses/opencode/node_modules/opencode-linux-x64"
            provider_cache = home / "local-llm-benchmark/cache/opencode-node-modules"
            allowed_provider_paths = {
                provider_cache,
                provider_cache.parent / "package.json",
                provider_cache.parent / "package-lock.json",
            }
            if (source != allowed_opencode and allowed_opencode not in source.parents
                    and source not in allowed_provider_paths):
                raise ValueError("home-directory runtime binds are limited to the installed OpenCode runtime")
            if source == provider_cache and not bind.symlinks_within_source:
                raise ValueError("the OpenCode provider cache requires in-tree symlink validation")
        if not (os.path.isfile(source) or os.path.isdir(source)):
            raise ValueError("runtime bind source is not mountable")
        if not (info.st_mode & 0o444):
            raise ValueError("runtime bind source is not readable")
        if stat.S_ISDIR(info.st_mode):
            _validate_runtime_tree(source, symlinks_within_source=bind.symlinks_within_source)
        result.append({"source": str(source), "target": str(bind.target)})
    return result


def _validate_runtime_tree(root: Path, *, max_entries: int = 50_000, max_depth: int = 64,
                           symlinks_within_source: bool = False) -> None:
    """Inspect runtime tree metadata only; reject IPC/device nodes before bind-mounting.

    Directory traversal never follows symlinks and is bounded by entry count/depth.
    Dependency trees can require links to resolve to existing files or directories
    inside the source tree, preventing a package link from exposing another host path.
    """
    root = root.resolve(strict=True)
    root_info = root.lstat()
    root_device = root_info.st_dev
    entries_seen = 0
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        if depth > max_depth:
            raise ValueError("runtime bind directory exceeds the maximum depth")
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries_seen += 1
                    if entries_seen > max_entries:
                        raise ValueError("runtime bind directory exceeds the metadata scan limit")
                    info = entry.stat(follow_symlinks=False)
                    if info.st_dev != root_device:
                        raise ValueError("runtime bind directory crosses a filesystem boundary")
                    mode = info.st_mode
                    if stat.S_ISDIR(mode):
                        pending.append((Path(entry.path), depth + 1))
                    elif stat.S_ISREG(mode):
                        continue
                    elif stat.S_ISLNK(mode):
                        link_target = os.readlink(entry.path)
                        if not link_target or len(os.fsencode(link_target)) > 4096:
                            raise ValueError("runtime bind contains an invalid or oversized symlink")
                        if symlinks_within_source:
                            if os.path.isabs(link_target):
                                raise ValueError("runtime dependency contains an absolute symlink")
                            lexical_target = Path(os.path.abspath(
                                os.path.join(os.path.dirname(entry.path), link_target)
                            ))
                            if root not in lexical_target.parents:
                                raise ValueError("runtime dependency symlink escapes its source tree")
                            try:
                                resolved_target = Path(entry.path).resolve(strict=True)
                                target_info = resolved_target.stat()
                            except OSError as exc:
                                raise ValueError("runtime dependency contains a dangling symlink") from exc
                            if (root not in resolved_target.parents
                                    or not (stat.S_ISREG(target_info.st_mode) or stat.S_ISDIR(target_info.st_mode))):
                                raise ValueError("runtime dependency symlink escapes its source tree")
                        # Ordinary runtime links are not followed in the host
                        # namespace; the candidate chroot resolves them later.
                    else:
                        raise ValueError("runtime bind contains a socket, FIFO, or device node")
        except OSError as exc:
            raise ValueError("runtime bind directory metadata cannot be inspected") from exc


def _validate_transcript_directory(path: Path, workspace: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        resolved = absolute.resolve(strict=True)
        info = absolute.lstat()
    except OSError as exc:
        raise ValueError("broker transcript directory must already exist") from exc
    if absolute != resolved or not stat.S_ISDIR(info.st_mode):
        raise ValueError("broker transcript directory must be a canonical directory")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("broker transcript directory must be owned by this user and private")
    repo = Path(__file__).resolve(strict=True).parents[1]
    if (absolute == repo or repo in absolute.parents or absolute == workspace
            or workspace in absolute.parents or absolute in workspace.parents):
        raise ValueError("broker transcript directory must be separate from the repository and workspace")
    return absolute


def _read_cgroup_file(cgroup_dir: Path, name: str) -> str:
    path = cgroup_dir / name
    if not path.is_file():
        raise SandboxError(f"required cgroup evidence unavailable: {name}")
    return path.read_text(encoding="ascii").strip()


def _cgroup_usage_sample(cgroup_dir: Path, elapsed_seconds: float) -> dict[str, Any]:
    sample: dict[str, Any] = {"elapsed_seconds": round(max(0.0, elapsed_seconds), 3)}
    for name in (
        "memory.current", "memory.swap.current", "pids.current", "cpu.stat", "io.stat",
        "memory.events", "pids.events", "cgroup.events",
    ):
        try:
            with (cgroup_dir / name).open("rb") as stream:
                value = stream.read(8193)
            if len(value) > 8192:
                sample[name] = value[:8192].decode("ascii", errors="replace") + "[truncated]"
            else:
                sample[name] = value.decode("ascii", errors="replace").strip()
        except OSError:
            sample[name] = None
    return sample


def _sample_cgroup_usage(cgroup_dir: Path, stop: threading.Event, samples: list[dict[str, Any]],
                         max_samples: int) -> None:
    started = time.monotonic()
    while len(samples) < max_samples:
        samples.append(_cgroup_usage_sample(cgroup_dir, time.monotonic() - started))
        if stop.wait(1.0):
            break


def _valid_export_mode(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 0o777


def _export_manifest_matches(export_files: Any, outputs: Mapping[str, bytes], modes: Mapping[str, int]) -> bool:
    if not isinstance(export_files, list) or len(export_files) != len(outputs):
        return False
    seen: set[str] = set()
    for item in export_files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "mode", "sha256"}:
            return False
        path = item["path"]
        if (not isinstance(path, str) or path in seen or path not in outputs
                or type(item["size"]) is not int or item["size"] != len(outputs[path])
                or not _valid_export_mode(item["mode"]) or item["mode"] != modes.get(path)
                or not isinstance(item["sha256"], str)
                or item["sha256"] != hashlib.sha256(outputs[path]).hexdigest()):
            return False
        seen.add(path)
    return seen == set(outputs)


def _valid_workspace_audit(value: Any) -> bool:
    required = {
        "complete", "seed_inventory", "final_inventory", "protected_changed", "protected_missing",
        "unauthorized_extra_paths", "missing_exports", "unsafe_paths", "entry_count",
    }
    if not isinstance(value, dict) or set(value) != required or type(value["complete"]) is not bool:
        return False
    for key in ("seed_inventory", "final_inventory"):
        entries = value[key]
        if not isinstance(entries, list):
            return False
        seen: set[str] = set()
        for item in entries:
            if not isinstance(item, dict) or set(item) != {"path", "type", "mode", "size", "sha256"}:
                return False
            path = item["path"]
            digest = item["sha256"]
            if (not isinstance(path, str) or not path or path in seen
                    or not isinstance(item["type"], str)
                    or item["type"] not in {"file", "directory", "symlink", "socket", "fifo", "device", "other"}
                    or not _valid_export_mode(item["mode"])
                    or type(item["size"]) is not int or item["size"] < 0
                    or (digest is not None and
                        (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)))):
                return False
            seen.add(path)
    if type(value["entry_count"]) is not int or value["entry_count"] != len(value["final_inventory"]):
        return False
    list_fields = ("protected_changed", "protected_missing", "unauthorized_extra_paths", "missing_exports", "unsafe_paths")
    if any(not isinstance(value[key], list) for key in list_fields):
        return False
    if any(not isinstance(path, str) for key in ("protected_missing", "missing_exports", "unsafe_paths") for path in value[key]):
        return False
    if any(not isinstance(item, dict) or not isinstance(item.get("path"), str)
           for key in ("protected_changed", "unauthorized_extra_paths") for item in value[key]):
        return False
    return True


def _scope_evidence(unit: str, limits: ResourceLimits) -> tuple[dict[str, Any], Path]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise SandboxError("systemctl is unavailable")
    shown = subprocess.run(
        [systemctl, "--user", "show", unit, "--property=ControlGroup", "--value"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False, timeout=4, text=True, env=_host_command_env(),
    )
    cgroup = shown.stdout.strip()
    if shown.returncode != 0 or not cgroup.startswith("/") or ".." in Path(cgroup).parts:
        raise SandboxError("systemd did not expose a safe scope cgroup path")
    root = Path("/sys/fs/cgroup").resolve(strict=True)
    cgroup_dir = root.joinpath(*Path(cgroup).parts[1:])
    try:
        actual = cgroup_dir.resolve(strict=True)
        actual.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SandboxError("scope cgroup is outside the unified hierarchy") from exc
    values = {
        "memory.max": _read_cgroup_file(actual, "memory.max"),
        "memory.swap.max": _read_cgroup_file(actual, "memory.swap.max"),
        "pids.max": _read_cgroup_file(actual, "pids.max"),
        "cpu.max": _read_cgroup_file(actual, "cpu.max"),
        "memory.current": _read_cgroup_file(actual, "memory.current"),
        "pids.current": _read_cgroup_file(actual, "pids.current"),
    }
    expected_cpu = f"{limits.cpu_quota_percent * 1000} 100000"
    expected = {
        "memory.max": str(limits.memory_bytes),
        "memory.swap.max": str(limits.swap_bytes),
        "pids.max": str(limits.pids),
        "cpu.max": expected_cpu,
    }
    if any(values[key] != value for key, value in expected.items()):
        raise SandboxError("transient cgroup limits do not match the requested bounds")
    values["expected"] = expected
    values["cgroup_path"] = cgroup
    return values, actual


def new_scope_unit(purpose: str = "sandbox") -> str:
    if purpose not in {"sandbox", "trusted-grader"}:
        raise ValueError("purpose must be sandbox or trusted-grader")
    return f"safe-model-{purpose}-{uuid.uuid4().hex}.scope"


def _validate_owned_unit(unit: str) -> None:
    if not _OWNED_UNIT.fullmatch(unit):
        raise ValueError("unit is not a uniquely named owned safe-model scope")


def systemd_scope_command(argv: tuple[str, ...] | list[str], limits: ResourceLimits, *, unit: str) -> list[str]:
    """Return the bounded transient-scope prefix followed by a trusted argv."""
    _validate_owned_unit(unit)
    if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
        raise ValueError("scope argv must contain non-empty strings without NULs")
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        raise SandboxError("systemd-run is unavailable")
    return [
        systemd_run, "--user", "--scope", "--quiet", "--unit", unit,
        "--property", f"MemoryMax={limits.memory_bytes}",
        "--property", f"MemorySwapMax={limits.swap_bytes}",
        "--property", f"TasksMax={limits.pids}",
        "--property", f"CPUQuota={limits.cpu_quota_percent}%",
        "--property", "KillMode=control-group",
        "--property", f"TimeoutStopSec={limits.stop_grace_seconds}s",
        "--", *argv,
    ]


def read_scope_resource_evidence(unit: str, limits: ResourceLimits) -> dict[str, Any]:
    """Read and verify actual cgroup limits for one active transient scope."""
    _validate_owned_unit(unit)
    evidence, _path = _scope_evidence(unit, limits)
    return evidence


def stop_owned_scope(unit: str) -> bool:
    """Kill all tasks in one exact UUID-named scope owned by this tool."""
    _validate_owned_unit(unit)
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    try:
        completed = subprocess.run(
            [systemctl, "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", unit],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=4, env=_host_command_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _host_command_env() -> dict[str, str]:
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"}
    if "XDG_RUNTIME_DIR" in os.environ:
        env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
    if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
        env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    return env


def _drain_output(stream: Any, limit: int, result: dict[str, Any]) -> None:
    stored = bytearray()
    observed = 0
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        observed += len(chunk)
        remaining = limit - len(stored)
        if remaining > 0:
            stored.extend(chunk[:remaining])
        if len(chunk) > remaining:
            result["limited"] = True
    result["output"] = bytes(stored)
    result["observed"] = observed


def _required_sandbox_evidence(evidence: Mapping[str, Any], runtime_count: int) -> bool:
    namespaces = evidence.get("namespace", {})
    mounts = evidence.get("mounts", {})
    caps = evidence.get("capabilities", {})
    process = evidence.get("process", {})
    network = evidence.get("network", {})
    required_ns = {"user", "mnt", "pid", "net", "uts", "ipc"}
    return (
        set(namespaces.get("isolated", {})) == required_ns
        and all(namespaces["isolated"].values())
        and namespaces.get("uid_map_valid") is True
        and mounts.get("root_read_only") is True
        and mounts.get("workspace_writable") is True
        and mounts.get("workspace_noexec") is True
        and mounts.get("workspace_tmpfs_bounded") is True
        and mounts.get("scratch_writable") is True
        and mounts.get("runtime_read_only") is True
        and len(mounts.get("mounts", {})) >= 3
        and caps.get("effective_capabilities_dropped") is True
        and caps.get("permitted_capabilities_dropped") is True
        and caps.get("bounding_capabilities_dropped") is True
        and caps.get("no_new_privileges") is True
        and caps.get("dumpable_disabled") is True
        and process.get("inherited_host_directory_fds") is False
        and process.get("candidate_control_fds") is False
        and network.get("only_loopback_interface") is True
        and network.get("routes_only_loopback") is True
        and network.get("external_egress_unavailable") is True
        and len(evidence.get("runtime_targets", [])) == runtime_count
    )


def _stop_owned_scope(unit: str, systemctl: str | None) -> None:
    if not systemctl:
        return
    try:
        subprocess.run(
            [systemctl, "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", unit],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=4, env=_host_command_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _cleanup_evidence(process: subprocess.Popen[bytes], cgroup_dir: Path | None) -> bool:
    try:
        if process.poll() is None:
            return False
        if cgroup_dir is None:
            return True
        try:
            cgroup_dir.stat()
        except FileNotFoundError:
            return True
        populated = _read_cgroup_file(cgroup_dir, "cgroup.events")
        values = dict(line.split() for line in populated.splitlines() if len(line.split()) == 2)
        return values.get("populated") == "0" and _read_cgroup_file(cgroup_dir, "cgroup.procs") == ""
    except (OSError, SandboxError):
        # systemd may remove an empty scope between stat and either read. cgroupfs
        # can report ENODEV here, or the reader can reject a vanished control file.
        # Only confirmed directory removal proves cleanup; unreadable is not empty.
        try:
            if cgroup_dir is not None:
                cgroup_dir.stat()
        except FileNotFoundError:
            return process.poll() is not None
        except OSError:
            pass
        return False
    except ValueError:
        return False


def _wait_for_cleanup_evidence(process: subprocess.Popen[bytes], cgroup_dir: Path | None,
                               timeout: float) -> bool:
    """Observe the same owned scope until its bounded teardown has completed."""
    deadline = time.monotonic() + timeout
    while True:
        if _cleanup_evidence(process, cgroup_dir):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _infrastructure_result(error: str, *, timed_out: bool = False, cleanup: bool = False,
                           output: bytes = b"", output_limited: bool = False,
                           resources: Mapping[str, Any] | None = None) -> RunResult:
    return RunResult(
        returncode=None,
        timed_out=timed_out,
        cleanup_verified=cleanup,
        output_limited=output_limited,
        output=output,
        workspace_outputs=MappingProxyType({}),
        workspace_output_modes=MappingProxyType({}),
        workspace_audit=MappingProxyType({}),
        namespace_evidence=MappingProxyType({}),
        file_evidence=MappingProxyType({}),
        network_evidence=MappingProxyType({}),
        resource_evidence=MappingProxyType(dict(resources or {})),
        infrastructure_error=error,
    )


class SandboxSupervisor:
    """Starts one uniquely named, transient systemd user scope per invocation."""

    def __init__(self, *, bootstrap_path: Path | None = None):
        self.bootstrap_path = Path(bootstrap_path or Path(__file__).with_name("sandbox_bootstrap.py")).resolve(strict=True)

    def run(self, spec: SandboxSpec) -> RunResult:
        if not sys.platform.startswith("linux"):
            return _infrastructure_result("linux_required")
        try:
            workspace = _canonical_workspace(spec.workspace)
            runtime_binds = _validate_runtime_binds(spec.runtime_ro)
            transcript_dir = (
                _validate_transcript_directory(spec.broker_transcript_dir, workspace)
                if spec.broker_transcript_dir is not None else None
            )
            namespace_inodes = _namespace_inodes()
        except (OSError, ValueError) as exc:
            return _infrastructure_result(f"invalid_spec:{type(exc).__name__}")
        systemd_run = shutil.which("systemd-run")
        systemctl = shutil.which("systemctl")
        unshare = shutil.which("unshare")
        python = shutil.which("python3")
        if not all((systemd_run, systemctl, unshare, python)):
            return _infrastructure_result("required_rootless_linux_tools_unavailable")

        unit = new_scope_unit("sandbox")
        limits = spec.limits
        temp_root = tempfile.mkdtemp(prefix="safe-model-sandbox-")
        Path(temp_root, "root").mkdir(mode=0o700)
        control_host, control_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        broker_host: socket.socket | None = None
        broker_child: socket.socket | None = None
        if spec.broker is not None:
            broker_host, broker_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        broker_config = None
        if spec.broker is not None:
            broker_config = {
                "upstream_port": spec.broker.upstream_port,
                "model_allowlist": list(spec.broker.model_allowlist),
                "output_token_cap": spec.broker.output_token_cap,
                "frozen_generation": dict(spec.broker.frozen_generation),
                "max_request_bytes": spec.broker.max_request_bytes,
                "max_response_bytes": spec.broker.max_response_bytes,
                "deadline_seconds": spec.broker.deadline_seconds,
                "max_requests": spec.broker.max_requests,
                "adapter_port": spec.broker.adapter_port,
            }
        config = {
            "root": str(Path(temp_root) / "root"),
            "workspace": str(workspace),
            "runtime_binds": runtime_binds,
            "argv": list(spec.argv),
            "env": dict(spec.env),
            "limits": asdict(limits),
            "exports": list(spec.workspace_exports),
            "expected_namespaces": namespace_inodes,
            "host_uid": os.getuid(),
            "evidence_fd": control_child.fileno(),
            "broker_fd": broker_child.fileno() if broker_child is not None else -1,
            "broker": broker_config,
        }
        encoded = json.dumps(config, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            control_host.close()
            control_child.close()
            if broker_host:
                broker_host.close()
            if broker_child:
                broker_child.close()
            shutil.rmtree(temp_root)
            return _infrastructure_result("sandbox_configuration_too_large")

        command = systemd_scope_command(
            (
                unshare, "--user", "--map-root-user", "--mount", "--pid", "--net", "--ipc", "--uts",
                "--fork", "--kill-child", python, "-I", str(self.bootstrap_path),
            ),
            limits,
            unit=unit,
        )
        output_state: dict[str, Any] = {"output": b"", "limited": False}
        process: subprocess.Popen[bytes] | None = None
        broker: ModelBroker | None = None
        broker_thread: threading.Thread | None = None
        cgroup_dir: Path | None = None
        resources: dict[str, Any] = {}
        evidence: dict[str, Any] = {}
        outputs: dict[str, bytes] = {}
        output_modes: dict[str, int] = {}
        workspace_audit: dict[str, Any] = {}
        cgroup_samples: list[dict[str, Any]] = []
        sampler_stop = threading.Event()
        sampler_thread: threading.Thread | None = None
        timed_out = False
        ready = False
        infra_error: str | None = None
        try:
            broker = ModelBroker(spec.broker, transcript_dir=transcript_dir) if spec.broker else None
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                close_fds=True,
                pass_fds=tuple(
                    fd for fd in (
                        control_child.fileno(),
                        broker_child.fileno() if broker_child is not None else -1,
                    ) if fd >= 0
                ),
                env=_host_command_env(),
                start_new_session=True,
            )
            output_thread = threading.Thread(
                target=_drain_output, args=(process.stdout, limits.output_bytes, output_state), daemon=True,
            )
            output_thread.start()
            assert process.stdin is not None
            process.stdin.write(encoded)
            process.stdin.close()
            control_child.close()
            if broker_child is not None:
                broker_child.close()
            control_host.settimeout(limits.startup_seconds)
            message = _recv_message(control_host)
            if message.get("type") != "READY" or not isinstance(message.get("evidence"), dict):
                infra_error = "sandbox_setup_failed"
                raise SandboxError(infra_error)
            evidence = message["evidence"]
            resources, cgroup_dir = _scope_evidence(unit, limits)
            sampler_thread = threading.Thread(
                target=_sample_cgroup_usage,
                args=(cgroup_dir, sampler_stop, cgroup_samples, min(limits.wall_seconds + 2, 3602)),
                daemon=True,
            )
            sampler_thread.start()
            if not _required_sandbox_evidence(evidence, len(runtime_binds)):
                infra_error = "sandbox_evidence_incomplete"
                raise SandboxError(infra_error)
            if broker is not None and broker_host is not None:
                broker_thread = threading.Thread(target=broker.serve_socket, args=(broker_host,), daemon=True)
                broker_thread.start()
            _send_message(control_host, {"type": "GO"})
            ready = True
            control_host.settimeout(limits.wall_seconds)
            start = time.monotonic()
            while True:
                remaining = limits.wall_seconds - (time.monotonic() - start)
                if remaining <= 0:
                    timed_out = True
                    infra_error = "sandbox_wall_timeout"
                    break
                control_host.settimeout(remaining)
                try:
                    message = _recv_message(control_host, max_bytes=max(16 * 1024 * 1024, limits.export_total_bytes + 8192))
                except socket.timeout:
                    timed_out = True
                    infra_error = "sandbox_wall_timeout"
                    break
                kind = message.get("type")
                if kind == "ERROR":
                    infra_error = "sandbox_bootstrap_error"
                    break
                if kind == "FILE":
                    path = message.get("path")
                    size = message.get("size")
                    mode = message.get("mode")
                    digest = message.get("sha256")
                    if (set(message) != {"type", "path", "size", "mode", "sha256"}
                            or not isinstance(path, str) or path not in spec.workspace_exports
                            or type(size) is not int or size < 0
                            or size > limits.export_file_bytes or path in outputs
                            or not _valid_export_mode(mode)
                            or not isinstance(digest, str) or len(digest) != 64):
                        infra_error = "invalid_workspace_export"
                        break
                    data = _recv_exact(control_host, size)
                    if hashlib.sha256(data).hexdigest() != digest:
                        infra_error = "workspace_export_digest_mismatch"
                        break
                    if sum(map(len, outputs.values())) + len(data) > limits.export_total_bytes:
                        infra_error = "workspace_export_total_limit"
                        break
                    outputs[path] = data
                    output_modes[path] = mode
                    continue
                if kind == "RESULT":
                    audit = message.get("workspace_audit")
                    if not _valid_workspace_audit(audit):
                        infra_error = "invalid_workspace_audit"
                        break
                    workspace_audit = audit
                    if audit["complete"] is not True:
                        infra_error = "workspace_audit_incomplete"
                        break
                    returncode = message.get("returncode")
                    if (set(message) != {
                        "type", "returncode", "descendants_clean", "exports_valid", "export_count",
                        "export_bytes", "export_files", "workspace_audit",
                    } or type(returncode) is not int):
                        infra_error = "invalid_sandbox_result"
                        break
                    if message.get("descendants_clean") is not True or message.get("exports_valid") is not True:
                        infra_error = "sandbox_cleanup_or_export_failed"
                        break
                    export_files = message.get("export_files")
                    export_bytes = sum(map(len, outputs.values()))
                    if (type(message.get("export_count")) is not int
                            or type(message.get("export_bytes")) is not int
                            or message["export_count"] != len(outputs)
                            or message["export_bytes"] != export_bytes
                            or not _export_manifest_matches(export_files, outputs, output_modes)):
                        infra_error = "workspace_export_manifest_mismatch"
                        break
                    resources.update({
                        "candidate_returncode": returncode,
                        "descendants_clean": message["descendants_clean"],
                        "exports_valid": message["exports_valid"],
                        "export_count": message.get("export_count"),
                        "export_bytes": export_bytes,
                        "output_captured_bytes": len(output_state["output"]),
                        "output_observed_bytes": output_state.get("observed", 0),
                        "output_limit_bytes": limits.output_bytes,
                    })
                    _send_message(control_host, {"type": "FINISH"})
                    try:
                        process.wait(timeout=limits.stop_grace_seconds + 5)
                    except subprocess.TimeoutExpired:
                        infra_error = "sandbox_scope_exit_timeout"
                    break
                infra_error = "unexpected_sandbox_control_message"
                break
        except (OSError, EOFError, json.JSONDecodeError, SandboxError, subprocess.TimeoutExpired, socket.timeout) as exc:
            if infra_error is None:
                infra_error = f"sandbox_supervisor_error:{type(exc).__name__}"
        finally:
            if process is not None and (process.poll() is None or infra_error is not None):
                _stop_owned_scope(unit, systemctl)
                try:
                    process.wait(timeout=limits.stop_grace_seconds + 5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            sampler_stop.set()
            if sampler_thread is not None:
                sampler_thread.join(timeout=2.0)
            if broker is not None:
                broker.cancel()
            if broker_host is not None:
                try:
                    broker_host.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                broker_host.close()
            if broker_thread is not None:
                broker_thread.join(timeout=1.0)
            if broker is not None:
                broker.close()
            if control_host.fileno() >= 0:
                control_host.close()
            if control_child.fileno() >= 0:
                control_child.close()
            if broker_child is not None and broker_child.fileno() >= 0:
                broker_child.close()
            if process is not None and process.stdout is not None:
                if "output_thread" in locals():
                    output_thread.join(timeout=2.0)
                    if output_thread.is_alive():
                        process.stdout.close()
                        output_thread.join(timeout=1.0)
                else:
                    process.stdout.close()

        cleanup = process is not None and _wait_for_cleanup_evidence(
            process, cgroup_dir, limits.stop_grace_seconds)
        try:
            shutil.rmtree(temp_root)
        except OSError:
            cleanup = False
            infra_error = infra_error or "sandbox_temp_cleanup_failed"
        if resources:
            resources["cgroup_usage_samples"] = cgroup_samples
            resources["cgroup_usage_sample_interval_seconds"] = 1.0
            resources.update({
                "cleanup_verified": cleanup,
                "scope_unit": unit,
                "memory_max": resources.get("memory.max"),
                "memory_swap_max": resources.get("memory.swap.max"),
                "pids_max": resources.get("pids.max"),
                "cpu_max": resources.get("cpu.max"),
                "output_captured_bytes": len(output_state["output"]),
                "output_observed_bytes": output_state.get("observed", 0),
                "output_limit_bytes": limits.output_bytes,
            })
        if not cleanup and infra_error is None:
            infra_error = "sandbox_cleanup_unverified"
        if not ready or infra_error is not None:
            return RunResult(
                returncode=None,
                timed_out=timed_out,
                cleanup_verified=cleanup,
                output_limited=bool(output_state["limited"]),
                output=output_state["output"],
                workspace_outputs=MappingProxyType({}),
                workspace_output_modes=MappingProxyType({}),
                workspace_audit=MappingProxyType(workspace_audit),
                namespace_evidence=MappingProxyType(dict(evidence.get("namespace", {}))),
                file_evidence=MappingProxyType(dict(evidence.get("mounts", {}))),
                network_evidence=MappingProxyType(dict(evidence.get("network", {}))),
                resource_evidence=MappingProxyType(resources),
                broker_events=broker.events if broker else (),
                broker_transcript_evidence=broker.transcript_evidence if broker else MappingProxyType({}),
                infrastructure_error=infra_error or "sandbox_not_ready",
            )
        return RunResult(
            returncode=resources.get("candidate_returncode"),
            timed_out=timed_out,
            cleanup_verified=cleanup,
            output_limited=bool(output_state["limited"]),
            output=output_state["output"],
            workspace_outputs=MappingProxyType(outputs),
            workspace_output_modes=MappingProxyType(output_modes),
            workspace_audit=MappingProxyType(workspace_audit),
            namespace_evidence=MappingProxyType(dict(evidence.get("namespace", {}))),
            file_evidence=MappingProxyType(dict(evidence.get("files", {}))),
            network_evidence=MappingProxyType(dict(evidence.get("network", {}))),
            resource_evidence=MappingProxyType(resources),
            broker_events=broker.events if broker else (),
            broker_transcript_evidence=broker.transcript_evidence if broker else MappingProxyType({}),
        )
