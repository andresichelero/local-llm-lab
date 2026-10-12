"""Unit tests for MTP agentic paired runner (Milestone M4 Task 6B)."""
from __future__ import annotations

from pathlib import Path

from benchmark.mtp_agentic_paired import (
    build_schedule,
    parse_prometheus_counters,
    server_command,
    summarize_mtp_agentic_results,
)


def test_build_schedule_structure() -> None:
    schedule = build_schedule()
    assert len(schedule) == 12

    # Check pair 1: alternating False then True
    p1 = [item for item in schedule if item["pair"] == 1]
    assert len(p1) == 4
    calc_p1 = [item for item in p1 if item["task"] == "calculator_division"]
    assert [item["mtp"] for item in calc_p1] == [False, True]

    # Check pair 2: alternating True then False
    p2 = [item for item in schedule if item["pair"] == 2]
    assert len(p2) == 4
    calc_p2 = [item for item in p2 if item["task"] == "calculator_division"]
    assert [item["mtp"] for item in calc_p2] == [True, False]


def test_server_command_flags() -> None:
    server_path = Path("/tools/llama-server")
    model_path = Path("/models/qwen.gguf")

    cmd_off = server_command(server_path, model_path, "qwen3.5-4b", mtp=False)
    assert "--spec-type" in cmd_off
    spec_idx = cmd_off.index("--spec-type")
    assert cmd_off[spec_idx + 1] == "none"
    assert "--metrics" in cmd_off

    cmd_on = server_command(server_path, model_path, "qwen3.5-4b", mtp=True)
    assert "--spec-type" in cmd_on
    spec_idx = cmd_on.index("--spec-type")
    assert cmd_on[spec_idx + 1] == "draft-mtp"
    assert "--spec-draft-n-max" in cmd_on
    assert cmd_on[cmd_on.index("--spec-draft-n-max") + 1] == "3"
    assert "--metrics" in cmd_on


def test_parse_prometheus_counters() -> None:
    raw = """
# HELP llamacpp:spec_decode_num_draft_tokens_total Number of draft tokens
# TYPE llamacpp:spec_decode_num_draft_tokens_total counter
llamacpp:spec_decode_num_draft_tokens_total 425
llamacpp:spec_decode_num_accepted_tokens_total 312
llamacpp:spec_decode_num_drafts_total 150
other_metric{label="foo"} 99.5
"""
    counters = parse_prometheus_counters(raw)
    assert counters["llamacpp:spec_decode_num_draft_tokens_total"] == 425.0
    assert counters["llamacpp:spec_decode_num_accepted_tokens_total"] == 312.0
    assert counters["llamacpp:spec_decode_num_drafts_total"] == 150.0
    assert counters["other_metric"] == 99.5


def test_summarize_mtp_agentic_results() -> None:
    records = [
        {
            "task": "calculator_division",
            "mtp": False,
            "strict_pass": True,
            "task_wall_seconds": 40.0,
        },
        {
            "task": "calculator_division",
            "mtp": True,
            "strict_pass": True,
            "task_wall_seconds": 25.0,
            "speculative_counters": {
                "drafted_tokens": 100,
                "accepted_tokens": 80,
                "verification_steps": 35,
            },
        },
        {
            "task": "calculator_division",
            "mtp": False,
            "strict_pass": True,
            "task_wall_seconds": 42.0,
        },
        {
            "task": "calculator_division",
            "mtp": True,
            "strict_pass": True,
            "task_wall_seconds": 27.0,
            "speculative_counters": {
                "drafted_tokens": 120,
                "accepted_tokens": 90,
                "verification_steps": 40,
            },
        },
    ]

    summary = summarize_mtp_agentic_results(records)
    calc = summary["calculator_division"]

    assert calc["mtp_off"]["attempts"] == 2
    assert calc["mtp_off"]["passes"] == 2
    assert calc["mtp_off"]["wall_median"] == 41.0

    assert calc["mtp_on"]["attempts"] == 2
    assert calc["mtp_on"]["passes"] == 2
    assert calc["mtp_on"]["wall_median"] == 26.0
    assert calc["mtp_on"]["total_drafted_tokens"] == 220
    assert calc["mtp_on"]["total_accepted_tokens"] == 170
    assert calc["mtp_on"]["overall_acceptance_rate"] == round(170 / 220, 4)

    # 41.0 / 26.0 = 1.577
    assert calc["wall_speedup"] == round(41.0 / 26.0, 3)
