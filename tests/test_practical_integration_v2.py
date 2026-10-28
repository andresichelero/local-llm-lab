"""Opt-in WSL integration: real namespaces/OpenCode/Node/Python/MCP, no model GPU."""
from __future__ import annotations

import base64
import json
import os
import shlex
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from benchmark import practical_tasks_v2
from benchmark import practical_runtime_v2 as runtime


_ENABLED = os.environ.get("RUN_PRACTICAL_INTEGRATION") == "1"
_RUNTIMES = runtime.OPENCODE.is_file() and runtime.NODE.is_file()
pytestmark = pytest.mark.skipif(not (_ENABLED and sys.platform.startswith("linux") and _RUNTIMES),
                                reason="requires explicit WSL integration opt-in and pinned runtimes")


def _write_files_command(files: dict[str, str]) -> str:
    payload = base64.b64encode(json.dumps(files, ensure_ascii=False).encode()).decode()
    script = (
        "import base64,json,pathlib; files=json.loads(base64.b64decode(" + repr(payload)
        + ")); [pathlib.Path(name).parent.mkdir(parents=True,exist_ok=True) for name in files]; "
        "[pathlib.Path(name).write_text(value,encoding='utf-8') for name,value in files.items()]"
    )
    return "python3 -c " + shlex.quote(script)


class _FakeOpenAI(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    phase = 0
    response_sequence = 0
    lock = threading.Lock()
    alias = "fixture-model"
    files = {
        "orders/report.py": """def build_report(records):
    totals = {}
    seen = set()
    for row in records:
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        customer = row['customer']
        totals[customer] = totals.get(customer, 0) + row['amount_cents']
    return totals
""",
        "tests/test_agent.py": """import unittest
from orders.report import build_report

class AgentAuthoredTest(unittest.TestCase):
    def test_first_delivery_wins_and_refunds_sum(self):
        self.assertEqual(build_report([
            {'id':'x','customer':'Ada','amount_cents':100},
            {'id':'x','customer':'Other','amount_cents':900},
            {'id':'y','customer':'Ada','amount_cents':-25},
        ]), {'Ada':75})
""",
    }

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps({"object": "list", "data": [{"id": self.alias, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _next_reply(self, request):
        names = []
        for tool in request.get("tools", []):
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            if function.get("name"):
                names.append(function["name"])
        with self.lock:
            if "bash" not in names:
                return {"text": "Fixture title"}
            self.__class__.phase += 1
            phase = self.__class__.phase
        if phase == 1:
            return {"tool": "bash", "arguments": {"command": _write_files_command(self.files),
                                                       "description": "Implement the report and add a regression test"}}
        if phase == 2:
            return {"tool": "bash", "arguments": {"command": "python3 -I -B -m unittest discover -s tests",
                                                       "description": "Run the project test suite"}}
        return {"text": "Implemented the report and verified the tests."}

    def _response(self, request):
        reply = self._next_reply(request)
        model = str(request.get("model", self.alias))
        with self.lock:
            self.__class__.response_sequence += 1
            response_sequence = self.__class__.response_sequence
        response_id = f"chatcmpl-{response_sequence}-{uuid.uuid4().hex}"
        created = int(time.time())
        usage = self._usage(request, reply)
        if "tool" in reply:
            call_id = f"call_{uuid.uuid4().hex[:24]}"
            arguments = json.dumps(reply["arguments"], ensure_ascii=False)
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": reply["tool"], "arguments": arguments}
            }]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": reply["text"]}
            finish = "stop"
        if request.get("stream") is True:
            chunks = [self._chunk(response_id, created, model, {"role": "assistant"})]
            if "tool_calls" in message:
                function = message["tool_calls"][0]["function"]
                chunks.extend((
                    self._chunk(response_id, created, model, {"tool_calls": [{
                        "index": 0, "id": call_id, "type": "function",
                        "function": {"name": function["name"], "arguments": ""},
                    }]}),
                    self._chunk(response_id, created, model, {"tool_calls": [{
                        "index": 0, "function": {"arguments": arguments},
                    }]}),
                ))
            else:
                chunks.append(self._chunk(response_id, created, model,
                                           {"content": message["content"]}))
            chunks.append(self._chunk(response_id, created, model, {}, finish_reason=finish))
            # OpenAI-compatible servers commonly return usage in the final stream
            # chunk; OpenCode uses it to advance message/session accounting.
            chunks.append({"id": response_id, "object": "chat.completion.chunk",
                           "created": created, "model": model, "choices": [], "usage": usage})
            stream = b"".join(
                b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n"
                for chunk in chunks
            ) + b"data: [DONE]\n\n"
            return stream, "text/event-stream"
        completion = {"id": response_id, "object": "chat.completion", "created": created,
                      "model": model, "choices": [{"index": 0, "message": message,
                                                       "finish_reason": finish}], "usage": usage}
        return json.dumps(completion).encode(), "application/json"

    @staticmethod
    def _chunk(response_id, created, model, delta, *, finish_reason=None):
        return {"id": response_id, "object": "chat.completion.chunk", "created": created,
                "model": model, "choices": [{"index": 0, "delta": delta,
                                               "finish_reason": finish_reason}]}

    @staticmethod
    def _usage(request, reply):
        prompt = json.dumps(request.get("messages", []), ensure_ascii=False)
        completion = (json.dumps(reply.get("arguments", {}), ensure_ascii=False)
                      if "tool" in reply else str(reply.get("text", "")))
        prompt_tokens = max(1, (len(prompt) + 3) // 4)
        completion_tokens = max(1, (len(completion) + 3) // 4)
        return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens}

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            # Keep fake inference close to a local endpoint's request cadence so
            # OpenCode cannot collapse multiple session transitions into one tick.
            time.sleep(0.02)
            body, content_type = self._response(request)
        except Exception as exc:  # pragma: no cover - integration diagnostic path
            body, content_type = json.dumps({"error": {"message": str(exc)}}).encode(), "application/json"
            self.send_response(500)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def test_real_python_and_node_graders_require_baseline_plus_agent_test(tmp_path: Path) -> None:
    """Acceptance and authored tests execute in separate real namespace sandboxes."""
    for task in ("B1", "B2"):
        workspace = tmp_path / task
        workspace.mkdir()
        practical_tasks_v2.seed_task(task, workspace)
        for name, content in practical_tasks_v2.reference_files(task).items():
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if task == "B1":
            (workspace / "tests/test_agent.py").write_text(
                "import unittest\nfrom orders.report import build_report\n"
                "class Extra(unittest.TestCase):\n"
                " def test_refund(self): self.assertEqual(build_report(["
                "{'id':'a','customer':'Ada','amount_cents':5},"
                "{'id':'b','customer':'Ada','amount_cents':-2}]), {'Ada':3})\n",
                encoding="utf-8")
        else:
            (workspace / "tests/test_agent.test.js").write_text(
                "const {test}=require('node:test'); const assert=require('node:assert/strict');\n"
                "const {convertJsonl}=require('../src');\n"
                "test('empty JSONL stays an array',()=>assert.deepEqual(JSON.parse(convertJsonl('')),[]));\n",
                encoding="utf-8")
        hidden = runtime._grader_result(task, 1, workspace, lab=runtime.LAB)
        authored = runtime._authored_test_result(task, workspace, lab=runtime.LAB)
        assert hidden["passed"], hidden
        assert authored["passed"], authored
        assert authored["baseline_count"] == 1
        assert authored["additional_count"] >= 1


def test_real_graders_reject_candidate_termination_games(tmp_path: Path) -> None:
    """B1 SystemExit(0) and B2 process.exit(0) stop reading as approvals."""
    python = tmp_path / "B1"
    python.mkdir()
    practical_tasks_v2.seed_task("B1", python)
    for name, content in practical_tasks_v2.reference_files("B1").items():
        target = python / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (python / "orders/report.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    hidden = runtime._grader_result("B1", 1, python, lab=runtime.LAB)
    assert hidden["passed"] is False
    assert hidden["infrastructure"] is False
    assert hidden["contract_invalid"] is False
    assert all(item["stop"] == "error" for item in hidden.get("failures", [])), hidden

    node = tmp_path / "B2"
    node.mkdir()
    practical_tasks_v2.seed_task("B2", node)
    for name, content in practical_tasks_v2.reference_files("B2").items():
        target = node / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (node / "src/index.js").write_text(
        "process.exit(0);\nmodule.exports = {};\n", encoding="utf-8")
    hidden = runtime._grader_result("B2", 1, node, lab=runtime.LAB)
    assert hidden["passed"] is False
    assert hidden["infrastructure"] is False
    assert hidden["contract_invalid"] is True


def test_full_python_episode_against_fake_model_uses_real_opencode_and_sandbox(tmp_path: Path) -> None:
    """A no-GPU fake chat API drives actual OpenCode tools and independent graders."""
    _FakeOpenAI.phase = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = "fake-practical-v2"
        models = {model: {"alias": _FakeOpenAI.alias, "path": "unused.gguf",
                          "sha256": "0" * 64, "revision": "fake-fixture"}}
        row = runtime._execute_episode(
            "B1", model, {"id": "baseline", "context_tokens": 16384, "cache_prompt": False}, 1,
            tmp_path, models, lab=runtime.LAB, server_process=None,
            upstream_port=server.server_address[1],
        )
        assert row["failure"] == "passed", row
        assert row["correct"] is True
        assert row["autonomous"] is True
        assert row["model_calls"] >= 3
        assert row["server_cleanup_verified"] is True
        assert row["sandbox"]["cleanup_verified"] is True
        assert row["phases"][0]["hidden"]["passed"] is True
        tests = row["phases"][0]["authored_tests"]
        assert tests["baseline_count"] == 1 and tests["additional_count"] >= 1
        # The authored regression diagnosis also ran for real: the restored
        # seed check is one more actual sandbox run inside the episode.
        quality = row["phases"][0]["authored_test_quality"]
        assert quality["quality"] == "regression_detected", quality["reason"]
        assert quality["seed"]["count"] == tests["count"]
        assert len(quality["provenance"]["restored_seed_sha256"]) == 3
        assert row["authored_test_quality"] == "regression_detected"
        run_dir = Path(row["run_dir"])
        assert (run_dir / ".snapshot1.zip").is_file()
        assert (run_dir / "native.jsonl").is_file()
        assert (run_dir / "broker/transcript.jsonl").is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


# --- opt-in MCP episodes under the isolated bridge (Task 7 Phase D) -----------

from benchmark.practical_mcp_bridge import trusted_calls  # noqa: E402
from benchmark.practical_mcp_grading_v2 import EXPECTED  # noqa: E402

_MCP_ACCEPT = {"id": "baseline", "context_tokens": 16384, "cache_prompt": False}
_MCP_MODEL = "fake-practical-v2"


def _scripted_model(script):
    """A fake no-GPU model that advances one step per chat request.

    Steps are: dict -> bash file writes, ("bash", {...}) -> any bash command,
    (tool_suffix, arguments) -> one lab MCP tool call, str -> final text.
    """
    class Scripted(_ScriptedEpisode):
        pass

    Scripted.script = tuple(script)
    Scripted.step = 0
    return Scripted


class _ScriptedEpisode(_FakeOpenAI):
    script = ()
    step = 0

    @staticmethod
    def _names(request):
        names = []
        for tool in request.get("tools", []) or []:
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            if function.get("name"):
                names.append(function["name"])
        return names

    @classmethod
    def _tool_name(cls, names, suffix):
        for name in names:
            if name == suffix or name.endswith("_" + suffix):
                return name
        raise AssertionError(f"no lab tool answering {suffix!r} in {names}")

    def _next_reply(self, request):
        names = self._names(request)
        if not names:
            return {"text": "Fixture title"}
        with self.lock:
            step = self.__class__.step
            self.__class__.step += 1
        if step >= len(self.script):
            return {"text": "Done."}
        entry = self.script[step]
        if isinstance(entry, dict):
            return {"tool": "bash",
                    "arguments": {"command": _write_files_command(entry),
                                  "description": "Create the workspace files"}}
        if isinstance(entry, str):
            return {"text": entry}
        if entry[0] == "bash":
            return {"tool": "bash", "arguments": dict(entry[1])}
        suffix, arguments = entry
        return {"tool": self._tool_name(names, suffix), "arguments": arguments}


def _run_episode(tmp_path: Path, task: str, script, task_contract_id: str | None = None):
    klass = _scripted_model(script)
    server = ThreadingHTTPServer(("127.0.0.1", 0), klass)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        models = {_MCP_MODEL: {"alias": _FakeOpenAI.alias, "path": "unused.gguf",
                               "sha256": "0" * 64, "revision": "fake-fixture"}}
        row = runtime._execute_episode(
            task, _MCP_MODEL, dict(_MCP_ACCEPT), 1, tmp_path, models, lab=runtime.LAB,
            server_process=None, upstream_port=server.server_address[1],
            task_contract_id=task_contract_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return row


def _episode_problems(row) -> str:
    if row.get("failure") == "passed" and row.get("correct") is True:
        return ""
    return json.dumps({
        "failure": row.get("failure"), "reason": row.get("reason"),
        "error": row.get("error"), "sandbox": row.get("sandbox"),
        "mcp_grade": row.get("mcp_grade"), "phases": row.get("phases"),
        "run_dir": row.get("run_dir")}, default=str)[:5000]


def _channel_journal(row):
    return json.loads(
        (Path(row["run_dir"]) / "mcp-journal.json").read_text(encoding="utf-8"))


_C2_SCRIPT = (
    ("list_issues", {"page_size": 2}),
    ("list_issues", {"page_size": 2, "cursor": "2"}),
    ("list_issues", {"page_size": 2, "cursor": "4"}),
    {"report.json": json.dumps(EXPECTED["C2"])},
    ("write_report", {"report": EXPECTED["C2"]}),
    "Report submitted.",
)

_M2_SCRIPT = (
    ("get_change", {"change_id": "C-17"}),
    ("apply_change", {"change_id": "C-17", "version": 1, "idempotency_key": "C-17-v2"}),
    ("get_change", {"change_id": "C-17"}),
    ("apply_change", {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}),
    ("apply_change", {"change_id": "C-17", "version": 2, "idempotency_key": "C-17-v2"}),
    {"receipt.json": json.dumps(EXPECTED["M2"])},
    "Change applied once.",
)

_D2_LIBRARY = {
    "tests/reconcile.test.js": """const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildReconciliationReport } = require('../src');
test('replay keys, posted filter, and totals hold', () => {
  assert.deepEqual(buildReconciliationReport(
    [{account_id:'A', balance_cents:100}, {account_id:'Z', balance_cents:5}],
    [{id:'t1', account_id:'A', delta_cents:20, status:'posted'},
     {id:'t1', account_id:'Z', delta_cents:900, status:'posted'},
     {id:'t2', account_id:'Z', delta_cents:-5, status:'posted'},
     {id:'t3', account_id:'A', delta_cents:90, status:'pending'}]),
    {balances:{A:120, Z:0}, changed_ids:['A', 'Z'],
     ignored_duplicate_ids:['t1'], total_balance_cents:120});
});
""",
    "src/ledger.js": """function splitAdjustments(adjustments) {
  const kept = [];
  const ignored = [];
  const seen = new Set();
  for (const row of adjustments) {
    if (seen.has(row.id)) { ignored.push(row.id); continue; }
    seen.add(row.id);
    kept.push({ ...row });
  }
  return { kept, ignored_duplicate_ids: [...new Set(ignored)].sort() };
}
module.exports = { splitAdjustments };
""",
    "src/reconcile.js": """function buildReport(accounts, split) {
  const balances = {};
  const opened = {};
  for (const account of accounts) {
    balances[account.account_id] = account.balance_cents;
    opened[account.account_id] = account.balance_cents;
  }
  for (const row of split.kept) {
    if (row.status !== 'posted') continue;
    if (!(row.account_id in balances)) continue;
    balances[row.account_id] += row.delta_cents;
  }
  const changed = Object.keys(balances)
    .filter((id) => balances[id] !== opened[id]).sort();
  return {
    balances,
    changed_ids: changed,
    ignored_duplicate_ids: split.ignored_duplicate_ids,
    total_balance_cents: Object.values(balances)
      .reduce((sum, value) => sum + value, 0),
  };
}
module.exports = { buildReport };
""",
    "src/index.js": """const { splitAdjustments } = require('./ledger');
const { buildReport } = require('./reconcile');
function buildReconciliationReport(accounts, adjustments) {
  return buildReport(accounts, splitAdjustments(adjustments));
}
module.exports = { buildReconciliationReport, splitAdjustments, buildReport };
""",
    "reconciliation.json": json.dumps(EXPECTED["D2"]),
}

_D2_SCRIPT = (
    dict(_D2_LIBRARY),
    ("list_accounts", {"page_size": 2}),
    ("list_accounts", {"page_size": 2, "cursor": "2"}),
    ("list_adjustments", {"page_size": 2}),
    ("list_adjustments", {"page_size": 2, "cursor": "2"}),
    ("list_adjustments", {"page_size": 2, "cursor": "4"}),
    ("apply_balance", {"account_id": "A-01", "target_balance_cents": 1175,
                       "version": 2, "idempotency_key": "A-01-v2"}),
    ("apply_balance", {"account_id": "A-02", "target_balance_cents": 425,
                       "version": 4, "idempotency_key": "A-02-v4"}),
    ("write_reconciliation", {"report": EXPECTED["D2"]}),
    "Reconciliation submitted.",
)

_H2_SCRIPT = (
    ("list_assets", {"page_size": 2}),
    ("list_assets", {"page_size": 2, "cursor": "2"}),
    ("list_audits", {"page_size": 2}),
    ("list_audits", {"page_size": 2, "cursor": "2"}),
    ("list_audits", {"page_size": 2, "cursor": "4"}),
    ("set_asset_status", {"asset_id": "AS-2", "status": "active", "version": 2,
                          "idempotency_key": "AS-2-v2-active"}),
    ("set_asset_status", {"asset_id": "AS-4", "status": "retired", "version": 3,
                          "idempotency_key": "AS-4-v3-retired"}),
    {"asset-report.json": json.dumps(EXPECTED["H2"])},
    ("write_asset_report", {"report": EXPECTED["H2"]}),
    "Asset statuses reconciled.",
)


def test_real_mcp_episode_c2_reports_the_paged_issue_catalog(tmp_path: Path) -> None:
    row = _run_episode(tmp_path, "C2", _C2_SCRIPT)
    assert row["failure"] == "passed" and row["correct"] is True, _episode_problems(row)
    assert row["phases"][0]["hidden"]["passed"] is True
    journal = _channel_journal(row)
    assert journal["schema"] == "practical-mcp-journal-v1"
    assert journal["clean_close"] is True and journal["fault"] is None
    calls = trusted_calls(journal)
    assert [entry["name"] for entry in calls] == [
        "list_issues", "list_issues", "list_issues", "write_report"]
    assert calls[0]["arguments"] == {"page_size": 2}
    assert calls[-1]["arguments"] == {"report": EXPECTED["C2"]}
    assert journal["final_state"]["report"] == EXPECTED["C2"]
    network = row["sandbox"]["network_evidence"]
    assert network["broker_listener_loopback_only"] is True
    assert network["mcp_listener_loopback_only"] is True


def test_real_mcp_episode_m2_recovers_through_expected_errors(tmp_path: Path) -> None:
    row = _run_episode(tmp_path, "M2", _M2_SCRIPT)
    assert row["failure"] == "passed" and row["correct"] is True, _episode_problems(row)
    assert row["phases"][0]["hidden"]["passed"] is True
    assert row["expected_tool_errors"] == 2, _episode_problems(row)
    journal = _channel_journal(row)
    assert journal["clean_close"] is True and journal["fault"] is None
    flags = [entry["envelope"]["result"]["isError"] for entry in trusted_calls(journal)]
    assert flags == [False, True, False, True, False]
    final = journal["final_state"]
    assert final["apply_count"] == 1 and final["get_change_reads"] == 2
    assert final["applied_by_key"]["C-17-v2"] == EXPECTED["M2"]


def test_real_mcp_episode_d2_javascript_library_and_mcp_reconcile(tmp_path: Path) -> None:
    """D2 checks the JavaScript library in a real grader and the MCP flow via
    the dedicated channel: pagination, two applies, artifact, and submission."""
    row = _run_episode(tmp_path, "D2", _D2_SCRIPT)
    assert row["failure"] == "passed" and row["correct"] is True, _episode_problems(row)
    phase = row["phases"][0]
    assert phase["hidden"]["passed"] is True
    assert phase["mcp"]["passed"] is True, _episode_problems(row)
    journal = _channel_journal(row)
    assert journal["clean_close"] is True and journal["fault"] is None
    names = [entry["name"] for entry in trusted_calls(journal)]
    assert names == ["list_accounts", "list_accounts", "list_adjustments",
                     "list_adjustments", "list_adjustments", "apply_balance",
                     "apply_balance", "write_reconciliation"]
    assert journal["final_state"]["reconciliation"] == EXPECTED["D2"]


def test_real_mcp_episode_h2_reconciles_asset_statuses(tmp_path: Path) -> None:
    row = _run_episode(tmp_path, "H2", _H2_SCRIPT)
    assert row["failure"] == "passed" and row["correct"] is True, _episode_problems(row)
    journal = _channel_journal(row)
    assert journal["clean_close"] is True and journal["fault"] is None
    calls = trusted_calls(journal)
    assert [entry["name"] for entry in calls] == [
        "list_assets", "list_assets", "list_audits", "list_audits", "list_audits",
        "set_asset_status", "set_asset_status", "write_asset_report"]
    assert journal["final_state"]["asset_report"] == EXPECTED["H2"]
    statuses = {row["asset_id"]: row["status"]
                for row in journal["final_state"]["assets"]}
    assert statuses == EXPECTED["H2"]["statuses"]


def test_real_m1_episode_fixes_config_merge_without_any_mcp_channel(tmp_path: Path) -> None:
    """A non-MCP episode wires no lab server and no dedicated channel; the
    trusted journal file is never created for tasks outside the MCP scope."""
    merge_fixed = """function mergeConfig(base, override) {
  const result = { ...(base || {}) };
  for (const key of Object.keys(override || {})) {
    const incoming = override[key];
    if (incoming === undefined) continue;
    if (Array.isArray(incoming)) { result[key] = [...incoming]; continue; }
    if (incoming !== null && typeof incoming === 'object') {
      const current = result[key];
      const nested = (current && typeof current === 'object'
                      && !Array.isArray(current)) ? current : {};
      result[key] = mergeConfig(nested, incoming);
      continue;
    }
    result[key] = incoming;
  }
  return result;
}
module.exports = { mergeConfig };
"""
    authored = """const { test } = require('node:test');
const assert = require('node:assert/strict');
const { resolveConfig, defaults } = require('../src/config');
test('explicit values survive and arrays are copied', () => {
  const overrides = { transport: { headers: { authorization: 'local' } }, tags: ['one'] };
  const result = resolveConfig(overrides);
  assert.equal(result.transport.headers.authorization, 'local');
  overrides.tags.push('extra');
  assert.deepEqual(result.tags, ['one']);
  assert.deepEqual(defaults.tags, ['default']);
});
"""
    row = _run_episode(tmp_path, "M1", (
        {"src/config/merge.js": merge_fixed, "tests/config.test.js": authored},
        ("bash", {"command": "/opt/node/bin/node --test tests/config.test.js",
                  "description": "Run the authored config test"}),
        "Merge behavior fixed.",
    ))
    assert row["failure"] == "passed" and row["correct"] is True, _episode_problems(row)
    assert row["phases"][0]["hidden"]["passed"] is True, _episode_problems(row)
    assert (Path(row["run_dir"]) / "mcp-journal.json").is_file() is False
    network = row["sandbox"]["network_evidence"]
    assert network["broker_listener_loopback_only"] is True
    assert network["mcp_listener_loopback_only"] is False
    assert row["sandbox"]["infrastructure_error"] is None
