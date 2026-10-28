import pytest

from benchmark.qwen_native_protocols import (
    ProtocolError,
    anthropic_sse,
    anthropic_to_chat,
    chat_to_anthropic,
    chat_to_responses,
    chat_sse,
    responses_sse,
    responses_to_chat,
)


def test_responses_messages_and_tool_outputs_preserve_calls_and_receipts():
    previous = [
        {"role": "system", "content": "same instructions"},
        {"role": "user", "content": "look up"},
    ]
    body = {
        "model": "openai/local-qwen",
        "instructions": "same instructions",
        "previous_response_id": "resp-local",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "receipt-17",
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "lookup",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ],
        "max_output_tokens": 16384,
    }
    result = responses_to_chat(body, "local-qwen", 8192, previous, [])
    assert result["messages"][0]["content"] == "same instructions"
    assert result["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "receipt-17",
    }
    assert result["max_tokens"] == 8192
    assert result["tools"][0]["function"]["name"] == "lookup"


def test_responses_rejects_unknown_prior_or_external_model():
    with pytest.raises(ProtocolError, match="previous_response_id"):
        responses_to_chat(
            {"previous_response_id": "not-in-session", "input": "hello"},
            "local-qwen",
            8192,
        )
    with pytest.raises(ProtocolError, match="pinned to the local Qwen"):
        responses_to_chat({"model": "remote/gpt", "input": "hello"}, "local-qwen", 8192)


def test_current_cli_response_metadata_is_accepted_but_not_forwarded_to_model():
    codex = responses_to_chat(
        {
            "model": "local-qwen",
            "input": "hello",
            "client_metadata": {"session_id": "synthetic"},
            "prompt_cache_key": "synthetic-cache-key",
        },
        "local-qwen",
        8192,
    )
    claude = anthropic_to_chat(
        {
            "model": "local-qwen",
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": "hello"}],
            "context_management": [],
            "output_config": {"effort": "high"},
        },
        "local-qwen",
        8192,
    )

    assert codex["messages"][-1]["content"] == "hello"
    assert "client_metadata" not in codex and "prompt_cache_key" not in codex
    assert claude["messages"][-1]["content"] == "hello"
    assert "context_management" not in claude and "output_config" not in claude


def test_anthropic_messages_preserve_in_band_system_messages():
    chat = anthropic_to_chat(
        {
            "model": "local-qwen",
            "max_tokens": 8192,
            "messages": [
                {"role": "developer", "content": "Keep the answer concise."},
                {"role": "user", "content": "hello"},
            ],
        },
        "local-qwen",
        8192,
    )

    assert chat["messages"][0] == {
        "role": "system",
        "content": "Keep the answer concise.",
    }


def test_anthropic_tool_schemas_become_chat_function_tools():
    chat = anthropic_to_chat(
        {
            "model": "local-qwen",
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": "edit"}],
            "tools": [
                {
                    "name": "write_file",
                    "description": "Write within the workspace",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
        },
        "local-qwen",
        8192,
    )

    assert chat["tools"][0]["function"]["name"] == "write_file"
    assert chat["tools"][0]["function"]["parameters"]["required"] == ["path"]


def test_codex_agent_control_namespace_is_filtered_from_baseline_requests():
    tools = [
        {
            "type": "namespace",
            "name": "codex_agents",
            "tools": [
                {"type": "function", "name": name, "parameters": {"type": "object"}}
                for name in (
                    "close_agent",
                    "resume_agent",
                    "send_input",
                    "spawn_agent",
                    "wait_agent",
                )
            ],
        }
    ]

    chat = responses_to_chat(
        {"model": "local-qwen", "input": "hello", "tools": tools},
        "local-qwen",
        8192,
    )

    assert chat["tools"] == []
    assert chat["_filtered_tool_names"] == [
        "close_agent",
        "resume_agent",
        "send_input",
        "spawn_agent",
        "wait_agent",
    ]


def test_responses_history_accepts_textual_assistant_output_items():
    chat = responses_to_chat(
        {
            "model": "local-qwen",
            "input": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "previous answer"}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "continue"}],
                },
            ],
        },
        "local-qwen",
        8192,
    )

    assert chat["messages"] == [
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "continue"},
    ]
def test_responses_calls_require_valid_json_and_supported_text_only_inputs():
    with pytest.raises(ProtocolError, match="valid JSON"):
        responses_to_chat(
            {
                "input": [
                    {
                        "type": "function_call",
                        "name": "lookup",
                        "call_id": "c1",
                        "arguments": "{",
                    }
                ]
            },
            "local-qwen",
            8192,
        )
    with pytest.raises(ProtocolError, match="image/audio/video input"):
        responses_to_chat(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": "http://remote"}
                        ],
                    }
                ]
            },
            "local-qwen",
            8192,
        )


def test_chat_results_roundtrip_to_both_official_local_protocols():
    chat = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"ids":[1]}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }
    responses = chat_to_responses(chat, "local-qwen")
    assert responses["output"][0]["type"] == "function_call"
    assert responses["usage"] == {
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    assert responses_sse(responses)[-1][0] == "response.completed"
    anthropic = chat_to_anthropic(chat, "local-qwen")
    assert anthropic["content"][0]["input"] == {"ids": [1]}
    assert anthropic["stop_reason"] == "tool_use"
    assert anthropic_sse(anthropic)[-1][0] == "message_stop"


def test_responses_and_messages_streams_finish_with_complete_schema():
    responses = chat_to_responses(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ]
        },
        "local-qwen",
    )
    assert [name for name, _ in responses_sse(responses)][-1] == "response.completed"
    response_events = responses_sse(responses)
    assert response_events[0][1]["type"] == "response.created"
    assert response_events[1][1]["type"] == "response.in_progress"
    assert response_events[-1][1]["type"] == "response.completed"
    assert response_events[0][1]["response"]["status"] == "in_progress"
    assert response_events[-1][1]["response"]["status"] == "completed"
    chat = {
        "choices": [
            {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
        ]
    }
    assert chat_sse(chat, "local-qwen")[-1]["choices"][0]["finish_reason"] == "stop"
    assert [name for name, _ in anthropic_sse(chat_to_anthropic(chat, "local-qwen"))][
        -1
    ] == "message_stop"


def test_message_requests_reject_nonlocal_model_alias_and_nontext_blocks():
    with pytest.raises(ProtocolError, match="pinned to the local Qwen"):
        anthropic_to_chat({"model": "remote/gpt", "messages": []}, "local-qwen", 8192)
    with pytest.raises(ProtocolError, match="block"):
        anthropic_to_chat(
            {
                "model": "local-qwen",
                "messages": [{"role": "user", "content": [{"type": "image"}]}],
            },
            "local-qwen",
            8192,
        )
