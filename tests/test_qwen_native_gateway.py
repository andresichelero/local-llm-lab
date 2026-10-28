import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


from benchmark.qwen_native_gateway import NativeGateway


class Model:
    def __init__(self):
        self.requests = []

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                result = {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "local answer"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 3,
                        "total_tokens": 10,
                    },
                }
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                raw = b'{"data":[{"id":"local-qwen"}]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def request(port, path, value):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST",
        path,
        json.dumps(value).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    response = conn.getresponse()
    payload = response.read()
    ctype = response.getheader("Content-Type")
    conn.close()
    return response.status, payload, ctype


def test_gateway_forces_recorded_profile_and_fails_closed_on_external_route():
    with Model() as model:
        with NativeGateway(
            model.server.server_address[1],
            "local-qwen",
            8192,
            generation={
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0,
                "presence_penalty": 0,
                "max_tokens": 8192,
            },
            aliases=["openai/local-qwen"],
        ) as gateway:
            status, body, ctype = request(
                gateway.port,
                "/v1/chat/completions",
                {
                    "model": "openai/local-qwen",
                    "messages": [{"role": "user", "content": "x"}],
                    "temperature": 0,
                    "stream": False,
                },
            )
            assert (
                status == 200
                and json.loads(body)["choices"][0]["message"]["content"]
                == "local answer"
            )
            assert model.requests[0]["model"] == "local-qwen"
            assert model.requests[0]["temperature"] == 0.6
            assert gateway.adapter_overrides[0]["fields_changed"] == ["temperature"]
            status, body, ctype = request(
                gateway.port,
                "/v1/chat/completions",
                {"model": "remote/gpt", "messages": []},
            )
            assert status == 400
            conn = http.client.HTTPConnection("127.0.0.1", gateway.port, timeout=5)
            conn.request("POST", "/remote", b"{}", {"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            assert resp.status == 404


def test_gateway_drops_stream_options_when_it_forces_nonstream_responses():
    with Model() as model:
        with NativeGateway(
            model.server.server_address[1],
            "local-qwen",
            8192,
            generation={
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0,
                "presence_penalty": 0,
                "max_tokens": 8192,
            },
        ) as gateway:
            status, body, _ = request(
                gateway.port,
                "/v1/chat/completions",
                {
                    "model": "local-qwen",
                    "messages": [{"role": "user", "content": "x"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            )

            assert status == 200, body
            assert model.requests[0]["stream"] is False
            assert "stream_options" not in model.requests[0]
            assert "stream_options" in gateway.adapter_overrides[0]["fields_changed"]


def test_gateway_hashes_and_drops_native_vendor_metadata():
    with Model() as model:
        with NativeGateway(
            model.server.server_address[1],
            "local-qwen",
            8192,
            generation={
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0,
                "presence_penalty": 0,
                "max_tokens": 8192,
            },
        ) as gateway:
            status, body, _ = request(
                gateway.port,
                "/v1/messages",
                {
                    "model": "local-qwen",
                    "max_tokens": 8192,
                    "messages": [{"role": "user", "content": "x"}],
                    "context_management": [],
                    "output_config": {"effort": "high"},
                },
            )

            assert status == 200, body
            assert model.requests[0]["messages"][-1]["content"] == "x"
            assert "context_management" not in model.requests[0]
            assert "output_config" not in model.requests[0]
            assert {"context_management", "output_config"} <= set(
                gateway.adapter_overrides[0]["fields_changed"]
            )


def test_gateway_normalizes_chat_sampler_alias_and_storage_metadata():
    with Model() as model:
        with NativeGateway(
            model.server.server_address[1],
            "local-qwen",
            8192,
            generation={
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0,
                "presence_penalty": 0,
                "max_tokens": 8192,
            },
        ) as gateway:
            status, body, _ = request(
                gateway.port,
                "/v1/chat/completions",
                {
                    "model": "local-qwen",
                    "messages": [{"role": "user", "content": "x"}],
                    "topP": 0.25,
                    "store": False,
                },
            )

            assert status == 200, body
            assert model.requests[0]["top_p"] == 0.95
            assert "store" not in model.requests[0]
            assert "topP" not in model.requests[0]
            assert {"store", "topP"} <= set(
                gateway.adapter_overrides[0]["fields_changed"]
            )


def test_gateway_preserves_responses_previous_turn_with_local_call_id():
    with Model() as model:
        with NativeGateway(
            model.server.server_address[1],
            "local-qwen",
            8192,
            generation={
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0,
                "presence_penalty": 0,
                "max_tokens": 8192,
            },
        ) as gateway:
            status, body, _ = request(
                gateway.port, "/v1/responses", {"model": "local-qwen", "input": "first"}
            )
            previous = json.loads(body)
            status, body, _ = request(
                gateway.port,
                "/v1/responses",
                {
                    "model": "local-qwen",
                    "previous_response_id": previous["id"],
                    "input": [{"type": "message", "role": "user", "content": "second"}],
                },
            )
            assert status == 200
            assert model.requests[1]["messages"][0]["content"] == "first"
            assert model.requests[1]["messages"][-1]["content"] == "second"
