import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from benchmark.qwen_engines import ApiClient, ModelProtocolError, llama_command


def test_llama_command_cannot_silently_reduce_context(tmp_path):
    args = llama_command(tmp_path / "server", tmp_path / "model.gguf", 1234, 32768)
    assert args[args.index("--ctx-size") + 1] == "32768"
    assert args[args.index("--fit") + 1] == "off"
    assert args[args.index("--parallel") + 1] == "1"
    assert args[args.index("--cache-reuse") + 1] == "0"
    enabled = llama_command(tmp_path / "server", tmp_path / "model", 1234, 16384, cache_reuse=256)
    assert enabled[enabled.index("--cache-reuse") + 1] == "256"


def test_stream_records_actual_usage_and_counts_failed_calls(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["model"] == "local-qwen"
            assert request["cache_prompt"] is False
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for row in [
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}}]},
                {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 1}},
            ]:
                self.wfile.write(("data: " + json.dumps(row) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ApiClient(server.server_port, tmp_path, generation={}, max_calls=1)
        result = client.chat([{"role": "user", "content": "test"}])
        assert result["usage"]["prompt_tokens"] == 8
        assert result["choices"][0]["message"]["content"] == "ok"
        assert client.calls == 1
        assert (tmp_path / "request-0001.json").exists()
        with pytest.raises(ModelProtocolError, match="budget"):
            client.chat([{"role": "user", "content": "again"}])
    finally:
        server.shutdown()


def test_invalid_model_port_cannot_be_remote(tmp_path):
    with pytest.raises(ValueError):
        ApiClient("https://external.example", tmp_path)


def test_cache_prompt_is_explicit_and_timings_are_recorded(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["cache_prompt"] is True
            self.send_response(200)
            self.end_headers()
            event = {"choices": [], "timings": {"prompt_n": 9, "cache_n": 42}}
            self.wfile.write(("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = ApiClient(server.server_port, tmp_path, cache_prompt=True)
        client.chat([{"role": "user", "content": "test"}])
        assert client.metrics[0]["timings"] == {"prompt_n": 9, "cache_n": 42}
    finally:
        server.shutdown()
