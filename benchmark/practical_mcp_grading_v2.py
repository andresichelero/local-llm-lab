"""Host-only grading for captured practical v2 MCP evidence."""

from __future__ import annotations

import json

from benchmark.practical_mcp_bridge import trusted_calls, validate_journal, same_json
from benchmark.practical_mcp_v2 import (
    ACCOUNTS,
    ADJUSTMENTS,
    ASSETS,
    AUDITS,
    ISSUES,
    Server,
    ToolFailure,
    TASK_TOOLS,
    TOOLS,
)

_TOOL_NAMES = {tool["name"] for tool in TOOLS}
EXPECTED = { "C2": {"open_ids": [101, 103, 104, 106], "total_estimate": 18},
    "M2": {"change_id": "C-17", "applied": True, "version": 2},
    "D2": {
        "balances": {"A-01": 1175, "A-02": 425, "A-03": -25},
        "changed_ids": ["A-01", "A-02"],
        "ignored_duplicate_ids": ["ADJ-1"],
        "total_balance_cents": 1575,
    },
    "H2": {
        "changed_ids": ["AS-2", "AS-4"],
        "statuses": {
            "AS-1": "active",
            "AS-2": "active",
            "AS-3": "retired",
            "AS-4": "retired",
        },
    },
}

C2_STRICT_CONTRACT = "mcp-no-confirmed-replay-v1"
HISTORICAL_CONTRACT = "historical-v2"
_HISTORICAL_CONTRACTS = frozenset({None, HISTORICAL_CONTRACT})


def _strict_write_cardinality(task, task_contract_id) -> bool:
    """Resolve the C2 write-cardinality rule announced by the contract id.

    The historical profile (no contract id, or ``historical-v2``) never gains a
    new functional reproval from a repeated confirmed write; under
    ``mcp-no-confirmed-replay-v1`` a confirmed submission may appear exactly
    once. Unknown or inapplicable ids are review cases, never silent regrades.
    """
    if task_contract_id in _HISTORICAL_CONTRACTS:
        return False
    if task_contract_id == C2_STRICT_CONTRACT and task == "C2":
        return True
    raise ValueError(
        f"unknown or inapplicable MCP task contract {task_contract_id!r} for {task!r}"
    )


def _decode_result(value):
    if isinstance(value, dict) and "content" in value:
        for part in value.get("content", []):
            if part.get("type") == "text":
                try:
                    return json.loads(part.get("text", ""))
                except (TypeError, json.JSONDecodeError):
                    pass
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _tool_name(event):
    raw = str(event.get("name", event.get("tool", "")))
    if raw in _TOOL_NAMES:
        return raw
    for name in _TOOL_NAMES:
        if (
            raw.endswith("__" + name)
            or raw.endswith("." + name)
            or raw.endswith("_" + name)
        ):
            return name
    return raw


def _trusted_record_result(envelope):
    """Decode a trusted journal response envelope to the observed MCP payload."""
    if not isinstance(envelope, dict):
        return None, None
    result = envelope.get("result") if "result" in envelope else envelope.get("error")
    if isinstance(result, dict) and "structuredContent" in result:
        payload = result["structuredContent"]
    elif result is not None:
        payload = _decode_result(result)
    else:
        payload = None
    is_error = bool(result.get("isError")) if isinstance(result, dict) else True
    return payload, is_error


def reconcile_journal_events(events, journal, *, task=None):
    """Reconcile public opencode events with the trusted host-side journal.

    The journal is the trusted request/response record of the episode's MCP
    channel.  A journal schema that is missing or unrecognized, a reported
    channel fault, absent, incomplete, reordered or result-divergent public
    events are all rejected explicitly.  ``None`` means the public sequence
    explains the trusted sequence exactly.
    """
    problem = validate_journal(journal, task=task)
    if problem:
        return problem
    try:
        trusted = trusted_calls(journal)
    except (ValueError, TypeError, KeyError) as exc:
        return f'trusted MCP journal is incomplete: {exc}'
    public = _events(events)
    if len(public) < len(trusted):
        return ("public MCP events are incomplete: "
                f"{len(trusted) - len(public)} trusted calls unobserved")
    if len(public) > len(trusted):
        return "public MCP events include calls absent from the trusted journal"
    for index, (call, entry) in enumerate(zip(trusted, public), start=1):
        if call["name"] != entry["name"] or call["arguments"] != entry["arguments"]:
            return f"public MCP call {index} diverges from the trusted journal"
        expected_result, expected_error = _trusted_record_result(call["envelope"])
        if entry.get("isError") != expected_error or not same_json(entry["result"], expected_result):
            return f"public MCP result {index} diverges from the trusted journal"
    return None


def _events(events):
    normalized = []
    for event in events or ():
        if not isinstance(event, dict):
            continue
        name = _tool_name(event)
        if name not in _TOOL_NAMES:
            continue
        result = _decode_result(event.get("result", event.get("output")))
        is_error = bool(event.get("isError", event.get("is_error", False)))
        if isinstance(result, dict) and "error" in result:
            is_error = is_error or bool(result.get("error"))
        normalized.append(
            {
                "name": name,
                "arguments": event.get("arguments", event.get("input", {})) or {},
                "result": result,
                "isError": is_error,
                "audit": result.get("_audit") if isinstance(result, dict) else None,
            }
        )
    return normalized


def _data(event):
    result = event["result"]
    return result.get("data") if isinstance(result, dict) else None


def _audit_state(events, state):
    # Only host replay attaches these audits. Never use candidate workspace state.
    for event in reversed(events):
        if isinstance(event.get("audit"), dict):
            return event["audit"]
    return {}


def _allowed_tools(task):
    return TASK_TOOLS[task]


def _replay_mcp_evidence(task, events):
    """Validate captured public results against deterministic host-side execution.

    This is a verifier, not a replacement for observed tool calls: every event
    must contain the public result actually captured from the agent transaction.
    The in-memory server recreates state privately, without returning its audit
    to the agent or trusting an audit supplied in historical evidence.
    """
    server = Server(task=task)
    calls = _events(events)
    for call in calls:
        if call["name"] not in _allowed_tools(task):
            raise ValueError("captured calls include a tool outside this task")
        try:
            expected = server.call(call["name"], call["arguments"])
            failed = False
        except ToolFailure as exc:
            expected = json.loads(str(exc))
            failed = True
        observed = call["result"]
        if isinstance(observed, dict):
            observed = {key: value for key, value in observed.items() if key != "_audit"}
        if call["isError"] != failed or observed != expected:
            raise ValueError("captured result does not match deterministic server replay")
        call["result"] = expected
        call["audit"] = server._snapshot(server.state["calls"][-1])
        yield call


def replay_mcp_evidence(task, events):
    """Return all verified calls; fail rather than grade an incomplete replay."""
    return list(_replay_mcp_evidence(task, events))


def expected_tool_errors(task, events):
    """Count each deliberately injected M2 recovery error once, after verification."""
    if task != "M2":
        return 0
    expected = {
        1: "stale or invalid version; read current change and retry",
        2: "temporary service failure; retry the same request and key",
    }
    seen = set()
    try:
        for call in _replay_mcp_evidence(task, events):
            args = call["arguments"]
            if (call["name"] == "apply_change" and call["isError"]
                    and isinstance(args, dict) and type(args.get("version")) is int
                    and args.get("change_id") == "C-17"
                    and args.get("idempotency_key") == "C-17-v2"
                    and call["result"].get("error") == expected.get(args["version"])):
                seen.add(args["version"])
    except (ValueError, TypeError, KeyError):
        # A later bad call must not relabel already validated injected faults.
        pass
    return len(seen)


def _position(events, predicate):
    return max(
        (index for index, event in enumerate(events) if predicate(event)), default=-1
    )


def _fail(reason):
    return {"passed": False, "reason": reason, "failures": [reason]}


def _ok():
    return {
        "passed": True,
        "reason": "trusted MCP evidence matches task",
        "failures": [],
    }


def _pagination_end(events, tool, rows):
    """Find the first complete cursor chain; extra verified reads are harmless."""
    returned_cursors = {None}
    for index, event in enumerate(events):
        if event["name"] != tool:
            continue
        args = event["arguments"]
        requested = args.get("cursor")
        if event["isError"]:
            continue
        if requested not in returned_cursors:
            continue
        size = args.get("page_size", 2)
        if type(size) is not int or not 1 <= size <= 2:
            return None, f"{tool}: successful call used an invalid page_size"
        result = _data(event)
        offset = 0 if requested is None else int(requested)
        expected_items = rows[offset : offset + size]
        next_offset = offset + len(expected_items)
        next_cursor = str(next_offset) if next_offset < len(rows) else None
        if result != {"items": expected_items, "next_cursor": next_cursor}:
            return None, f"{tool}: page result does not match the server catalog"
        if next_cursor is None:
            return index, ""
        returned_cursors.add(next_cursor)
    return None, f"{tool}: pagination did not reach next_cursor null"


def _page_checks(events, tool, rows):
    index, reason = _pagination_end(events, tool, rows)
    return index is not None, reason


def grade_mcp_evidence(task, events, state=None, artifacts=None, *,
                       journal=None, task_contract_id=None):
    """Grade native MCP requests/results with privately replayed server state.

    Events have name, arguments, result, and isError fields. Results may be
    decoded objects or MCP content envelopes containing JSON text. Every public
    result is checked against deterministic replay. Supplied state and audit
    fields are ignored; this helper never reads candidate workspace state.

    When a trusted ``journal`` from the episode's dedicated MCP channel is
    available, the public event sequence must first reconcile with it exactly
    (same calls, same order, same observed results); the candidate may not
    supply a state file, and a journal that reports a channel fault fails the
    channel as infrastructure.

    ``task_contract_id`` selects the functional contract: ``None`` or
    ``historical-v2`` keep the historical profile: the last confirmed write is
    compared, so a repeated confirmed C2 write stays a workflow diagnostic, not
    a new functional reproval. ``mcp-no-confirmed-replay-v1`` is the strict C2
    contract announced for future episodes: exactly one successful
    ``write_report`` after pagination, while previously denied attempts never
    reject it. Unknown or inapplicable ids raise ValueError instead of
    silently regrading; D2 already enforces one confirmed apply per account in
    the historical contract, so it has no separate strict id.
    """
    if task not in EXPECTED:
        return _fail(f"unknown MCP task {task!r}")
    if journal is not None and state is not None:
        raise ValueError("candidate-supplied MCP state is never graded")
    if journal is not None:
        divergence = reconcile_journal_events(events, journal, task=task)
        if divergence is not None:
            return _fail(divergence)
    strict_writes = _strict_write_cardinality(task, task_contract_id)
    try:
        calls = replay_mcp_evidence(task, events)
    except (ValueError, TypeError, KeyError) as exc:
        return _fail(str(exc))
    if not calls:
        return _fail("no captured MCP tool calls")
    if any(call["name"] not in _allowed_tools(task) for call in calls):
        return _fail("captured calls include a tool outside this task")
    trusted = _audit_state(calls, state)
    artifacts = artifacts or {}

    if task == "C2":
        ok, reason = _page_checks(calls, "list_issues", ISSUES)
        if not ok:
            return _fail(reason)
        writes = [call for call in calls if call['name'] == 'write_report' and not call['isError']]
        expected = EXPECTED["C2"]
        if strict_writes:
            # Announced contract: one successful submission after pagination;
            # a denied attempt is allowed and never counts as the submission.
            if len(writes) != 1:
                return _fail(
                    "write_report must succeed exactly once under "
                    + C2_STRICT_CONTRACT
                )
            submission = writes[0]
        else:
            if not writes:
                return _fail("write_report must succeed once")
            submission = writes[-1]
        final_page, _ = _pagination_end(calls, "list_issues", ISSUES)
        if _position(calls, lambda c: c['name'] == 'write_report' and not c['isError']) <= final_page:
            return _fail("write_report must follow successful pagination")
        if submission["arguments"].get("report") != expected:
            return _fail("wrong report submitted")
        if trusted.get("report") != expected:
            return _fail("server did not store the report")
        if artifacts.get("report.json") != expected:
            return _fail("report.json is missing or incorrect")
        return _ok()

    if task == "M2":
        relevant = [
            call for call in calls if call["name"] in {"get_change", "apply_change"}
        ]

        def read_version(call, version):
            return (
                call["name"] == "get_change"
                and not call["isError"]
                and _data(call)
                == {
                    "change_id": "C-17",
                    "version": version,
                    "idempotency_key": "C-17-v2",
                }
            )

        def apply_version(call, version, is_error):
            return (
                call["name"] == "apply_change"
                and call["isError"] == is_error
                and call["arguments"]
                == {
                    "change_id": "C-17",
                    "version": version,
                    "idempotency_key": "C-17-v2",
                }
                and (is_error or _data(call) == EXPECTED["M2"])
            )

        required = (
            lambda call: read_version(call, 1),
            lambda call: apply_version(call, 1, True),
            lambda call: read_version(call, 2),
            lambda call: apply_version(call, 2, True),
            lambda call: apply_version(call, 2, False),
        )
        step = 0
        for call in relevant:
            if call["name"] == "apply_change":
                args = call["arguments"]
                if (
                    args.get("change_id") != "C-17"
                    or args.get("idempotency_key") != "C-17-v2"
                    or args.get("version") not in (1, 2)
                ):
                    return _fail(
                        "all apply attempts must refer to the requested change and key"
                    )
            if step < len(required) and required[step](call):
                step += 1
        if step != len(required):
            return _fail(
                "workflow must read, reject stale, refresh, retry transient, and succeed"
            )
        if (
            trusted.get("apply_count") != 1
            or trusted.get("applied_by_key", {}).get("C-17-v2") != EXPECTED["M2"]
        ):
            return _fail("server must show exactly one C-17 effect")
        if artifacts.get("receipt.json") != EXPECTED["M2"]:
            return _fail("receipt.json is missing or incorrect")
        return _ok()

    if task == "D2":
        ok, reason = _page_checks(calls, "list_accounts", ACCOUNTS)
        if not ok:
            return _fail(reason)
        ok, reason = _page_checks(calls, "list_adjustments", ADJUSTMENTS)
        if not ok:
            return _fail(reason)
        expected = EXPECTED["D2"]
        applies = [call for call in calls if call["name"] == "apply_balance"]
        if not applies:
            return _fail("account changes were not applied")
        first_apply = min(calls.index(call) for call in applies)
        last_page = max(_pagination_end(calls, "list_accounts", ACCOUNTS)[0],
                        _pagination_end(calls, "list_adjustments", ADJUSTMENTS)[0])
        if first_apply <= last_page:
            return _fail("account updates must follow successful pagination")
        applied_calls = {}
        for call in applies:
            args = call["arguments"]
            account_id = args.get("account_id")
            version = next(
                (row["version"] for row in ACCOUNTS if row["account_id"] == account_id),
                None,
            )
            if call["isError"]:
                return _fail("an account update failed")
            if (
                account_id not in expected["changed_ids"]
                or args.get("version") != version
                or args.get("target_balance_cents")
                != expected["balances"].get(account_id)
                or args.get("idempotency_key") != f"{account_id}-v{version}"
            ):
                return _fail("account update arguments do not match reconciliation")
            applied_calls[account_id] = applied_calls.get(account_id, 0) + 1
        if sorted(applied_calls) != expected["changed_ids"]:
            return _fail("each changed account must be applied")
        if any(count != 1 for count in applied_calls.values()):
            # The task text already requires one call per changed account; a
            # redundant idempotent replay's stored effect does not substitute
            # the confirmed call.
            return _fail("exactly one confirmed apply is required per changed account")
        if (
            trusted.get("account_count") != len(ACCOUNTS)
            or trusted.get("account_balances") != expected["balances"]
        ):
            return _fail("server audit balances do not match")
        if trusted.get("account_apply_count") != {"A-01": 1, "A-02": 1}:
            return _fail("server must show one effect per changed account")
        expected_receipts = {
            "A-01-v2": {
                "account_id": "A-01",
                "balance_cents": 1175,
                "version": 3,
                "idempotent_replay": False,
            },
            "A-02-v4": {
                "account_id": "A-02",
                "balance_cents": 425,
                "version": 5,
                "idempotent_replay": False,
            },
        }
        if trusted.get("account_applied_by_key") != expected_receipts:
            return _fail("server audit does not show one receipt per changed account")
        writes = [call for call in calls if call['name'] == 'write_reconciliation' and not call['isError']][-1:]
        last_apply = _position(
            calls, lambda call: call["name"] == "apply_balance" and not call["isError"]
            and not _data(call).get("idempotent_replay")
        )
        if len(writes) != 1 or _position(calls, lambda c: c['name'] == 'write_reconciliation' and not c['isError']) <= last_apply:
            return _fail("write_reconciliation must follow successful updates")
        if (
            len(writes) != 1
            or writes[0]["isError"]
            or writes[0]["arguments"].get("report") != expected
            or trusted.get("reconciliation") != expected
        ):
            return _fail("write_reconciliation must store the exact report")
        if artifacts.get("reconciliation.json") != expected:
            return _fail("reconciliation.json is missing or incorrect")
        return _ok()

    ok, reason = _page_checks(calls, "list_assets", ASSETS)
    if not ok:
        return _fail(reason)
    ok, reason = _page_checks(calls, "list_audits", AUDITS)
    if not ok:
        return _fail(reason)
    expected = EXPECTED["H2"]
    updates = [call for call in calls if call["name"] == "set_asset_status"]
    if not updates:
        return _fail("asset status updates were not applied")
    first_update = min(calls.index(call) for call in updates)
    last_page = max(_pagination_end(calls, "list_assets", ASSETS)[0],
                    _pagination_end(calls, "list_audits", AUDITS)[0])
    if first_update <= last_page:
        return _fail("asset updates must follow successful pagination")
    changed = {}
    for call in updates:
        args = call["arguments"]
        asset_id = args.get("asset_id")
        version = next(
            (row["version"] for row in ASSETS if row["asset_id"] == asset_id), None
        )
        status = expected["statuses"].get(asset_id)
        if call["isError"]:
            return _fail("an asset update failed")
        if (
            asset_id not in expected["changed_ids"]
            or args.get("version") != version
            or args.get("status") != status
            or args.get("idempotency_key") != f"{asset_id}-v{version}-{status}"
        ):
            return _fail("asset update arguments do not match latest distinct audit")
        changed[asset_id] = True
    if sorted(changed) != expected["changed_ids"]:
        return _fail("each changed asset must be updated")
    if (
        trusted.get("asset_count") != len(ASSETS)
        or trusted.get("asset_statuses") != expected["statuses"]
    ):
        return _fail("server audit statuses do not match")
    if len(trusted.get("updated_by_key", {})) != len(expected["changed_ids"]):
        return _fail("server must show one effect per changed asset")
    expected_receipts = {
        "AS-2-v2-active": {
            "asset_id": "AS-2",
            "status": "active",
            "version": 3,
            "idempotent_replay": False,
        },
        "AS-4-v3-retired": {
            "asset_id": "AS-4",
            "status": "retired",
            "version": 4,
            "idempotent_replay": False,
        },
    }
    if trusted.get("updated_by_key") != expected_receipts:
        return _fail("server audit does not show one receipt per changed asset")
    writes = [call for call in calls if call['name'] == 'write_asset_report' and not call['isError']][-1:]
    last_update = _position(
        calls, lambda call: call["name"] == "set_asset_status" and not call["isError"]
        and not _data(call).get("idempotent_replay")
    )
    if len(writes) != 1 or _position(calls, lambda c: c['name'] == 'write_asset_report' and not c['isError']) <= last_update:
        return _fail("write_asset_report must follow successful updates")
    if (
        len(writes) != 1
        or writes[0]["isError"]
        or writes[0]["arguments"].get("report") != expected
        or trusted.get("asset_report") != expected
    ):
        return _fail("write_asset_report must store the exact report")
    if artifacts.get("asset-report.json") != expected:
        return _fail("asset-report.json is missing or incorrect")
    return _ok()


__all__ = ["grade_mcp_evidence", "replay_mcp_evidence", "expected_tool_errors",
           "reconcile_journal_events",
           "EXPECTED", "C2_STRICT_CONTRACT", "HISTORICAL_CONTRACT"]
