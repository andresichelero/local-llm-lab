"""Trusted in-namespace setup and export process for :mod:`linux_sandbox`.

This file runs before candidate code, then remains PID 1 in the private PID
namespace.  Candidate processes inherit no control/export descriptors.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import resource
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any

# ``-I`` keeps inherited environment and site imports out of the bootstrap.
# Load its one sibling dependency from this trusted, source-bound directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_broker import BrokerChannelClient, BrokerPolicy, LoopbackAdapter


_LIBC = ctypes.CDLL(None, use_errno=True)
_MS_RDONLY = 1
_MS_NOSUID = 2
_MS_NODEV = 4
_MS_NOEXEC = 8
_MS_REMOUNT = 32
_MS_BIND = 4096
_MS_REC = 16384
_MS_PRIVATE = 1 << 18
_MNT_DETACH = 2
_PR_SET_DUMPABLE = 4
_PR_SET_NO_NEW_PRIVS = 38
_PR_CAPBSET_READ = 23
_PR_CAPBSET_DROP = 24
_CAP_VERSION_3 = 0x20080522
_ADAPTER_STOP = threading.Event()


class BootstrapError(RuntimeError):
    pass


def _fail_errno(action: str) -> None:
    error = ctypes.get_errno()
    raise BootstrapError(f"{action} failed: {os.strerror(error)}")


def _mount(source: str | None, target: str, filesystem: str | None, flags: int, data: str | None = None) -> None:
    result = _LIBC.mount(
        None if source is None else os.fsencode(source),
        os.fsencode(target),
        None if filesystem is None else os.fsencode(filesystem),
        ctypes.c_ulong(flags),
        None if data is None else os.fsencode(data),
    )
    if result != 0:
        _fail_errno(f"mount {target}")


def _umount(path: str) -> None:
    if _LIBC.umount2(os.fsencode(path), ctypes.c_int(_MNT_DETACH)) != 0:
        error = ctypes.get_errno()
        if error not in (errno.EINVAL, errno.ENOENT):
            _fail_errno(f"unmount {path}")


def _mkdir(path: str, mode: int = 0o755) -> None:
    os.makedirs(path, mode=mode, exist_ok=True)


def _target_path(root: str, target: str) -> str:
    value = PurePosixPath(target)
    if not value.is_absolute() or ".." in value.parts or value == PurePosixPath("/"):
        raise BootstrapError("runtime target is not a safe absolute path")
    return os.path.join(root, *value.parts[1:])


def _mount_bind_ro(source: str, target: str) -> None:
    source_path = Path(source)
    try:
        info = source_path.lstat()
    except OSError as exc:
        raise BootstrapError("runtime source is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise BootstrapError("runtime source must be a regular file or directory")
    if os.path.realpath(source) != source:
        raise BootstrapError("runtime source must be canonical")
    _mkdir(os.path.dirname(target))
    if stat.S_ISDIR(info.st_mode):
        _mkdir(target)
    else:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    _mount(source, target, None, _MS_BIND)
    flags = _MS_BIND | _MS_REMOUNT | _MS_RDONLY | _MS_NOSUID
    if stat.S_ISDIR(info.st_mode):
        flags |= _MS_NODEV
    _mount(None, target, None, flags)


def _mount_device(source: str, target: str, expected: tuple[int, int]) -> None:
    try:
        info = os.stat(source)
    except OSError:
        return
    if not stat.S_ISCHR(info.st_mode) or (os.major(info.st_rdev), os.minor(info.st_rdev)) != expected:
        raise BootstrapError("a standard device node does not match its expected device number")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    _mount(source, target, None, _MS_BIND)
    # /dev/null must remain writable as a harmless sink.  Device access stays
    # restricted to these three standard character devices on a nodev tmpfs.
    _mount(None, target, None, _MS_BIND | _MS_REMOUNT | _MS_NOSUID)


def _safe_relative_path(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise BootstrapError("workspace export path must be a safe relative path")
    if any(part in ("", ".") for part in path.parts):
        raise BootstrapError("workspace export path must be normalized")
    return path.parts


def _copy_workspace(source: str, destination: str, max_bytes: int, max_files: int, max_file_bytes: int) -> tuple[int, int]:
    """Copy a bounded, symlink-free task tree using no-follow file opens."""
    root_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    total_bytes = 0
    file_count = 0

    def copy_dir(source_fd: int, target: str, depth: int) -> None:
        nonlocal total_bytes, file_count
        if depth > 32:
            raise BootstrapError("workspace seed is too deeply nested")
        for entry in os.scandir(source_fd):
            name = entry.name
            if name in (".", "..") or "/" in name or "\x00" in name:
                raise BootstrapError("workspace seed contains an invalid name")
            source_stat = entry.stat(follow_symlinks=False)
            target_path = os.path.join(target, name)
            if stat.S_ISDIR(source_stat.st_mode):
                os.mkdir(target_path, 0o700)
                child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
                try:
                    copy_dir(child_fd, target_path, depth + 1)
                finally:
                    os.close(child_fd)
                os.chmod(target_path, stat.S_IMODE(source_stat.st_mode) & 0o777)
                continue
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                raise BootstrapError("workspace seed may contain only regular files and directories")
            if source_stat.st_size > max_file_bytes:
                raise BootstrapError("workspace seed file exceeds its per-file limit")
            total_bytes += source_stat.st_size
            file_count += 1
            if total_bytes > max_bytes or file_count > max_files:
                raise BootstrapError("workspace seed exceeds its aggregate limit")
            input_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
            try:
                opened = os.fstat(input_fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_ino != source_stat.st_ino or opened.st_dev != source_stat.st_dev:
                    raise BootstrapError("workspace seed changed during staging")
                output_fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                copied = 0
                try:
                    remaining = max_file_bytes + 1
                    while remaining:
                        data = os.read(input_fd, min(1024 * 1024, remaining))
                        if not data:
                            break
                        copied += len(data)
                        remaining -= len(data)
                        if remaining < 0:
                            raise BootstrapError("workspace seed grew beyond its per-file limit")
                        view = memoryview(data)
                        while view:
                            written = os.write(output_fd, view)
                            view = view[written:]
                    if os.read(input_fd, 1):
                        raise BootstrapError("workspace seed changed during staging")
                    after = os.fstat(input_fd)
                    if (copied != opened.st_size or after.st_size != opened.st_size
                            or after.st_mtime_ns != opened.st_mtime_ns
                            or after.st_ctime_ns != opened.st_ctime_ns):
                        raise BootstrapError("workspace seed changed during staging")
                finally:
                    os.close(output_fd)
                os.chmod(target_path, stat.S_IMODE(source_stat.st_mode) & 0o777)
            finally:
                os.close(input_fd)

    try:
        copy_dir(root_fd, destination, 0)
    finally:
        os.close(root_fd)
    return total_bytes, file_count


def _bring_loopback_up() -> None:
    import fcntl

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        request = bytearray(40)
        struct.pack_into("16sH", request, 0, b"lo", 0)
        flags = fcntl.ioctl(sock.fileno(), 0x8913, bytes(request))
        current = struct.unpack_from("H", flags, 16)[0]
        struct.pack_into("H", request, 16, current | 1)
        fcntl.ioctl(sock.fileno(), 0x8914, bytes(request))
    finally:
        sock.close()


def _set_hostname() -> None:
    hostname = b"sandbox"
    if _LIBC.sethostname(hostname, len(hostname)) != 0:
        _fail_errno("set namespace hostname")


def _read_cap_last() -> int:
    try:
        return min(255, int(Path("/proc/sys/kernel/cap_last_cap").read_text(encoding="ascii").strip()))
    except (OSError, ValueError) as exc:
        raise BootstrapError("cannot determine the capability set") from exc


def _drop_capabilities_and_privilege_gain() -> dict[str, bool]:
    cap_last = _read_cap_last()
    for capability in range(cap_last + 1):
        present = _LIBC.prctl(_PR_CAPBSET_READ, ctypes.c_ulong(capability), 0, 0, 0)
        if present < 0:
            error = ctypes.get_errno()
            if error == errno.EINVAL:
                continue
            _fail_errno("read capability bounding set")
        if present == 1 and _LIBC.prctl(_PR_CAPBSET_DROP, ctypes.c_ulong(capability), 0, 0, 0) != 0:
            _fail_errno("drop capability bounding set")

    class CapHeader(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]

    class CapData(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]

    header = CapHeader(_CAP_VERSION_3, 0)
    data = (CapData * 2)()
    if _LIBC.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
        _fail_errno("clear capability sets")
    if _LIBC.prctl(_PR_SET_NO_NEW_PRIVS, ctypes.c_ulong(1), 0, 0, 0) != 0:
        _fail_errno("set no-new-privileges")
    if _LIBC.prctl(_PR_SET_DUMPABLE, ctypes.c_ulong(0), 0, 0, 0) != 0:
        _fail_errno("disable process inspection")
    status = Path("/proc/self/status").read_text(encoding="ascii", errors="replace")
    values = {}
    for line in status.splitlines():
        if line.startswith(("CapEff:", "CapPrm:", "CapBnd:", "NoNewPrivs:")):
            key, value = line.split(":", 1)
            values[key] = value.strip()
    return {
        "effective_capabilities_dropped": values.get("CapEff") == "0000000000000000",
        "permitted_capabilities_dropped": values.get("CapPrm") == "0000000000000000",
        "bounding_capabilities_dropped": values.get("CapBnd") == "0000000000000000",
        "no_new_privileges": values.get("NoNewPrivs") == "1",
        "dumpable_disabled": _LIBC.prctl(3, 0, 0, 0, 0) == 0,
    }


def _namespace_evidence(expected: dict[str, int], host_uid: int) -> dict[str, Any]:
    names = ("user", "mnt", "pid", "net", "uts", "ipc")
    isolated: dict[str, bool] = {}
    observed: dict[str, int] = {}
    for name in names:
        inode = os.stat(f"/proc/self/ns/{name}").st_ino
        observed[name] = inode
        isolated[name] = inode != int(expected[name])
    uid_map = Path("/proc/self/uid_map").read_text(encoding="ascii").strip().split()
    uid_map_valid = len(uid_map) == 3 and uid_map[0] == "0" and uid_map[1] == str(host_uid) and uid_map[2] == "1"
    return {"isolated": isolated, "observed_namespace_inodes": observed, "uid_map_valid": uid_map_valid}


def _mount_evidence(runtime_targets: list[str], limits: dict[str, int]) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 10 or "-" not in fields:
            continue
        separator = fields.index("-")
        target = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        options = set(fields[5].split(","))
        filesystem = fields[separator + 1]
        super_options = set(fields[separator + 3].split(",")) if len(fields) > separator + 3 else set()
        entries[target] = {
            "read_only": "ro" in options,
            "no_exec": "noexec" in options,
            "filesystem": filesystem,
            "options": sorted(options),
            "super_options": sorted(super_options),
        }
    runtime_ro = all(entries.get(target, {}).get("read_only", False) for target in runtime_targets)
    workspace = entries.get("/workspace", {})
    scratch = entries.get("/scratch", {})
    root = entries.get("/", {})
    tmpfs_bounded = all(
        entries.get(target, {}).get("filesystem") == "tmpfs"
        and any(option.startswith("size=") for option in entries.get(target, {}).get("super_options", []))
        for target in ("/workspace", "/scratch")
    )
    return {
        "mounts": entries,
        "root_read_only": root.get("read_only", False),
        "workspace_writable": "/workspace" in entries and not workspace.get("read_only", True),
        "workspace_noexec": workspace.get("no_exec", False),
        "workspace_tmpfs_bounded": tmpfs_bounded,
        "runtime_read_only": runtime_ro,
        "scratch_writable": "/scratch" in entries and not scratch.get("read_only", True),
        "scratch_size_bytes": limits["scratch_bytes"],
        "workspace_size_bytes": limits["workspace_bytes"],
    }


def _network_evidence(broker_enabled: bool) -> dict[str, Any]:
    links = sorted(name for _index, name in socket.if_nameindex())
    route_devices: set[str] = set()
    ipv6_route_devices: set[str] = set()
    try:
        for line in Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]:
            columns = line.split()
            if columns:
                route_devices.add(columns[0])
        for line in Path("/proc/net/ipv6_route").read_text(encoding="ascii").splitlines():
            columns = line.split()
            if len(columns) >= 10:
                ipv6_route_devices.add(columns[-1])
    except OSError:
        return {"only_loopback_interface": False, "routes_only_loopback": False, "external_egress_unavailable": False}
    only_loopback = links == ["lo"]
    routes_only_loopback = route_devices <= {"lo"} and ipv6_route_devices <= {"lo"}
    return {
        "interfaces": links,
        "route_interfaces": sorted(route_devices),
        "ipv6_route_interfaces": sorted(ipv6_route_devices),
        "only_loopback_interface": only_loopback,
        "routes_only_loopback": routes_only_loopback,
        "external_egress_unavailable": only_loopback and routes_only_loopback,
        "broker_listener_loopback_only": broker_enabled,
    }


def _write_static_files(root: str) -> None:
    etc = os.path.join(root, "etc")
    _mkdir(etc)
    files = {
        "passwd": "root:x:0:0:Sandbox Agent:/scratch/home/agent:/bin/sh\n",
        "group": "root:x:0:\n",
        "hosts": "127.0.0.1 localhost\n::1 localhost\n",
        "hostname": "sandbox\n",
        "resolv.conf": "",
    }
    for name, content in files.items():
        with open(os.path.join(etc, name), "x", encoding="ascii") as stream:
            stream.write(content)


def _mount_root(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    root = config["root"]
    if not os.path.isabs(root) or not os.path.isdir(root):
        raise BootstrapError("private root path is invalid")
    _mount(None, "/", None, _MS_REC | _MS_PRIVATE)
    _mount("tmpfs", root, "tmpfs", _MS_NOSUID | _MS_NODEV | _MS_NOEXEC, f"size={config['limits']['rootfs_bytes']},mode=755")
    for path in ("dev", "etc", "proc", "workspace", "scratch", "tmp", "bin", "usr", "lib", "lib64", "home", "opt", "var", "run"):
        _mkdir(os.path.join(root, path))
    scratch = os.path.join(root, "scratch")
    _mount("tmpfs", scratch, "tmpfs", _MS_NOSUID | _MS_NODEV | _MS_NOEXEC, f"size={config['limits']['scratch_bytes']},mode=755")
    workspace = os.path.join(root, "workspace")
    _mount("tmpfs", workspace, "tmpfs", _MS_NOSUID | _MS_NODEV | _MS_NOEXEC, f"size={config['limits']['workspace_bytes']},mode=755")
    _mkdir(os.path.join(scratch, "tmp"), 0o700)
    _mkdir(os.path.join(scratch, "home", "agent"), 0o700)
    _mkdir(os.path.join(scratch, "home", "agent", ".config", "opencode"), 0o700)
    _mkdir(os.path.join(scratch, "home", "agent", ".local", "share", "opencode"), 0o700)
    _mkdir(os.path.join(scratch, "cache"), 0o700)
    _mkdir(os.path.join(scratch, "data"), 0o700)
    _write_static_files(root)
    seed = os.path.join(root, "seed")
    _mkdir(seed)
    _mount(config["workspace"], seed, None, _MS_BIND)
    _mount(None, seed, None, _MS_BIND | _MS_REMOUNT | _MS_RDONLY | _MS_NOSUID | _MS_NODEV)
    try:
        staged_bytes, staged_files = _copy_workspace(
            seed,
            workspace,
            config["limits"]["workspace_bytes"],
            config["limits"]["workspace_files"],
            config["limits"]["workspace_file_bytes"],
        )
    finally:
        _umount(seed)
        os.rmdir(seed)

    runtime_targets: list[str] = []
    for item in config["runtime_binds"]:
        target = _target_path(root, item["target"])
        _mount_bind_ro(item["source"], target)
        runtime_targets.append(item["target"])

    dev = os.path.join(root, "dev")
    _mount("tmpfs", dev, "tmpfs", _MS_NOSUID | _MS_NODEV | _MS_NOEXEC, "size=4m,mode=755")
    for name, device in (("null", (1, 3)), ("zero", (1, 5)), ("urandom", (1, 9))):
        _mount_device(f"/dev/{name}", os.path.join(dev, name), device)
    os.symlink("/proc/self/fd", os.path.join(dev, "fd"))
    os.symlink("/proc/self/fd/0", os.path.join(dev, "stdin"))
    os.symlink("/proc/self/fd/1", os.path.join(dev, "stdout"))
    os.symlink("/proc/self/fd/2", os.path.join(dev, "stderr"))
    os.rmdir(os.path.join(root, "tmp"))
    os.symlink("/scratch/tmp", os.path.join(root, "tmp"))
    _mount("proc", os.path.join(root, "proc"), "proc", _MS_NOSUID | _MS_NODEV | _MS_NOEXEC | _MS_RDONLY, "hidepid=2")
    _mount(None, root, None, _MS_BIND | _MS_REMOUNT | _MS_RDONLY | _MS_NOSUID | _MS_NODEV | _MS_NOEXEC)
    os.chroot(root)
    os.chdir("/workspace")
    limit_evidence = _namespace_evidence(config["expected_namespaces"], config["host_uid"])
    return root, {
        "runtime_targets": runtime_targets,
        "staged_workspace_bytes": staged_bytes,
        "staged_workspace_files": staged_files,
        "namespace": limit_evidence,
        "mounts": _mount_evidence(runtime_targets, config["limits"]),
        "network": _network_evidence(config["broker"] is not None),
    }


def _apply_resource_limits(limits: dict[str, int]) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits["open_files"], limits["open_files"]))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits["file_bytes"], limits["file_bytes"]))
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))


def _evidence_socket(fd: int) -> socket.socket:
    channel = socket.socket(fileno=fd)
    channel.set_inheritable(False)
    return channel


def _send_message(channel: socket.socket, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 16 * 1024 * 1024:
        raise BootstrapError("supervisor control message exceeds its limit")
    channel.sendall(struct.pack("!I", len(encoded)) + encoded)


def _recv_message(channel: socket.socket, maximum: int = 1024 * 1024) -> dict[str, Any]:
    size = struct.unpack("!I", _recv_exact(channel, 4))[0]
    if size > maximum:
        raise BootstrapError("supervisor control message is too large")
    payload = json.loads(_recv_exact(channel, size).decode("utf-8"))
    if not isinstance(payload, dict):
        raise BootstrapError("supervisor control message is invalid")
    return payload


def _recv_exact(channel: socket.socket, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        part = channel.recv(size - len(output))
        if not part:
            raise EOFError("supervisor closed control channel")
        output.extend(part)
    return bytes(output)


def _close_unneeded_fds(keep: set[int]) -> None:
    try:
        fd_names = os.listdir("/proc/self/fd")
    except OSError as exc:
        raise BootstrapError("cannot enumerate inherited descriptors") from exc
    for value in fd_names:
        try:
            fd = int(value)
        except ValueError:
            continue
        if fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass


def _kill_namespace_children() -> bool:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        for entry in os.listdir("/proc"):
            if entry.isdigit() and entry != "1":
                try:
                    os.kill(int(entry), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        while True:
            try:
                child, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if child == 0:
                break
        remaining = [entry for entry in os.listdir("/proc") if entry.isdigit() and entry != "1"]
        if not remaining:
            return True
        time.sleep(0.02)
    return not [entry for entry in os.listdir("/proc") if entry.isdigit() and entry != "1"]


def _read_export(path_parts: tuple[str, ...], max_bytes: int) -> tuple[bytes, int]:
    dir_fd = os.open("/workspace", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path_parts[:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = child_fd
        fd = os.open(path_parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
                raise BootstrapError("workspace export is not a bounded regular file")
            data = bytearray()
            while len(data) <= max_bytes:
                chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > max_bytes:
                raise BootstrapError("workspace export exceeded its per-file limit")
            return bytes(data), stat.S_IMODE(info.st_mode) & 0o777
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def _workspace_inventory(*, hash_paths: set[str] | None, max_files: int,
                         max_file_bytes: int, max_total_bytes: int) -> tuple[list[dict[str, Any]], list[str], int]:
    """Return bounded metadata for workspace entries and hash only trusted paths.

    ``hash_paths=None`` is used once before candidate execution for the trusted
    seed. After execution, hashes are read only for seed paths and declared
    exports. Newly-created unauthorized files contribute metadata only.
    """
    root_fd = os.open("/workspace", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    entries: list[dict[str, Any]] = []
    unsafe: list[str] = []
    total_bytes = 0
    file_count = 0
    entry_count = 0
    max_entries = max_files * 2 + 64

    def scan(directory_fd: int, prefix: str, depth: int) -> None:
        nonlocal total_bytes, file_count, entry_count
        if depth > 32:
            raise BootstrapError("workspace inventory exceeds the maximum depth")
        with os.scandir(directory_fd) as iterator:
            for item in iterator:
                name = item.name
                path = f"{prefix}/{name}" if prefix else name
                try:
                    encoded_path = path.encode("utf-8")
                except UnicodeEncodeError:
                    unsafe.append(path.encode("utf-8", errors="backslashreplace").decode("ascii"))
                    continue
                if len(encoded_path) > 1024:
                    raise BootstrapError("workspace inventory path exceeds its limit")
                entry_count += 1
                if entry_count > max_entries:
                    raise BootstrapError("workspace inventory exceeds its entry limit")
                info = item.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode) & 0o777
                if stat.S_ISDIR(info.st_mode):
                    entries.append({"path": path, "type": "directory", "mode": mode, "size": 0, "sha256": None})
                    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        scan(child_fd, path, depth + 1)
                    finally:
                        os.close(child_fd)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    kind = (
                        "symlink" if stat.S_ISLNK(info.st_mode) else
                        "socket" if stat.S_ISSOCK(info.st_mode) else
                        "fifo" if stat.S_ISFIFO(info.st_mode) else
                        "device" if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode) else "other"
                    )
                    unsafe.append(path)
                    entries.append({"path": path, "type": kind, "mode": mode, "size": max(0, info.st_size), "sha256": None})
                    continue
                file_count += 1
                total_bytes += info.st_size
                if (info.st_nlink != 1 or info.st_size > max_file_bytes or file_count > max_files
                        or total_bytes > max_total_bytes):
                    unsafe.append(path)
                    entries.append({"path": path, "type": "file", "mode": mode,
                                    "size": max(0, info.st_size), "sha256": None})
                    continue
                digest: str | None = None
                if hash_paths is None or path in hash_paths:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        opened = os.fstat(fd)
                        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                                or opened.st_ino != info.st_ino or opened.st_dev != info.st_dev):
                            unsafe.append(path)
                        else:
                            hasher = hashlib.sha256()
                            remaining = max_file_bytes + 1
                            read_size = 0
                            while remaining:
                                part = os.read(fd, min(1024 * 1024, remaining))
                                if not part:
                                    break
                                hasher.update(part)
                                read_size += len(part)
                                remaining -= len(part)
                            after = os.fstat(fd)
                            if (read_size != info.st_size or read_size > max_file_bytes
                                    or after.st_size != info.st_size or after.st_mtime_ns != info.st_mtime_ns
                                    or after.st_ctime_ns != info.st_ctime_ns):
                                unsafe.append(path)
                            else:
                                digest = hasher.hexdigest()
                    finally:
                        os.close(fd)
                entries.append({"path": path, "type": "file", "mode": mode,
                                "size": info.st_size, "sha256": digest})

    try:
        scan(root_fd, "", 0)
    finally:
        os.close(root_fd)
    entries.sort(key=lambda item: item["path"])
    return entries, sorted(set(unsafe)), total_bytes


def _workspace_audit(seed: list[dict[str, Any]], final: list[dict[str, Any]], unsafe: list[str],
                     exports: list[str]) -> dict[str, Any]:
    seed_by_path = {item["path"]: item for item in seed}
    final_by_path = {item["path"]: item for item in final}
    export_set = set(exports)
    export_parents = {
        "/".join(parts[:index])
        for path in exports
        for parts in (path.split("/"),)
        for index in range(1, len(parts))
    }
    protected_changed: list[dict[str, Any]] = []
    protected_missing: list[str] = []
    missing_exports: list[str] = []
    unauthorized_extra: list[dict[str, Any]] = []
    for path, original in seed_by_path.items():
        current = final_by_path.get(path)
        if current is None:
            if path in export_set:
                missing_exports.append(path)
            else:
                protected_missing.append(path)
        elif path not in export_set and any(
            current.get(key) != original.get(key) for key in ("type", "mode", "size", "sha256")
        ):
            protected_changed.append({"path": path, "before": original, "after": current})
    for path, current in final_by_path.items():
        if path in seed_by_path or path in export_set:
            continue
        if current["type"] == "directory" and path in export_parents:
            continue
        if current["type"] == "file" and current.get("sha256") is not None:
            # Hashes for new files are emitted only for exact declared exports.
            raise BootstrapError("workspace audit hashed a non-export candidate file")
        unauthorized_extra.append({key: current[key] for key in ("path", "type", "mode", "size")})
    return {
        "complete": not unsafe,
        "seed_inventory": seed,
        "final_inventory": final,
        "protected_changed": protected_changed,
        "protected_missing": sorted(protected_missing),
        "unauthorized_extra_paths": unauthorized_extra,
        "missing_exports": sorted(missing_exports),
        "unsafe_paths": unsafe,
        "entry_count": len(final),
    }


def _export_files(channel: socket.socket, paths: list[str], max_file_bytes: int, max_total_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    files: list[dict[str, Any]] = []
    total = 0
    try:
        for value in paths:
            parts = _safe_relative_path(value)
            data, mode = _read_export(parts, max_file_bytes)
            total += len(data)
            if total > max_total_bytes:
                raise BootstrapError("workspace exports exceed their aggregate limit")
            files.append({"path": value, "size": len(data), "mode": mode, "sha256": hashlib.sha256(data).hexdigest()})
            _send_message(channel, {"type": "FILE", "path": value, "size": len(data), "mode": mode, "sha256": hashlib.sha256(data).hexdigest()})
            channel.sendall(data)
        return files, True
    except FileNotFoundError:
        # Missing allowlisted output paths are reported explicitly and are not an error.
        return files, True
    except (OSError, BootstrapError):
        return files, False


def _clean_environment(config: dict[str, Any]) -> dict[str, str]:
    env = {
        "HOME": "/scratch/home/agent",
        "TMPDIR": "/scratch/tmp",
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": "/scratch/home/agent/.config",
        "XDG_CACHE_HOME": "/scratch/cache",
        "XDG_DATA_HOME": "/scratch/home/agent/.local/share",
    }
    for key, value in config["env"].items():
        env[key] = value
    if config["broker"] is not None:
        env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{config['broker']['adapter_port']}/v1"
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_API_TOKEN", None)
    return env


def _validate_child_request(config: dict[str, Any]) -> None:
    if set(config) != {
        "root", "workspace", "runtime_binds", "argv", "env", "limits", "exports",
        "expected_namespaces", "host_uid", "evidence_fd", "broker_fd", "broker",
    }:
        raise BootstrapError("sandbox configuration fields do not match the contract")
    if not isinstance(config["argv"], list) or not config["argv"] or any(
        not isinstance(arg, str) or "\x00" in arg for arg in config["argv"]
    ):
        raise BootstrapError("sandbox command is invalid")
    if not isinstance(config["env"], dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or "\x00" in key or "\x00" in value
        for key, value in config["env"].items()
    ):
        raise BootstrapError("sandbox environment is invalid")
    if not isinstance(config["runtime_binds"], list) or not isinstance(config["exports"], list):
        raise BootstrapError("sandbox mount or export list is invalid")
    for item in config["runtime_binds"]:
        if not isinstance(item, dict) or set(item) != {"source", "target"}:
            raise BootstrapError("runtime bind declaration is invalid")
    for path in config["exports"]:
        _safe_relative_path(path)


def run(config: dict[str, Any]) -> int:
    _validate_child_request(config)
    evidence = _evidence_socket(int(config["evidence_fd"]))
    broker_socket: socket.socket | None = None
    adapter: LoopbackAdapter | None = None
    adapter_thread: threading.Thread | None = None
    candidate: subprocess.Popen[bytes] | None = None
    seed_inventory: list[dict[str, Any]] = []
    workspace_audit: dict[str, Any] = {
        "complete": False, "seed_inventory": [], "final_inventory": [],
        "protected_changed": [], "protected_missing": [], "unauthorized_extra_paths": [],
        "missing_exports": [], "unsafe_paths": [], "entry_count": 0,
    }
    try:
        if config["broker"] is not None:
            broker_socket = socket.socket(fileno=int(config["broker_fd"]))
            broker_socket.set_inheritable(False)
        else:
            os.close(int(config["broker_fd"])) if int(config["broker_fd"]) >= 0 else None

        _bring_loopback_up()
        _set_hostname()
        _apply_resource_limits(config["limits"])
        _root, setup = _mount_root(config)
        caps = _drop_capabilities_and_privilege_gain()
        setup["capabilities"] = caps
        # Drop all original host-side descriptors except the two trusted channels and stdio.
        keep = {0, 1, 2, evidence.fileno()}
        if broker_socket is not None:
            keep.add(broker_socket.fileno())
        _close_unneeded_fds(keep)
        setup["capabilities"] = caps
        setup["process"] = {"inherited_host_directory_fds": False, "candidate_control_fds": False}
        setup["files"] = _mount_evidence(setup["runtime_targets"], config["limits"])
        setup["network"] = _network_evidence(config["broker"] is not None)
        _send_message(evidence, {"type": "READY", "evidence": setup})
        command = _recv_message(evidence)
        if command.get("type") != "GO":
            _send_message(evidence, {"type": "ABORTED"})
            return 125

        seed_inventory, seed_unsafe, _seed_bytes = _workspace_inventory(
            hash_paths=None,
            max_files=config["limits"]["workspace_files"],
            max_file_bytes=config["limits"]["workspace_file_bytes"],
            max_total_bytes=config["limits"]["workspace_bytes"],
        )
        if seed_unsafe:
            raise BootstrapError("trusted seed workspace inventory is unsafe")

        if broker_socket is not None:
            policy = BrokerPolicy(**config["broker"])
            client = BrokerChannelClient(broker_socket, max_request_bytes=policy.max_request_bytes)
            adapter = LoopbackAdapter(client, policy)
            adapter_thread = threading.Thread(target=adapter.serve_forever, args=(_ADAPTER_STOP,), daemon=True)
            adapter_thread.start()

        argv = config["argv"]
        try:
            candidate = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=None,
                stderr=subprocess.STDOUT,
                close_fds=True,
                env=_clean_environment(config),
                start_new_session=True,
            )
            returncode = candidate.wait()
        except OSError:
            returncode = 127
        descendants_clean = _kill_namespace_children()
        if descendants_clean:
            known_hashes = {
                item["path"] for item in seed_inventory if item["type"] == "file"
            } | set(config["exports"])
            final_inventory, unsafe_paths, _final_bytes = _workspace_inventory(
                hash_paths=known_hashes,
                max_files=config["limits"]["workspace_files"],
                max_file_bytes=config["limits"]["workspace_file_bytes"],
                max_total_bytes=config["limits"]["workspace_bytes"],
            )
            workspace_audit = _workspace_audit(
                seed_inventory, final_inventory, unsafe_paths, config["exports"],
            )
        _ADAPTER_STOP.set()
        if adapter is not None:
            adapter.close()
        if adapter_thread is not None:
            adapter_thread.join(timeout=1.0)
        if broker_socket is not None:
            broker_socket.close()
        export_ok, export_count, export_total = True, 0, 0
        output_metadata: list[dict[str, Any]] = []
        total_limit = config["limits"]["export_total_bytes"]
        per_file_limit = config["limits"]["export_file_bytes"]
        total = 0
        for path in config["exports"]:
            try:
                data, mode = _read_export(_safe_relative_path(path), per_file_limit)
            except FileNotFoundError:
                continue
            except (OSError, BootstrapError):
                export_ok = False
                break
            total += len(data)
            if total > total_limit:
                export_ok = False
                break
            digest = hashlib.sha256(data).hexdigest()
            metadata = {"type": "FILE", "path": path, "size": len(data), "mode": mode, "sha256": digest}
            _send_message(evidence, metadata)
            evidence.sendall(data)
            output_metadata.append({"path": path, "size": len(data), "mode": mode, "sha256": digest})
            export_count += 1
            export_total += len(data)
        _send_message(evidence, {
            "type": "RESULT",
            "returncode": returncode,
            "descendants_clean": descendants_clean,
            "exports_valid": export_ok,
            "export_count": export_count,
            "export_bytes": export_total,
            "export_files": output_metadata,
            "workspace_audit": workspace_audit,
        })
        try:
            finish = _recv_message(evidence)
            if finish.get("type") != "FINISH":
                return 125
        except (EOFError, OSError):
            return 125
        return 0
    except BaseException as exc:
        try:
            _send_message(evidence, {"type": "ERROR", "error": type(exc).__name__})
        except OSError:
            pass
        if candidate is not None and candidate.poll() is None:
            candidate.kill()
            candidate.wait(timeout=2)
        if broker_socket is not None:
            try:
                broker_socket.close()
            except OSError:
                pass
        return 125
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except OSError:
                pass
        if broker_socket is not None and not broker_socket.fileno() < 0:
            try:
                broker_socket.close()
            except OSError:
                pass
        evidence.close()


def main() -> int:
    config_bytes = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(config_bytes) > 1024 * 1024:
        return 125
    try:
        config = json.loads(config_bytes.decode("utf-8"))
        if not isinstance(config, dict):
            return 125
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 125
    # The input descriptor carried a host-side configuration stream.  No
    # trusted bootstrap channel should remain reachable through /proc/1/fd.
    try:
        os.close(0)
    except OSError:
        pass
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
