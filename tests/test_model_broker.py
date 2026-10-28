from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
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


def test_loopback_http_server_module_is_imported_before_namespace_chroot():
    module_root = Path(__file__).resolve().parents[1] / "benchmark"
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(module_root)!r}); "
        "import model_broker, sandbox_bootstrap; "
        "assert 'http.server' in sys.modules; "
        "assert 'encodings.idna' in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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


def test_model_specific_sampler_is_frozen_and_forwarded(fake_endpoint: int) -> None:
    generation = {
        "temperature": 1.0,
        "top_p": 0.95,
        "min_p": 0.0,
        "seed": 1234,
        "max_tokens": 32,
    }
    broker = ModelBroker(policy(fake_endpoint, frozen_generation=generation))
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "fixture prompt"}],
        "temperature": 1,
        "top_p": 0.95,
        "min_p": 0,
    }).encode()

    status, _content_type, _response = through_channel(broker, "POST", "/v1/chat/completions", body)

    assert status == 200
    forwarded = json.loads(FakeModelHandler.requests[0][1])
    assert {key: forwarded[key] for key in generation} == generation


def test_model_specific_sampler_overrides_are_rejected(fake_endpoint: int) -> None:
    generation = {"temperature": 1.0, "top_p": 0.95, "min_p": 0.0,
                  "seed": 1234, "max_tokens": 32}
    broker = ModelBroker(policy(fake_endpoint, frozen_generation=generation))
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "fixture prompt"}],
        "temperature": 0.0,
    }).encode()

    status, _content_type, _response = through_channel(broker, "POST", "/v1/chat/completions", body)

    assert status == 400
    assert FakeModelHandler.requests == []


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


def test_sse_chunks_are_forwarded_and_transcribed_with_full_stream_timing(
    fake_endpoint: int, tmp_path,
) -> None:
    transcript_dir = tmp_path / "trusted-transcript"
    transcript_dir.mkdir(mode=0o700)
    transcript_dir.chmod(0o700)
    broker = ModelBroker(policy(fake_endpoint), transcript_dir=transcript_dir)
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
    assert broker.events[0].completed_utc is not None
    assert broker.events[0].upstream_first_response_byte_seconds is not None
    assert broker.events[0].first_response_chunk_seconds is not None
    evidence = broker.transcript_evidence
    assert evidence["complete"] is True
    assert evidence["completed_requests"] == 1
    record = json.loads((transcript_dir / "transcript.jsonl").read_text(encoding="utf-8"))
    assert record["upstream_status"] == 200
    assert record["request_to_upstream_first_response_byte_seconds"] is not None
    assert record["response_duration_seconds"] >= 0.05
    recorded_response = (transcript_dir / record["files"]["upstream_response"]["name"]).read_bytes()
    assert recorded_response == response
    client_request = (transcript_dir / record["files"]["client_request"]["name"]).read_bytes()
    upstream_request = (transcript_dir / record["files"]["upstream_request"]["name"]).read_bytes()
    assert json.loads(client_request)["messages"][0]["content"] == "fixture prompt"
    assert json.loads(upstream_request)["max_tokens"] == 32
    assert b"Authorization" not in (transcript_dir / "transcript.jsonl").read_bytes()


def test_transcript_close_releases_directory_and_incomplete_exchange_fds(tmp_path) -> None:
    transcript_dir = tmp_path / "incomplete-transcript"
    transcript_dir.mkdir(mode=0o700)
    transcript_dir.chmod(0o700)
    before = len(os.listdir("/proc/self/fd"))
    broker = ModelBroker(policy(12345), transcript_dir=transcript_dir)
    assert broker._transcript is not None
    broker._transcript.begin("POST", "/v1/chat/completions", b"fixture request")
    assert len(os.listdir("/proc/self/fd")) >= before + 5

    broker.close()
    broker.close()

    assert broker.transcript_evidence["complete"] is False
    assert len(os.listdir("/proc/self/fd")) == before


def test_transcript_initialization_failure_unwinds_open_file_descriptors(tmp_path) -> None:
    transcript_dir = tmp_path / "failed-transcript"
    transcript_dir.mkdir(mode=0o700)
    transcript_dir.chmod(0o700)
    before = len(os.listdir("/proc/self/fd"))
    broker = ModelBroker(policy(12345, max_request_bytes=1), transcript_dir=transcript_dir)
    assert broker._transcript is not None

    with pytest.raises(BrokerError, match="per-file limit"):
        broker._transcript.begin("POST", "/v1/chat/completions", b"too long")
    broker.close()

    assert len(os.listdir("/proc/self/fd")) == before


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


def test_unknown_request_option_names_are_recorded_without_request_content(fake_endpoint: int) -> None:
    broker = ModelBroker(policy(fake_endpoint))
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "fixture"}],
        "vendor_extension": {"private": "do not retain"},
    }).encode()

    status, _content_type, _response = through_channel(
        broker, "POST", "/v1/chat/completions", body
    )

    assert status == 400
    assert broker.events[0].rejected_fields == ("vendor_extension",)


def test_generation_policy_must_match_output_cap() -> None:
    with pytest.raises(BrokerError):
        policy(12345, frozen_generation={"temperature": 0, "seed": 1234, "max_tokens": 16})


def test_explicit_unclassified_native_requests_use_main_budget(fake_endpoint: int) -> None:
    limits = {"main": 2, "wall_seconds": 60.0, "compaction": 1, "title": 1, "metadata": 10}
    broker = ModelBroker(
        policy(
            fake_endpoint,
            request_limits=limits,
            max_requests=4,
            unclassified_request_category="main",
        )
    )
    body = json.dumps({
        "model": "fake-model",
        "messages": [{"role": "user", "content": "native harness request"}],
    }).encode()

    status, _content_type, response = through_channel(
        broker, "POST", "/v1/chat/completions", body
    )

    assert status == 200, response
    assert broker.ledger.snapshot()["used"]["main"] == 1


COMPACTION_SYSTEM = "You are a context summarization agent. Summarize the session."
MAIN_SYSTEM = "You are opencode, the agent behind the terminal."


def _chat_body(system: str) -> bytes:
    return json.dumps({
        "model": "fake-model",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": "fixture"}],
    }).encode()


def _budget_broker(endpoint: int, **overrides: int) -> ModelBroker:
    limits: dict[str, object] = {
        "main": 4, "wall_seconds": 60.0, "compaction": 1, "title": 1, "metadata": 10,
    }
    limits.update(overrides)
    ceiling = int(limits["main"]) + int(limits["title"]) + int(limits["compaction"])
    return ModelBroker(policy(endpoint, request_limits=limits, max_requests=ceiling))


def test_first_terminal_limit_is_a_typed_unretryable_local_error(fake_endpoint) -> None:
    broker = _budget_broker(fake_endpoint)
    body = _chat_body(COMPACTION_SYSTEM)

    assert through_channel(broker, "POST", "/v1/chat/completions", body)[0] == 200
    status, _content_type, response = through_channel(broker, "POST", "/v1/chat/completions", body)

    assert status == 400
    assert json.loads(response)["error"]["message"] == "budget_exhausted:compaction"
    assert broker.terminal_limit == "budget_exhausted:compaction"


def test_after_the_terminal_limit_generation_stops_without_borrowing(fake_endpoint) -> None:
    broker = _budget_broker(fake_endpoint)
    exhausted = _chat_body(COMPACTION_SYSTEM)
    main = _chat_body(MAIN_SYSTEM)

    through_channel(broker, "POST", "/v1/chat/completions", exhausted)   # used = 1/1
    through_channel(broker, "POST", "/v1/chat/completions", exhausted)   # terminal
    before = len(FakeModelHandler.requests)
    for _ in range(2):
        status, _content_type, _response = through_channel(
            broker, "POST", "/v1/chat/completions", main)
        assert status == 400

    assert len(FakeModelHandler.requests) == before == 1
    snapshot = broker.ledger.snapshot()
    assert snapshot["used"] == {"main": 0, "title": 0, "compaction": 1, "metadata": 0}
    assert snapshot["attempted"] == {"main": 2, "title": 0, "compaction": 2, "metadata": 0}
    assert snapshot["ceilings"] == {"main": 4, "title": 1, "compaction": 1, "metadata": 10}
    assert snapshot["limit_reason"] == "compaction"


def test_wall_deadline_is_a_typed_terminal_budget_error(fake_endpoint, monkeypatch) -> None:
    broker = _budget_broker(fake_endpoint)
    ledger_class = type(broker.ledger)
    monkeypatch.setattr(ledger_class, "remaining_seconds", lambda self: 0.0)
    status, _content_type, response = through_channel(
        broker, "POST", "/v1/chat/completions", _chat_body(MAIN_SYSTEM))

    assert status == 400
    assert json.loads(response)["error"]["message"] == "budget_exhausted:wall"
    assert broker.terminal_limit == "budget_exhausted:wall"
    monkeypatch.undo()
    assert through_channel(broker, "POST", "/v1/chat/completions", _chat_body(MAIN_SYSTEM))[0] == 400


def test_metadata_quota_stays_local_and_never_halts_the_episode(fake_endpoint) -> None:
    broker = _budget_broker(fake_endpoint, metadata=1)
    body = _chat_body(MAIN_SYSTEM)

    assert through_channel(broker, "GET", "/v1/models", b"")[0] == 200
    assert through_channel(broker, "GET", "/v1/models", b"")[0] == 429
    assert broker.terminal_limit is None
    assert through_channel(broker, "POST", "/v1/chat/completions", body)[0] == 200


def test_only_the_first_terminal_cause_is_recorded() -> None:
    from benchmark.practical_policy import PolicyLimit
    broker = _budget_broker(12345)

    assert broker._note_terminal_limit(PolicyLimit("metadata")) is False
    assert broker.terminal_limit is None
    assert broker._note_terminal_limit(PolicyLimit("compaction")) is True
    assert broker.terminal_limit == "budget_exhausted:compaction"
    assert broker._note_terminal_limit(PolicyLimit("wall")) is False
    assert broker.terminal_limit == "budget_exhausted:compaction"
