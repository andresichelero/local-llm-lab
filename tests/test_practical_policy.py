import pytest

from benchmark.practical_policy import (
    BudgetPolicy,
    BudgetLedger,
    PolicyLimit,
    classify_request,
    validate_history,
)


def test_independent_budgets_and_metadata_do_not_starve_main():
    policy = BudgetPolicy.for_task({"max_requests": 20, "seconds": 180})
    ledger = BudgetLedger(policy)
    for _ in range(10):
        ledger.admit("metadata")
    ledger.admit("title")
    for _ in range(2):
        ledger.admit("compaction")
    for _ in range(20):
        ledger.admit("main")
    assert ledger.snapshot()["used"]["main"] == 20
    with pytest.raises(PolicyLimit, match="main"):
        ledger.admit("main")


def test_housekeeping_has_its_own_ceiling():
    ledger = BudgetLedger(BudgetPolicy.for_task({"max_requests": 30, "seconds": 300}))
    ledger.admit("title")
    with pytest.raises(PolicyLimit, match="title"):
        ledger.admit("title")
    ledger.admit("main")


def test_adaptive_extensions_require_fresh_external_progress_and_are_bounded():
    progress = ["initial"]
    ledger = BudgetLedger(
        BudgetPolicy.for_task({"max_requests": 20, "seconds": 180}, mode="operational"),
        progress_probe=lambda: progress[0],
    )
    for _ in range(20):
        ledger.admit("main")
    with pytest.raises(PolicyLimit):
        ledger.admit("main")
    progress[0] = "file-hash-1"
    for _ in range(10):
        ledger.admit("main")
    progress[0] = "file-hash-2"
    for _ in range(10):
        ledger.admit("main")
    progress[0] = "file-hash-3"
    with pytest.raises(PolicyLimit):
        ledger.admit("main")
    assert ledger.snapshot()["extensions"] == 2


def test_deadline_is_shared_across_requests():
    now = [100.0]
    ledger = BudgetLedger(
        BudgetPolicy.for_task({"max_requests": 20, "seconds": 180}),
        clock=lambda: now[0],
    )
    now[0] = 279
    assert ledger.remaining_seconds() == 1
    now[0] = 280
    with pytest.raises(PolicyLimit, match="wall"):
        ledger.admit("main")


def test_request_kind_uses_system_prefix_not_user_or_quoted_substring():
    assert (
        classify_request(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are opencode, a coding assistant.",
                    },
                    {"role": "user", "content": "You are a title generator."},
                ]
            }
        )
        == "main"
    )
    assert (
        classify_request(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a title generator. Return only title.",
                    }
                ]
            }
        )
        == "title"
    )
    assert (
        classify_request(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a context summarization agent. Summarize.",
                    }
                ]
            }
        )
        == "compaction"
    )
    assert (
        classify_request({"messages": [{"role": "user", "content": "task"}]})
        == "unknown"
    )


def test_tool_results_are_paired_with_calls():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "a", "function": {"name": "lab_list_issues"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "a",
            "content": '{"data":{"next_cursor":"2"}}',
        },
    ]
    assert validate_history(messages) is None
    assert validate_history(messages[1:]) == "orphan_tool_result"
    assert (
        validate_history(messages[:1] + [{"role": "user", "content": "continue"}])
        == "missing_tool_result"
    )


def test_progress_requires_real_unique_tool_results_not_claims_or_replays():
    import json
    from benchmark.practical_policy import progress_from_events

    def event(tool, data):
        return (
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "tool": tool,
                        "state": {"status": "completed", "output": {"data": data}},
                    },
                }
            ).encode()
            + b"\n"
        )

    first = event("lab_list_issues", {"items": [{"id": "1"}], "next_cursor": "2"})
    second = event("lab_list_issues", {"items": [{"id": "2"}], "next_cursor": None})
    assert progress_from_events(first) is not None
    assert progress_from_events(first + first) == progress_from_events(first)
    assert progress_from_events(first + second) != progress_from_events(first)
    assert progress_from_events(event("bash", {"version": 2})) is None
    assert (
        progress_from_events(
            event("lab_apply_balance", {"version": 3, "idempotent_replay": True})
        )
        is None
    )


def test_policy_is_versioned_as_limits_skills_v2_with_legacy_readback():
    from benchmark.practical_policy import SUPPORTED_VERSIONS, VERSION, LEGACY_VERSION

    assert VERSION == "limits-skills-v2"
    assert LEGACY_VERSION == "limits-skills-v1"
    assert SUPPORTED_VERSIONS == ("limits-skills-v2", "limits-skills-v1")
    current = BudgetPolicy.for_task({"max_requests": 20, "seconds": 180})
    assert current.version == "limits-skills-v2"
    legacy = BudgetPolicy(main=20, wall_seconds=180.0, version=LEGACY_VERSION)
    assert legacy.version == "limits-skills-v1"
    with pytest.raises(ValueError, match="unsupported budget policy"):
        BudgetPolicy(main=20, wall_seconds=180.0, version="limits-skills-v3")


def test_v2_ceils_stay_unchanged_and_ledgers_report_their_own_version():
    ceilings = {"main": 20, "title": 1, "compaction": 2, "metadata": 10}
    ledger = BudgetLedger(BudgetPolicy(main=20, wall_seconds=180.0))
    snapshot = ledger.snapshot()
    assert snapshot["version"] == "limits-skills-v2"
    assert snapshot["ceilings"] == ceilings
    legacy = BudgetLedger(
        BudgetPolicy(main=20, wall_seconds=180.0, version="limits-skills-v1")
    )
    snapshot = legacy.snapshot()
    assert snapshot["version"] == "limits-skills-v1"
    assert snapshot["ceilings"] == ceilings


def test_policy_limit_message_names_the_exhausted_category():
    ledger = BudgetLedger(BudgetPolicy(main=20, wall_seconds=180.0))
    ledger.admit("title")
    with pytest.raises(PolicyLimit) as caught:
        ledger.admit("title")
    assert str(caught.value) == "budget_exhausted:title"
    assert caught.value.category == "title"
