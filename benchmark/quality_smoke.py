#!/usr/bin/env python3
"""Deterministic JSON-output and one local tool-round-trip check."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def request(url: str, model: str, messages: list[dict], **extra) -> tuple[dict, float]:
    payload = {"model": model, "messages": messages, "temperature": 0, "seed": 1234, "max_tokens": 128, **extra}
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read(4096).decode(errors='replace')}") from exc
    return data, time.perf_counter() - started


def is_valid_strict_json_response(parsed: object) -> bool:
    return (
        type(parsed) is dict
        and set(parsed) == {"ok", "count"}
        and type(parsed["ok"]) is bool
        and parsed["ok"] is True
        and type(parsed["count"]) is int
        and parsed["count"] == 3
    )


def validate_add_arguments(arguments: object) -> bool:
    """Validate that arguments is a dictionary containing exclusively a=19 and b=23 as ints."""
    if not isinstance(arguments, dict):
        return False
    if set(arguments.keys()) != {"a", "b"}:
        return False
    val_a = arguments["a"]
    val_b = arguments["b"]
    if type(val_a) is not int or type(val_b) is not int:
        return False
    return val_a == 19 and val_b == 23


def validate_add_final(content: object) -> bool:
    """Validate that content is exclusively a JSON object with exactly {'result': 42}."""
    if not isinstance(content, str):
        return False
    stripped = content.strip()
    if not stripped:
        return False
    try:
        data = json.loads(stripped)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if set(data.keys()) != {"result"}:
        return False
    val = data["result"]
    if type(val) is not int:
        return False
    return val == 42


def get_required_tool_call(message: dict) -> dict:
    calls = message.get("tool_calls")
    if (not isinstance(calls, list) or len(calls) != 1
            or not isinstance(calls[0], dict)
            or not calls[0].get("id")
            or not isinstance(calls[0].get("function"), dict)
            or calls[0].get("function", {}).get("name") != "add"):
        details = {
            "finish_reason": message.get("finish_reason"),
            "content": message.get("content"),
            "tool_calls": calls,
        }
        raise RuntimeError(f"model did not return exactly one required add tool call: {json.dumps(details, ensure_ascii=False)}")
    return calls[0]


def record(mode: str, model: str, elapsed: float, success: bool, **fields) -> dict:
    source_dirty_env = os.environ.get("LAB_SOURCE_DIRTY")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "tier0_quality_smoke",
        "mode": mode,
        "model": model,
        "quant": "GGUF Q4_K_M",
        "runtime": "llama.cpp",
        "git_sha": os.environ.get("LAB_GIT_SHA"),
        "source_tree_dirty": (source_dirty_env.lower() == "true") if source_dirty_env is not None else None,
        "runtime_commit": os.environ.get("LAB_RUNTIME_COMMIT"),
        "reasoning": os.environ.get("LAB_REASONING", "unknown"),
        "context_tokens": int(os.environ.get("LAB_CONTEXT_TOKENS", "2048")),
        "kv_cache_k": os.environ.get("LAB_KV_CACHE_K", "f16"),
        "kv_cache_v": os.environ.get("LAB_KV_CACHE_V", "f16"),
        "gpu_layers": int(os.environ.get("LAB_GPU_LAYERS", "99")),
        "flash_attention": "on",
        "wall_time_s": round(elapsed, 4),
        "success": success,
        **fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18181")
    parser.add_argument("--model", default="local")
    bench_storage_root = Path(os.environ.get("BENCH_STORAGE_ROOT", Path.home() / "local-llm-benchmark"))
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("QUALITY_RESULT_JSONL", bench_storage_root / "results/raw/tier0-quality.jsonl")))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    try:
        response, elapsed = request(
            args.url,
            args.model,
            [{"role": "user", "content": 'Return a JSON object with exactly the keys "ok" and "count"; use true and 3.'}],
            response_format={"type": "json_object"},
        )
        message = response["choices"][0]["message"]
        content = message.get("content") or ""
        parsed = json.loads(content)
        valid = is_valid_strict_json_response(parsed)
        usage = response.get("usage", {})
        results.append(record(
            "structured_json", args.model, elapsed, valid,
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            output=content, parsed=parsed,
        ))
    except (OSError, RuntimeError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        results.append(record("structured_json", args.model, 0, False, error=str(exc)))

    tools = [{
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers and return their sum.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }]
    messages = [{"role": "user", "content": 'Use the add tool with a=19 and b=23. Then report the result exclusively as a JSON object {"result": 42}.'}]
    started = time.perf_counter()
    try:
        first, _ = request(args.url, args.model, messages, tools=tools, tool_choice="required")
        assistant = first["choices"][0]["message"]
        call = get_required_tool_call(assistant)
        arguments = json.loads(call["function"]["arguments"])
        valid_args = validate_add_arguments(arguments)
        if not valid_args:
            raise RuntimeError(f"invalid tool arguments against contract: {arguments!r}")
        result = arguments["a"] + arguments["b"]
        followup_messages = messages + [assistant, {
            "role": "tool", "tool_call_id": call["id"], "name": "add", "content": json.dumps({"result": result}),
        }]
        final, _ = request(args.url, args.model, followup_messages)
        final_text = final["choices"][0]["message"].get("content") or ""
        valid_final = validate_add_final(final_text)
        success = valid_args and valid_final
        first_usage, final_usage = first.get("usage", {}), final.get("usage", {})
        results.append(record(
            "tool_round_trip", args.model, time.perf_counter() - started, success,
            tool_calls=1, failed_tool_calls=0, retries=0,
            input_tokens=(first_usage.get("prompt_tokens") or 0) + (final_usage.get("prompt_tokens") or 0),
            output_tokens=(first_usage.get("completion_tokens") or 0) + (final_usage.get("completion_tokens") or 0),
            tool_name="add", arguments=arguments, tool_result=result, final_output=final_text,
            raw_response={"first": first, "final": final},
        ))
    except (OSError, RuntimeError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        results.append(record(
            "tool_round_trip", args.model, time.perf_counter() - started, False,
            tool_calls=0, failed_tool_calls=1, retries=0, error=str(exc),
        ))

    with args.output.open("a", encoding="utf-8") as output:
        for item in results:
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(json.dumps(item, ensure_ascii=False))
    return 0 if all(item["success"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
