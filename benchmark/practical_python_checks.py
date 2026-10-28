"""Trusted Python checker with a data-only RPC boundary to candidate code."""

from __future__ import annotations

import argparse
import builtins
import importlib
import importlib.abc
import importlib.machinery
import inspect
import io
import json
import math
import os
import re
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types
import unittest
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import practical_worker_guard


_DEFAULT_DEADLINE = 18.0
_MAX_FRAME = 1024 * 1024
_REPORT_PREFIX = "PRACTICAL_GRADE_REPORT:"
_SEED_FILE_NAME = ".practical-grade-seed.json"
_EXCEPTION_TYPES = {
    name: getattr(builtins, name)
    for name in (
        "AssertionError", "AttributeError", "IndexError", "KeyError", "LookupError",
        "NameError", "NotImplementedError", "OverflowError", "RuntimeError",
        "StopIteration", "SystemExit", "TypeError", "ValueError", "ZeroDivisionError",
    )
}


class CandidateRemoteError(Exception):
    """A candidate function raised an ordinary exception in its worker."""


class CandidateWorkerEnded(RuntimeError):
    """The data-only candidate worker ended during a trusted check."""


class CandidateWorkerGuardFailed(RuntimeError):
    """The required worker isolation could not be installed."""


class GradeProtocolError(RuntimeError):
    """The candidate worker violated the data-only RPC protocol."""


def _send_frame(channel: socket.socket, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if len(raw) > _MAX_FRAME:
        raise GradeProtocolError("grader RPC message exceeds its size limit")
    channel.sendall(struct.pack("!I", len(raw)) + raw)


def _recv_exact(channel: socket.socket, size: int, deadline: float) -> bytes:
    output = bytearray()
    while len(output) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("candidate worker RPC deadline exceeded")
        readable, _, _ = select.select([channel], [], [], remaining)
        if not readable:
            raise TimeoutError("candidate worker RPC deadline exceeded")
        part = channel.recv(size - len(output))
        if not part:
            raise CandidateWorkerEnded("candidate worker closed its RPC channel")
        output.extend(part)
    return bytes(output)


def _recv_frame(channel: socket.socket, deadline: float) -> dict[str, Any]:
    size = struct.unpack("!I", _recv_exact(channel, 4, deadline))[0]
    if size > _MAX_FRAME:
        raise GradeProtocolError("candidate worker RPC message exceeds its size limit")
    raw = _recv_exact(channel, size, deadline)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GradeProtocolError("candidate worker returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise GradeProtocolError("candidate worker returned a non-object message")
    return value


def _pack_scalar(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"$float": "nan"}
        if math.isinf(value):
            return {"$float": "inf" if value > 0 else "-inf"}
        return value
    raise GradeProtocolError(f"unsupported grader RPC value: {type(value).__name__}")


def _unpack_scalar(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$float"}:
        special = value["$float"]
        if special == "nan":
            return float("nan")
        if special == "inf":
            return float("inf")
        if special == "-inf":
            return float("-inf")
        raise GradeProtocolError("candidate worker returned an invalid float tag")
    return value


class _HostGraph:
    """Serialize check inputs while retaining their identity for mutation checks."""

    def __init__(self) -> None:
        self.objects: dict[str, Any] = {}
        self.object_ids: dict[int, str] = {}
        self.callbacks: dict[str, Callable[..., Any]] = {}
        self._next_object = 0
        self._next_callback = 0

    def encode(self, value: Any, nodes: dict[str, Any]) -> Any:
        if callable(value):
            callback_id = f"cb{self._next_callback}"
            self._next_callback += 1
            self.callbacks[callback_id] = value
            return {"$callback": callback_id}
        if isinstance(value, tuple):
            return {"$tuple": [self.encode(item, nodes) for item in value]}
        if isinstance(value, (dict, list)):
            identity = id(value)
            ref = self.object_ids.get(identity)
            if ref is None or self.objects.get(ref) is not value:
                ref = f"h{self._next_object}"
                self._next_object += 1
                self.object_ids[identity] = ref
                self.objects[ref] = value
            if ref not in nodes:
                nodes[ref] = None
                if isinstance(value, dict):
                    nodes[ref] = {
                        "kind": "dict",
                        "items": [[self.encode(key, nodes), self.encode(item, nodes)]
                                  for key, item in value.items()],
                    }
                else:
                    nodes[ref] = {
                        "kind": "list",
                        "items": [self.encode(item, nodes) for item in value],
                    }
            return {"$ref": ref}
        return _pack_scalar(value)

    def encode_call(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
        nodes: dict[str, Any] = {}
        encoded_args = [self.encode(value, nodes) for value in args]
        encoded_kwargs = {key: self.encode(value, nodes) for key, value in kwargs.items()}
        return encoded_args, encoded_kwargs, nodes

    def decode_worker_payload(self, value: Any, nodes: Mapping[str, Any], *, sync: bool) -> Any:
        objects: dict[str, Any] = dict(self.objects)
        for ref, node in nodes.items():
            if not isinstance(node, dict):
                raise GradeProtocolError("candidate worker returned a malformed graph node")
            if ref not in objects:
                kind = node.get("kind")
                if kind == "dict":
                    objects[ref] = {}
                elif kind == "list":
                    objects[ref] = []
                else:
                    raise GradeProtocolError("candidate worker returned an unknown graph node")
        def decode(item: Any) -> Any:
            if isinstance(item, dict):
                if set(item) == {"$float"}:
                    return _unpack_scalar(item)
                if set(item) == {"$tuple"}:
                    return tuple(decode(value) for value in item["$tuple"])
                if set(item) == {"$ref"}:
                    ref = item["$ref"]
                    if ref not in objects:
                        raise GradeProtocolError("candidate worker returned a dangling graph ref")
                    return objects[ref]
                if set(item) == {"$remote"}:
                    return _RemoteObjectRef(self, str(item["$remote"]))
                if set(item) == {"$callback"}:
                    raise GradeProtocolError("candidate worker returned a callback handle")
            return item

        if sync:
            for ref, node in nodes.items():
                target = objects[ref]
                kind = node["kind"]
                if kind == "dict":
                    target.clear()
                    for key, item in node.get("items", []):
                        target[decode(key)] = decode(item)
                else:
                    target[:] = [decode(item) for item in node.get("items", [])]
        return decode(value)

    def decode_callback_args(self, values: list[Any], nodes: Mapping[str, Any]) -> list[Any]:
        return self.decode_worker_payload(values, nodes, sync=False)


class _WorkerGraph:
    """Decode inputs in the candidate process and return observations as data."""

    def __init__(self, channel: socket.socket) -> None:
        self.channel = channel
        self.refs: dict[str, Any] = {}
        self.object_ids: dict[int, str] = {}
        self.handles: dict[str, Any] = {}
        self.touched: set[str] = set()
        self._next_result = 0
        self._next_handle = 0
        self._next_callback = 0

    def decode_inputs(self, nodes: Mapping[str, Any]) -> None:
        for ref, node in nodes.items():
            if not isinstance(node, dict):
                raise GradeProtocolError("trusted checker sent a malformed graph node")
            if ref not in self.refs:
                kind = node.get("kind")
                if kind == "dict":
                    self.refs[ref] = {}
                elif kind == "list":
                    self.refs[ref] = []
                else:
                    raise GradeProtocolError("trusted checker sent an unknown graph node")
            self.object_ids[id(self.refs[ref])] = ref
            self.touched.add(ref)

        def decode(item: Any) -> Any:
            if isinstance(item, dict):
                if set(item) == {"$float"}:
                    return _unpack_scalar(item)
                if set(item) == {"$tuple"}:
                    return tuple(decode(value) for value in item["$tuple"])
                if set(item) == {"$ref"}:
                    ref = item["$ref"]
                    if ref not in self.refs:
                        raise GradeProtocolError("trusted checker sent a dangling graph ref")
                    return self.refs[ref]
                if set(item) == {"$callback"}:
                    return _RemoteCallback(self, str(item["$callback"]))
            return item

        for ref, node in nodes.items():
            target = self.refs[ref]
            if node["kind"] == "dict":
                target.clear()
                for key, item in node.get("items", []):
                    target[decode(key)] = decode(item)
            else:
                target[:] = [decode(item) for item in node.get("items", [])]

    def decode_value(self, item: Any) -> Any:
        if isinstance(item, dict):
            if set(item) == {"$float"}:
                return _unpack_scalar(item)
            if set(item) == {"$tuple"}:
                return tuple(self.decode_value(value) for value in item["$tuple"])
            if set(item) == {"$ref"}:
                ref = item["$ref"]
                if ref not in self.refs:
                    raise GradeProtocolError("trusted checker sent a dangling graph ref")
                return self.refs[ref]
            if set(item) == {"$callback"}:
                return _RemoteCallback(self, str(item["$callback"]))
            if set(item) == {"$remote"}:
                return self.handles[str(item["$remote"])]
        return item

    def encode_value(self, value: Any, nodes: dict[str, Any]) -> Any:
        if isinstance(value, tuple):
            return {"$tuple": [self.encode_value(item, nodes) for item in value]}
        if isinstance(value, (dict, list)):
            identity = id(value)
            ref = self.object_ids.get(identity)
            if ref is None or self.refs.get(ref) is not value:
                ref = f"w{self._next_result}"
                self._next_result += 1
                self.object_ids[identity] = ref
                self.refs[ref] = value
            if ref not in nodes:
                nodes[ref] = None
                if isinstance(value, dict):
                    nodes[ref] = {
                        "kind": "dict",
                        "items": [[self.encode_value(key, nodes),
                                   self.encode_value(item, nodes)]
                                  for key, item in value.items()],
                    }
                else:
                    nodes[ref] = {
                        "kind": "list",
                        "items": [self.encode_value(item, nodes) for item in value],
                    }
            return {"$ref": ref}
        return _pack_scalar(value)

    def encode_response(self, value: Any) -> tuple[Any, dict[str, Any]]:
        nodes: dict[str, Any] = {}
        packed = self.encode_value(value, nodes)
        for ref in tuple(self.touched):
            obj = self.refs.get(ref)
            if obj is not None:
                self._encode_forced_node(ref, obj, nodes)
        return packed, nodes

    def _encode_forced_node(self, ref: str, value: Any, nodes: dict[str, Any]) -> None:
        if ref in nodes:
            return
        nodes[ref] = None
        if isinstance(value, dict):
            nodes[ref] = {
                "kind": "dict",
                "items": [[self.encode_value(key, nodes),
                           self.encode_value(item, nodes)]
                          for key, item in value.items()],
            }
        elif isinstance(value, list):
            nodes[ref] = {
                "kind": "list",
                "items": [self.encode_value(item, nodes) for item in value],
            }
        else:
            raise GradeProtocolError("candidate changed a non-container RPC reference")


class _RemoteCallback:
    def __init__(self, graph: _WorkerGraph, callback_id: str) -> None:
        self.graph = graph
        self.callback_id = callback_id

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        nodes: dict[str, Any] = {}
        encoded_args = [self.graph.encode_value(value, nodes) for value in args]
        encoded_kwargs = {key: self.graph.encode_value(value, nodes)
                          for key, value in kwargs.items()}
        callback_request = self.graph._next_callback
        self.graph._next_callback += 1
        _send_frame(self.graph.channel, {
            "type": "callback", "id": callback_request,
            "callback": self.callback_id, "args": encoded_args,
            "kwargs": encoded_kwargs, "nodes": nodes,
        })
        deadline = time.monotonic() + _DEFAULT_DEADLINE
        response = _recv_frame(self.graph.channel, deadline)
        if response.get("type") != "callback_result" or response.get("id") != callback_request:
            raise GradeProtocolError("trusted checker returned an invalid callback reply")
        self.graph.decode_inputs(response.get("nodes", {}))
        if not response.get("ok"):
            error = response.get("error") or {}
            raise _worker_exception(error)
        return self.graph.decode_value(response.get("value"))


class _CandidateRPC:
    def __init__(self, *, launcher: Path, workspace: Path,
                 deadline: float, node_root: Path | None = None,
                 node_reporter: Path | None = None) -> None:
        self.launcher = launcher.resolve(strict=True)
        self.workspace = workspace.resolve(strict=True)
        self.deadline = deadline
        self.node_root = node_root
        self.node_reporter = node_reporter
        self.graph = _HostGraph()
        self.graph.rpc = self
        self.process: subprocess.Popen[bytes] | None = None
        self.channel: socket.socket | None = None
        self.broken: str | None = None
        self.infrastructure_error: str | None = None
        self.candidate_import_error: str | None = None
        self._next_request = 0

    def _start(self) -> None:
        if self.process is not None:
            return
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        fd = child.fileno()
        env = {"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"}
        if self.node_root is None:
            argv = [sys.executable, "-B", "-I", str(self.launcher),
                    "--candidate-worker", "--rpc-fd", str(fd),
                    "--workspace", str(self.workspace),
                    "--helper-path", str(self.launcher)]
            if self.node_reporter is not None:
                argv.extend(("--node-reporter", str(self.node_reporter)))
            env["PRACTICAL_WORKER_KIND"] = "python"
        else:
            if self.node_reporter is None:
                parent.close()
                child.close()
                raise CandidateWorkerGuardFailed("Node reporter helper is missing")
            node_exec = self.node_root / "bin" / "node"
            argv = [sys.executable, "-B", "-I", str(self.launcher),
                    "--candidate-exec", "--rpc-fd", str(fd),
                    "--workspace", str(self.workspace),
                    "--node-root", str(self.node_root),
                    "--node-exec", str(node_exec),
                    "--node-reporter", str(self.node_reporter)]
            env["PRACTICAL_WORKER_KIND"] = "node"
        try:
            self.process = subprocess.Popen(
                argv, cwd=self.workspace, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, pass_fds=(fd,))
        except OSError as exc:
            parent.close()
            child.close()
            self.infrastructure_error = f"candidate worker could not start: {type(exc).__name__}"
            raise CandidateWorkerGuardFailed(self.infrastructure_error) from exc
        child.close()
        parent.setblocking(True)
        self.channel = parent

    def invoke(self, operation: str, module: str, name: str,
               args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None,
               *, handle: str | None = None) -> Any:
        if self.broken:
            raise CandidateWorkerEnded(self.broken)
        self._start()
        assert self.channel is not None
        encoded_args, encoded_kwargs, nodes = self.graph.encode_call(args, kwargs or {})
        request_id = self._next_request
        self._next_request += 1
        _send_frame(self.channel, {
            "type": "request", "id": request_id, "op": operation,
            "module": module, "name": name, "handle": handle,
            "args": encoded_args, "kwargs": encoded_kwargs, "nodes": nodes,
        })
        while True:
            try:
                response = _recv_frame(self.channel, self.deadline)
            except (OSError, EOFError, TimeoutError, GradeProtocolError,
                    CandidateWorkerEnded) as exc:
                self.broken = f"candidate worker data channel failed: {type(exc).__name__}"
                if isinstance(exc, TimeoutError):
                    self._stop(force=True)
                raise CandidateWorkerEnded(self.broken) from exc
            message_type = response.get("type")
            if message_type == "guard_error":
                self.infrastructure_error = str(response.get("reason") or "worker guard failed")
                self.broken = self.infrastructure_error
                raise CandidateWorkerGuardFailed(self.infrastructure_error)
            if message_type == "callback":
                self._reply_callback(response)
                continue
            if message_type != "response" or response.get("id") != request_id:
                self.broken = "candidate worker sent a non-data or out-of-order RPC message"
                raise GradeProtocolError(self.broken)
            value = self.graph.decode_worker_payload(
                response.get("value"), response.get("nodes", {}), sync=True)
            if not response.get("ok"):
                if response.get("stage") == "candidate_import":
                    error = response.get("error") or {}
                    self.candidate_import_error = (
                        f"{error.get('type', 'ImportError')}: "
                        f"{error.get('message', 'candidate import failed')}")
                raise _worker_exception(response.get("error") or {})
            return value

    def _reply_callback(self, message: Mapping[str, Any]) -> None:
        callback_id = str(message.get("callback") or "")
        callback = self.graph.callbacks.get(callback_id)
        if callback is None:
            self.broken = "candidate worker invoked an unknown trusted callback"
            raise GradeProtocolError(self.broken)
        try:
            args = self.graph.decode_callback_args(message.get("args", []),
                                                  message.get("nodes", {}))
            kwargs = self.graph.decode_worker_payload(
                message.get("kwargs", {}), message.get("nodes", {}), sync=False)
            value = callback(*args, **kwargs)
            nodes: dict[str, Any] = {}
            encoded = self.graph.encode(value, nodes)
            _send_frame(self.channel, {
                "type": "callback_result", "id": message.get("id"),
                "ok": True, "value": encoded, "nodes": nodes,
            })
        except BaseException as exc:
            _send_frame(self.channel, {
                "type": "callback_result", "id": message.get("id"),
                "ok": False, "error": _exception_payload(exc), "nodes": {},
            })

    def stop(self) -> None:
        self._stop(force=False)

    def _stop(self, *, force: bool) -> None:
        if self.channel is not None:
            if not force:
                try:
                    _send_frame(self.channel, {"type": "stop"})
                except OSError:
                    pass
            self.channel.close()
            self.channel = None
        if self.process is not None:
            if self.process.poll() is None and force:
                self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None


class _RemoteSymbol:
    def __init__(self, rpc: _CandidateRPC, module: str, name: str) -> None:
        self.rpc = rpc
        self.module = module
        self.name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.rpc.invoke("invoke", self.module, self.name, args, kwargs)


class _RemoteObjectRef:
    def __init__(self, rpc: _HostGraph, handle: str) -> None:
        self.rpc = rpc
        self.handle = handle

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return _RemoteMethod(self.rpc, self.handle, name)


class _RemoteMethod:
    def __init__(self, graph: _HostGraph, handle: str, name: str) -> None:
        self.graph = graph
        self.handle = handle
        self.name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        rpc = getattr(self.graph, "rpc", None)
        if rpc is None:
            raise CandidateWorkerEnded("candidate object is detached from its RPC worker")
        return rpc.invoke("method", "", self.name, args, kwargs, handle=self.handle)


class _ProxyModule(types.ModuleType):
    def __init__(self, name: str, rpc: _CandidateRPC, *, package: bool) -> None:
        super().__init__(name)
        self.__dict__["_candidate_rpc"] = rpc
        if package:
            self.__dict__["__path__"] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return _RemoteSymbol(self.__dict__["_candidate_rpc"], self.__name__, name)


class _ProxyLoader(importlib.abc.Loader):
    def __init__(self, rpc: _CandidateRPC, name: str, *, package: bool) -> None:
        self.rpc = rpc
        self.name = name
        self.package = package

    def create_module(self, spec):
        return _ProxyModule(self.name, self.rpc, package=self.package)

    def exec_module(self, _module) -> None:
        return None


class _ProxyFinder(importlib.abc.MetaPathFinder):
    def __init__(self, rpc: _CandidateRPC, roots: set[str]) -> None:
        self.rpc = rpc
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root not in self.roots:
            if root in sys.stdlib_module_names:
                search=[entry for entry in (sys.path if path is None else path)
                        if not _is_under(Path(entry or os.getcwd()),self.rpc.workspace)]
                return importlib.machinery.PathFinder.find_spec(fullname,search)
            return None
        package = "." not in fullname
        return importlib.machinery.ModuleSpec(
            fullname, _ProxyLoader(self.rpc, fullname, package=package),
            is_package=package)


class _GradeResult(unittest.TextTestResult):
    def __init__(self, *args, expected: tuple[str, ...], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.expected = expected
        self.stops: dict[str, str] = {}
        self.error_summaries: list[str] = []

    def _record(self, test: unittest.TestCase, stop: str) -> None:
        case = test.id().rsplit(".", 2)[-2:]
        case_id = ".".join(case)
        previous = self.stops.get(case_id)
        if previous != "fail" and previous != "error":
            self.stops[case_id] = stop

    def addSuccess(self, test) -> None:
        self._record(test, "pass")
        super().addSuccess(test)

    def addFailure(self, test, err) -> None:
        self._record(test, "fail")
        super().addFailure(test, err)

    def addError(self, test, err) -> None:
        self._record(test, "error")
        self.error_summaries.append(
            f"{type(err[1]).__name__}: {str(err[1])[:300]}")
        super().addError(test, err)

    def addSkip(self, test, reason) -> None:
        self._record(test, "skipped")
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err) -> None:
        if err is not None:
            self._record(test, "fail")
        super().addSubTest(test, subtest, err)

    def addExpectedFailure(self, test, err) -> None:
        self._record(test, "skipped")
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test) -> None:
        self._record(test, "fail")
        super().addUnexpectedSuccess(test)


def _exception_payload(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:500]}


def _build_report(nonce: str, expected: list[str], events: list[dict[str, Any]],
                  returncode: int | None, deadline_exceeded: bool,
                  protocol_fault: bool) -> dict[str, Any]:
    """Compatibility helper for old event-contract unit fixtures only.

    The live launcher never consumes worker-authored stop events; all current
    reports are built by ``_run_python_checks`` in the trusted process.
    """
    header = {"schema": "practical-grade-report-v1", "nonce": nonce,
              "expected_case_ids": list(expected)}
    ended = any(event.get("event") == "end" for event in events)
    faults = [event for event in events if event.get("event") == "worker_fault"]
    if protocol_fault or faults:
        return {**header, "status": "infrastructure",
                "reason": "legacy fixture reported a worker fault",
                "checks": [], "tests_run": 0}
    import_errors = [event for event in events if event.get("event") == "import_error"]
    if len(import_errors) > 1:
        return {**header, "status": "infrastructure",
                "reason": "legacy fixture repeated an import error",
                "checks": [], "tests_run": 0}
    if import_errors:
        error = import_errors[0]
        if error.get("provenance") == "candidate":
            return {**header, "status": "complete",
                    "reason": "candidate import failed: " + str(error.get("detail") or ""),
                    "checks": [{"id": case, "stop": "error"} for case in expected],
                    "tests_run": len(expected)}
        if error.get("provenance") == "harness":
            return {**header, "status": "infrastructure",
                    "reason": "trusted harness import failed",
                    "checks": [], "tests_run": 0}
        return {**header, "status": "invalid",
                "reason": "legacy import error has unknown provenance",
                "checks": [], "tests_run": 0}
    stops: dict[str, str] = {}
    for event in events:
        if event.get("event") == "stop":
            check = event.get("check")
            stop = event.get("stop")
            if check in stops or check not in expected or stop not in {
                    "pass", "fail", "error", "skipped"}:
                return {**header, "status": "invalid",
                        "reason": "duplicate or unexpected legacy stop",
                        "checks": [], "tests_run": len(stops)}
            stops[check] = stop
    if not ended or returncode != 0 or deadline_exceeded or set(stops) != set(expected):
        return {**header, "status": "invalid",
                "reason": "legacy event stream incomplete", "checks": [],
                "tests_run": len(stops)}
    return {**header, "status": "complete", "checks": [
        {"id": case, "stop": stops[case]} for case in expected],
        "tests_run": len(expected)}


def _worker_exception(payload: Mapping[str, Any]) -> BaseException:
    name = str(payload.get("type") or "CandidateRemoteError")
    message = str(payload.get("message") or "candidate call failed")[:500]
    cls = _EXCEPTION_TYPES.get(name, CandidateRemoteError)
    try:
        return cls(message)
    except Exception:
        return CandidateRemoteError(f"{name}: {message}")


def _read_nonce(workspace: Path, seed_name: str) -> str | None:
    seed = workspace / seed_name
    try:
        payload = json.loads(seed.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        seed.unlink()
    except OSError:
        return None
    nonce = payload.get("nonce") if isinstance(payload, dict) else None
    if not isinstance(nonce, str) or len(nonce) != 32 or any(
            char not in "0123456789abcdef" for char in nonce):
        return None
    return nonce


def _candidate_worker(args: argparse.Namespace, launcher: Path) -> int:
    channel = socket.socket(fileno=args.rpc_fd)
    graph = _WorkerGraph(channel)
    try:
        helper_paths = [launcher.resolve(strict=True),
                        Path(practical_worker_guard.__file__).resolve(strict=True)]
        if args.node_reporter:
            helper_paths.append(Path(args.node_reporter).resolve(strict=True))
        practical_worker_guard.restrict_candidate_process(
            workspace=Path(args.workspace), helper_paths=helper_paths,
            runtime_paths=(Path(sys.executable),), node_root=None)
    except BaseException as exc:
        _send_frame(channel, {"type": "guard_error", "reason": str(exc)[:500]})
        channel.close()
        return 3

    sys.path.insert(0, str(Path(args.workspace).resolve()))
    while True:
        try:
            request = _recv_frame(channel, time.monotonic() + _DEFAULT_DEADLINE)
        except (OSError, EOFError, TimeoutError, GradeProtocolError):
            break
        if request.get("type") == "stop":
            break
        if request.get("type") != "request":
            _send_frame(channel, {"type": "worker_fault", "reason": "unexpected message"})
            break
        request_id = request.get("id")
        graph.touched.clear()
        stage = "candidate_import"
        try:
            graph.decode_inputs(request.get("nodes", {}))
            args_values = [graph.decode_value(item) for item in request.get("args", [])]
            kwargs_values = {key: graph.decode_value(item)
                             for key, item in request.get("kwargs", {}).items()}
            operation = request.get("op")
            if operation == "invoke":
                module = importlib.import_module(str(request.get("module") or ""))
                stage = "candidate_lookup"
                function = getattr(module, str(request.get("name") or ""))
                stage = "candidate_call"
                if inspect.isclass(function):
                    instance = function(*args_values, **kwargs_values)
                    handle = f"obj{graph._next_handle}"
                    graph._next_handle += 1
                    graph.handles[handle] = instance
                    result = {"$remote": handle}
                else:
                    result = function(*args_values, **kwargs_values)
            elif operation == "method":
                handle = str(request.get("handle") or "")
                target = graph.handles[handle]
                result = getattr(target, str(request.get("name") or ""))(
                    *args_values, **kwargs_values)
            else:
                raise GradeProtocolError("trusted checker requested an unknown operation")
            value, nodes = graph.encode_response(result)
            if operation == 'invoke' and inspect.isclass(function):
                value = {'$remote':handle}
            _send_frame(channel, {"type": "response", "id": request_id,
                                  "ok": True, "value": value, "nodes": nodes})
        except BaseException as exc:
            try:
                value, nodes = graph.encode_response(None)
                _send_frame(channel, {"type": "response", "id": request_id,
                                      "ok": False, "error": _exception_payload(exc),
                                      "value": value, "nodes": nodes,
                                      "stage": stage})
            except BaseException:
                break
    channel.close()
    return 0


def _candidate_exec(args: argparse.Namespace, launcher: Path) -> int:
    if not args.node_exec or not args.node_reporter or not args.node_root:
        return 3
    helper_paths = [launcher.resolve(strict=True),
                    Path(practical_worker_guard.__file__).resolve(strict=True),
                    Path(args.node_reporter).resolve(strict=True)]
    try:
        practical_worker_guard.restrict_candidate_process(
            workspace=Path(args.workspace), helper_paths=helper_paths,
            runtime_paths=(Path(sys.executable),),
            node_root=Path(args.node_root))
    except BaseException:
        return 3
    command = [args.node_exec, args.node_reporter,
               "--candidate-worker", "--rpc-fd", str(args.rpc_fd),
               "--workspace", str(args.workspace)]
    os.execve(args.node_exec, command,
              {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    return 3


def _run_python_checks(source: str, expected: tuple[str, ...], rpc: _CandidateRPC,
                       workspace: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "practical-grade-report-v1", "status": "invalid",
        "reason": None, "expected_case_ids": list(expected),
        "checks": [], "tests_run": 0,
    }
    roots = {name.split(".", 1)[0] for name in _nonstandard_import_roots(source)}
    finder = _ProxyFinder(rpc, roots)
    sys.meta_path.insert(0, finder)
    module_name = f"practical_trusted_checks_{os.getpid()}"
    module = types.ModuleType(module_name)
    module.__file__ = "<trusted practical checks>"
    module.__dict__["__builtins__"] = builtins
    original_path = list(sys.path)
    def prohibit_candidate_exec(event, arguments):
        if event == 'exec' and arguments:
            filename = getattr(arguments[0],'co_filename','')
            if filename and not filename.startswith('<') and _is_under(Path(filename),workspace):
                raise GradeProtocolError('candidate code may only execute in its guarded RPC worker')
    sys.addaudithook(prohibit_candidate_exec)
    try:
        sys.path[:] = [entry for entry in sys.path
                       if not _is_under(Path(entry or os.getcwd()), workspace)]
        sys.path.insert(0, str(workspace))
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        stream = io.StringIO()
        runner = unittest.TextTestRunner(
            stream=stream, verbosity=0,
            resultclass=lambda *args, **kwargs: _GradeResult(
                *args, expected=expected, **kwargs))
        result = runner.run(suite)
        if rpc.infrastructure_error:
            report.update(status="infrastructure", reason=rpc.infrastructure_error)
        elif rpc.broken:
            report.update(status="invalid",
                          reason="checks terminated before candidate execution completed: "
                          + rpc.broken)
        else:
            stops = dict(result.stops)
            if result.testsRun != len(expected) or set(stops) != set(expected):
                report.update(status="invalid",
                              reason="trusted test runner did not execute the expected checks",
                              tests_run=result.testsRun)
            else:
                report.update(
                    status="complete", tests_run=result.testsRun,
                    checks=[{"id": case, "stop": stops[case]} for case in expected])
                if rpc.candidate_import_error:
                    report["reason"] = "candidate import failed: " + rpc.candidate_import_error
                elif result.error_summaries:
                    report["reason"] = "checks reported error: " + result.error_summaries[0]
        return report
    except BaseException as exc:
        report.update(status="infrastructure",
                      reason=f"trusted check harness failed: {type(exc).__name__}: {str(exc)[:300]}")
        return report
    finally:
        sys.meta_path.remove(finder)
        sys.path[:] = original_path
        rpc.stop()


def _nonstandard_import_roots(source: str) -> tuple[str, ...]:
    from practical_grade_contract import python_candidate_module_roots

    return python_candidate_module_roots(source)


def _run_node_checks(checks: Path, expected: tuple[str, ...], rpc: _CandidateRPC,
                     workspace: Path) -> dict[str, Any]:
    """Trusted Node assertions and a guarded candidate are sibling processes."""
    report = {'schema':'practical-grade-report-v1','status':'invalid',
              'checks':[],'tests_run':0,'expected_case_ids':list(expected)}
    stop = threading.Event()
    with tempfile.TemporaryDirectory(prefix='grade-private-') as temporary:
        address = str(Path(temporary)/'rpc.sock')
        listener = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        listener.bind(address)
        listener.listen(2)
        listener.settimeout(0.1)
        def relay():
            while not stop.is_set():
                try:
                    client,_ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                with client:
                    try:
                        request = _recv_frame(client,rpc.deadline)
                        rpc._start()
                        _send_frame(rpc.channel,request)
                        response = _recv_frame(rpc.channel,rpc.deadline)
                        if response.get('type') == 'guard_error':
                            rpc.infrastructure_error = str(response.get('reason'))
                        elif response.get('type') != 'response' or response.get('id') != request.get('id'):
                            rpc.broken = 'candidate worker sent a non-data RPC response'
                        elif response.get('stage') == 'candidate_import' and not response.get('ok'):
                            rpc.candidate_import_error = str(response.get('error'))
                        _send_frame(client,response)
                    except BaseException as exc:
                        rpc.broken = f'candidate RPC ended: {type(exc).__name__}'
                        try:
                            _send_frame(client,{'type':'rpc_fault','reason':rpc.broken})
                        except OSError:
                            pass
        thread = threading.Thread(target=relay,daemon=True)
        thread.start()
        try:
            result = subprocess.run([str(rpc.node_root/'bin/node'),str(rpc.node_reporter),
                '--trusted-checker','--checks',str(checks),'--workspace',str(workspace),
                '--rpc-socket',address],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,timeout=max(1,rpc.deadline-time.monotonic()+2),
                cwd=workspace,env={'PATH':'/usr/bin:/bin','LANG':'C','NODE_NO_WARNINGS':'1'})
            output = result.stdout.decode(errors='replace')
            stops = {}
            for match in re.finditer(r'(?m)^(not )?ok \d+ - (.+)$',output):
                name = match.group(2)
                skipped = ' # SKIP' in name or ' # TODO' in name
                name = re.split(r' # (?:SKIP|TODO)',name)[0]
                if name in stops:
                    rpc.broken = 'trusted Node runner repeated a check'
                stops[name] = 'skipped' if skipped else 'fail' if match.group(1) else 'pass'
            if rpc.infrastructure_error:
                report.update(status='infrastructure',reason=rpc.infrastructure_error)
            elif rpc.broken:
                report['reason'] = rpc.broken
            elif rpc.candidate_import_error:
                report.update(status='complete',reason='candidate import failed: '+rpc.candidate_import_error,
                    candidate_import_error=rpc.candidate_import_error,
                    checks=[{'id':case,'stop':'error'} for case in expected],tests_run=0)
            elif set(stops) == set(expected):
                report.update(status='complete',checks=[{'id':case,'stop':stops[case]} for case in expected],
                              tests_run=len(stops))
            else:
                report['reason'] = 'trusted Node runner did not complete all checks: '+result.stderr.decode(errors='replace')[-700:]
            report['diagnostic_output'] = output[-6000:]
        except subprocess.TimeoutExpired:
            report['reason'] = 'trusted Node runner deadline exceeded'
        finally:
            stop.set()
            listener.close()
            rpc.stop()
            thread.join(timeout=2)
    return report


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _run_parent(args: argparse.Namespace, launcher: Path) -> int:
    from practical_grade_contract import (
        REPORT_PREFIX, REPORT_SCHEMA, python_check_case_ids, node_check_case_ids,
        report_export_paths)

    workspace = Path(args.workspace or os.getcwd()).resolve()
    nonce = _read_nonce(workspace, args.seed_file or _SEED_FILE_NAME)
    if nonce is None:
        return 3
    try:
        check_path = Path(args.checks).resolve(strict=True)
        source = check_path.read_text(encoding="utf-8")
        expected = node_check_case_ids(source) if args.language == 'javascript' else python_check_case_ids(source)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return 3
    if not expected:
        return 3
    try:
        practical_worker_guard.disable_process_inspection()
        rpc = _CandidateRPC(
            launcher=launcher, workspace=workspace,
            deadline=time.monotonic() + _DEFAULT_DEADLINE,
            node_root=(Path(args.node_root) if args.language == "javascript" else None),
            node_reporter=(Path(args.node_reporter) if args.node_reporter else None))
        report = (_run_node_checks(check_path,expected,rpc,workspace)
                  if args.language == 'javascript' else _run_python_checks(source, expected, rpc, workspace))
    except BaseException as exc:
        report = {"schema": REPORT_SCHEMA, "status": "infrastructure",
                  "reason": f"trusted checker setup failed: {type(exc).__name__}: {str(exc)[:300]}",
                  "expected_case_ids": list(expected), "checks": [], "tests_run": 0}
    report.update(schema=REPORT_SCHEMA, nonce=nonce,
                  expected_case_ids=list(expected))
    _write_export(workspace, report, report_export_paths(nonce))
    sys.stdout.write(REPORT_PREFIX + json.dumps(report, ensure_ascii=False,
                                               separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


def _write_export(workspace: Path, report: Mapping[str, Any], slots: tuple[str, ...]) -> None:
    raw = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    for slot in slots:
        try:
            with (workspace / slot).open("x", encoding="utf-8") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            return
        except FileExistsError:
            continue
        except OSError:
            continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", action="store_true")
    parser.add_argument("--candidate-worker", action="store_true")
    parser.add_argument("--candidate-exec", action="store_true")
    parser.add_argument("--checks")
    parser.add_argument("--seed-file", default=_SEED_FILE_NAME)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--rpc-fd", type=int, default=None)
    parser.add_argument("--language", choices=("python", "javascript"), default="python")
    parser.add_argument("--node-root")
    parser.add_argument("--node-exec")
    parser.add_argument("--node-reporter")
    parser.add_argument("--helper-path")
    args = parser.parse_args(argv)
    launcher = Path(__file__).resolve()
    try:
        if args.candidate_worker:
            if args.rpc_fd is None or args.workspace is None:
                return 2
            return _candidate_worker(args, launcher)
        if args.candidate_exec:
            return _candidate_exec(args, launcher)
        if args.parent and args.checks:
            return _run_parent(args, launcher)
        return 2
    except BaseException:
        traceback.print_exc(file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
