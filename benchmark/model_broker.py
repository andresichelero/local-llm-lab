"""A narrow, framed channel from a private network namespace to one local model API.

This module deliberately accepts a port, not a URL.  It never forwards caller
headers, credentials, arbitrary paths, or arbitrary HTTP methods to the host.
"""
from __future__ import annotations

import base64
import http.client
import hashlib
import json
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping


class BrokerError(ValueError):
    """Raised when a broker policy or framed request is invalid."""


_MAX_FRAME_BYTES = 8 * 1024 * 1024
_CHUNK_BYTES = 16 * 1024
_GENERATION_FIELDS = {
    "frequency_penalty",
    "max_tokens",
    "presence_penalty",
    "seed",
    "stop",
    "temperature",
    "top_p",
}
_CHAT_FIELDS = {
    "messages",
    "model",
    "parallel_tool_calls",
    "stream",
    "stream_options",
    "tool_choice",
    "tools",
}
_MAX_TRANSCRIPT_BODY_BYTES = 768 * 1024 * 1024


@dataclass(frozen=True)
class BrokerPolicy:
    """The fixed host destination and request contract for one benchmark run."""

    upstream_port: int
    model_allowlist: tuple[str, ...]
    output_token_cap: int = 512
    frozen_generation: Mapping[str, Any] = field(
        default_factory=lambda: {"temperature": 0, "seed": 1234, "max_tokens": 512}
    )
    max_request_bytes: int = 2 * 1024 * 1024
    max_response_bytes: int = 16 * 1024 * 1024
    deadline_seconds: float = 60.0
    max_requests: int = 32
    adapter_port: int = 18888

    def __post_init__(self) -> None:
        models = tuple(self.model_allowlist)
        if not 1 <= self.upstream_port <= 65535:
            raise BrokerError("upstream_port must be an explicit TCP port")
        if not 1 <= self.adapter_port <= 65535:
            raise BrokerError("adapter_port must be an explicit TCP port")
        if self.upstream_port == self.adapter_port:
            raise BrokerError("host and namespace broker ports must differ")
        if not models or len(set(models)) != len(models):
            raise BrokerError("model_allowlist must be non-empty and unique")
        if any(not isinstance(model, str) or not model or len(model) > 128 for model in models):
            raise BrokerError("invalid model identifier")
        if any(any(ch.isspace() for ch in model) for model in models):
            raise BrokerError("invalid model identifier")
        if not 1 <= self.output_token_cap <= 1_000_000:
            raise BrokerError("output_token_cap is outside the supported range")
        generation = dict(self.frozen_generation)
        if not generation or set(generation) - _GENERATION_FIELDS:
            raise BrokerError("frozen_generation contains an unsupported option")
        if set(generation) != {"temperature", "seed", "max_tokens"}:
            raise BrokerError("generation policy must freeze temperature, seed, and max_tokens")
        if generation["temperature"] != 0 or type(generation["seed"]) is not int:
            raise BrokerError("temperature must be zero and seed must be an integer")
        max_tokens = generation.get("max_tokens")
        if type(max_tokens) is not int or max_tokens != self.output_token_cap:
            raise BrokerError("frozen max_tokens must equal the output token cap")
        for key, value in generation.items():
            if key == "stop":
                if not (isinstance(value, str) or (
                    isinstance(value, list) and all(isinstance(item, str) for item in value)
                )):
                    raise BrokerError("frozen stop must be a string or list of strings")
            elif key == "seed":
                if type(value) is not int:
                    raise BrokerError("frozen seed must be an integer")
            elif key in {"max_tokens"}:
                if type(value) is not int:
                    raise BrokerError("frozen max_tokens must be an integer")
            elif type(value) not in (int, float) or not -2 <= float(value) <= 2:
                raise BrokerError(f"invalid frozen generation option: {key}")
        if not 1 <= self.max_request_bytes <= _MAX_FRAME_BYTES - 1024:
            raise BrokerError("max_request_bytes is outside the supported range")
        if not 1 <= self.max_response_bytes <= 256 * 1024 * 1024:
            raise BrokerError("max_response_bytes is outside the supported range")
        if not 0.1 <= self.deadline_seconds <= 3600:
            raise BrokerError("deadline_seconds is outside the supported range")
        if not 1 <= self.max_requests <= 10_000:
            raise BrokerError("max_requests is outside the supported range")
        object.__setattr__(self, "model_allowlist", models)
        object.__setattr__(self, "frozen_generation", MappingProxyType(generation))


@dataclass(frozen=True)
class BrokerEvent:
    method: str
    path: str
    status: int
    model_id: str | None
    request_bytes: int
    response_bytes: int
    elapsed_seconds: float
    outcome: str
    request_started_utc: str | None = None
    completed_utc: str | None = None
    upstream_first_response_byte_seconds: float | None = None
    first_response_chunk_seconds: float | None = None


@dataclass(frozen=True)
class BrokerResponse:
    status: int
    content_type: str
    chunks: Iterator[bytes]


class _TranscriptExchange:
    def __init__(self, owner: _BrokerTranscript, index: int, method: str, path: str, body: bytes):
        self.owner = owner
        self.index = index
        self.method = method
        self.path = path
        self.started = time.monotonic()
        self.started_utc = datetime.now(timezone.utc).isoformat()
        self.upstream_started: float | None = None
        self.upstream_started_utc: str | None = None
        self.upstream_first_byte: float | None = None
        self.first_chunk: float | None = None
        self.upstream_status: int | None = None
        self.upstream_content_type: str | None = None
        self.model_id: str | None = None
        self.status = 0
        self.content_type = ""
        self.outcome = "incomplete"
        self.error: str | None = None
        self.files: dict[str, dict[str, Any]] = {}
        self._fds: dict[str, int] = {}
        self._hashes: dict[str, Any] = {}
        self._closed = False
        try:
            self._write_file("client_request", body, owner.policy.max_request_bytes)
            self._open_file("upstream_request")
            self._open_file("upstream_response")
            self._open_file("response")
        except BaseException:
            self.abort()
            raise

    def _filename(self, kind: str) -> str:
        return f"request-{self.index:06d}-{kind}.bin"

    def _open_file(self, kind: str) -> None:
        fd = os.open(self._filename(kind), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=self.owner._dir_fd)
        self._fds[kind] = fd
        self._hashes[kind] = hashlib.sha256()
        self.files[kind] = {"name": self._filename(kind), "bytes": 0}

    def _write_file(self, kind: str, data: bytes, per_file_limit: int) -> None:
        if kind not in self._fds:
            self._open_file(kind)
        record = self.files[kind]
        if record["bytes"] + len(data) > per_file_limit:
            raise BrokerError("broker transcript per-file limit exceeded")
        self.owner._reserve(len(data))
        view = memoryview(data)
        while view:
            count = os.write(self._fds[kind], view)
            if count <= 0:
                raise OSError("short transcript write")
            view = view[count:]
        self._hashes[kind].update(data)
        record["bytes"] += len(data)

    def set_upstream_request(self, body: bytes) -> None:
        self._write_file("upstream_request", body, self.owner.policy.max_request_bytes)

    def mark_upstream_started(self) -> None:
        self.upstream_started = time.monotonic()
        self.upstream_started_utc = datetime.now(timezone.utc).isoformat()

    def mark_upstream_first_byte(self) -> None:
        if self.upstream_first_byte is None:
            self.upstream_first_byte = time.monotonic()

    def mark_upstream_response(self, status: int, content_type: str) -> None:
        self.upstream_status = status
        self.upstream_content_type = content_type

    def write_upstream_response(self, data: bytes) -> None:
        if data:
            self.mark_upstream_first_byte()
            self._write_file("upstream_response", data, self.owner.policy.max_response_bytes)

    def mark_first_chunk(self) -> None:
        if self.first_chunk is None:
            self.first_chunk = time.monotonic()

    def write_response(self, data: bytes) -> None:
        if data:
            self.mark_first_chunk()
            self._write_file("response", data, self.owner.policy.max_response_bytes)

    def finish(self, *, status: int, content_type: str, model_id: str | None,
               outcome: str, error: str | None = None) -> dict[str, Any]:
        self.status = status
        self.content_type = content_type
        self.model_id = model_id
        self.outcome = outcome
        self.error = error
        for fd in tuple(self._fds.values()):
            os.fsync(fd)
            os.close(fd)
        self._fds.clear()
        for kind, record in self.files.items():
            record["sha256"] = self._hashes[kind].hexdigest()
        completed = time.monotonic()
        summary = {
            "request_id": self.index,
            "request_started_utc": self.started_utc,
            "upstream_started_utc": self.upstream_started_utc,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "method": self.method,
            "path": self.path,
            "model_id": self.model_id,
            "status": status,
            "content_type": content_type,
            "upstream_status": self.upstream_status,
            "upstream_content_type": self.upstream_content_type,
            "outcome": outcome,
            "error": error,
            "request_to_upstream_first_response_byte_seconds": self._elapsed(self.upstream_first_byte),
            "upstream_to_first_response_byte_seconds": self._delta(self.upstream_started, self.upstream_first_byte),
            "request_to_first_response_chunk_seconds": self._elapsed(self.first_chunk),
            "response_duration_seconds": round(max(0.0, completed - self.started), 6),
            "files": self.files,
        }
        self.abort()
        self.owner._record(summary, self)
        return summary

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in tuple(self._fds.values()):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()

    def _elapsed(self, moment: float | None) -> float | None:
        return None if moment is None else round(max(0.0, moment - self.started), 6)

    @staticmethod
    def _delta(start: float | None, end: float | None) -> float | None:
        return None if start is None or end is None else round(max(0.0, end - start), 6)

class _BrokerTranscript:
    def __init__(self, directory: Path, policy: BrokerPolicy):
        self.directory = directory
        self.policy = policy
        self._lock = threading.Lock()
        self._next = 0
        self._body_bytes = 0
        self._metadata_bytes = 0
        self._completed = 0
        self._active: set[_TranscriptExchange] = set()
        self._closed = False
        self._dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self._manifest_fd = -1
        try:
            info = os.fstat(self._dir_fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BrokerError("broker transcript directory is not private")
            self._manifest_fd = os.open(
                "transcript.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=self._dir_fd,
            )
        except BaseException:
            os.close(self._dir_fd)
            self._dir_fd = -1
            raise

    def begin(self, method: str, path: str, body: bytes) -> _TranscriptExchange:
        with self._lock:
            if self._closed:
                raise BrokerError("broker transcript is closed")
            if self._next >= self.policy.max_requests + 1:
                raise BrokerError("broker transcript request-count limit exceeded")
            self._next += 1
            index = self._next
        exchange = _TranscriptExchange(self, index, method, path, body)
        with self._lock:
            if self._closed:
                exchange.abort()
                raise BrokerError("broker transcript is closed")
            self._active.add(exchange)
        return exchange

    def _reserve(self, size: int) -> None:
        with self._lock:
            if self._closed:
                raise BrokerError("broker transcript is closed")
            if self._body_bytes + size > _MAX_TRANSCRIPT_BODY_BYTES:
                raise BrokerError("broker transcript aggregate body limit exceeded")
            self._body_bytes += size

    def _record(self, summary: Mapping[str, Any], exchange: _TranscriptExchange) -> None:
        data = json.dumps(summary, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        if len(data) > 8192:
            raise BrokerError("broker transcript metadata exceeds its limit")
        with self._lock:
            if self._closed:
                raise BrokerError("broker transcript is closed")
            metadata_limit = (self.policy.max_requests + 1) * 8192
            if self._metadata_bytes + len(data) > metadata_limit:
                raise BrokerError("broker transcript metadata aggregate limit exceeded")
            view = memoryview(data)
            while view:
                count = os.write(self._manifest_fd, view)
                if count <= 0:
                    raise OSError("short transcript manifest write")
                view = view[count:]
            os.fsync(self._manifest_fd)
            self._metadata_bytes += len(data)
            self._completed += 1
            self._active.discard(exchange)

    @property
    def evidence(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType({
                "enabled": True,
                "complete": self._completed == self._next,
                "directory": str(self.directory),
                "manifest": str(self.directory / "transcript.jsonl"),
                "completed_requests": self._completed,
                "request_count": self._next,
                "body_bytes": self._body_bytes,
                "body_limit_bytes": _MAX_TRANSCRIPT_BODY_BYTES,
                "metadata_bytes": self._metadata_bytes,
                "metadata_limit_bytes": (self.policy.max_requests + 1) * 8192,
            })

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = tuple(self._active)
            self._active.clear()
            manifest_fd = self._manifest_fd
            self._manifest_fd = -1
            dir_fd = self._dir_fd
            self._dir_fd = -1
        for exchange in active:
            exchange.abort()
        try:
            if manifest_fd >= 0:
                try:
                    os.fsync(manifest_fd)
                finally:
                    os.close(manifest_fd)
        finally:
            if dir_fd >= 0:
                os.close(dir_fd)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise EOFError("broker channel closed")
        chunks.extend(part)
    return bytes(chunks)


def _recv_frame(sock: socket.socket, maximum: int = _MAX_FRAME_BYTES) -> bytes:
    size = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if size > maximum:
        raise BrokerError("broker frame exceeds the configured limit")
    return _recv_exact(sock, size) if size else b""


def _send_frame(sock: socket.socket, data: bytes) -> None:
    if len(data) > _MAX_FRAME_BYTES:
        raise BrokerError("broker frame exceeds the protocol limit")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _decode_json(data: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise BrokerError(f"non-finite JSON value is forbidden: {value}")

    try:
        return json.loads(data.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("broker request is not valid UTF-8 JSON") from exc


def _compact_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _error_body(message: str) -> bytes:
    return _compact_json({"error": {"message": message, "type": "invalid_request_error"}})


class BrokerChannelClient:
    """Namespace-side client for the single inherited socketpair endpoint."""

    def __init__(self, channel: socket.socket, *, max_request_bytes: int):
        self._channel = channel
        self._max_request_bytes = max_request_bytes
        self._lock = threading.Lock()

    def request(self, method: str, path: str, body: bytes) -> BrokerResponse:
        if len(body) > self._max_request_bytes:
            raise BrokerError("request body exceeds the configured limit")
        meta = _compact_json({"method": method, "path": path, "body": base64.b64encode(body).decode("ascii")})
        if len(meta) > _MAX_FRAME_BYTES:
            raise BrokerError("request metadata exceeds the protocol limit")
        self._lock.acquire()
        try:
            _send_frame(self._channel, meta)
            response_meta = _decode_json(_recv_frame(self._channel, 4096))
            if not isinstance(response_meta, dict):
                raise BrokerError("invalid broker response metadata")
            status = response_meta.get("status")
            content_type = response_meta.get("content_type")
            if type(status) is not int or not 100 <= status <= 599 or not isinstance(content_type, str):
                raise BrokerError("invalid broker response metadata")
        except BaseException:
            self._lock.release()
            raise

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    size = struct.unpack("!I", _recv_exact(self._channel, 4))[0]
                    if size == 0:
                        return
                    if size > _CHUNK_BYTES:
                        raise BrokerError("broker response chunk exceeds the protocol limit")
                    yield _recv_exact(self._channel, size)
            finally:
                self._lock.release()

        return BrokerResponse(status, content_type, chunks())


class ModelBroker:
    """Host-side fixed-target HTTP client and socketpair protocol handler."""

    def __init__(self, policy: BrokerPolicy, *, transcript_dir: Path | None = None):
        self.policy = policy
        self._events: list[BrokerEvent] = []
        self._events_lock = threading.Lock()
        self._request_count = 0
        self._transcript = _BrokerTranscript(transcript_dir, policy) if transcript_dir is not None else None
        self._active_connections: set[http.client.HTTPConnection] = set()
        self._connections_lock = threading.Lock()
        self._cancelled = False

    @property
    def events(self) -> tuple[BrokerEvent, ...]:
        with self._events_lock:
            return tuple(self._events)

    @property
    def transcript_evidence(self) -> Mapping[str, Any]:
        return MappingProxyType({}) if self._transcript is None else self._transcript.evidence

    def close(self) -> None:
        if self._transcript is not None:
            self._transcript.close()

    def cancel(self) -> None:
        with self._connections_lock:
            self._cancelled = True
            connections = tuple(self._active_connections)
        for connection in connections:
            connection.close()

    def _release_connection(self, connection: http.client.HTTPConnection) -> None:
        connection.close()
        with self._connections_lock:
            self._active_connections.discard(connection)

    def _record(self, event: BrokerEvent) -> None:
        with self._events_lock:
            self._events.append(event)

    def handle(self, method: str, path: str, body: bytes, *,
               _transcript: _TranscriptExchange | None = None) -> tuple[int, str, Iterator[bytes], str | None, int]:
        started = time.monotonic()
        started_utc = datetime.now(timezone.utc).isoformat()
        model_id: str | None = None
        status = 400
        response_type = "application/json"
        response_bytes = 0
        outcome = "rejected"
        try:
            self._request_count += 1
            if self._request_count > self.policy.max_requests:
                status, data = 429, _error_body("request budget exceeded")
                outcome = "request_budget"
                return status, response_type, iter((data,)), model_id, len(data)
            if method == "GET" and path == "/v1/models":
                if body:
                    status, data = 400, _error_body("GET requests cannot include a body")
                    outcome = "invalid_body"
                    return status, response_type, iter((data,)), model_id, len(data)
                if _transcript is not None:
                    _transcript.set_upstream_request(b"")
                status, response_type, chunks, response_bytes = self._upstream(
                    "GET", "/v1/models", b"", streaming=False, model_list=True, started=started,
                    transcript=_transcript,
                )
                outcome = "allowed"
                return status, response_type, chunks, model_id, response_bytes
            if method != "POST" or path != "/v1/chat/completions":
                status, data = 404, _error_body("route is not allowed")
                outcome = "route_denied"
                return status, response_type, iter((data,)), model_id, len(data)
            if not body or len(body) > self.policy.max_request_bytes:
                status, data = 413 if body else 400, _error_body("request body is empty or too large")
                outcome = "body_limit"
                return status, response_type, iter((data,)), model_id, len(data)
            request = _decode_json(body)
            if not isinstance(request, dict):
                status, data = 400, _error_body("chat request must be an object")
                outcome = "invalid_json_shape"
                return status, response_type, iter((data,)), model_id, len(data)
            model_id = request.get("model") if isinstance(request.get("model"), str) else None
            if model_id not in self.policy.model_allowlist:
                status, data = 403, _error_body("model is not allowed")
                outcome = "model_denied"
                return status, response_type, iter((data,)), model_id, len(data)
            if not isinstance(request.get("messages"), list) or not request["messages"]:
                status, data = 400, _error_body("messages must be a non-empty array")
                outcome = "invalid_messages"
                return status, response_type, iter((data,)), model_id, len(data)
            if len(request["messages"]) > 256:
                status, data = 413, _error_body("too many messages")
                outcome = "message_limit"
                return status, response_type, iter((data,)), model_id, len(data)
            allowed = _CHAT_FIELDS | set(self.policy.frozen_generation)
            if set(request) - allowed:
                status, data = 400, _error_body("request contains an unsupported option")
                outcome = "unknown_option"
                return status, response_type, iter((data,)), model_id, len(data)
            stream = request.get("stream", False)
            if type(stream) is not bool:
                status, data = 400, _error_body("stream must be boolean")
                outcome = "invalid_stream_option"
                return status, response_type, iter((data,)), model_id, len(data)
            stream_options = request.get("stream_options")
            if stream_options is not None:
                if (not stream or not isinstance(stream_options, dict)
                        or set(stream_options) - {"include_usage"}
                        or ("include_usage" in stream_options and type(stream_options["include_usage"]) is not bool)):
                    status, data = 400, _error_body("stream_options are not allowed")
                    outcome = "invalid_stream_options"
                    return status, response_type, iter((data,)), model_id, len(data)
            forwarded = dict(request)
            for key, value in self.policy.frozen_generation.items():
                if key in request and (type(request[key]) is not type(value) or request[key] != value):
                    status, data = 400, _error_body(f"{key} differs from the frozen generation policy")
                    outcome = "generation_policy_denied"
                    return status, response_type, iter((data,)), model_id, len(data)
                forwarded[key] = value
            wire = _compact_json(forwarded)
            if len(wire) > self.policy.max_request_bytes:
                status, data = 413, _error_body("canonical request exceeds the configured limit")
                outcome = "body_limit"
                return status, response_type, iter((data,)), model_id, len(data)
            if _transcript is not None:
                _transcript.set_upstream_request(wire)
            status, response_type, chunks, response_bytes = self._upstream(
                "POST", "/v1/chat/completions", wire, streaming=stream,
                model_list=False, started=started, transcript=_transcript,
            )
            outcome = "allowed"
            return status, response_type, chunks, model_id, response_bytes
        finally:
            # The response byte count is refined by the framed server after streaming.
            elapsed = max(0.0, time.monotonic() - started)
            self._record(BrokerEvent(method, path, status, model_id, len(body), response_bytes, elapsed, outcome,
                                     started_utc))

    def _upstream(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        streaming: bool,
        model_list: bool,
        started: float,
        transcript: _TranscriptExchange | None = None,
    ) -> tuple[int, str, Iterator[bytes], int]:
        remaining = self.policy.deadline_seconds - (time.monotonic() - started)
        if remaining <= 0:
            data = _error_body("broker deadline exceeded")
            return 504, "application/json", iter((data,)), len(data)
        connection = http.client.HTTPConnection("127.0.0.1", self.policy.upstream_port, timeout=remaining)
        with self._connections_lock:
            if self._cancelled:
                data = _error_body("broker is stopping")
                return 503, "application/json", iter((data,)), len(data)
            self._active_connections.add(connection)
        try:
            if transcript is not None:
                transcript.mark_upstream_started()
            headers = {
                "Accept": "text/event-stream" if streaming else "application/json",
                "Connection": "close",
            }
            if method == "POST":
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body if method == "POST" else None, headers=headers)
            response = connection.getresponse()
            response_type = response.getheader("Content-Type", "application/json").split(";", 1)[0].strip().lower()
            if transcript is not None:
                transcript.mark_upstream_response(response.status, response_type)
            if response_type not in {"application/json", "text/event-stream"}:
                self._read_bounded(response, connection, started, transcript=transcript)
                self._release_connection(connection)
                data = _error_body("upstream content type is not allowed")
                return 502, "application/json", iter((data,)), len(data)
            if model_list:
                data = self._read_bounded(response, connection, started, transcript=transcript)
                self._release_connection(connection)
                parsed = _decode_json(data)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
                    safe_data = _error_body("upstream model list is invalid")
                    return 502, "application/json", iter((safe_data,)), len(safe_data)
                filtered = [entry for entry in parsed["data"]
                            if isinstance(entry, dict) and entry.get("id") in self.policy.model_allowlist]
                safe_models = [{"id": entry["id"], "object": "model"} for entry in filtered]
                filtered_body = _compact_json({"object": "list", "data": safe_models})
                return response.status, "application/json", iter((filtered_body,)), len(filtered_body)
            if response.status >= 400:
                self._read_bounded(response, connection, started, transcript=transcript)
                self._release_connection(connection)
                data = _error_body("local model endpoint rejected the request")
                return response.status, "application/json", iter((data,)), len(data)
            if streaming and response_type != "text/event-stream":
                data = self._read_bounded(response, connection, started, transcript=transcript)
                self._release_connection(connection)
                return response.status, response_type, iter((data,)), len(data)
            if not streaming:
                return response.status, response_type, self._stream_bounded(
                    response, connection, started, transcript=transcript,
                ), 0
            return response.status, response_type, self._stream_bounded(
                response, connection, started, transcript=transcript,
            ), 0
        except (OSError, http.client.HTTPException, TimeoutError, BrokerError, ValueError):
            self._release_connection(connection)
            data = _error_body("upstream request failed or exceeded its limit")
            return 502, "application/json", iter((data,)), len(data)

    def _stream_bounded(self, response: http.client.HTTPResponse, connection: http.client.HTTPConnection,
                        started: float, *, transcript: _TranscriptExchange | None = None) -> Iterator[bytes]:
        total = 0
        try:
            while True:
                remaining = self.policy.deadline_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("broker response deadline exceeded")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(_CHUNK_BYTES)
                if not chunk:
                    return
                total += len(chunk)
                if total > self.policy.max_response_bytes:
                    raise BrokerError("broker response exceeds the configured limit")
                if transcript is not None:
                    transcript.write_upstream_response(chunk)
                yield chunk
        finally:
            self._release_connection(connection)

    def _read_bounded(self, response: http.client.HTTPResponse, connection: http.client.HTTPConnection,
                      started: float, *, transcript: _TranscriptExchange | None = None) -> bytes:
        chunks = bytearray()
        try:
            while True:
                remaining = self.policy.deadline_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("broker response deadline exceeded")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                part = response.read1(min(_CHUNK_BYTES, self.policy.max_response_bytes - len(chunks) + 1))
                if not part:
                    return bytes(chunks)
                if transcript is not None:
                    transcript.write_upstream_response(part)
                chunks.extend(part)
                if len(chunks) > self.policy.max_response_bytes:
                    raise BrokerError("broker response exceeds the configured limit")
        except (OSError, http.client.HTTPException, TimeoutError, BrokerError) as exc:
            raise BrokerError("upstream request failed or exceeded its limit") from exc

    def serve_socket(self, channel: socket.socket) -> None:
        """Serve framed requests until the namespace closes its socketpair end."""
        try:
            while True:
                try:
                    request_data = _recv_frame(channel, _MAX_FRAME_BYTES)
                except EOFError:
                    return
                try:
                    request = _decode_json(request_data)
                    if not isinstance(request, dict) or set(request) != {"method", "path", "body"}:
                        raise BrokerError("invalid broker request envelope")
                    method, path, encoded_body = request["method"], request["path"], request["body"]
                    if not isinstance(method, str) or not isinstance(path, str) or not isinstance(encoded_body, str):
                        raise BrokerError("invalid broker request envelope")
                    body = base64.b64decode(encoded_body, validate=True)
                    if len(body) > self.policy.max_request_bytes:
                        raise BrokerError("request body exceeds the configured limit")
                except (BrokerError, ValueError, TypeError, KeyError, EOFError):
                    data = _error_body("broker request rejected")
                    _send_frame(channel, _compact_json({"status": 400, "content_type": "application/json", "model_id": None}))
                    channel.sendall(struct.pack("!I", len(data)) + data + struct.pack("!I", 0))
                    continue
                started = time.monotonic()
                with self._events_lock:
                    event_index = len(self._events)
                exchange: _TranscriptExchange | None = None
                if self._transcript is not None:
                    try:
                        exchange = self._transcript.begin(method, path, body)
                    except (OSError, BrokerError):
                        data = _error_body("trusted transcript could not record this request")
                        _send_frame(channel, _compact_json({"status": 507, "content_type": "application/json", "model_id": None}))
                        channel.sendall(struct.pack("!I", len(data)) + data + struct.pack("!I", 0))
                        continue
                try:
                    status, content_type, chunks, model_id, _ = self.handle(
                        method, path, body, _transcript=exchange,
                    )
                    _send_frame(channel, _compact_json({"status": status, "content_type": content_type, "model_id": model_id}))
                except (BrokerError, ValueError, TypeError, KeyError, OSError, http.client.HTTPException):
                    data = _error_body("broker request rejected")
                    _send_frame(channel, _compact_json({"status": 502, "content_type": "application/json", "model_id": None}))
                    channel.sendall(struct.pack("!I", len(data)) + data + struct.pack("!I", 0))
                    if exchange is not None:
                        try:
                            exchange.write_response(data)
                            exchange.finish(status=502, content_type="application/json", model_id=None,
                                            outcome="broker_error", error="request_rejected")
                        except (OSError, BrokerError):
                            pass
                    continue
                try:
                    response_size = 0
                    for chunk in chunks:
                        if not chunk:
                            continue
                        response_size += len(chunk)
                        if response_size > self.policy.max_response_bytes:
                            raise BrokerError("response exceeds the configured limit")
                        if exchange is not None:
                            exchange.write_response(chunk)
                        for offset in range(0, len(chunk), _CHUNK_BYTES):
                            part = chunk[offset:offset + _CHUNK_BYTES]
                            channel.sendall(struct.pack("!I", len(part)) + part)
                    channel.sendall(struct.pack("!I", 0))
                    event = self.events[event_index] if event_index < len(self.events) else None
                    self._update_response_event(event_index, response_size, time.monotonic() - started, exchange)
                    if exchange is not None:
                        exchange.finish(
                            status=status,
                            content_type=content_type,
                            model_id=model_id,
                            outcome=event.outcome if event is not None else "allowed",
                        )
                    if event is not None and event.outcome == "request_budget":
                        return
                except (BrokerError, BrokenPipeError, ConnectionError, OSError, TimeoutError) as exc:
                    if exchange is not None:
                        try:
                            event = self.events[event_index] if event_index < len(self.events) else None
                            exchange.finish(
                                status=status,
                                content_type=content_type,
                                model_id=model_id,
                                outcome=event.outcome if event is not None else "broker_error",
                                error=type(exc).__name__,
                            )
                        except (OSError, BrokerError):
                            pass
                    return
        except (EOFError, OSError):
            return
        finally:
            self.close()

    def _update_response_event(self, index: int, size: int, elapsed: float,
                               exchange: _TranscriptExchange | None = None) -> None:
        with self._events_lock:
            if 0 <= index < len(self._events):
                event = self._events[index]
                self._events[index] = BrokerEvent(
                    event.method, event.path, event.status, event.model_id,
                    event.request_bytes, size, max(event.elapsed_seconds, elapsed), event.outcome,
                    event.request_started_utc, datetime.now(timezone.utc).isoformat(),
                    None if exchange is None else exchange._elapsed(exchange.upstream_first_byte),
                    None if exchange is None else exchange._elapsed(exchange.first_chunk),
                )


class LoopbackAdapter:
    """HTTP listener placed inside the network namespace and bound only to loopback."""

    def __init__(self, client: BrokerChannelClient, policy: BrokerPolicy):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *args: Any) -> None:
                return

            def _send_error(self, status: int, message: str) -> None:
                data = _error_body(message)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _serve(self) -> None:
                host = self.headers.get("Host", "")
                if host not in {f"127.0.0.1:{policy.adapter_port}", "127.0.0.1", "localhost"}:
                    self._send_error(400, "invalid host header")
                    return
                if self.headers.get_all("Transfer-Encoding"):
                    self._send_error(400, "transfer encoding is not accepted")
                    return
                lengths = self.headers.get_all("Content-Length") or []
                if len(lengths) > 1:
                    self._send_error(400, "duplicate content length")
                    return
                try:
                    content_length = int(lengths[0]) if lengths else 0
                except ValueError:
                    self._send_error(400, "invalid content length")
                    return
                if content_length < 0 or content_length > policy.max_request_bytes:
                    self._send_error(413, "request body exceeds the configured limit")
                    return
                if self.command == "GET" and content_length:
                    self._send_error(400, "GET requests cannot include a body")
                    return
                if self.command == "POST":
                    content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if content_type != "application/json":
                        self._send_error(415, "content type must be application/json")
                        return
                if (self.command, self.path) not in {
                    ("GET", "/v1/models"),
                    ("POST", "/v1/chat/completions"),
                }:
                    self._send_error(404, "route is not allowed")
                    return
                try:
                    body = self.rfile.read(content_length) if content_length else b""
                    if len(body) != content_length:
                        self._send_error(400, "incomplete request body")
                        return
                    response = client.request(self.command, self.path, body)
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.content_type)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        for chunk in response.chunks:
                            self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii"))
                            self.wfile.write(chunk)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                    finally:
                        try:
                            self.wfile.write(b"0\r\n\r\n")
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                        self.close_connection = True
                except (BrokerError, EOFError, OSError, ConnectionError):
                    self.close_connection = True

            def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
                self._serve()

            def do_POST(self) -> None:  # noqa: N802 - HTTP handler API
                self._serve()

            def do_PUT(self) -> None:  # noqa: N802
                self._send_error(404, "method is not allowed")

            def do_DELETE(self) -> None:  # noqa: N802
                self._send_error(404, "method is not allowed")

            def do_PATCH(self) -> None:  # noqa: N802
                self._send_error(404, "method is not allowed")

        class Server(HTTPServer):
            request_queue_size = 8

        self._server = Server(("127.0.0.1", policy.adapter_port), Handler)
        self._server.timeout = 0.25

    def serve_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self._server.handle_request()

    def close(self) -> None:
        self._server.server_close()
