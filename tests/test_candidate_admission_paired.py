"""Unit tests for candidate admission paired runner (Milestone M5 Tarefa 7)."""
from __future__ import annotations

from pathlib import Path

from benchmark.candidate_admission_paired import (
    build_schedule,
    server_command,
    summarize_admission_results,
)


def test_build_schedule_structure() -> None:
    schedule = build_schedule()
    assert len(schedule) == 12

    # Check repeat 1 models
    r1 = [item for item in schedule if item["repeat"] == 1]
    assert len(r1) == 4
    calc_r1 = [item for item in r1 if item["task"] == "calculator_division"]
    assert [item["model"] for item in calc_r1] == ["qwen3.5-4b", "gemma-4-e4b"]

    # Check repeat 2 models (inverted BA order)
    r2 = [item for item in schedule if item["repeat"] == 2]
    assert len(r2) == 4
    calc_r2 = [item for item in r2 if item["task"] == "calculator_division"]
    assert [item["model"] for item in calc_r2] == ["gemma-4-e4b", "qwen3.5-4b"]


def test_server_command_flags() -> None:
    server_path = Path("/tools/llama-server")
    model_path = Path("/models/gemma.gguf")

    cmd = server_command(server_path, model_path, "gemma-4-e4b")
    assert "--model" in cmd
    assert "--cache-prompt" in cmd
    assert "--flash-attn" in cmd
    assert "--ctx-size" in cmd
    assert cmd[cmd.index("--ctx-size") + 1] == "16384"


def test_summarize_admission_results() -> None:
    records = [
        {
            "task": "calculator_division",
            "model": "qwen3.5-4b",
            "strict_pass": True,
            "task_wall_seconds": 22.0,
            "resource_summary": {"vram_used_mb_peak": 4500.0},
        },
        {
            "task": "calculator_division",
            "model": "gemma-4-e4b",
            "strict_pass": True,
            "task_wall_seconds": 24.0,
            "resource_summary": {"vram_used_mb_peak": 4200.0},
        },
        {
            "task": "calculator_division",
            "model": "qwen3.5-4b",
            "strict_pass": True,
            "task_wall_seconds": 20.0,
            "resource_summary": {"vram_used_mb_peak": 4550.0},
        },
        {
            "task": "calculator_division",
            "model": "gemma-4-e4b",
            "strict_pass": False,
            "task_wall_seconds": 26.0,
            "resource_summary": {"vram_used_mb_peak": 4250.0},
        },
    ]

    summary = summarize_admission_results(records)
    calc = summary["calculator_division"]

    assert calc["qwen3.5-4b"]["attempts"] == 2
    assert calc["qwen3.5-4b"]["passes"] == 2
    assert calc["qwen3.5-4b"]["pass_rate"] == 1.0
    assert calc["qwen3.5-4b"]["wall_median"] == 21.0
    assert calc["qwen3.5-4b"]["vram_peak_max"] == 4550.0

    assert calc["gemma-4-e4b"]["attempts"] == 2
    assert calc["gemma-4-e4b"]["passes"] == 1
    assert calc["gemma-4-e4b"]["pass_rate"] == 0.5
    assert calc["gemma-4-e4b"]["wall_median"] == 25.0
    assert calc["gemma-4-e4b"]["vram_peak_max"] == 4250.0


def test_build_schedule_granite() -> None:
    schedule = build_schedule(
        control="qwen3.5-4b",
        candidate="granite-4.1-8b",
        tasks=("retry_policy", "dotenv_line_parser"),
        repeats=3,
    )
    assert len(schedule) == 12
    # Check trial 1
    assert schedule[0]["model"] == "qwen3.5-4b"
    assert schedule[0]["task"] == "retry_policy"
    # Check trial 2
    assert schedule[1]["model"] == "granite-4.1-8b"
    assert schedule[1]["task"] == "retry_policy"


def test_server_command_granite() -> None:
    server_path = Path("/tools/llama-server")
    model_path = Path("/models/granite-4.1-8b-Q4_K_M.gguf")

    cmd = server_command(server_path, model_path, "granite-4.1-8b")
    assert "--model" in cmd
    assert "--cache-prompt" in cmd
    assert "--alias" in cmd
    assert cmd[cmd.index("--alias") + 1] == "granite-4.1-8b-Q4_K_M"
    assert cmd[cmd.index("--ctx-size") + 1] == "16384"

