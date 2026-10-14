from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from benchmark.model_broker import (
    BrokerChannelClient,
    BrokerError,
    BrokerPolicy,
    ModelBroker,
)


class FakeModelHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, bytes, dict[str, str]]] = []
    body = b'{"id":"fake-result","choices":[{"message":{"content":"fake-only"}}]}'

    def log_message(self, _format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        body = b'{"object":"list","data":[{"id":"fake-model"},{"id":"unlisted-model"}]}'
        type(self).requests.append((self.command, b"", dict(self.headers.items())))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests.append((self.command, body, dict(self.headers.items())))
        if json.loads(body).get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[]}\n\n')
            self.wfile.flush()
            time.sleep(0.06)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)


@pytest.fixture
def fake_endpoint():
    FakeModelHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), FakeModelHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def policy(port: int, **overrides: object) -> BrokerPolicy:
    values: dict[str, object] = {
        "upstream_port": port,
        "model_allowlist": ("fake-model",),
        "output_token_cap": 32,
        "frozen_generation": {"temperature": 0, "seed": 1234, "max_tokens": 32},
        "adapter_port": 18888,
    }
    values.update(overrides)
    return BrokerPolicy(**values)  # type: ignore[arg-type]


def through_channel(broker: ModelBroker, method: str, path: str, body: bytes) -> tuple[int, str, bytes]:
    host, client_sock = socket.socketpair()
    thread = threading.Thread(target=broker.serve_socket, args=(host,), daemon=True)
    thread.start()
    try:
        response = BrokerChannelClient(client_sock, max_request_bytes=broker.policy.max_request_bytes).request(
            method, path, body,
        )
        return response.status, response.content_type, b"".join(response.chunks)
    finally:
        client_sock.close()
        thread.join(timeout=2)


def test_only_allowlisted_frozen_request_reaches_fake_endpoint(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "fixture prompt"}],
    }).encode()

    status, content_type, response = through_channel(broker, "POST", "/v1/chat/completions", body)

    assert status == 200
    assert content_type == "application/json"
    assert b"fake-only" in response
    assert len(FakeModelHandler.requests) == 1
    method, forwarded_bytes, headers = FakeModelHandler.requests[0]
    forwarded = json.loads(forwarded_bytes)
    assert method == "POST"
    assert forwarded["model"] == "fake-model"
    assert forwarded["temperature"] == 0
    assert forwarded["seed"] == 1234
    assert forwarded["max_tokens"] == 32
    assert "Authorization" not in headers
    assert broker.events[0].response_bytes == len(FakeModelHandler.body)
    assert broker.events[0].elapsed_seconds >= 0


def test_model_and_generation_overrides_fail_before_upstream(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    rejected_model = json.dumps({
        "model": "not-allowed",
        "messages": [{"role": "user", "content": "x"}],
    }).encode()
    rejected_tokens = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 33,
    }).encode()

    assert through_channel(broker, "POST", "/v1/chat/completions", rejected_model)[0] == 403
    assert through_channel(broker, "POST", "/v1/chat/completions", rejected_tokens)[0] == 400
    assert FakeModelHandler.requests == []


def test_model_list_is_filtered_to_allowlist(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    status, _content_type, response = through_channel(broker, "GET", "/v1/models", b"")

    assert status == 200
    assert [item["id"] for item in json.loads(response)["data"]] == ["fake-model"]


def test_sse_chunks_are_forwarded_with_full_stream_timing(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "fixture prompt"}],
        "stream": True,
    }).encode()

    status, content_type, response = through_channel(broker, "POST", "/v1/chat/completions", body)

    assert status == 200
    assert content_type == "text/event-stream"
    assert b"data: [DONE]" in response
    assert broker.events[0].response_bytes == len(response)
    assert broker.events[0].elapsed_seconds >= 0.05


def test_unlisted_routes_and_unknown_generation_fields_are_rejected(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    assert broker.handle("GET", "/v1/anything", b"")[0] == 404
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "x"}],
        "max_completion_tokens": 999999,
    }).encode()
    assert broker.handle("POST", "/v1/chat/completions", body)[0] == 400
    assert FakeModelHandler.requests == []


def test_generation_policy_must_match_output_cap() -> None:
    with pytest.raises(BrokerError):
        policy(12345, frozen_generation={"temperature": 0, "seed": 1234, "max_tokens": 16})
