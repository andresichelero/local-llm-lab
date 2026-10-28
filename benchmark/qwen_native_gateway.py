"""Local-only Responses/Anthropic wire shim to the audited chat-only broker.

The shim binds to private loopback, accepts no provider keys or external
hostnames, and sends exactly one translated Chat request through the existing
model broker for each client generation request.
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import threading
from urllib.parse import urlsplit

try:
    from benchmark.qwen_native_protocols import (
        ProtocolError,
        anthropic_sse,
        anthropic_to_chat,
        chat_sse,
        chat_to_anthropic,
        chat_to_responses,
        responses_sse,
        responses_to_chat,
    )
except ImportError:
    from qwen_native_protocols import (
        ProtocolError,
        anthropic_sse,
        anthropic_to_chat,
        chat_sse,
        chat_to_anthropic,
        chat_to_responses,
        responses_sse,
        responses_to_chat,
    )


class NativeGateway:
    def __init__(
        self,
        broker_port: int,
        model_alias: str,
        output_cap: int,
        *,
        port: int = 0,
        generation=None,
        aliases=(),
    ):
        if type(broker_port) is not int or not 1 <= broker_port <= 65535:
            raise ValueError("broker port must be an explicit loopback TCP port")
        self.broker_port, self.model_alias, self.output_cap = (
            broker_port,
            model_alias,
            output_cap,
        )
        self.model_aliases = set(aliases) | {
            model_alias,
            "qwen-local",
            "openai/" + model_alias,
            "local/" + model_alias,
            "ollama/" + model_alias,
        }
        self.previous = {}
        self.calls = 0
        self.generations = 0
        self.tool_calls = 0
        self.tool_budget_exhausted = False
        self.model_budget_exhausted = False
        self.profile = dict(
            generation
            or {
                "temperature": 0.6,
                "top_p": 0.95,
                "min_p": 0.0,
                "presence_penalty": 0.0,
                "max_tokens": output_cap,
            }
        )
        self.adapter_overrides = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def _reply(self, status, value, ctype="application/json"):
                raw = (
                    value
                    if isinstance(value, bytes)
                    else json.dumps(value, separators=(",", ":")).encode()
                )
                if len(raw) > 32 * 1024**2:
                    status, raw, ctype = (
                        502,
                        b"upstream response exceeded gateway size limit",
                        "text/plain",
                    )
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                if self.headers.get("Origin"):
                    raise ProtocolError("browser-origin requests are not accepted")
                if (
                    self.headers.get("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length") or []) > 1
                ):
                    raise ProtocolError("invalid request framing")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 2 * 1024**2:
                    raise ProtocolError("request exceeds gateway size limit")
                if (
                    not self.headers.get("Content-Type", "")
                    .lower()
                    .startswith("application/json")
                ):
                    raise ProtocolError("content type must be JSON")
                return json.loads(self.rfile.read(length))

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/health" and not parsed.query:
                    return self._reply(200, {"status": "ok"})
                if parsed.path != "/v1/models" or parsed.query:
                    return self._reply(
                        404, {"error": "native gateway route is unavailable"}
                    )
                conn = http.client.HTTPConnection(
                    "127.0.0.1", owner.broker_port, timeout=20
                )
                try:
                    conn.request("GET", "/v1/models")
                    res = conn.getresponse()
                    data = json.loads(res.read(1024 * 1024))
                    self._reply(res.status, data)
                except Exception as exc:
                    self._reply(
                        502, {"error": f"{type(exc).__name__}: {str(exc)[:250]}"}
                    )
                finally:
                    conn.close()

            def do_POST(self):
                path = urlsplit(self.path).path
                try:
                    body = owner._body(self)
                    if not isinstance(body, dict):
                        raise ProtocolError("request body must be a JSON object")
                    native_metadata = {}
                    stream = bool(body.get("stream", False))
                    if path == "/v1/responses":
                        if body.get("model") not in (None, *owner.model_aliases):
                            raise ProtocolError(
                                "Responses model alias is not the pinned local Qwen"
                            )
                        previous_id = body.get("previous_response_id")
                        prior = owner.previous.get(previous_id) if previous_id else None
                        if previous_id and prior is None:
                            raise ProtocolError(
                                "previous_response_id is not stored for this task session"
                            )
                        body = dict(body)
                        native_metadata = {
                            key: body[key]
                            for key in ("client_metadata", "prompt_cache_key")
                            if key in body
                        }
                        body["model"] = owner.model_alias
                        chat = responses_to_chat(
                            body,
                            owner.model_alias,
                            owner.output_cap,
                            prior.get("messages") if prior else None,
                            prior.get("output") if prior else None,
                        )
                        native_kind = "responses"
                    elif path == "/v1/messages":
                        if body.get("model") not in (None, *owner.model_aliases):
                            raise ProtocolError(
                                "Anthropic model alias is not the pinned local Qwen"
                            )
                        body = dict(body)
                        native_metadata = {
                            key: body[key]
                            for key in ("context_management", "output_config")
                            if key in body
                        }
                        body["model"] = owner.model_alias
                        chat = anthropic_to_chat(
                            body, owner.model_alias, owner.output_cap
                        )
                        native_kind = "anthropic"
                    elif path == "/v1/chat/completions":
                        if not isinstance(body, dict) or body.get("model") not in (
                            {None} | owner.model_aliases
                        ):
                            raise ProtocolError(
                                "chat model alias is not the pinned local Qwen"
                            )
                        chat = dict(body)
                        chat["model"] = owner.model_alias
                        native_kind = "chat"
                    else:
                        return self._reply(
                            404, {"error": "native gateway route is unavailable"}
                        )
                    if "topP" in chat:
                        native_metadata["topP"] = chat.pop("topP")
                        chat.setdefault("top_p", native_metadata["topP"])
                    if "store" in chat:
                        native_metadata["store"] = chat.pop("store")
                    filtered_tool_names = chat.pop("_filtered_tool_names", [])
                    if filtered_tool_names:
                        native_metadata["filtered_tool_names"] = filtered_tool_names
                    requested = {
                        key: chat.get(key)
                        for key in (
                            "temperature",
                            "top_p",
                            "top_k",
                            "min_p",
                            "presence_penalty",
                            "frequency_penalty",
                            "max_tokens",
                            "max_completion_tokens",
                            "repeat_penalty",
                            "repetition_penalty",
                        )
                        if key in chat
                    }
                    if native_metadata:
                        requested = {
                            "generation": requested,
                            "native_metadata_sha256": hashlib.sha256(
                                json.dumps(
                                    native_metadata,
                                    sort_keys=True,
                                    default=str,
                                ).encode()
                            ).hexdigest(),
                        }
                    changed = sorted(
                        key
                        for key, value in owner.profile.items()
                        if key in chat and chat[key] != value
                    )
                    changed.extend(native_metadata)
                    if "stream_options" in chat:
                        changed.append("stream_options")
                        chat.pop("stream_options", None)
                    if chat.get("stream") is True:
                        changed.append("stream")
                    changed = sorted(set(changed))
                    for key in (
                        "top_k",
                        "repeat_penalty",
                        "repetition_penalty",
                        "frequency_penalty",
                        "enable_thinking",
                        "reasoning_effort",
                        "chat_template_kwargs",
                        "max_completion_tokens",
                    ):
                        chat.pop(key, None)
                    chat.update(owner.profile)
                    chat["model"] = owner.model_alias
                    chat["max_tokens"] = owner.output_cap
                    chat["stream"] = False
                    owner.calls += 1
                    if "messages" in chat:
                        owner.generations += 1
                    owner.adapter_overrides.append(
                        {
                            "call": owner.calls,
                            "fields_changed": changed,
                            "requested_sha256": hashlib.sha256(
                                json.dumps(
                                    requested, sort_keys=True, default=str
                                ).encode()
                            ).hexdigest(),
                            "effective": owner.profile,
                        }
                    )
                    # Existing trusted broker enforces effective generation parameters,
                    # tool schemas, request counts, deadlines, transcript and response sizes.
                    conn = http.client.HTTPConnection(
                        "127.0.0.1", owner.broker_port, timeout=240
                    )
                    try:
                        encoded = json.dumps(chat, separators=(",", ":")).encode()
                        conn.request(
                            "POST",
                            "/v1/chat/completions",
                            encoded,
                            {
                                "Content-Type": "application/json",
                                "Authorization": "Bearer local",
                            },
                        )
                        upstream = conn.getresponse()
                        raw = upstream.read(16 * 1024**2)
                        if upstream.status != 200:
                            if upstream.status == 429:
                                owner.model_budget_exhausted = True
                            return self._reply(
                                upstream.status,
                                raw,
                                upstream.getheader("Content-Type", "application/json"),
                            )
                        result = json.loads(raw)
                    finally:
                        conn.close()
                    if native_kind == "chat":
                        try:
                            parsed = json.loads(raw)
                            count = sum(
                                len(c.get("tool_calls") or [])
                                for c in parsed.get("choices", [])
                            )
                            owner.tool_calls += count
                            if owner.tool_calls > 240:
                                owner.tool_budget_exhausted = True
                                return self._reply(
                                    429,
                                    {"error": "per-episode tool-call limit reached"},
                                )
                        except (json.JSONDecodeError, AttributeError, TypeError):
                            pass
                        if stream:
                            events = chat_sse(result, owner.model_alias)
                            text = (
                                "".join(
                                    "data: "
                                    + json.dumps(value, separators=(",", ":"))
                                    + "\n\n"
                                    for value in events
                                )
                                + "data: [DONE]\n\n"
                            )
                            return self._reply(200, text.encode(), "text/event-stream")
                        return self._reply(200, result)
                    if native_kind == "responses":
                        response = chat_to_responses(
                            result,
                            owner.model_alias,
                            request=body,
                            previous_response_id=previous_id,
                        )
                        count = sum(
                            item.get("type") == "function_call"
                            for item in response["output"]
                        )
                        owner.tool_calls += count
                        if owner.tool_calls > 240:
                            owner.tool_budget_exhausted = True
                            return self._reply(
                                429, {"error": "per-episode tool-call limit reached"}
                            )
                        response.update(
                            model=owner.model_alias,
                            max_output_tokens=owner.output_cap,
                            temperature=owner.profile["temperature"],
                            top_p=owner.profile["top_p"],
                            store=False,
                        )
                        owner.previous[response["id"]] = {
                            "response": response,
                            "output": response["output"],
                            "messages": chat["messages"]
                            + [result["choices"][0]["message"]],
                        }
                        for old_id in list(owner.previous)[:-128]:
                            owner.previous.pop(old_id, None)
                        if stream:
                            events = responses_sse(response)
                            text = (
                                "".join(
                                    "event: "
                                    + name
                                    + "\ndata: "
                                    + json.dumps(value, separators=(",", ":"))
                                    + "\n\n"
                                    for name, value in events
                                )
                                + "data: [DONE]\n\n"
                            )
                            return self._reply(200, text.encode(), "text/event-stream")
                        return self._reply(200, response)
                    response = chat_to_anthropic(result, owner.model_alias)
                    count = sum(
                        item.get("type") == "tool_use" for item in response["content"]
                    )
                    owner.tool_calls += count
                    if owner.tool_calls > 240:
                        owner.tool_budget_exhausted = True
                        return self._reply(
                            429, {"error": "per-episode tool-call limit reached"}
                        )
                    if stream:
                        events = anthropic_sse(response)
                        text = (
                            "".join(
                                "event: "
                                + name
                                + "\ndata: "
                                + json.dumps(value, separators=(",", ":"))
                                + "\n\n"
                                for name, value in events
                            )
                            + "\n"
                        )
                        return self._reply(200, text.encode(), "text/event-stream")
                    return self._reply(200, response)
                except ProtocolError as exc:
                    self._reply(
                        400,
                        {
                            "error": {
                                "type": "unsupported_request",
                                "message": str(exc)[:300],
                            }
                        },
                    )
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                    self._reply(
                        400,
                        {
                            "error": {
                                "type": "invalid_request",
                                "message": str(exc)[:300],
                            }
                        },
                    )
                except Exception as exc:
                    self._reply(
                        502,
                        {
                            "error": {
                                "type": "local_gateway_error",
                                "message": f"{type(exc).__name__}: {str(exc)[:250]}",
                            }
                        },
                    )

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _body(self, handler):
        return handler._body()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
