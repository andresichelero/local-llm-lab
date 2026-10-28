import json

import pytest

from benchmark.model_broker import BrokerPolicy, ModelBroker
from benchmark.practical_policy import BudgetPolicy


def broker(monkeypatch, **policy_options):
    p = BudgetPolicy.for_task({"max_requests": 20, "seconds": 180})
    b = ModelBroker(
        BrokerPolicy(
            upstream_port=12345,
            model_allowlist=("m",),
            request_limits=p.as_dict(),
            max_requests=p.max_model_requests,
            **policy_options,
        )
    )
    monkeypatch.setattr(
        b, "_upstream", lambda *a, **k: (200, "application/json", iter([b"{}"]), 2)
    )
    return b


def request_body(kind="main", *, user_text="task", **overrides):
    system = {
        "main": "You are opencode, a coding assistant.",
        "title": "You are a title generator.",
        "compaction": "You are a context summarization agent.",
    }[kind]
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }
    body.update(overrides)
    return json.dumps(body).encode()


def request(b, kind="main"):
    return b.handle("POST", "/v1/chat/completions", request_body(kind))[0]


def test_broker_keeps_metadata_and_housekeeping_out_of_main_allowance(monkeypatch):
    b = broker(monkeypatch)
    for _ in range(10):
        assert b.handle("GET", "/v1/models", b"")[0] == 200
    assert request(b, "title") == 200
    assert request(b, "compaction") == 200
    assert request(b, "compaction") == 200
    for _ in range(20):
        assert request(b) == 200
    exhausted = b.handle("POST", "/v1/chat/completions", request_body())
    assert exhausted[0] == 400, "terminal limits reply typed and non-retryable"
    assert json.loads(next(exhausted[2]))["error"]["message"] == "budget_exhausted:main"
    assert b.events[-1].outcome == "budget_exhausted:main"
    assert b.terminal_limit == "budget_exhausted:main"


def test_rejected_metadata_request_counts_attempt_without_using_budget(monkeypatch):
    b = broker(monkeypatch)

    assert b.handle("GET", "/v1/models", b"invalid body")[0] == 400
    snapshot = b.ledger.snapshot()
    assert snapshot["used"]["metadata"] == 0
    assert snapshot["attempted"]["metadata"] == 1

    for _ in range(10):
        assert b.handle("GET", "/v1/models", b"")[0] == 200
    snapshot = b.ledger.snapshot()
    assert snapshot["used"]["metadata"] == 10
    assert snapshot["attempted"]["metadata"] == 11


def test_broker_rejects_orphan_tool_result_as_contract_error(monkeypatch):
    b = broker(monkeypatch)
    status, *_ = b.handle(
        "POST",
        "/v1/chat/completions",
        json.dumps(
            {
                "model": "m",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are opencode, a coding assistant.",
                    },
                    {"role": "tool", "tool_call_id": "lost", "content": "done"},
                ],
            }
        ).encode(),
    )
    assert status == 400
    assert b.events[-1].outcome == "contract_error:orphan_tool_result"
    snapshot = b.ledger.snapshot()
    assert snapshot["used"]["main"] == 0
    assert snapshot["attempted"]["main"] == 1


@pytest.mark.parametrize(
    ("overrides", "user_text", "policy_options", "expected_status"),
    [
        ({"model": "blocked"}, "task", {}, 403),
        ({"unsupported_option": True}, "task", {}, 400),
        ({"temperature": 0.5}, "task", {}, 400),
        ({}, "task" + "x" * 40, {"max_request_bytes": 200}, 413),
    ],
)
def test_locally_rejected_categorized_requests_count_attempts_without_using_budget(
    monkeypatch, overrides, user_text, policy_options, expected_status
):
    b = broker(monkeypatch, **policy_options)

    status, *_ = b.handle(
        "POST", "/v1/chat/completions", request_body(user_text=user_text, **overrides)
    )

    assert status == expected_status
    snapshot = b.ledger.snapshot()
    assert snapshot["used"]["main"] == 0
    assert snapshot["attempted"]["main"] == 1

    assert request(b) == 200
    snapshot = b.ledger.snapshot()
    assert snapshot["used"]["main"] == 1
    assert snapshot["attempted"]["main"] == 2
