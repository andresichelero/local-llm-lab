"""Run the fixed local coding task across isolated agent harnesses."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.harness_eval import grade_workspace

DEFAULT_ROOT = Path("/home/foxtrot/local-llm-benchmark")
DEFAULT_MODEL = "Qwen3.5-9B-Q4_K_M"
HARNESS_NAMES = ("pi", "opencode", "vibe")


def build_command(
    harness: str,
    install_root: Path,
    prompt_file: Path,
    workspace: Path,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = 10,
    max_tokens: int = 100_000,
    time_limit: int = 180,
) -> list[str]:
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    node_bin = install_root / "runtimes/node-v22.23.3-linux-x64/bin"
    if harness == "pi":
        executable = install_root / "envs/node-harnesses/pi/node_modules/.bin/pi"
        return [
            str(executable), "--provider", "local-llama", "--model", model,
            "--thinking", "off", "--tools", "read,bash,edit,write", "--no-mcp",
            "--mode", "json", "--print", prompt,
        ]
    if harness == "opencode":
        executable = install_root / "envs/node-harnesses/opencode/node_modules/.bin/opencode"
        return [
            str(executable), "run", "--auto", "--format", "json", "--model",
            f"local/{model}", prompt,
        ]
    if harness == "vibe":
        executable = install_root / "envs/mistral-vibe/bin/vibe"
        return [
            str(executable), "--prompt-file", str(prompt_file), "--workdir", str(workspace),
            "--trust", "--auto-approve", "--max-turns", str(max_turns),
            "--max-tokens", str(max_tokens), "--time-limit", str(time_limit),
            "--output", "json", "--output-dir", str(output_dir),
        ]
    raise ValueError(f"Unsupported harness: {harness}")


def summarize_usage(
    harness: str,
    events: list[dict[str, Any]],
    export: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "model_calls": 0,
        "prompt_tokens": 0,
        "first_prompt_tokens": None,
        "completion_tokens": 0,
        "tool_calls": 0,
        "tool_failures": 0,
        "compactions": 0,
    }
    prompts: list[int] = []

    if harness == "pi":
        for event in events:
            kind = event.get("type")
            message = event.get("message", {})
            if kind == "message_end" and message.get("role") == "assistant":
                usage = message.get("usage", {})
                prompt = int(usage.get("input", 0) or 0) + int(usage.get("cacheRead", 0) or 0)
                prompts.append(prompt)
                result["prompt_tokens"] = int(result["prompt_tokens"] or 0) + prompt
                result["completion_tokens"] = int(result["completion_tokens"] or 0) + int(usage.get("output", 0) or 0)
                result["model_calls"] = int(result["model_calls"] or 0) + 1
            elif kind == "tool_execution_start":
                result["tool_calls"] = int(result["tool_calls"] or 0) + 1
            elif kind == "tool_execution_end" and event.get("result", {}).get("isError"):
                result["tool_failures"] = int(result["tool_failures"] or 0) + 1
            elif kind in {"compaction", "compacted"}:
                result["compactions"] = int(result["compactions"] or 0) + 1
    elif harness == "opencode":
        for event in events:
            kind = event.get("type")
            part = event.get("part", {})
            if kind == "step_finish":
                tokens = part.get("tokens", {})
                prompt = int(tokens.get("input", 0) or 0) + int(tokens.get("cache", {}).get("read", 0) or 0)
                prompts.append(prompt)
                result["prompt_tokens"] = int(result["prompt_tokens"] or 0) + prompt
                result["completion_tokens"] = int(result["completion_tokens"] or 0) + int(tokens.get("output", 0) or 0)
                result["model_calls"] = int(result["model_calls"] or 0) + 1
            elif kind == "tool_use":
                result["tool_calls"] = int(result["tool_calls"] or 0) + 1
                state = part.get("state", {})
                if part.get("tool") == "invalid" or state.get("status") in {"error", "failed"}:
                    result["tool_failures"] = int(result["tool_failures"] or 0) + 1
            elif kind in {"compaction", "compacted"}:
                result["compactions"] = int(result["compactions"] or 0) + 1
    elif harness == "vibe":
        export = export or {}
        usage = export.get("usage", {})
        prompt = int(usage.get("input_tokens", 0) or 0) + int(usage.get("cached_input_tokens", 0) or 0)
        result["prompt_tokens"] = prompt
        result["completion_tokens"] = int(usage.get("output_tokens", 0) or 0)
        result["model_calls"] = int(export.get("steps", 0) or 0)
        for event in events:
            payload = event.get("payload", {})
            if event.get("type") == "action_result":
                action_result = payload.get("result", {}).get("result", {})
                call_usage = action_result.get("usage", {})
                if call_usage:
                    prompts.append(
                        int(call_usage.get("input_tokens", 0) or 0)
                        + int(call_usage.get("cached_input_tokens", 0) or 0)
                    )
                parts = action_result.get("parts", [])
                for part in parts:
                    if part.get("type") == "tool_call":
                        result["tool_calls"] = int(result["tool_calls"] or 0) + 1
            if "compaction" in str(event.get("type", "")).lower():
                result["compactions"] = int(result["compactions"] or 0) + 1
    else:
        raise ValueError(f"Unsupported harness: {harness}")

    if prompts:
        result["first_prompt_tokens"] = prompts[0]
    return result


def parse_server_prompt_eval_tokens(server_log: str) -> list[int]:
    total_pattern = re.compile(r"prompt processing,\s*n_tokens\s*=\s*(\d+)", re.IGNORECASE)
    total_counts = [int(match.group(1)) for match in total_pattern.finditer(server_log)]
    if total_counts:
        return total_counts
    pattern = re.compile(r"prompt eval time\s*=.*?/\s*(\d+)\s+tokens", re.IGNORECASE)
    return [int(match.group(1)) for match in pattern.finditer(server_log)]


def summarize_resources(rows: list[dict[str, Any]]) -> dict[str, int | float | None]:
    metrics = {
        "cpu_util_pct": lambda row: row.get("cpu_util_pct"),
        "ram_used_mb": lambda row: row.get("ram_used_mb"),
        "swap_used_mb": lambda row: row.get("swap_used_mb"),
        "vram_used_mb": lambda row: row.get("gpu", {}).get("vram_used_mb"),
        "gpu_util_pct": lambda row: row.get("gpu", {}).get("gpu_util_pct"),
        "temperature_c": lambda row: row.get("gpu", {}).get("temperature_c"),
        "gpu_clock_mhz": lambda row: row.get("gpu", {}).get("gpu_clock_mhz"),
        "power_w": lambda row: row.get("gpu", {}).get("power_w"),
    }
    result: dict[str, int | float | None] = {"sample_count": len(rows)}
    for name, getter in metrics.items():
        values: list[float] = []
        for row in rows:
            raw = getter(row)
            try:
                if raw is not None and str(raw).strip() not in {"", "[N/A]", "N/A"}:
                    values.append(float(raw))
            except (TypeError, ValueError):
                continue
        result[f"{name}_avg"] = round(statistics.mean(values), 1) if values else None
        result[f"{name}_peak"] = round(max(values), 1) if values else None
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _read_server_log_after(path: Path, offset: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as source:
        source.seek(offset)
        return source.read().decode("utf-8", errors="replace")


def _preflight(install_root: Path, model: str, context: int) -> dict[str, Any]:
    model_path = install_root / "models/gguf/Qwen3.5-9B-Q4_K_M.gguf"
    if not model_path.is_file():
        raise RuntimeError(f"SSD model is missing: {model_path}; stage it from E: first")
    url = "http://127.0.0.1:8080/v1/models"
    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.load(response)
    loaded = next((item for item in data.get("data", []) if item.get("id") == model), None)
    if loaded is None:
        raise RuntimeError(f"Local llama.cpp server does not expose model {model}")
    model_context = int(loaded.get("meta", {}).get("n_ctx", 0) or 0)
    if model_context < context:
        raise RuntimeError(f"Server context {model_context} is below requested context {context}")
    return {"model": model, "context": model_context, "model_bytes": model_path.stat().st_size}


def _isolated_environment(
    harness: str, run_dir: Path, install_root: Path, workspace: Path
) -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.endswith("_API_KEY") or key in {
            "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "CODEX_OSS_BASE_URL",
            "OPENAI_BASE_URL", "OPENAI_API_BASE", "ANTHROPIC_BASE_URL",
        }:
            env.pop(key, None)
    node_bin = install_root / "runtimes/node-v22.23.3-linux-x64/bin"
    env["PATH"] = ":".join(
        ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin", "/usr/lib/wsl/lib", str(node_bin)]
    )
    env["HOME"] = str(run_dir / "home")
    env["PWD"] = str(workspace)
    env["XDG_CONFIG_HOME"] = str(run_dir / "home/.config")
    env["XDG_DATA_HOME"] = str(run_dir / "home/.local/share")
    env["XDG_CACHE_HOME"] = str(run_dir / "home/.cache")
    if harness == "vibe":
        env["VIBE_HOME"] = str(run_dir / "home")
    return env


def _prepare_run(harness: str, run_dir: Path, install_root: Path, prompt_text: str) -> Path:
    workspace = run_dir / "workspace"
    home = run_dir / "home"
    output = run_dir / "output"
    workspace.mkdir(parents=True)
    home.mkdir(parents=True)
    output.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "benchmark/fixtures/harness_task", workspace, dirs_exist_ok=True)
    prompt_file = run_dir / "TASK_PROMPT.md"
    prompt_file.write_text(prompt_text + "\n", encoding="utf-8")
    if harness == "pi":
        agent_dir = home / ".pi/agent"
        agent_dir.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "benchmark/configs/harnesses/pi.models.json", agent_dir / "models.json")
    elif harness == "opencode":
        config_dir = home / ".config/opencode"
        config_dir.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "benchmark/configs/harnesses/opencode.json", config_dir / "opencode.json")
    elif harness == "vibe":
        shutil.copy2(REPO_ROOT / "benchmark/configs/harnesses/vibe.config.toml", home / "config.toml")
    else:
        raise ValueError(f"Unsupported harness: {harness}")

    subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Local LLM Lab", "-c", "user.email=lab@example.invalid", "commit", "--quiet", "-m", "fixture baseline"],
        cwd=workspace,
        check=True,
    )
    return prompt_file


def run_one(
    harness: str,
    install_root: Path,
    limit_seconds: int,
    max_turns: int,
    max_tokens: int,
    run_kind: str = "measurement",
) -> dict[str, Any]:
    preflight = _preflight(install_root, DEFAULT_MODEL, 16384)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = install_root / "results/harness-runs" / f"{timestamp}-{harness}"
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = (REPO_ROOT / "benchmark/configs/harnesses/task_prompt.md").read_text(encoding="utf-8").strip()
    prompt_file = _prepare_run(harness, run_dir, install_root, prompt)
    workspace = run_dir / "workspace"
    output_dir = run_dir / "output"
    stdout_path = run_dir / ("stdout.json" if harness == "vibe" else "events.jsonl")
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"
    server_log = install_root / "logs/harness-llama-server.log"
    server_offset = server_log.stat().st_size if server_log.exists() else 0
    env = _isolated_environment(harness, run_dir, install_root, workspace)
    command = build_command(
        harness,
        install_root,
        prompt_file,
        workspace,
        output_dir,
        max_turns=max_turns,
        max_tokens=max_tokens,
        time_limit=limit_seconds,
    )
    sampler = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"), "--output", str(resource_path), "--interval", "1"],
        cwd=workspace,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    start = time.perf_counter()
    timed_out = False
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=stdout, stderr=stderr)
            try:
                return_code = process.wait(timeout=limit_seconds + 10)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.terminate()
                try:
                    return_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait()
    finally:
        sampler.terminate()
        try:
            sampler.wait(timeout=3)
        except subprocess.TimeoutExpired:
            sampler.kill()
            sampler.wait()
    wall_seconds = round(time.perf_counter() - start, 3)

    try:
        quality = grade_workspace(workspace, REPO_ROOT / "benchmark/fixtures/harness_task")
    except Exception as error:  # Preserve benchmark outcomes if independent grading itself fails.
        quality = {"success": False, "grader_error": f"{type(error).__name__}: {error}"}
    (run_dir / "quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")

    export: dict[str, Any] | None = None
    if harness == "vibe" and (output_dir / "export.json").exists():
        export = json.loads((output_dir / "export.json").read_text(encoding="utf-8"))
    events_path = stdout_path if harness != "vibe" else output_dir / "session/journal/0000000000000001.jsonl"
    if harness == "vibe":
        events = _read_jsonl(events_path)
    else:
        events = _read_jsonl(events_path)
    usage = summarize_usage(harness, events, export)
    server_text = _read_server_log_after(server_log, server_offset)
    server_prompt_eval_tokens = parse_server_prompt_eval_tokens(server_text)
    resource_rows = _read_jsonl(resource_path)
    resources = summarize_resources(resource_rows)
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=workspace, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "harness-coding-task-smoke",
        "run_kind": run_kind,
        "harness": harness,
        "harness_version": {"pi": "1.1.0", "opencode": "1.19.0", "vibe": "2.26.1"}[harness],
        "model": DEFAULT_MODEL,
        "runtime": "llama.cpp v0.6.0-dev d81235049",
        "quant": "Q4_K_M",
        "context_tokens": preflight["context"],
        "kv_cache": "Q4_0",
        "server_prompt_eval_tokens": server_prompt_eval_tokens,
        "storage_profile": "ssd-wsl-ext4-c",
        "wall_s": wall_seconds,
        "exit_code": return_code,
        "timed_out": timed_out,
        **usage,
        **resources,
        "changed_files": changed,
        "quality": quality,
        "success": bool(quality.get("success")) and return_code == 0 and not timed_out,
        "run_dir": str(run_dir),
    }
    (run_dir / "metrics.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    summary_path = REPO_ROOT / "results/raw/harness-run-summary.jsonl"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("a", encoding="utf-8") as summary:
        summary.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", choices=(*HARNESS_NAMES, "all"), default="all")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit-seconds", type=int, default=180)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=100_000)
    parser.add_argument("--warmup", action="store_true", help="Run one warm-up record instead of measured repeats")
    parser.add_argument("--benchmark-root", type=Path, default=Path(os.getenv("BENCHMARK_ROOT", str(DEFAULT_ROOT))))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.repeat < 1 or args.limit_seconds < 1:
        parser.error("--repeat and --limit-seconds must be positive")
    if args.warmup and args.repeat != 1:
        parser.error("--warmup runs one record; omit --repeat or set it to 1")
    harnesses = HARNESS_NAMES if args.harness == "all" else (args.harness,)
    if args.dry_run:
        print(json.dumps({"harnesses": harnesses, "repeat": args.repeat, "model": DEFAULT_MODEL, "context_tokens": 16384, "benchmark_root": str(args.benchmark_root)}, indent=2))
        return 0
    for harness in harnesses:
        iterations = 1 if args.warmup else args.repeat
        run_kind = "warmup" if args.warmup else "measurement"
        for _ in range(iterations):
            record = run_one(harness, args.benchmark_root, args.limit_seconds, args.max_turns, args.max_tokens, run_kind)
            print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
