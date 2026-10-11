#!/usr/bin/env python3
"""Deterministic JSON-output and one local tool-round-trip check."""
from __future__ import annotations

import argparse
import json
import os
import re
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


def record(mode: str, model: str, elapsed: float, success: bool, **fields) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "tier0_quality_smoke",
        "mode": mode,
        "model": model,
        "quant": "GGUF Q4_K_M",
        "runtime": "llama.cpp",
        "git_sha": os.environ.get("LAB_GIT_SHA"),
        "source_tree_dirty": os.environ.get("LAB_SOURCE_DIRTY", "unknown") == "true",
        "runtime_commit": os.environ.get("LAB_RUNTIME_COMMIT"),
        "context_tokens": 2048,
        "kv_cache_k": "f16",
        "kv_cache_v": "f16",
        "gpu_layers": 99,
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
        valid = parsed == {"ok": True, "count": 3}
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
    messages = [{"role": "user", "content": "Use the add tool with a=19 and b=23. Then report the result."}]
    started = time.perf_counter()
    try:
        first, _ = request(args.url, args.model, messages, tools=tools, tool_choice="required")
        assistant = first["choices"][0]["message"]
        calls = assistant.get("tool_calls") or []
        if not calls or calls[0].get("function", {}).get("name") != "add":
            raise RuntimeError("model did not return the required add tool call")
        call = calls[0]
        arguments = json.loads(call["function"]["arguments"])
        if set(arguments) != {"a", "b"} or any(type(arguments[key]) is not int for key in ("a", "b")):
            raise RuntimeError(f"invalid tool arguments: {arguments!r}")
        result = arguments["a"] + arguments["b"]
        followup_messages = messages + [assistant, {
            "role": "tool", "tool_call_id": call["id"], "name": "add", "content": json.dumps({"result": result}),
        }]
        final, _ = request(args.url, args.model, followup_messages)
        final_text = final["choices"][0]["message"].get("content") or ""
        success = result == 42 and bool(re.search(r"\b42\b|forty[- ]two", final_text, re.IGNORECASE))
        first_usage, final_usage = first.get("usage", {}), final.get("usage", {})
        results.append(record(
            "tool_round_trip", args.model, time.perf_counter() - started, success,
            tool_calls=1, failed_tool_calls=0, retries=0,
            input_tokens=(first_usage.get("prompt_tokens") or 0) + (final_usage.get("prompt_tokens") or 0),
            output_tokens=(first_usage.get("completion_tokens") or 0) + (final_usage.get("completion_tokens") or 0),
            tool_name="add", arguments=arguments, tool_result=result, final_output=final_text,
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
