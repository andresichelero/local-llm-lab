"""Test the real v2 MCP stdio protocol, idempotency, and trusted grading."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from benchmark import practical_mcp_v2 as mcp
from benchmark import practical_mcp_grading_v2 as grading


def invoke(server, events, name, arguments):
    try:
        result = server.call(name, arguments)
        is_error = False
    except mcp.ToolFailure as exc:
        result = json.loads(str(exc))
        is_error = True
    event = {
        "name": name,
        "arguments": arguments,
        "result": result,
        "isError": is_error,
    }
    events.append(event)
    return result


def pages(server, events, tool):
    cursor, rows = None, []
    while True:
        result = invoke(server, events, tool, {"cursor": cursor, "page_size": 2})
        rows.extend(result["data"]["items"])
        cursor = result["data"]["next_cursor"]
        if cursor is None:
            return rows


def report_c2(server, events):
    rows = pages(server, events, "list_issues")
    report = {
        "open_ids": sorted(row["id"] for row in rows if row["status"] == "open"),
        "total_estimate": sum(
            row["estimate"] for row in rows if row["status"] == "open"
        ),
    }
    invoke(server, events, "write_report", {"report": report})
    return report


def report_c2_with_sizes(server, events):
    cursor, rows = None, []
    sizes = iter((1, 2, 1, 2, 1, 2))
    while True:
        result = invoke(
            server,
            events,
            "list_issues",
            {
                "cursor": cursor,
                "page_size": next(sizes),
            },
        )
        rows.extend(result["data"]["items"])
        cursor = result["data"]["next_cursor"]
        if cursor is None:
            break
    report = {
        "open_ids": sorted(row["id"] for row in rows if row["status"] == "open"),
        "total_estimate": sum(
            row["estimate"] for row in rows if row["status"] == "open"
        ),
    }
    invoke(server, events, "write_report", {"report": report})
    return report


def complete_m2(server, events):
    invoke(server, events, "get_change", {"change_id": "C-17"})
    stale_args = {"change_id": "C-17", "version": 1, "idempotency_key": "C-17-v2"}
    invoke(server, events, "apply_change", stale_args)
    invoke(server, events, "get_change", {"change_id": "C-17"})
    current_args = {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}
    invoke(server, events, "apply_change", current_args)
    invoke(server, events, "apply_change", current_args)


def test_recovery_accepts_extra_reads_and_idempotent_confirmation(tmp_path):
    server = mcp.Server(tmp_path / "state.json")
    events = []
    complete_m2(server, events)
    invoke(server, events, "get_change", {"change_id": "C-17"})
    invoke(
        server,
        events,
        "apply_change",
        {
            "change_id": "C-17",
            "version": 2,
            "idempotency_key": "C-17-v2",
        },
    )
    result = grading.grade_mcp_evidence(
        "M2",
        events,
        artifacts={
            "receipt.json": {"change_id": "C-17", "applied": True, "version": 2},
        },
    )
    assert result["passed"], result
    assert server.state["apply_count"] == 1


def complete_d2(server, events):
    accounts = pages(server, events, "list_accounts")
    adjustments = pages(server, events, "list_adjustments")
    first, duplicates = {}, set()
    for row in adjustments:
        if row["id"] in first:
            duplicates.add(row["id"])
        else:
            first[row["id"]] = row
    balances = {row["account_id"]: row["balance_cents"] for row in accounts}
    for row in first.values():
        if row["status"] == "posted":
            balances[row["account_id"]] += row["delta_cents"]
    changed = sorted(
        key
        for key, value in balances.items()
        if value
        != next(row["balance_cents"] for row in accounts if row["account_id"] == key)
    )
    report = {
        "balances": dict(sorted(balances.items())),
        "changed_ids": changed,
        "ignored_duplicate_ids": sorted(duplicates),
        "total_balance_cents": sum(balances.values()),
    }
    for account_id in changed:
        account = next(row for row in accounts if row["account_id"] == account_id)
        invoke(
            server,
            events,
            "apply_balance",
            {
                "account_id": account_id,
                "version": account["version"],
                "target_balance_cents": balances[account_id],
                "idempotency_key": f"{account_id}-v{account['version']}",
            },
        )
    invoke(server, events, "write_reconciliation", {"report": report})
    return report


def complete_h2(server, events):
    assets = pages(server, events, "list_assets")
    audits = pages(server, events, "list_audits")
    first, duplicates = {}, set()
    for audit in audits:
        if audit["id"] in first:
            duplicates.add(audit["id"])
        else:
            first[audit["id"]] = audit
    latest = {}
    for audit in first.values():
        current = latest.get(audit["asset_id"])
        if current is None or audit["observed_at"] > current["observed_at"]:
            latest[audit["asset_id"]] = audit
    statuses = {asset["asset_id"]: asset["status"] for asset in assets}
    changed = []
    for asset in assets:
        status = latest[asset["asset_id"]]["status"]
        if status != asset["status"]:
            changed.append(asset["asset_id"])
            statuses[asset["asset_id"]] = status
            invoke(
                server,
                events,
                "set_asset_status",
                {
                    "asset_id": asset["asset_id"],
                    "version": asset["version"],
                    "status": status,
                    "idempotency_key": f"{asset['asset_id']}-v{asset['version']}-{status}",
                },
            )
    report = {
        "changed_ids": sorted(changed),
        "statuses": dict(sorted(statuses.items())),
    }
    invoke(server, events, "write_asset_report", {"report": report})
    return report


def grade(task, events, artifact_name, artifact, state=None, **kwargs):
    return grading.grade_mcp_evidence(
        task,
        events,
        state=state,
        artifacts={artifact_name: artifact},
        **kwargs,
    )


def test_pagination_reports_and_mcp_tool_evidence(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    events = []
    report = report_c2(server, events)
    assert report == grading.EXPECTED["C2"]
    assert grade("C2", events, "report.json", report)["passed"]

    # Public tool results contain task data, never the grader's audit state.
    response = server.respond(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "list_issues",
                "arguments": {"cursor": None, "page_size": 2},
            },
        }
    )
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["data"]["items"] == mcp.ISSUES[:2]
    assert set(content) == {"data"}


def test_c2_write_report_schema_describes_the_report_fields():
    tool = next(item for item in mcp.TOOLS if item["name"] == "write_report")
    report = tool["inputSchema"]["properties"]["report"]
    assert report["properties"] == {
        "open_ids": {"type": "array", "items": {"type": "integer"}},
        "total_estimate": {"type": "integer"},
    }
    assert report["required"] == ["open_ids", "total_estimate"]
    assert report["additionalProperties"] is False


def test_c2_write_report_rejects_schema_wrapper_instead_of_storing_it(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json", task="C2")
    events = []
    result = invoke(server, events, "write_report", {
        "report": {"additionalProperties": grading.EXPECTED["C2"]},
    })
    assert events[-1]["isError"]
    assert "report must contain open_ids" in result["error"]
    assert server.state.get("report") is None


def test_final_report_can_correct_an_earlier_submission(tmp_path):
    server = mcp.Server(tmp_path/'state.json', task='C2')
    events = []
    pages(server, events, 'list_issues')
    invoke(server, events, 'write_report', {'report': {**grading.EXPECTED['C2'], 'total_estimate': 19}})
    invoke(server, events, 'write_report', {'report': grading.EXPECTED['C2']})
    assert grade('C2', events, 'report.json', grading.EXPECTED['C2'])['passed']


def test_cursor_schema_announces_the_fallback_page_size_of_two():
    for name in ("list_issues", "list_accounts", "list_adjustments",
                 "list_assets", "list_audits"):
        tool = next(item for item in mcp.TOOLS if item["name"] == name)
        page = tool["inputSchema"]["properties"]["page_size"]
        assert page["default"] == 2, name
        assert "2" in page["description"], name


def test_c2_strict_contract_counts_confirmed_replay_as_failure(tmp_path):
    server = mcp.Server(tmp_path/'state.json', task='C2')
    events = []
    pages(server, events, 'list_issues')
    invoke(server, events, 'write_report',
           {'report': {**grading.EXPECTED['C2'], 'total_estimate': 19}})
    invoke(server, events, 'write_report', {'report': grading.EXPECTED['C2']})
    artifact = grading.EXPECTED['C2']
    repeated = grade('C2', events, 'report.json', artifact)
    assert repeated['passed']                 # historical: workflow diagnostic only
    assert grade('C2', events, 'report.json', artifact,
                 task_contract_id=grading.HISTORICAL_CONTRACT)['passed']
    strict = grading.grade_mcp_evidence(
        'C2', events, artifacts={'report.json': artifact},
        task_contract_id=grading.C2_STRICT_CONTRACT)
    assert not strict['passed']
    assert 'exactly once' in strict['reason']


def test_c2_strict_contract_accepts_denied_attempt_then_one_success(tmp_path):
    server = mcp.Server(tmp_path/'state.json', task='C2')
    events = []
    pages(server, events, 'list_issues')
    invoke(server, events, 'write_report', {'report': {}})
    invoke(server, events, 'write_report', {'report': grading.EXPECTED['C2']})
    assert events[-2]['isError']
    result = grading.grade_mcp_evidence(
        'C2', events, artifacts={'report.json': grading.EXPECTED['C2']},
        task_contract_id=grading.C2_STRICT_CONTRACT)
    assert result['passed'], result


def test_grade_mcp_evidence_validates_contract_ids(tmp_path):
    server = mcp.Server(tmp_path/'state.json', task='C2')
    events = []
    report_c2(server, events)
    for contract in ('workflows-v9', 'm1-independent-copy-v1'):
        with __import__('pytest').raises(ValueError):
            grading.grade_mcp_evidence('C2', events, task_contract_id=contract)
    with __import__('pytest').raises(ValueError):
        grading.grade_mcp_evidence('D2', [], task_contract_id=grading.C2_STRICT_CONTRACT)


def test_variable_page_sizes_follow_returned_cursors(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    events = []
    report = report_c2_with_sizes(server, events)
    assert report == grading.EXPECTED["C2"]
    assert grade("C2", events, "report.json", report)["passed"]


def test_workspace_state_cannot_replace_native_tool_evidence():
    forged = {"report": grading.EXPECTED["C2"]}
    assert not grade("C2", [], "report.json", grading.EXPECTED["C2"], state=forged)[
        "passed"
    ]


def test_m2_requires_stale_then_transient_retry_and_one_effect(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    events = []
    complete_m2(server, events)
    assert server.state["apply_count"] == 1
    assert events[1]["isError"] is True
    assert "stale" in events[1]["result"]["error"]
    assert events[3]["isError"] is True
    assert "temporary" in events[3]["result"]["error"]
    assert grade("M2", events, "receipt.json", grading.EXPECTED["M2"])["passed"]

    skipped_refresh = [events[0], events[1], events[3], events[4]]
    assert not grade("M2", skipped_refresh, "receipt.json", grading.EXPECTED["M2"])[
        "passed"
    ]
    assert not grade(
        "M2",
        events,
        "receipt.json",
        {"change_id": "C-17", "applied": True, "version": 1},
    )["passed"]


def test_d2_reconciliation_pages_changes_and_state(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    events = []
    report = complete_d2(server, events)
    assert report == grading.EXPECTED["D2"]
    assert grade("D2", events, "reconciliation.json", report)["passed"]
    assert server.state["account_apply_count"] == {"A-01": 1, "A-02": 1}
    assert {
        row["account_id"]: row["balance_cents"] for row in server.state["accounts"]
    } == report["balances"]
    assert not grade("D2", events[:-1], "reconciliation.json", report)["passed"]


def test_h2_uses_first_audit_id_and_latest_distinct_audit(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    events = []
    report = complete_h2(server, events)
    assert report == grading.EXPECTED["H2"]
    assert grade("H2", events, "asset-report.json", report)["passed"]
    assert len(server.state["updated_by_key"]) == 2


def test_public_results_hide_audit_and_host_replay_is_task_scoped(tmp_path):
    scenarios = [
        ("C2", report_c2, {"sequence", "call", "report"}),
        (
            "M2",
            complete_m2,
            {
                "sequence",
                "call",
                "current_version",
                "get_change_reads",
                "temporary_seen",
                "apply_count",
                "applied_by_key",
            },
        ),
        (
            "D2",
            complete_d2,
            {
                "sequence",
                "call",
                "account_count",
                "account_balances",
                "account_apply_count",
                "account_applied_by_key",
                "reconciliation",
            },
        ),
        (
            "H2",
            complete_h2,
            {
                "sequence",
                "call",
                "asset_count",
                "asset_statuses",
                "updated_by_key",
                "asset_report",
            },
        ),
    ]
    private_catalogs = {"accounts", "adjustments", "assets", "audits"}
    for task, run, fields in scenarios:
        server = mcp.Server(tmp_path / f"{task}-state.json")
        events = []
        run(server, events)
        assert events
        for event in events:
            serialized = json.dumps(event["result"], ensure_ascii=False)
            assert len(serialized.encode("utf-8")) < 6000
            assert "_audit" not in event["result"]
        replayed = grading.replay_mcp_evidence(task, events)
        for event in replayed:
            audit = event["audit"]
            assert set(audit) == fields
            assert not private_catalogs.intersection(audit)


def test_idempotency_keys_apply_effect_once(tmp_path):
    server = mcp.Server(tmp_path / "server-state.json")
    args = {
        "account_id": "A-01",
        "version": 2,
        "target_balance_cents": 1175,
        "idempotency_key": "A-01-v2",
    }
    first = server.call("apply_balance", args)
    replay = server.call("apply_balance", args)
    assert first["data"]["idempotent_replay"] is False
    assert replay["data"]["idempotent_replay"] is True
    assert server.state["account_apply_count"] == {"A-01": 1}
    with __import__("pytest").raises(mcp.ToolFailure):
        server.call("apply_balance", {**args, "target_balance_cents": 88})


def test_real_stdio_jsonrpc_returns_only_public_data(tmp_path):
    source = Path(importlib.util.find_spec("benchmark.practical_mcp_v2").origin)
    process = subprocess.Popen(
        [sys.executable, str(source), str(tmp_path / "state.json")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        for ident, method, params in [
            (1, "initialize", {"protocolVersion": "2024-11-05"}),
            (2, "tools/list", {}),
        ]:
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": ident,
                        "method": method,
                        "params": params,
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            assert response["id"] == ident
            assert "result" in response
        names = {tool["name"] for tool in response["result"]["tools"]}
        assert {
            "list_issues",
            "write_report",
            "apply_balance",
            "set_asset_status",
        } <= names
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "list_issues",
                        "arguments": {"cursor": None, "page_size": 2},
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        result = json.loads(process.stdout.readline())["result"]
        decoded = json.loads(result["content"][0]["text"])
        assert decoded["data"]["items"] == mcp.ISSUES[:2]
        assert set(decoded) == {"data"}
        assert result["isError"] is False
    finally:
        process.stdin.close()
        process.wait(timeout=5)


def test_task_scoped_tool_discovery_and_calls(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="M2")
    response = server.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert {tool["name"] for tool in response["result"]["tools"]} == {
        "get_change", "apply_change",
    }
    with __import__("pytest").raises(mcp.ToolFailure, match="not available"):
        server.call("write_report", {"report": {}})


def test_stdio_cli_accepts_task_scope(tmp_path):
    source = Path(importlib.util.find_spec("benchmark.practical_mcp_v2").origin)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    result = subprocess.run(
        [sys.executable, str(source), str(tmp_path / "state.json"), "M2"],
        input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert {tool["name"] for tool in response["result"]["tools"]} == {
        "get_change", "apply_change",
    }
    assert not (tmp_path / "state.json").exists()


def test_replay_rejects_fabricated_public_data_and_ignores_forged_audit(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="C2")
    events = []
    report = report_c2(server, events)
    events[-1]["result"]["_audit"] = {"report": {"forged": True}}
    assert grade("C2", events, "report.json", report)["passed"]
    events[0]["result"]["data"]["items"][0]["estimate"] = 9999
    result = grade("C2", events, "report.json", report)
    assert not result["passed"]
    assert "captured result" in result["reason"]


def test_m2_errors_do_not_reveal_current_version_or_apply_counters(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="M2")
    events = []
    complete_m2(server, events)
    for event in events:
        assert "_audit" not in event["result"]
        assert not {"current_version", "apply_count", "temporary_seen"}.intersection(
            event["result"]
        )
    assert grading.expected_tool_errors("M2", events) == 2
    assert grading.expected_tool_errors("C2", []) == 0


def test_m2_prompt_does_not_require_unavailable_report_tool(tmp_path):
    from benchmark import practical_tasks_v2 as tasks

    prompt = tasks.seed_task("M2", tmp_path)
    assert "only when the task explicitly requests" in prompt


def test_m2_reused_key_cannot_confirm_a_different_change(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="M2")
    complete_m2(server, [])
    with __import__("pytest").raises(mcp.ToolFailure):
        server.call("apply_change", {
            "change_id": "OTHER", "version": 2, "idempotency_key": "C-17-v2",
        })
    assert server.state["apply_count"] == 1


def test_expected_recovery_errors_survive_a_later_bad_call(tmp_path):
    server = mcp.Server(tmp_path / "state.json")
    events = []
    complete_m2(server, events)
    invoke(server, events, "write_report", {"report": {}})
    assert grading.expected_tool_errors("M2", events) == 2
    assert not grade("M2", events, "receipt.json", grading.EXPECTED["M2"])["passed"]


def test_pagination_allows_reread_with_different_page_size(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="C2")
    events = []
    invoke(server, events, "list_issues", {"page_size": 1})
    invoke(server, events, "list_issues", {"page_size": 2})
    invoke(server, events, "list_issues", {"cursor": "2"})
    invoke(server, events, "list_issues", {"cursor": "4"})
    report = grading.EXPECTED["C2"]
    invoke(server, events, "write_report", {"report": report})
    invoke(server, events, "list_issues", {"page_size": 1})
    assert grade("C2", events, "report.json", report)["passed"]


def test_pagination_still_rejects_a_missing_middle_page(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="C2")
    events = []
    invoke(server, events, "list_issues", {})
    invoke(server, events, "list_issues", {"cursor": "4"})
    report = grading.EXPECTED["C2"]
    invoke(server, events, "write_report", {"report": report})
    result = grade("C2", events, "report.json", report)
    assert not result["passed"]
    assert "pagination" in result["reason"]


def test_post_update_verification_reads_and_idempotent_replays(tmp_path):
    scenarios = [
        ("D2", complete_d2, "reconciliation.json", "list_accounts", "apply_balance"),
        ("H2", complete_h2, "asset-report.json", "list_assets", "set_asset_status"),
    ]
    for task, complete, artifact, list_tool, apply_tool in scenarios:
        server = mcp.Server(tmp_path / f"{task}.json", task=task)
        events = []
        report = complete(server, events)
        invoke(server, events, list_tool, {"page_size": 1})
        args = next(event["arguments"] for event in events if event["name"] == apply_tool)
        invoke(server, events, apply_tool, args)
        result = grade(task, events, artifact, report)
        if task == "D2":
            # The D2 text already requires one call per changed account, so an
            # idempotent replay must not substitute the confirmed call. H2 has
            # no such written rule and stays tolerant.
            assert not result["passed"], result
            assert "exactly one confirmed apply" in result["reason"]
        else:
            assert result["passed"], result


def test_d2_redundant_idempotent_replay_does_not_satisfy_a_confirmed_call(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="D2")
    events = []
    report = complete_d2(server, events)
    assert grade("D2", events, "reconciliation.json", report)["passed"]
    retry_args = next(event["arguments"] for event in events
                      if event["name"] == "apply_balance")
    replay = invoke(server, events, "apply_balance", retry_args)
    assert replay["data"]["idempotent_replay"] is True
    assert server.state["account_apply_count"] == {"A-01": 1, "A-02": 1}
    result = grade("D2", events, "reconciliation.json", report)
    assert not result["passed"], result
    assert "exactly one confirmed apply" in result["reason"]


def test_m2_preserved_recovery_flow_is_untouched(tmp_path):
    server = mcp.Server(tmp_path / "state.json", task="M2")
    events = []
    complete_m2(server, events)
    assert server.state["apply_count"] == 1
    result = grade("M2", events, "receipt.json", grading.EXPECTED["M2"])
    assert result["passed"], result
    assert grading.expected_tool_errors("M2", events) == 2
