import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "benchmark/qwen_native_mcp.py"


def test_stdio_mcp_proxy_only_forwards_one_bounded_jsonrpc_channel():
    seen = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for raw in self.rfile:
                item = json.loads(raw)
                seen.append(item)
                if "id" in item:
                    self.wfile.write(
                        (
                            json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": item["id"],
                                    "result": {"tools": []},
                                }
                            )
                            + "\n"
                        ).encode()
                    )

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = (
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                ),
            ]
        )
        + "\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(server.server_address[1])],
            input=request,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": []},
    }
    assert [row["method"] for row in seen] == [
        "tools/list",
        "notifications/initialized",
    ]


def test_stdio_mcp_proxy_refuses_methods_outside_the_episode_tool_contract():
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(server.server_address[1])],
            input=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "sampling/createMessage"}
            )
            + "\n",
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 77
    assert result.stdout == ""
