"""Dedicated MCP channel: host-side trusted server, namespace relay, stdio proxy.

Implements the ``Fonte MCP fora da visão do agente`` design section.  The
trusted server (fixtures and private state) runs on the host, one instance per
episode, outside every candidate namespace.  The candidate receives only a
stdio JSON-RPC proxy with no tool catalog, none of the server source, and no
private state file.  Host and namespace share one dedicated socketpair channel
with length-prefix framing; the model broker channel, its HTTP adapter, and its
counters are never reused for MCP.

The proxy forwards only ``initialize``, ``notifications/*``, ``tools/list`` and
``tools/call`` (plus the connectivity ``ping`` probe); every other method is
refused without touching the trusted server.  The host journals every request,
every response, and the final trusted state per episode.  The journal, not the
candidate, is the trusted source for grading.
"""
from __future__ import annotations

import copy
import json
import socket
import struct
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MCP_FRAME_BYTES = 1 * 1024 * 1024

# Registry-required MCP surface.  Everything else is refused on both ends
# without reaching the trusted server.
RELAY_METHODS = frozenset({"initialize", "tools/list", "tools/call", "ping"})
NOTIFICATION_PREFIX = "notifications/"

METHOD_NOT_FOUND = {"code": -32601, "message": "Method not found"}
PARSE_ERROR = {"code": -32700, "message": "Parse error"}
INVALID_REQUEST = {"code": -32600, "message": "Invalid Request"}

JOURNAL_SCHEMA = "practical-mcp-journal-v1"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def same_json(left: Any, right: Any) -> bool:
    """JSON equality keeps schema types (in particular bool versus integer)."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False)


def _stamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recv_exact(channel: socket.socket, size: int) -> bytes:
    parts = bytearray()
    while len(parts) < size:
        chunk = channel.recv(size - len(parts))
        if not chunk:
            if parts:
                raise OSError("mcp frame truncated while reading header or body")
            raise EOFError("mcp channel closed")
        parts.extend(chunk)
    return bytes(parts)


def _frame_send(channel: socket.socket, data: bytes) -> None:
    channel.sendall(struct.pack("!I", len(data)) + data)


def _frame_header(channel: socket.socket) -> int:
    """Read the 4-byte frame header; a clean EOF here is a normal close."""
    try:
        header = _recv_exact(channel, 4)
    except EOFError:
        raise EOFError("mcp channel closed cleanly before a frame header") from None
    (size,) = struct.unpack("!I", header)
    return size


def _frame_body(channel: socket.socket, size: int, maximum: int) -> bytes:
    """Read one frame body; truncation is a channel fault, never a clean close."""
    if size > maximum:
        raise OSError(f"mcp frame of {size} bytes exceeds the {maximum} byte limit")
    if size == 0:
        raise OSError("mcp frame header announces an empty frame")
    try:
        return _recv_exact(channel, size)
    except EOFError:
        raise OSError("mcp frame truncated by a closed channel") from None


def _is_request(message: Any) -> bool:
    """A JSON-RPC message whose answer must be routed back to its sender."""
    if not isinstance(message, dict):
        return False
    ident = message.get("id")
    return isinstance(ident, (str, int)) and not isinstance(ident, bool)


def _trusted_server(task: str):
    """Lazy trusted-server import; namespace copies may only import siblings."""
    try:
        from benchmark.practical_mcp_v2 import Server
    except ModuleNotFoundError:
        from practical_mcp_v2 import Server
    return Server(task=task)


def trusted_calls(journal: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Trusted ``tools/call`` requests with their matching trusted responses.

    Returns ``[{"name", "arguments", "id", "envelope"}...]`` in the exact
    sequence the trusted server observed them, in that episode, in that state.
    Requests pair with the response that immediately follows them, never by
    reusing candidate ids: clients may legitimately repeat an id.
    """
    calls: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for record in journal.get("records", []):
        if not isinstance(record, dict):
            continue
        kind = record.get("kind")
        if kind == "request" and record.get("method") == "tools/call":
            if pending is not None:
                raise ValueError("trusted MCP journal has an unanswered tool call")
            params = record.get("params") if isinstance(record.get("params"), dict) else {}
            arguments = params.get("arguments", {})
            pending = {
                "name": params.get("name"),
                "arguments": arguments if isinstance(arguments, dict) else {},
                "id": record.get("id"),
                "envelope": None,
            }
        elif kind == "response" and pending is not None:
            if record.get("id") != pending["id"]:
                raise ValueError("trusted MCP response id disagrees with its request")
            pending["envelope"] = record.get("envelope")
            calls.append(pending)
            pending = None
    if pending is not None:
        raise ValueError("trusted MCP journal has an unanswered tool call")
    return calls


def validate_journal(journal: Mapping[str, Any], *, task: str | None = None,
                     task_contract_id: str | None = None) -> str | None:
    """Verify the complete host transcript and its actual final server state."""
    if not isinstance(journal, dict) or journal.get('schema') != JOURNAL_SCHEMA:
        return 'trusted MCP journal is missing or unrecognized'
    if journal.get('fault'):
        return f"trusted journal reports a channel fault: {journal['fault']}"
    if journal.get('clean_close') is not True:
        return 'trusted MCP journal did not close cleanly'
    recorded_task = journal.get('task')
    if not isinstance(recorded_task, str) or (task is not None and recorded_task != task):
        return 'trusted MCP journal task disagrees with the episode'
    recorded_contract = journal.get('task_contract_id') or 'historical-v2'
    if task_contract_id is not None and recorded_contract != task_contract_id:
        return 'trusted MCP journal contract disagrees with the episode'
    records = journal.get('records')
    if not isinstance(records, list) or not records:
        return 'trusted MCP journal carries no close record'
    if records[-1].get('kind') != 'journal_close':
        return 'trusted MCP journal is not finalized'
    try:
        server = _trusted_server(recorded_task)
        pending = None
        closed = False
        for sequence, record in enumerate(records, start=1):
            if not isinstance(record, dict) or record.get('seq') != sequence:
                return 'trusted MCP journal sequence is malformed'
            kind = record.get('kind')
            if closed:
                return 'trusted MCP journal contains data after finalization'
            if kind == 'request':
                if pending is not None:
                    return 'trusted MCP journal has an unanswered RPC request'
                method = record.get('method')
                if not isinstance(method, str):
                    return 'trusted MCP journal method is malformed'
                request = {'jsonrpc':'2.0', 'method':method, 'params':record.get('params',{})}
                ident = record.get('id')
                if ident is not None:
                    if not isinstance(ident,(str,int)) or isinstance(ident,bool):
                        return 'trusted MCP journal id is malformed'
                    request['id'] = ident
                elif not method.startswith(NOTIFICATION_PREFIX):
                    return 'trusted MCP journal has an RPC without an id'
                pending = server.respond(copy.deepcopy(request))
            elif kind == 'response':
                if pending is None or not same_json(record.get('envelope'), pending):
                    return 'trusted MCP journal response diverges from server replay'
                if record.get('id') != pending.get('id'):
                    return 'trusted MCP journal response id is inconsistent'
                pending = None
            elif kind == 'journal_close':
                if pending is not None:
                    return 'trusted MCP journal closed with an unanswered RPC request'
                closed = True
            elif kind not in {'channel_close','method_refused','parse_fault'}:
                return 'trusted MCP journal carries an unknown or faulted record'
        if not closed or not isinstance(journal.get('final_state'), dict):
            return 'trusted MCP final state is missing'
        if not same_json(journal['final_state'], server.state):
            return 'trusted MCP final state diverges from server replay'
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return f'trusted MCP journal is invalid: {type(exc).__name__}'
    return None


class McpBridge:
    """Host side of one episode's dedicated MCP channel.

    The bridge owns the trusted ``Server`` and journals each request, each
    response, and the final trusted state.  ``serve_socket`` runs in its own
    thread and exits when the namespace end closes its channel.  Protocol
    faults are journaled; host-side failures additionally set ``fault`` so the
    runtime can classify the episode as infrastructure.
    """

    def __init__(self, task: str, *, journal_path: Path | None = None,
                 contract_id: str | None = None) -> None:
        self.task = str(task)
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.contract_id = contract_id
        self._server = None
        self._records: list[dict[str, Any]] = []
        self._seq = 0
        self._lock = threading.Lock()
        self.fault: str | None = None
        self.closed = False

    def start(self) -> None:
        with self._lock:
            if self._server is None:
                self._server = _trusted_server(self.task)

    def _stamp(self, kind: str, **fields: Any) -> None:
        self._seq += 1
        self._records.append({"seq": self._seq, "ts_utc": _stamp_now(),
                              "kind": kind, **fields})

    def _refusal(self, message: Any, *, parse_fault: bool = False) -> dict[str, Any] | None:
        """Build the refusal envelope without touching the trusted server."""
        if _is_request(message):
            self._stamp("parse_fault" if parse_fault else "method_refused",
                        method=message.get("method"), id=message["id"])
            return {"jsonrpc": "2.0", "id": message["id"],
                    "error": PARSE_ERROR if parse_fault else METHOD_NOT_FOUND}
        method = (message.get("method")
                  if isinstance(message, dict) and isinstance(message.get("method"), str)
                  else repr(message))
        self._stamp("parse_fault" if parse_fault else "method_refused", method=method)
        return None

    def dispatch(self, channel: socket.socket, message: Any) -> None:
        """Handle one framed JSON-RPC message; keeps the trusted server's lock."""
        self.start()
        if self.closed:
            raise OSError('MCP service is closed')
        if not isinstance(message, dict) or not isinstance(message.get("method"), str):
            self._send_refusal(channel, self._refusal(message, parse_fault=True))
            return
        method = message["method"]
        if not (method in RELAY_METHODS or method.startswith(NOTIFICATION_PREFIX)):
            self._send_refusal(channel, self._refusal(message))
            return
        with self._lock:
            self._stamp("request", method=method, id=message.get("id"),
                        params=copy.deepcopy(message.get("params", {})))
            response = self._server.respond(copy.deepcopy(message))
            if response is not None:
                self._stamp("response", id=message.get("id"),
                            envelope=copy.deepcopy(response))
        if response is not None:
            try:
                _frame_send(channel, _json_bytes(response))
            except OSError as exc:
                with self._lock:
                    if self.fault is None:
                        self.fault = f"mcp_channel_send_failed:{type(exc).__name__}"
                    self._stamp("fault", reason=self.fault)

    def _send_refusal(self, channel: socket.socket, envelope: dict[str, Any] | None) -> None:
        if envelope is None:
            return
        try:
            _frame_send(channel, _json_bytes(envelope))
        except OSError as exc:
            with self._lock:
                if self.fault is None:
                    self.fault = f"mcp_channel_send_failed:{type(exc).__name__}"
                self._stamp("fault", reason=self.fault)

    def serve_socket(self, channel: socket.socket) -> None:
        """Serve framed JSON-RPC requests until the namespace end closes."""
        try:
            self.start()
            while True:
                try:
                    size = _frame_header(channel)
                    data = _frame_body(channel, size, _MCP_FRAME_BYTES)
                except EOFError:
                    self._stamp("channel_close")
                    return
                except OSError as exc:
                    with self._lock:
                        self.fault = self.fault or f"mcp_channel_error:{exc}"[:160]
                        self._stamp("fault", reason=self.fault)
                    return
                try:
                    message = json.loads(data)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.dispatch(channel, None)
                    continue
                self.dispatch(channel, message)
        except Exception as exc:  # never crash the supervisor thread silently
            with self._lock:
                if self.fault is None:
                    self.fault = f"mcp_server_error:{type(exc).__name__}"
                self._stamp("fault", reason=self.fault)

    def close(self, *, reason: str | None = None) -> dict[str, Any]:
        """Finalize the journal with the trusted end state (never the candidate's)."""
        with self._lock:
            if reason and self.fault is None:
                self.fault = reason
                self._stamp("fault", reason=reason)
            if not self.closed:
                self.closed = True
                self._stamp("journal_close")
            final_state = None if self._server is None else copy.deepcopy(self._server.state)
            journal = {
                "schema": JOURNAL_SCHEMA,
                "task": self.task,
                "task_contract_id": self.contract_id,
                "clean_close": self.fault is None,
                "fault": self.fault,
                "final_state": final_state,
                "records": copy.deepcopy(self._records),
            }
            if self.journal_path is not None:
                payload = json.dumps(journal, ensure_ascii=False, allow_nan=False)
                try:
                    self.journal_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.journal_path.with_name(self.journal_path.name + ".tmp")
                    temporary.write_text(payload, encoding="utf-8")
                    temporary.replace(self.journal_path)
                except OSError as first:
                    # The journal is the trusted record: a failed write must be
                    # visible, never silently weakened or lost. This close
                    # already holds the lock, so it stamps without re-acquiring.
                    self.fault = self.fault or f"mcp_journal_write_failed:{type(first).__name__}"
                    self._stamp("fault", reason=self.fault)
                    journal = {
                        "schema": JOURNAL_SCHEMA,
                        "task": self.task,
                        "task_contract_id": self.contract_id,
                        "clean_close": False,
                        "fault": self.fault,
                        "final_state": final_state,
                        "records": self._records,
                    }
                    try:
                        self.journal_path.write_text(
                            json.dumps(journal, ensure_ascii=False, allow_nan=False),
                            encoding="utf-8")
                    except OSError as second:
                        self.fault = self.fault or f"mcp_journal_write_failed:{type(second).__name__}"
                        journal["fault"] = self.fault
            return journal

    def journal(self) -> dict[str, Any]:
        return self.close()


class NamespaceRelay:
    """In-namespace loopback listener forwarding signals to the host channel.

    The relay accepts newline-delimited JSON from candidate-side clients (the
    stdio proxy), forwards every accepted message as one framed request through
    the dedicated socketpair, and routes exactly one framed response back to
    the same connection.  It listens on ``127.0.0.1`` only: no external
    network, no additional processes, and nothing survives the episode.
    """

    def __init__(self, channel: socket.socket, port: int, *,
                 max_line_bytes: int = _MCP_FRAME_BYTES):
        import socketserver

        self._channel = channel
        self._max = int(max_line_bytes)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connections = 0
        self.refusals = 0
        outer = self

        class _Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

            def process_request(self, request: socket.socket, address) -> None:
                outer.connections += 1
                outer._serve_connection(request)

            def handle_error(self, _request, _client_address) -> None:
                pass

        self._server = _Server(("127.0.0.1", int(port)), self._unsupported_handler)
        self.port = int(self._server.server_address[1])

    @staticmethod
    def _unsupported_handler(*args, **kwargs):  # never invoked: process_request overrides
        return None

    def _serve_connection(self, sock: socket.socket) -> None:
        try:
            stream = sock.makefile("rb")
            try:
                while not self._stop.is_set():
                    line = stream.readline(self._max + 2)
                    if not line:
                        return
                    if len(line) > self._max or not line.endswith(b"\n"):
                        self._error_line(sock, None, PARSE_ERROR)
                        return
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        self._error_line(sock, None, PARSE_ERROR)
                        continue
                    if not isinstance(message, dict):
                        self._error_line(sock, None, INVALID_REQUEST)
                        continue
                    method = message.get("method")
                    if not isinstance(method, str) or not (
                            method in RELAY_METHODS or method.startswith(NOTIFICATION_PREFIX)):
                        self.refusals += 1
                        self._error_line(sock, message.get("id"), METHOD_NOT_FOUND)
                        continue
                    with self._lock:
                        _frame_send(self._channel, line.rstrip(b"\r\n"))
                        if _is_request(message):
                            sock.sendall(_frame_body(
                                self._channel, _frame_header(self._channel),
                                self._max) + b"\n")
            finally:
                stream.close()
        except (OSError, EOFError, struct.error):
            return

    @staticmethod
    def _error_line(sock: socket.socket, ident: Any, error: Mapping[str, Any]) -> None:
        if isinstance(ident, bool) or not isinstance(ident, (str, int)):
            ident = None
        payload = _json_bytes({"jsonrpc": "2.0", "id": ident, "error": dict(error)})
        try:
            sock.sendall(payload + b"\n")
        except OSError:
            pass

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.05)

    def close(self) -> None:
        self._stop.set()
        try:
            self._server.shutdown()
        except OSError:
            pass
        self._server.server_close()


def run_proxy(host: str, port: int) -> int:
    """Candidate-side stdio JSON-RPC proxy: no catalog, no state, no fixtures.

    Reads newline-delimited JSON-RPC on stdin, forwards every allowed message
    to the loopback relay, writes one response line per request onto stdout,
    and refuses every other method locally without any forwarding.
    """
    channel: socket.socket | None = None

    def connect() -> socket.socket:
        target = socket.create_connection((host, int(port)), timeout=60)
        target.settimeout(90)
        return target

    def _std_error(ident: Any, error: Mapping[str, Any]) -> None:
        sys.stdout.buffer.write(_json_bytes(
            {"jsonrpc": "2.0", "id": ident, "error": dict(error)}) + b"\n")
        sys.stdout.buffer.flush()

    for raw in sys.stdin.buffer:
        line = raw.rstrip(b"\r\n")
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            _std_error(None, PARSE_ERROR)
            continue
        method = message.get("method") if isinstance(message, dict) else None
        if not isinstance(method, str) or not (
                method in RELAY_METHODS or method.startswith(NOTIFICATION_PREFIX)):
            ident = message.get("id") if isinstance(message, dict) else None
            _std_error(ident, METHOD_NOT_FOUND)
            continue
        if channel is None:
            try:
                channel = connect()
            except OSError as exc:
                _std_error(message.get("id"),
                           {"code": -32001, "message": f"relay unavailable: {exc}"})
                continue
        try:
            channel.sendall(line + b"\n")
            if _is_request(message):
                response = bytearray()
                while b"\n" not in response:
                    chunk = channel.recv(65536)
                    if not chunk:
                        raise ConnectionError("relay closed")
                    response.extend(chunk)
                    if len(response) > _MCP_FRAME_BYTES:
                        raise ConnectionError("response exceeds the relay limit")
                sys.stdout.buffer.write(bytes(response))
                sys.stdout.buffer.flush()
        except (OSError, ConnectionError, struct.error) as exc:
            try:
                channel.close()
            except OSError:
                pass
            channel = None
            if _is_request(message):
                _std_error(message.get("id"),
                           {"code": -32001,
                            "message": f"relay failure: {type(exc).__name__}"})
    if channel is not None:
        try:
            channel.close()
        except OSError:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 3 and arguments[0] == "--proxy":
        return run_proxy(arguments[1], int(arguments[2]))
    raise SystemExit("usage: practical_mcp_bridge.py --proxy HOST PORT")


if __name__ == "__main__":
    raise SystemExit(main())
