"""Unit tests for cascade routing matrix runner (Trilha A)."""
from __future__ import annotations

from pathlib import Path

from benchmark.cascade_routing_matrix import (
    MODELS,
    POLICIES,
    TASKS,
    build_schedule,
    decide_escalation,
    server_command,
    summarize_cascade_results,
)


def test_build_schedule_structure() -> None:
    schedule = build_schedule()
    assert len(schedule) == 36

    # 12 trials per policy
    for policy in POLICIES:
        policy_trials = [t for t in schedule if t["policy"] == policy]
        assert len(policy_trials) == 12
        # 2 repeats of 6 tasks
        for task in TASKS:
            task_trials = [t for t in policy_trials if t["task"] == task]
            assert len(task_trials) == 2


def test_server_command_configurations() -> None:
    server_bin = Path("/usr/local/bin/llama-server")
    m4b_path = Path("/models/qwen3.5-4b.gguf")
    m9b_path = Path("/models/qwen3.5-9b.gguf")

    # 4B command: must include --cache-prompt and MTP speculation flags
    cmd_4b = server_command(server_bin, m4b_path, MODELS["qwen3.5-4b"])
    assert "--cache-prompt" in cmd_4b
    assert "--spec-type" in cmd_4b
    assert "draft-mtp" in cmd_4b
    assert "--spec-draft-n-max" in cmd_4b
    assert "3" in cmd_4b

    # 9B command: must include --cache-prompt, must NOT include MTP draft speculation
    cmd_9b = server_command(server_bin, m9b_path, MODELS["qwen3.5-9b"])
    assert "--cache-prompt" in cmd_9b
    assert "draft-mtp" not in cmd_9b


def test_decide_escalation() -> None:
    # Under always-4b: never escalates even on failure
    assert decide_escalation(policy="always-4b", initial_pass=False) is False
    assert decide_escalation(policy="always-4b", initial_pass=True) is False

    # Under always-9b: never escalates
    assert decide_escalation(policy="always-9b", initial_pass=False) is False
    assert decide_escalation(policy="always-9b", initial_pass=True) is False

    # Under dynamic-cascade: escalates if initial pass is False, does not escalate if True
    assert decide_escalation(policy="dynamic-cascade", initial_pass=True) is False
    assert decide_escalation(policy="dynamic-cascade", initial_pass=False) is True


def test_summarize_cascade_results() -> None:
    records = [
        # always-4b trials
        {"policy": "always-4b", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 18.0, "escalated": False, "peak_vram_mib": 4800},
        {"policy": "always-4b", "task": "retry_policy", "strict_pass": False, "task_wall_seconds": 120.0, "escalated": False, "peak_vram_mib": 4850},
        # always-9b trials
        {"policy": "always-9b", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 25.0, "escalated": False, "peak_vram_mib": 7100},
        {"policy": "always-9b", "task": "retry_policy", "strict_pass": True, "task_wall_seconds": 47.0, "escalated": False, "peak_vram_mib": 7200},
        # dynamic-cascade trials
        {"policy": "dynamic-cascade", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 18.2, "escalated": False, "peak_vram_mib": 4820},
        {"policy": "dynamic-cascade", "task": "retry_policy", "strict_pass": True, "task_wall_seconds": 52.0, "escalated": True, "swap_duration_seconds": 4.1, "peak_vram_mib": 7210},
    ]

    summary = summarize_cascade_results(records)
    assert "policies" in summary

    p4b = summary["policies"]["always-4b"]
    assert p4b["trials"] == 2
    assert p4b["strict_pass_count"] == 1
    assert p4b["escalation_count"] == 0

    p9b = summary["policies"]["always-9b"]
    assert p9b["trials"] == 2
    assert p9b["strict_pass_count"] == 2
    assert p9b["escalation_count"] == 0

    p_dyn = summary["policies"]["dynamic-cascade"]
    assert p_dyn["trials"] == 2
    assert p_dyn["strict_pass_count"] == 2
    assert p_dyn["escalation_count"] == 1
    assert p_dyn["escalation_rate_pct"] == 50.0
