"""Bounded stdio-to-loopback relay for the trusted per-episode MCP bridge."""

from __future__ import annotations

import json
import socket
import sys

MAX_LINE = 4 * 1024 * 1024
METHODS = {
    "initialize",
    "notifications/initialized",
    "notifications/cancelled",
    "ping",
    "tools/list",
    "tools/call",
}


def main():
    if len(sys.argv) != 2:
        return 64
    try:
        port = int(sys.argv[1])
    except ValueError:
        return 64
    if not 1 <= port <= 65535:
        return 64
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    except OSError as exc:
        print("episode MCP bridge unavailable: " + type(exc).__name__, file=sys.stderr)
        return 75
    try:
        sock.settimeout(240)
        reader = sock.makefile("rb")
        for raw in sys.stdin.buffer:
            if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                print("invalid/oversized MCP JSON-RPC line", file=sys.stderr)
                return 65
            try:
                request = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                print("invalid MCP JSON-RPC JSON", file=sys.stderr)
                return 65
            if not isinstance(request, dict) or not isinstance(
                request.get("method"), str
            ):
                print("invalid MCP JSON-RPC envelope", file=sys.stderr)
                return 65
            method = request["method"]
            if method not in METHODS and not method.startswith("notifications/"):
                print("MCP method refused by episode policy", file=sys.stderr)
                return 77
            sock.sendall(raw)
            if "id" not in request:
                continue
            response = reader.readline(MAX_LINE + 2)
            if not response or len(response) > MAX_LINE or not response.endswith(b"\n"):
                print("MCP bridge returned incomplete framed response", file=sys.stderr)
                return 75
            try:
                parsed = json.loads(response)
            except ValueError:
                print("MCP bridge returned invalid JSON", file=sys.stderr)
                return 75
            if not isinstance(parsed, dict) or parsed.get("id") != request["id"]:
                print("MCP request/response ID mismatch", file=sys.stderr)
                return 75
            sys.stdout.buffer.write(response)
            sys.stdout.buffer.flush()
        return 0
    except (BrokenPipeError, ConnectionError, TimeoutError, OSError):
        return 75
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
