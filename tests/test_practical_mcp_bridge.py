"""Task 7 controls: the MCP source and state live outside the candidate."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

from benchmark import practical_mcp_bridge as bridge
from benchmark import practical_mcp_grading_v2 as mcp_grading
from benchmark import practical_mcp_v2 as mcp


def _frame(channel: socket.socket, message: object) -> None:
    bridge._frame_send(channel, bridge._json_bytes(message))


def _read_frame(channel: socket.socket) -> dict:
    return json.loads(bridge._frame_body(
        channel, bridge._frame_header(channel), bridge._MCP_FRAME_BYTES))


def _start_bridge(task: str) -> tuple[bridge.McpBridge, socket.socket]:
    """Start a bridge thread on a dedicated socketpair; return (bridge, client)."""
    instance = bridge.McpBridge(task)
    host, client = socket.socketpair()
    thread = threading.Thread(target=instance.serve_socket, args=(host,), daemon=True)
    thread.start()
    return instance, client


def _wait_until(predicate) -> None:
    for _ in range(500):
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition never became true")


# --- registry surface: the host serves the catalog, the module carries none ----


def test_tools_catalog_is_served_by_the_host_not_the_module():
    instance, client = _start_bridge("C2")
    _frame(client, {"jsonrpc": "2.0", "id": "i1", "method": "initialize", "params": {}})
    reply = _read_frame(client)
    assert reply["id"] == "i1"
    assert reply["result"]["serverInfo"]["name"] == "practical-agent-v2"

    _frame(client, {"jsonrpc": "2.0", "id": "i2", "method": "tools/list", "params": {}})
    tools = _read_frame(client)["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["list_issues", "write_report"]
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    instance.close()

    # The namespace-copied module carries no fixture rows and no tool catalog:
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    for marker in ('"A-01"', '"ADJ-1"', '"AS-1"', '"AU-1"', '"C-17"', "ISSUES",
                   "ACCOUNTS", "ADJUSTMENTS", "ASSETS", "AUDITS", "TASK_TOOLS",
                   "total_estimate", "outputSchema"):
        assert marker not in source, marker


def test_m2_fault_placement_and_ids_survive_the_two_hops():
    """Every bridge response equals a direct trusted-server replay of the same
    call: ids are forwarded verbatim, M2 error placement and receipts do not
    drift, and the trusted end state shows exactly one applied effect."""
    instance, client = _start_bridge("M2")
    direct = mcp.Server(task="M2")
    stale = {"change_id": "C-17", "version": 1, "idempotency_key": "C-17-v2"}
    current = {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}
    sequence = [
        ("get_change", {"change_id": "C-17"}),
        ("apply_change", stale),                 # rejected: stale version
        ("get_change", {"change_id": "C-17"}),   # refreshed read: version 2
        ("apply_change", current),               # rejected: injected transient
        ("apply_change", current),               # confirmed receipt
        ("apply_change", current),               # idempotent replay of the key
    ]
    observed_flags = []
    for index, (name, arguments) in enumerate(sequence, start=1):
        message = {"jsonrpc": "2.0", "id": f"seq-{index}", "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
        _frame(client, message)
        observed = _read_frame(client)
        expected = direct.respond(json.loads(json.dumps(message)))
        assert observed["id"] == f"seq-{index}"
        assert observed["result"] == expected["result"], (index, observed, expected)
        observed_flags.append(observed["result"]["isError"])
    assert observed_flags == [False, True, False, True, False, False]
    final = instance.journal()["final_state"]
    assert final["get_change_reads"] == 2
    assert final["apply_count"] == 1
    assert final["applied_by_key"]["C-17-v2"] == {
        "change_id": "C-17", "applied": True, "version": 2}


def test_pagination_cursor_semantics_survive_the_two_hops():
    instance, client = _start_bridge("C2")
    direct = mcp.Server(task="C2")
    for index, arguments in enumerate(({}, {"cursor": "2"}, {"cursor": "4"},
                                       {"cursor": "6"}), start=1):
        message = {"jsonrpc": "2.0", "id": f"p{index}", "method": "tools/call",
                   "params": {"name": "list_issues", "arguments": arguments}}
        _frame(client, message)
        observed = _read_frame(client)
        expected = direct.respond(json.loads(json.dumps(message)))
        assert observed["result"] == expected["result"]
    # The final page is empty: the candidate walked the chain to next_cursor
    # null, exactly as the trusted server pages it.
    assert observed["result"]["isError"] is False
    instance.close()


def test_journal_records_requests_responses_and_final_state():
    instance, client = _start_bridge("D2")
    _frame(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    _frame(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                    "params": {"name": "list_accounts", "arguments": {}}})
    reply = _read_frame(client)
    instance.close()
    journal = instance.journal()
    assert journal["schema"] == "practical-mcp-journal-v1"
    assert journal["task"] == "D2" and journal["clean_close"] is True
    assert journal["fault"] is None
    assert [record["kind"] for record in journal["records"]] == [
        "request", "request", "response", "journal_close"]
    notification = journal["records"][0]
    assert notification["method"] == "notifications/initialized"
    request_record = journal["records"][1]
    assert request_record["method"] == "tools/call"
    assert request_record["id"] == 7
    assert request_record["params"] == {"name": "list_accounts", "arguments": {}}
    assert request_record["ts_utc"] and request_record["seq"] == 2
    assert journal["records"][2]["envelope"] == reply
    assert journal["final_state"]["accounts"] == [
        dict(row) for row in mcp.ACCOUNTS]


def test_untrusted_methods_are_refused_without_reaching_the_server():
    instance, client = _start_bridge("C2")
    before = len(instance._records)
    for index, method in enumerate(("resources/list", "sampling/createMessage",
                                    "prompts/get", "shutdown"), start=1):
        _frame(client, {"jsonrpc": "2.0", "id": index, "method": method})
        reply = _read_frame(client)
        assert reply["error"] == {"code": -32601, "message": "Method not found"}
        assert reply["id"] == index
    records = instance._records[before:]
    assert all(record["kind"] == "method_refused" for record in records)
    assert not any(record["kind"] == "request" for record in records)
    instance.close()


def test_parse_faults_are_journaled_and_never_stop_the_bridge():
    instance, client = _start_bridge("C2")
    _frame(client, {"garbage": "not a json-rpc message"})  # object without method
    _wait_until(lambda: any(record["kind"] == "parse_fault"
                            for record in instance._records))
    assert not any(record["kind"] == "response" for record in instance._records)
    bridge._frame_send(client, b"clearly not json bytes at all")  # invalid framing JSON
    _wait_until(lambda: sum(record["kind"] == "parse_fault"
                            for record in instance._records) >= 2)
    # The channel survives: an ordinary call still answers afterwards.
    _frame(client, {"jsonrpc": "2.0", "id": "after", "method": "tools/call",
                    "params": {"name": "list_issues", "arguments": {}}})
    assert _read_frame(client)["id"] == "after"
    instance.close()


def test_non_object_messages_are_invalid_requests():
    instance, client = _start_bridge("C2")
    _frame(client, ["arrays", "are", "not", "json-rpc"])
    _wait_until(lambda: any(record["kind"] == "parse_fault"
                            for record in instance._records))
    _frame(client, {"jsonrpc": "2.0", "id": "next", "method": "ping"})
    assert _read_frame(client)["id"] == "next"
    instance.close()


def test_partial_frame_is_a_fault_and_a_clean_eof_is_not():
    instance, client = _start_bridge("C2")
    client.sendall(b"\x00\x00\x00\x40" + b"\x01\x02\x03")  # 64 announced, 3 delivered
    client.close()
    _wait_until(lambda: instance.fault is not None)
    journal = instance.close()
    assert journal["fault"].startswith("mcp_channel_error:")
    assert journal["clean_close"] is False
    assert any(record["kind"] == "fault" for record in journal["records"])

    clean_instance, clean_client = _start_bridge("C2")
    clean_client.close()  # orderly shutdown: EOF before any frame header
    _wait_until(lambda: clean_instance._records
                and clean_instance._records[-1]["kind"] == "channel_close")
    clean_journal = clean_instance.close()
    assert clean_instance.fault is None
    assert clean_journal["clean_close"] is True and clean_journal["fault"] is None


def test_two_bridges_never_share_state():
    first, first_client = _start_bridge("D2")
    second, second_client = _start_bridge("D2")
    apply_message = {"jsonrpc": "2.0", "id": "a", "method": "tools/call",
                     "params": {"name": "apply_balance", "arguments": {
                         "account_id": "A-01", "version": 2,
                         "target_balance_cents": 1175, "idempotency_key": "A-01-v2"}}}
    _frame(first_client, apply_message)
    assert _read_frame(first_client)["result"]["isError"] is False
    _frame(first_client, {"jsonrpc": "2.0", "id": "b", "method": "tools/call",
                          "params": {"name": "list_accounts", "arguments": {}}})
    _frame(second_client, {"jsonrpc": "2.0", "id": "c", "method": "tools/call",
                           "params": {"name": "list_accounts", "arguments": {}}})
    first_items = _read_frame(first_client)["result"]["structuredContent"]["data"]["items"]
    second_items = _read_frame(second_client)["result"]["structuredContent"]["data"]["items"]
    assert next(row["balance_cents"] for row in first_items
                if row["account_id"] == "A-01") == 1175
    second_journey = second.journal()
    second_after = next(row for row in second_journey["final_state"]["accounts"]
                        if row["account_id"] == "A-01")
    assert second_after["balance_cents"] == 1000
    assert next(row["balance_cents"] for row in second_items
                if row["account_id"] == "A-01") == 1000
    second.close()
    first.close()


def test_trusted_calls_decode_the_journal_for_grading():
    instance, client = _start_bridge("C2")
    _frame(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    _frame(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "list_issues", "arguments": {"cursor": None}}})
    first = _read_frame(client)
    _frame(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "list_issues", "arguments": {"cursor": "2"}}})
    second = _read_frame(client)
    trusted = bridge.trusted_calls(instance.journal())
    assert len(trusted) == 2
    # Repeated candidate ids pair by sequence, never by id lookup.
    assert trusted[0]["id"] == trusted[1]["id"] == 1
    assert trusted[0]["arguments"] == {"cursor": None}
    assert trusted[1]["arguments"] == {"cursor": "2"}
    assert trusted[0]["envelope"] == first
    assert trusted[1]["envelope"] == second
    assert bridge.trusted_calls({"records": []}) == []


def test_bridge_close_writes_the_journal_atomically(tmp_path: Path):
    path = tmp_path / "mcp-journal.json"
    instance = bridge.McpBridge("M2", journal_path=path)
    host, client = socket.socketpair()
    thread = threading.Thread(target=instance.serve_socket, args=(host,), daemon=True)
    thread.start()
    _frame(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "get_change", "arguments": {"change_id": "C-17"}}})
    _read_frame(client)
    instance.close()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["schema"] == "practical-mcp-journal-v1"
    assert stored["task"] == "M2"
    assert stored["clean_close"] is True and stored["fault"] is None
    assert stored["final_state"]["get_change_reads"] == 1
    assert not path.with_name(path.name + ".tmp").exists()
    # A second close keeps the journal file identical (idempotent finalization).
    first_bytes = path.read_bytes()
    instance.close()
    assert path.read_bytes() == first_bytes


def test_bridge_close_reports_journal_write_failures(tmp_path: Path):
    directory = tmp_path / "not-a-directory-file"
    directory.write_text("occupied", encoding="utf-8")
    instance = bridge.McpBridge("M2", journal_path=directory / "journal.json")
    instance.close()
    # The trusted record must be visible as a fault, never silently lost.
    assert instance.fault is not None
    assert instance.fault.startswith("mcp_journal_write_failed:")
    journal = instance.journal()
    assert journal["clean_close"] is False and journal["fault"] == instance.fault
    assert any(record["kind"] == "fault" for record in journal["records"])


# --- the namespace relay ------------------------------------------------------


def _relay_pair() -> tuple[bridge.NamespaceRelay, socket.socket]:
    host, child = socket.socketpair()
    relay = bridge.NamespaceRelay(child, 0)
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    return relay, host


def _client(relay: bridge.NamespaceRelay) -> socket.socket:
    return socket.create_connection(("127.0.0.1", relay.port), timeout=5)


def _line(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(payload + b"\n")


def _read_line(sock: socket.socket) -> dict:
    data = bytearray()
    while b"\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("relay closed")
        data.extend(chunk)
    return json.loads(bytes(data.split(b"\n")[0]))


def test_relay_only_forwards_the_registry_surface():
    relay, host = _relay_pair()
    try:
        client = _client(relay)

        _line(client, b"{broken json")
        assert _read_line(client)["error"]["code"] == -32700

        _line(client, json.dumps({"jsonrpc": "2.0", "id": 2,
                                  "method": "resources/list"}).encode())
        assert _read_line(client)["error"]["code"] == -32601
        host.settimeout(0.05)
        try:
            leaked = host.recv(16, socket.MSG_PEEK)
            raise AssertionError(f"refusal must not cross the channel: {leaked!r}")
        except socket.timeout:
            pass

        _line(client, json.dumps({"jsonrpc": "2.0",
                                  "method": "notifications/initialized"}).encode())
        forwarded = json.loads(bridge._frame_body(
            host, bridge._frame_header(host), bridge._MCP_FRAME_BYTES))
        assert forwarded["method"] == "notifications/initialized"

        _line(client, json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}).encode())
        bridge._frame_header(host)
        bridge._frame_send(host, bridge._json_bytes({"jsonrpc": "2.0", "id": 3, "result": {}}))
        relay_reply = _read_line(client)
        assert relay_reply["id"] == 3 and relay_reply["result"] == {}
        assert relay.connections >= 1 and relay.refusals >= 1
        client.close()
    finally:
        relay.close()
        host.close()


def test_relay_routes_each_response_to_its_request():
    relay, host = _relay_pair()
    try:
        client = _client(relay)
        for ident in (9, "outer"):
            _line(client, json.dumps({"jsonrpc": "2.0", "id": ident,
                                      "method": "tools/call",
                                      "params": {"name": "list_issues",
                                                 "arguments": {}}}).encode())
            bridge._frame_header(host)
            bridge._frame_send(host, bridge._json_bytes(
                {"jsonrpc": "2.0", "id": ident, "result": {"echo": ident}}))
            assert _read_line(client)["id"] == ident
        client.close()
    finally:
        relay.close()
        host.close()


def test_relay_rejects_oversize_lines():
    relay, host = _relay_pair()
    try:
        client = _client(relay)
        oversize = b'{"id": 1, "method": "ping", "pad": "' + b"x" * (relay._max + 8) + b'"}\n'
        client.sendall(oversize)  # one line beyond the cap: framing fault, then close
        reply = _read_line(client)
        assert reply["error"]["code"] == -32700
        # The relay closes the connection instead of reading the oversize tail.
        client.settimeout(2)
        try:
            rest = client.recv(64)
        except OSError:
            rest = b""
        assert rest == b"", f"connection must close after the framing fault: {rest!r}"
        client.close()
    finally:
        relay.close()
        host.close()


def test_relay_binds_loopback_only_and_closes_cleanly():
    relay, host = _relay_pair()
    try:
        assert relay._server.server_address[0] == "127.0.0.1"
        client = _client(relay)
        _line(client, json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}).encode())
        bridge._frame_send(host, bridge._json_bytes(
            {"jsonrpc": "2.0", "id": 9, "result": {"tools": []}}))
        assert _read_line(client)["id"] == 9
        client.close()
    finally:
        relay.close()
        host.close()


# --- grading reconciliation of journal, public events, and artifacts -----------


def test_reconciliation_rejects_absent_divergent_and_incomplete_events():
    instance, client = _start_bridge("C2")
    _frame(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "list_issues", "arguments": {}}})
    envelope = _read_frame(client)
    journal = instance.close()
    page = envelope["result"]["structuredContent"]
    events = [{"name": "list_issues", "arguments": {}, "result": page, "isError": False}]

    assert mcp_grading.reconcile_journal_events(events, journal) is None

    tampered_result = [dict(events[0], result={
        "data": {"items": [-1], "next_cursor": None}})]
    assert "diverges" in mcp_grading.reconcile_journal_events(tampered_result, journal)

    wrong_arguments = [dict(events[0], arguments={"cursor": "99"})]
    assert "trusted journal" in mcp_grading.reconcile_journal_events(wrong_arguments, journal)

    shuffled = [events[0], {"name": "list_issues", "arguments": {"cursor": "2"},
                            "result": page, "isError": False}]
    assert "trusted journal" in mcp_grading.reconcile_journal_events(shuffled, journal)

    assert "incomplete" in mcp_grading.reconcile_journal_events([], journal)

    account_event = {"name": "list_accounts", "arguments": {}, "result": page,
                     "isError": False}
    assert "absent" in mcp_grading.reconcile_journal_events(
        [events[0], account_event], journal)

    state_tampered = [dict(events[0], isError=True)]
    assert "diverges" in mcp_grading.reconcile_journal_events(state_tampered, journal)

    # A bridge that recorded a channel fault reconciles as infrastructure, not
    # as a candidate failure.
    faulted = dict(journal)
    faulted["fault"], faulted["clean_close"] = "mcp_channel_error:OSError", False
    result = mcp_grading.reconcile_journal_events(events, faulted)
    assert result is not None and "channel fault" in result


M2_RECEIPT = {"change_id": "C-17", "applied": True, "version": 2}


def _event_from(name: str, arguments: dict, envelope: dict) -> dict:
    """Public opencode event mirror of one trusted response envelope."""
    result = envelope["result"]
    if "structuredContent" in result:
        payload = result["structuredContent"]
    else:
        payload = mcp_grading._decode_result(result)
    return {"name": name, "arguments": arguments, "result": payload,
            "isError": bool(result.get("isError"))}


def _canonical_m2_run():
    """Drive the grader-required M2 workflow through a real bridge thread."""
    instance, client = _start_bridge("M2")
    events = []
    sequence = [
        ("get_change", {"change_id": "C-17"}),
        ("apply_change", {"change_id": "C-17", "version": 1, "idempotency_key": "C-17-v2"}),
        ("get_change", {"change_id": "C-17"}),
        ("apply_change", {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}),
        ("apply_change", {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}),
    ]
    for name, arguments in sequence:
        _frame(client, {"jsonrpc": "2.0", "id": "x", "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}})
        envelope = _read_frame(client)
        events.append(_event_from(name, arguments, envelope))
    journal = instance.close()
    return events, journal


def test_grading_uses_the_trusted_journal_for_mcp_evidence():
    events, journal = _canonical_m2_run()
    assert journal["schema"] == "practical-mcp-journal-v1"
    assert journal["clean_close"] is True and journal["fault"] is None
    assert mcp_grading.reconcile_journal_events(events, journal) is None
    grade = mcp_grading.grade_mcp_evidence(
        "M2", events, None, {"receipt.json": M2_RECEIPT}, journal=journal)
    assert grade["passed"] is True, grade
    try:
        mcp_grading.grade_mcp_evidence("M2", events, {"applied_by_key": {
            "C-17-v2": M2_RECEIPT}}, {}, journal=journal)
        raise AssertionError("candidate-supplied state must be rejected with a journal")
    except ValueError:
        pass


def test_grading_without_a_journal_agrees_with_the_trusted_path():
    """The legacy replay-only grading accepts the same honest evidence, so the
    journal path adds reconciliation without changing functional verdicts."""
    events, journal = _canonical_m2_run()
    trusted = mcp_grading.grade_mcp_evidence(
        "M2", events, None, {"receipt.json": M2_RECEIPT}, journal=journal)
    legacy = mcp_grading.grade_mcp_evidence(
        "M2", events, None, {"receipt.json": M2_RECEIPT})
    assert trusted["passed"] is True and trusted == legacy
