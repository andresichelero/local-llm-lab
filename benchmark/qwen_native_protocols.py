"""Lossless-text adapters for native OpenAI Responses and Anthropic Messages SDKs.

These functions only translate documented request/response wire shapes to a
single local Chat Completions engine. Sampling, model choice and token limits
are applied by the trusted model broker; no remote provider or fallback exists.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Mapping


class ProtocolError(ValueError):
    pass


_CODEX_AGENT_CONTROL_TOOLS = frozenset(
    {"close_agent", "resume_agent", "send_input", "spawn_agent", "wait_agent"}
)


def _tool_definitions(tools):
    result = []
    for tool in tools or []:
        if tool.get("type") != "function":
            nested = tool.get("tools")
            child_kinds = (
                ",".join(
                    f"{item.get('type')}:{item.get('name')}"
                    for item in nested[:8]
                    if isinstance(item, dict)
                )
                if isinstance(nested, list)
                else "none"
            )
            raise ProtocolError(
                "unsupported tool type for the local coding harness: "
                + str(tool.get("type"))
                + "; child tools: "
                + child_kinds
            )
        name = tool.get("name") or (tool.get("function") or {}).get("name")
        parameters = tool.get("parameters") or (tool.get("function") or {}).get(
            "parameters"
        )
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ProtocolError("invalid function name")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ProtocolError("function parameters must be an object schema")
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get(
                        "description",
                        (tool.get("function") or {}).get("description", ""),
                    ),
                    "parameters": parameters,
                },
            }
        )
    if len(result) > 64:
        raise ProtocolError("function tool count exceeds 64")
    return result


def _responses_tools(tools):
    allowed, filtered = [], []
    for tool in tools or []:
        if tool.get("type") == "namespace":
            children = tool.get("tools")
            names = [
                item.get("name")
                for item in children or []
                if isinstance(item, dict) and item.get("type") == "function"
            ]
            if (
                isinstance(children, list)
                and names
                and len(names) == len(children)
                and set(names) <= _CODEX_AGENT_CONTROL_TOOLS
            ):
                filtered.extend(names)
                continue
        allowed.append(tool)
    return _tool_definitions(allowed), filtered


def _text_content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ProtocolError("only text input is available for local model workloads")
    output = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in {
            "text",
            "input_text",
            "output_text",
        }:
            kind = item.get("type") if isinstance(item, dict) else type(item).__name__
            raise ProtocolError(
                "image/audio/video input is not present in this text coding workload: "
                + str(kind)
            )
        output.append(item.get("text", ""))
    return "".join(output)


def _response_output_to_chat(items):
    messages = []
    for item in items:
        if item.get("type") == "message":
            text = "".join(
                part.get("text", "")
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
            if text:
                messages.append(
                    {"role": item.get("role", "assistant"), "content": text}
                )
        elif item.get("type") == "function_call":
            args = item.get("arguments", "{}")
            json.loads(args)
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": item["call_id"],
                            "type": "function",
                            "function": {"name": item["name"], "arguments": args},
                        }
                    ],
                }
            )
    return messages


def responses_to_chat(
    body: Mapping[str, Any],
    model_alias: str,
    output_cap: int,
    prior_messages=None,
    prior_outputs=None,
):
    if not isinstance(body, Mapping):
        raise ProtocolError("Responses request must be a JSON object")
    allowed = {
        "model",
        "input",
        "instructions",
        "tools",
        "tool_choice",
        "max_output_tokens",
        "temperature",
        "top_p",
        "stream",
        "previous_response_id",
        "metadata",
        "store",
        "parallel_tool_calls",
        "reasoning",
        "text",
        "include",
        "truncation",
        "user",
        "client_metadata",
        "prompt_cache_key",
    }
    if set(body) - allowed:
        raise ProtocolError(
            "unsupported Responses field: " + ",".join(sorted(set(body) - allowed))
        )
    if body.get("model") is not None and body.get("model") not in {
        model_alias,
        "qwen-local",
        "openai/" + model_alias,
        "local/" + model_alias,
        "ollama/" + model_alias,
    }:
        raise ProtocolError(
            "requested model alias is not pinned to the local Qwen artifact"
        )
    messages = []
    instructions = body.get("instructions")
    instruction_text = _text_content(instructions) if instructions else None
    if body.get("previous_response_id") is not None:
        if not isinstance(body["previous_response_id"], str) or prior_messages is None:
            raise ProtocolError(
                "previous_response_id is not owned by this isolated session"
            )
        prior = list(prior_messages)
        messages.extend(prior)
        if instruction_text:
            if messages and messages[0].get("role") == "system":
                if messages[0].get("content") != instruction_text:
                    messages[0]["content"] += (
                        "\nAdditional task instructions:\n" + instruction_text
                    )
            else:
                messages.insert(0, {"role": "system", "content": instruction_text})
    elif instruction_text:
        messages.append({"role": "system", "content": instruction_text})
    raw = body.get("input", "")
    if isinstance(raw, str):
        raw = [{"role": "user", "content": raw}]
    if not isinstance(raw, list):
        raise ProtocolError("Responses input must be text or a message-item array")
    for item in raw:
        if not isinstance(item, dict):
            raise ProtocolError("Responses input item must be an object")
        kind = item.get("type", "message")
        if kind == "message":
            role = item.get("role")
            if role not in {"system", "developer", "user", "assistant"}:
                raise ProtocolError("unsupported Responses message role")
            content = _text_content(item.get("content", ""))
            role = "system" if role == "developer" else role
            if messages and messages[0]["role"] == "system" and role == "system":
                messages[0]["content"] += "\n" + content
            else:
                messages.append({"role": role, "content": content})
        elif kind == "function_call":
            name, call_id = item.get("name"), item.get("call_id")
            args = item.get("arguments", "{}")
            if (
                not isinstance(name, str)
                or not isinstance(call_id, str)
                or not isinstance(args, str)
            ):
                raise ProtocolError("malformed Responses function_call")
            try:
                json.loads(args)
            except ValueError as exc:
                raise ProtocolError("function arguments must be valid JSON") from exc
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": args},
                        }
                    ],
                }
            )
        elif kind == "function_call_output":
            call_id = item.get("call_id")
            if not isinstance(call_id, str):
                raise ProtocolError("Responses function_call_output needs a call_id")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _text_content(item.get("output", "")),
                }
            )
        elif kind == "item_reference":
            ref = item.get("id")
            found = next((x for x in (prior_outputs or []) if x.get("id") == ref), None)
            if found is None:
                raise ProtocolError(
                    "item_reference does not belong to this isolated session"
                )
            messages.extend(_response_output_to_chat([found]))
        elif kind == "reasoning":
            # Qwen's published template omits prior hidden thinking from history.
            continue
        else:
            raise ProtocolError("unsupported Responses input item: " + str(kind))
    tools, filtered_tool_names = _responses_tools(body.get("tools"))
    cap = body.get("max_output_tokens", output_cap)
    if type(cap) is not int or cap <= 0:
        raise ProtocolError("max_output_tokens must be a positive integer")
    return {
        "model": model_alias,
        "messages": messages or [{"role": "user", "content": ""}],
        "tools": tools,
        "tool_choice": "auto" if tools else "none",
        "max_tokens": min(cap, output_cap),
        "stream": False,
        "parallel_tool_calls": bool(body.get("parallel_tool_calls", False)),
        "_filtered_tool_names": filtered_tool_names,
    }


def chat_to_responses(value, model_alias, *, request=None, previous_response_id=None):
    message = value["choices"][0]["message"]
    out = []
    if message.get("content"):
        out.append(
            {
                "id": "msg_" + uuid.uuid4().hex,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": message["content"],
                        "annotations": [],
                    }
                ],
            }
        )
    for call in message.get("tool_calls") or []:
        out.append(
            {
                "id": "fc_" + uuid.uuid4().hex,
                "type": "function_call",
                "status": "completed",
                "call_id": call["id"],
                "name": call["function"]["name"],
                "arguments": call["function"]["arguments"],
            }
        )
    usage = value.get("usage") or {}
    finish_reason = value["choices"][0].get("finish_reason")
    finished = (
        message.get("content") is not None or bool(message.get("tool_calls"))
    ) and finish_reason != "length"
    response_id = "resp_" + uuid.uuid4().hex
    request = request or {}
    import time

    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed" if finished else "incomplete",
        "error": None,
        "background": False,
        "model": model_alias,
        "output": out,
        "incomplete_details": None if finished else {"reason": "max_output_tokens"},
        "instructions": request.get("instructions"),
        "max_output_tokens": request.get("max_output_tokens"),
        "parallel_tool_calls": bool(request.get("parallel_tool_calls", False)),
        "previous_response_id": previous_response_id,
        "reasoning": request.get("reasoning"),
        "store": False,
        "temperature": request.get("temperature"),
        "text": request.get("text"),
        "tool_choice": request.get("tool_choice", "auto"),
        "tools": request.get("tools", []),
        "top_p": request.get("top_p"),
        "truncation": request.get("truncation"),
        "user": request.get("user"),
        "metadata": request.get("metadata"),
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def anthropic_to_chat(body: Mapping[str, Any], model_alias: str, output_cap: int):
    if not isinstance(body, Mapping):
        raise ProtocolError("Anthropic Messages request must be a JSON object")
    allowed = {
        "model",
        "system",
        "messages",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
        "top_p",
        "stop_sequences",
        "stream",
        "metadata",
        "thinking",
        "context_management",
        "output_config",
    }
    if set(body) - allowed:
        raise ProtocolError(
            "unsupported Messages field: " + ",".join(sorted(set(body) - allowed))
        )
    if body.get("model") is not None and body.get("model") not in {
        model_alias,
        "qwen-local",
        "openai/" + model_alias,
        "local/" + model_alias,
        "ollama/" + model_alias,
    }:
        raise ProtocolError(
            "requested model alias is not pinned to the local Qwen artifact"
        )
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": _text_content(body["system"])})
    for item in body.get("messages", []):
        role, content = item.get("role"), item.get("content", "")
        if role in {"system", "developer"}:
            messages.append({"role": "system", "content": _text_content(content)})
            continue
        if role not in {"user", "assistant"}:
            raise ProtocolError("unsupported Anthropic message role: " + str(role))
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise ProtocolError("Anthropic content must be text blocks")
        text, calls, results = [], [], []
        for part in content:
            if not isinstance(part, dict):
                raise ProtocolError("Anthropic content block must be an object")
            kind = part.get("type")
            if kind == "text":
                text.append(part.get("text", ""))
            elif kind in {"thinking", "redacted_thinking"}:
                continue
            elif kind == "tool_use" and role == "assistant":
                calls.append(
                    {
                        "id": part["id"],
                        "type": "function",
                        "function": {
                            "name": part["name"],
                            "arguments": json.dumps(
                                part["input"], separators=(",", ":")
                            ),
                        },
                    }
                )
            elif kind == "tool_result" and role == "user":
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": part["tool_use_id"],
                        "content": _text_content(part.get("content", "")),
                    }
                )
            else:
                raise ProtocolError("unsupported Anthropic content block: " + str(kind))
        if text or calls:
            messages.append(
                {
                    "role": role,
                    "content": "".join(text) or None,
                    **({"tool_calls": calls} if calls else {}),
                }
            )
        messages.extend(results)
    tools = [
        {
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t["input_schema"],
        }
        for t in body.get("tools", [])
    ]
    response_tools = _tool_definitions(tools)
    cap = body.get("max_tokens", output_cap)
    if type(cap) is not int or cap <= 0:
        raise ProtocolError("max_tokens must be a positive integer")
    return {
        "model": model_alias,
        "messages": messages or [{"role": "user", "content": ""}],
        "tools": response_tools,
        "tool_choice": "auto" if response_tools else "none",
        "max_tokens": min(cap, output_cap),
        "stream": False,
    }


def chat_to_anthropic(value, model_alias):
    message = value["choices"][0]["message"]
    content = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls") or []:
        content.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["function"]["name"],
                "input": json.loads(call["function"]["arguments"]),
            }
        )
    usage = value.get("usage") or {}
    finish = value["choices"][0].get("finish_reason")
    stop = (
        "max_tokens"
        if finish == "length"
        else (
            "tool_use" if any(x["type"] == "tool_use" for x in content) else "end_turn"
        )
    )
    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": model_alias,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def responses_sse(response):
    events = [
        (
            "response.created",
            {
                "type": "response.created",
                "response": dict(
                    response,
                    status="in_progress",
                    output=[],
                    usage=None,
                    incomplete_details=None,
                ),
            },
        ),
        (
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": dict(
                    response,
                    status="in_progress",
                    output=[],
                    usage=None,
                    incomplete_details=None,
                ),
            },
        ),
    ]
    for index, item in enumerate(response["output"]):
        events.append(
            (
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": index,
                    "item": dict(item, status="in_progress"),
                },
            )
        )
        if item["type"] == "message":
            events.append(
                (
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "output_index": index,
                        "content_index": 0,
                        "item_id": item["id"],
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    },
                )
            )
            text = item["content"][0]["text"] if item.get("content") else ""
            events.append(
                (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "output_index": index,
                        "content_index": 0,
                        "item_id": item["id"],
                        "delta": text,
                    },
                )
            )
            events.append(
                (
                    "response.output_text.done",
                    {
                        "type": "response.output_text.done",
                        "output_index": index,
                        "content_index": 0,
                        "item_id": item["id"],
                        "text": text,
                    },
                )
            )
            events.append(
                (
                    "response.content_part.done",
                    {
                        "type": "response.content_part.done",
                        "output_index": index,
                        "content_index": 0,
                        "item_id": item["id"],
                        "part": item["content"][0],
                    },
                )
            )
        else:
            events.append(
                (
                    "response.function_call_arguments.delta",
                    {
                        "type": "response.function_call_arguments.delta",
                        "output_index": index,
                        "item_id": item["id"],
                        "delta": item["arguments"],
                    },
                )
            )
            events.append(
                (
                    "response.function_call_arguments.done",
                    {
                        "type": "response.function_call_arguments.done",
                        "output_index": index,
                        "item_id": item["id"],
                        "arguments": item["arguments"],
                    },
                )
            )
        events.append(
            (
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "item": item,
                },
            )
        )
    terminal = (
        "response.completed"
        if response["status"] == "completed"
        else "response.incomplete"
    )
    events.append(
        (terminal, {"type": terminal, "response": dict(response)})
    )
    return events


def chat_sse(response, model_alias):
    result = response["choices"][0]
    chunk_id = "chatcmpl_" + uuid.uuid4().hex
    common = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(__import__("time").time()),
        "model": model_alias,
    }
    events = [
        dict(
            common,
            choices=[
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        )
    ]
    msg = result["message"]
    if msg.get("content"):
        events.append(
            dict(
                common,
                choices=[
                    {
                        "index": 0,
                        "delta": {"content": msg["content"]},
                        "finish_reason": None,
                    }
                ],
            )
        )
    for index, call in enumerate(msg.get("tool_calls") or []):
        events.append(
            dict(
                common,
                choices=[
                    {
                        "index": 0,
                        "delta": {"tool_calls": [dict(call, index=index)]},
                        "finish_reason": None,
                    }
                ],
            )
        )
    events.append(
        dict(
            common,
            choices=[
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": result.get("finish_reason") or "stop",
                }
            ],
        )
    )
    if response.get("usage"):
        events.append(dict(common, choices=[], usage=response["usage"]))
    return events


def anthropic_sse(response):
    message = {
        k: v for k, v in response.items() if k not in {"stop_reason", "stop_sequence"}
    }
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": dict(
                    message, content=[], stop_reason=None, stop_sequence=None
                ),
            },
        )
    ]
    for index, block in enumerate(response["content"]):
        item = (
            {"type": "text", "text": ""}
            if block["type"] == "text"
            else {
                "type": "tool_use",
                "id": block["id"],
                "name": block["name"],
                "input": {},
            }
        )
        events.append(
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": item},
            )
        )
        if block["type"] == "text":
            delta = {"type": "text_delta", "text": block["text"]}
        else:
            delta = {
                "type": "input_json_delta",
                "partial_json": json.dumps(block["input"], separators=(",", ":")),
            }
        events.append(
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            )
        )
        events.append(
            ("content_block_stop", {"type": "content_block_stop", "index": index})
        )
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": response["stop_reason"],
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": response["usage"]["output_tokens"]},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return events
