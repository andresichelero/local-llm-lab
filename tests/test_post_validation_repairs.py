"""Regression requirements found by the independent implementation audit."""

from __future__ import annotations

import copy
import socket
import threading

import pytest

from benchmark import practical_evidence as evidence
from benchmark import practical_mcp_bridge as bridge
from benchmark import practical_mcp_grading_v2 as grading
from benchmark import practical_review_replay as replay
from benchmark import practical_test_quality as quality
from test_practical_test_quality import _candidate, _make_snapshot


@pytest.mark.parametrize("failure", ["unknown", "configuration", None, "unrecognized"])
def test_unknown_execution_cannot_score(failure):
    row = {
        "status": "complete",
        "failure": failure,
        "correct": True,
        "autonomous": True,
    }
    assert evidence.is_scoring_eligible(row) is False


def test_explicit_invalid_execution_cannot_score():
    assert (
        evidence.is_scoring_eligible(
            {
                "status": "complete",
                "failure": "passed",
                "correct": True,
                "autonomous": True,
                "execution_valid": False,
            }
        )
        is False
    )


@pytest.mark.parametrize(
    "task,output",
    [
        (
            "B1",
            "ERROR: test_agent (unittest.loader._FailedTest.test_agent)\n"
            "ModuleNotFoundError: no helper\nRan 2 tests in 0.01s\nFAILED (errors=1)\n",
        ),
        (
            "B1",
            "ERROR: setUpClass (test_agent.Tests)\nRuntimeError: setup\n"
            "Ran 2 tests in 0.01s\nFAILED (errors=1)\n",
        ),
        (
            "B1",
            "ERROR: test_work (test_agent.Tests.test_work)\n"
            '  File "/workspace/tests/test_agent.py", line 3, in setUp\n'
            "RuntimeError: setup\nRan 2 tests in 0.01s\nFAILED (errors=1)\n",
        ),
        (
            "M1",
            "not ok 1 - /workspace/tests/test_agent.test.js\n"
            "  code: 'MODULE_NOT_FOUND'\n# tests 2\n# fail 1\n",
        ),
    ],
)
def test_counted_import_or_setup_error_is_not_regression(
    monkeypatch, tmp_path, task, output
):
    snapshot = _make_snapshot(tmp_path, {"tests/test_agent.py": "# fixture\n"})
    monkeypatch.setattr(
        quality,
        "run_seed_suite",
        lambda *a, **k: {
            "returncode": 1,
            "count": 2,
            "infrastructure": False,
            "timed_out": False,
            "output": output,
            "cleanup_verified": True,
            "suite_passed": False,
        },
    )
    assessment = quality.assess_authored_regression(
        task, snapshot, lab=tmp_path, candidate=_candidate()
    )
    assert assessment["quality"] == quality.UNVERIFIED


@pytest.mark.parametrize("prefix", [b"x", b"xx", b"xxx"])
def test_partial_mcp_header_is_not_clean_close(prefix):
    instance = bridge.McpBridge("C2")
    host, client = socket.socketpair()
    thread = threading.Thread(target=instance.serve_socket, args=(host,))
    thread.start()
    client.sendall(prefix)
    client.close()
    thread.join(timeout=2)
    try:
        assert not thread.is_alive()
        journal = instance.close()
        assert journal["fault"] and journal["clean_close"] is False
    finally:
        host.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "unclean",
        "no_state",
        "wrong_task",
        "unanswered",
        "wrong_state",
        "wrong_state_type",
    ],
)
def test_journal_consistency_is_required(mutation):
    from test_practical_mcp_bridge import _canonical_m2_run

    events, journal = _canonical_m2_run()
    altered = copy.deepcopy(journal)
    if mutation == "unclean":
        altered["clean_close"] = False
    if mutation == "no_state":
        altered["final_state"] = None
    if mutation == "wrong_task":
        altered["task"] = "C2"
    if mutation == "wrong_state":
        altered["final_state"]["apply_count"] = 99
    if mutation == "wrong_state_type":
        altered["final_state"]["apply_count"] = True
    if mutation == "unanswered":
        altered["records"].insert(
            -1,
            {
                "kind": "request",
                "method": "tools/call",
                "id": "pending",
                "params": {"name": "get_change", "arguments": {"change_id": "C-17"}},
            },
        )
        for number, record in enumerate(altered["records"], start=1):
            record["seq"] = number
    result = grading.grade_mcp_evidence(
        "M2", events, None, {"receipt.json": grading.EXPECTED["M2"]}, journal=altered
    )
    assert result["passed"] is False


def test_initial_capacity_failure_reaches_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(replay.runtime, "LAB", tmp_path / "lab")
    monkeypatch.setattr(replay, "_active_llama_servers", lambda: [])
    monkeypatch.setattr(
        replay,
        "prepare",
        lambda *a, **k: {"engineering_ready": True, "execution_capacity_ready": False},
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        replay, "_capacity_probe", lambda: SimpleNamespace(reason="still unavailable")
    )
    called = []
    monkeypatch.setattr(
        replay.runtime, "capacity_guard", lambda probe: called.append(True) or False
    )
    assert replay.execute_prepared(tmp_path / "out") == 2
    assert called == [True]
    assert (tmp_path / "out/capacity-wait.json").exists()
