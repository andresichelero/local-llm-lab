"""Fail-closed filesystem and process-inspection restrictions for grade workers."""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat
import sys
import sysconfig
from pathlib import Path
from typing import Iterable


_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
_LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
_LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
_LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
_LANDLOCK_ACCESS_FS_REFER = 1 << 13
_LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14
_LANDLOCK_ACCESS_NET_BIND_TCP = 1 << 0
_LANDLOCK_ACCESS_NET_CONNECT_TCP = 1 << 1
_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_DUMPABLE = 4
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_ALLOW = 0x7FFF0000
_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_RET_K = 0x06
_AUDIT_ARCH_X86_64 = 0xC000003E
_AUDIT_ARCH_AARCH64 = 0xC00000B7
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_MIN_LANDLOCK_ABI = 4
_MAX_PROTOCOL_BYTES = 1 << 20


class WorkerGuardError(RuntimeError):
    """The requested worker isolation could not be installed."""


def worker_capabilities() -> dict:
    """Read-only preparation check; never restricts the caller or loads a model."""
    abi=_landlock_abi() if sys.platform.startswith('linux') else 0
    return {'landlock_abi':abi,'minimum_abi':_MIN_LANDLOCK_ABI,
            'architecture':platform.machine().lower(),'kernel':platform.release(),
            'supported':abi>=_MIN_LANDLOCK_ABI and platform.machine().lower() in
                {'x86_64','amd64','aarch64','arm64'}}


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32)]


class _SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16),
                ("filter", ctypes.POINTER(_SockFilter))]


def disable_process_inspection() -> None:
    """Prevent same-uid child processes from inspecting this trusted process."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        _raise_errno("PR_SET_DUMPABLE")


def restrict_candidate_process(*, workspace: Path,
                               helper_paths: Iterable[Path],
                               runtime_paths: Iterable[Path] = (),
                               node_root: Path | None = None) -> None:
    """Confine a worker to its input tree, exact helpers and runtime libraries.

    Landlock and the process-inspection seccomp filter are inherited through
    exec. A missing kernel feature or unresolvable allow path is a hard error.
    """
    if not sys.platform.startswith("linux"):
        raise WorkerGuardError("Linux worker isolation is required")
    machine = platform.machine().lower()
    arch = (_AUDIT_ARCH_X86_64 if machine in {"x86_64", "amd64"}
            else _AUDIT_ARCH_AARCH64 if machine in {"aarch64", "arm64"}
            else None)
    if arch is None:
        raise WorkerGuardError(f"unsupported worker architecture: {machine}")

    _set_no_new_privs()
    _install_process_inspection_filter(arch)
    abi = _landlock_abi()
    if abi < _MIN_LANDLOCK_ABI:
        raise WorkerGuardError(f"Landlock ABI {abi} is below required ABI {_MIN_LANDLOCK_ABI}")

    fs_rights = (1 << 15) - 1
    net_rights = _LANDLOCK_ACCESS_NET_BIND_TCP | _LANDLOCK_ACCESS_NET_CONNECT_TCP
    ruleset_attr = _RulesetAttr(fs_rights, net_rights)
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(ruleset_attr),
                      ctypes.sizeof(ruleset_attr), 0)
    if fd < 0:
        _raise_errno("landlock_create_ruleset")

    try:
        readonly = (_LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_FILE
                    | _LANDLOCK_ACCESS_FS_READ_DIR)
        writable_workspace = (readonly | _LANDLOCK_ACCESS_FS_WRITE_FILE
                              | _LANDLOCK_ACCESS_FS_REMOVE_DIR
                              | _LANDLOCK_ACCESS_FS_REMOVE_FILE
                              | _LANDLOCK_ACCESS_FS_MAKE_DIR
                              | _LANDLOCK_ACCESS_FS_MAKE_REG
                              | _LANDLOCK_ACCESS_FS_MAKE_SOCK
                              | _LANDLOCK_ACCESS_FS_MAKE_FIFO
                              | _LANDLOCK_ACCESS_FS_MAKE_SYM
                              | _LANDLOCK_ACCESS_FS_REFER
                              | _LANDLOCK_ACCESS_FS_TRUNCATE)
        _add_path_rule(fd, Path(workspace).resolve(strict=True), writable_workspace)

        paths = set(Path(path).resolve(strict=True) for path in helper_paths)
        paths.update(Path(path).resolve(strict=True) for path in runtime_paths)
        paths.update(_runtime_library_paths())
        paths.update(_device_paths())
        if node_root is not None:
            paths.add(Path(node_root).resolve(strict=True))
        for path in sorted(paths, key=lambda item: (len(item.parts), str(item))):
            _add_path_rule(fd, path, readonly)

        if libc.syscall(_SYS_LANDLOCK_RESTRICT_SELF, fd, 0) != 0:
            _raise_errno("landlock_restrict_self")
    finally:
        os.close(fd)


def _runtime_library_paths() -> set[Path]:
    paths: set[Path] = set()
    for key in ("stdlib", "platstdlib"):
        value = sysconfig.get_path(key)
        if value:
            path = Path(value)
            if path.exists():
                paths.add(path.resolve(strict=True))
    executable = Path(sys.executable)
    if executable.exists():
        paths.add(executable.resolve(strict=True))
    prefix = Path(sys.prefix)
    venv_config = prefix / "pyvenv.cfg"
    if venv_config.is_file():
        paths.add(venv_config.resolve(strict=True))
    for value in ("/lib", "/usr/lib", "/lib64", "/usr/lib64",
                  "/etc/ld.so.cache", "/etc/ld.so.preload"):
        path = Path(value)
        if path.exists():
            paths.add(path.resolve(strict=True))
    return paths


def _device_paths() -> set[Path]:
    paths = set()
    for value in ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"):
        path = Path(value)
        if path.exists():
            paths.add(path.resolve(strict=True))
    return paths


def _landlock_abi() -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, None, 0,
                          _LANDLOCK_CREATE_RULESET_VERSION)
    if result < 0:
        _raise_errno("landlock version query")
    return int(result)


def _add_path_rule(ruleset_fd: int, path: Path, access: int) -> None:
    flags = getattr(os, "O_PATH", None)
    if flags is None:
        raise WorkerGuardError("O_PATH is required for Landlock")
    try:
        path_fd = os.open(path, flags | os.O_CLOEXEC)
    except OSError as exc:
        raise WorkerGuardError(f"cannot allow worker path {path}: {exc}") from exc
    try:
        mode = os.fstat(path_fd).st_mode
        if stat.S_ISDIR(mode):
            access &= (_LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_WRITE_FILE
                       | _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR
                       | _LANDLOCK_ACCESS_FS_REMOVE_DIR | _LANDLOCK_ACCESS_FS_REMOVE_FILE
                       | _LANDLOCK_ACCESS_FS_MAKE_DIR | _LANDLOCK_ACCESS_FS_MAKE_REG
                       | _LANDLOCK_ACCESS_FS_MAKE_SOCK | _LANDLOCK_ACCESS_FS_MAKE_FIFO
                       | _LANDLOCK_ACCESS_FS_MAKE_SYM | _LANDLOCK_ACCESS_FS_REFER
                       | _LANDLOCK_ACCESS_FS_TRUNCATE)
        else:
            access &= (_LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_WRITE_FILE
                       | _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_TRUNCATE)
        attr = _PathBeneathAttr(access, path_fd)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.syscall(_SYS_LANDLOCK_ADD_RULE, ruleset_fd,
                        _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(attr), 0) != 0:
            _raise_errno(f"landlock_add_rule:{path}")
    finally:
        os.close(path_fd)


def _set_no_new_privs() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _raise_errno("PR_SET_NO_NEW_PRIVS")


def _install_process_inspection_filter(arch: int) -> None:
    if platform.machine().lower() in {"x86_64", "amd64"}:
        denied = (101, 310, 311, 312, 434, 438)  # ptrace/process_vm/kcmp/pidfd
    else:
        denied = (117, 270, 271, 272, 434, 438)
    instructions = [
        _SockFilter(_BPF_LD_W_ABS, 0, 0, 4),
        _SockFilter(_BPF_JMP_JEQ_K, 1, 0, arch),
        _SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        _SockFilter(_BPF_LD_W_ABS, 0, 0, 0),
    ]
    for number in denied:
        instructions.extend((
            _SockFilter(_BPF_JMP_JEQ_K, 0, 1, number),
            _SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | errno.EPERM),
        ))
    instructions.append(_SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW))
    program_array = (_SockFilter * len(instructions))(*instructions)
    program = _SockFprog(len(instructions), program_array)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER,
                  ctypes.byref(program), 0, 0) != 0:
        _raise_errno("PR_SET_SECCOMP")


def _raise_errno(operation: str) -> None:
    error = ctypes.get_errno()
    detail = os.strerror(error) if error else "unknown error"
    raise WorkerGuardError(f"{operation} failed: [{error}] {detail}")
