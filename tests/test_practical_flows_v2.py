"""Whole real-agent transactions with deterministic fake inference, never a GPU."""

import json
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

from benchmark import practical_runtime_v2 as runtime, practical_tasks_v2 as tasks
from test_practical_integration_v2 import _FakeOpenAI, _write_files_command


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PRACTICAL_INTEGRATION") != "1"
    or not sys.platform.startswith("linux"),
    reason="explicit real WSL integration without GPU",
)


class ScriptedModel(_FakeOpenAI):
    sequence = []

    def _next_reply(self, request):
        names = [
            tool.get("function", {}).get("name", "")
            for tool in request.get("tools", [])
        ]
        if "bash" not in names:
            return {"text": "Fixture title"}
        with self.lock:
            index = self.__class__.phase
            self.__class__.phase += 1
        if index >= len(self.sequence):
            return {"text": "Done."}
        suffix, arguments = self.sequence[index]
        if suffix == "final":
            return {"text": arguments}
        name = next(
            (name for name in names if name == suffix or name.endswith("_" + suffix)),
            None,
        )
        if name is None:
            raise AssertionError(f"Missing real tool: {suffix}; available={names}")
        return {"tool": name, "arguments": arguments}


def write_files(files):
    return (
        "bash",
        {
            "command": _write_files_command(files),
            "description": "Deliver fixture files",
        },
    )


def run_flow(task, sequence, tmp_path, expected_failure='passed', policy_mode='benchmark'):
    handler = type(
        "IsolatedScriptedModel", (ScriptedModel,), {"phase": 0, "sequence": sequence}
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    model = "fixture"
    try:
        row = runtime._execute_episode(
            task,
            model,
            {"id": "baseline", "context_tokens": 16384, "cache_prompt": False},
            1,
            tmp_path,
            {
                model: {
                    "alias": handler.alias,
                    "path": "unused.gguf",
                    "sha256": "0" * 64,
                    "revision": "fixture",
                }
            },
            lab=runtime.LAB,
            server_process=None,
            upstream_port=server.server_port, policy_mode=policy_mode,
        )
        if row['failure'] != expected_failure:
            print(json.dumps({'failure':row['failure'],'error':row.get('error'),'phases':row.get('driver_phases'),
                              'infra':row.get('sandbox',{}).get('infrastructure_error')}))
        assert row["failure"] == expected_failure, {'failure':row['failure'], 'error':row.get('error'),
            'phases':row.get('driver_phases'), 'tool_review':row.get('tool_review'),
            'infrastructure_error':row.get('sandbox',{}).get('infrastructure_error')}
        if expected_failure == 'passed':
            assert row["correct"] and row["autonomous"], row
        assert row["sandbox"]["cleanup_verified"], row
        return row
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)



def assert_public_mcp_outputs_have_no_private_audit(row):
    raw = (Path(row["run_dir"]) / "native.jsonl").read_bytes()
    native, _ = runtime._events(raw)
    calls = runtime._mcp_events(native)
    assert calls, "real MCP transport must produce captured tool results"
    for event in calls:
        assert "_audit" not in json.dumps(event["result"]), event


def test_real_opencode_plugin_stops_repeat_before_third_execution(tmp_path):
    row = run_flow('B2', [('bash', {'command':'ls /workspace', 'description':'Inspect workspace'})]*4,
                   tmp_path, expected_failure='model_no_progress')
    native = (Path(row['run_dir'])/'native.jsonl').read_text()
    assert 'LAB_POLICY_STOP:model_no_progress' in native
    assert row['history_delivery_verified']
    assert not row['review_required']


def test_candidate_shell_cannot_overwrite_task_or_baseline_tests(tmp_path):
    row = run_flow('B2', [('bash', {'command': 'echo changed > TASK.md; echo changed > tests/test_existing.test.js',
                                   'description':'Attempt forbidden change'}), ('final','Stopped.')],
                   tmp_path, expected_failure='wrong_result')
    native = (Path(row['run_dir'])/'native.jsonl').read_text()
    assert 'Read-only file system' in native or 'read-only file system' in native


def test_operational_recovery_can_finish_without_erasing_initial_error(tmp_path):
    files = tasks.reference_files('B2', variant=1)
    files['tests/custom.test.js'] = (
        "const {test}=require('node:test');const assert=require('node:assert/strict');"
        "const {convertJsonl}=require('../src/index.js');"
        "test('empty',()=>assert.deepEqual(JSON.parse(convertJsonl('')),[]));")
    row = run_flow('B2', [('bash', {'command':'ls /workspace', 'description':'Inspect'})]*3
                   + [write_files(files), ('final', 'Implemented and tested.')],
                   tmp_path, policy_mode='operational')
    assert len(row['recoveries']) == 1 and row['recoveries'][0]['exit_code'] == 0
    assert 'LAB_POLICY_STOP:model_no_progress' in (Path(row['run_dir'])/'native.jsonl').read_text()
    assert row['budget_ledger']['used']['main'] >= 5


def test_real_mcp_pagination_and_persisted_report(tmp_path):
    report = {"open_ids": [101, 103, 104, 106], "total_estimate": 18}
    row = run_flow(
        "C2",
        [
            ("list_issues", {}),
            ("list_issues", {"cursor": "2"}),
            ("list_issues", {"cursor": "4"}),
            ("write_report", {"report": report}),
            write_files({"report.json": json.dumps(report)}),
            ("final", "Report saved and verified."),
        ],
        tmp_path,
    )
    assert row["mcp_grade"]["passed"]
    assert row["environment_passed"] is True
    assert row["tool_errors"] == 0
    assert row["expected_tool_errors"] == 0
    assert row["avoidable_tool_errors"] == 0
    assert_public_mcp_outputs_have_no_private_audit(row)


def test_real_mcp_recovery_accepts_errors_and_exactly_once_effect(tmp_path):
    receipt = {"change_id": "C-17", "applied": True, "version": 2}
    stale = {"change_id": "C-17", "version": 1, "idempotency_key": "C-17-v2"}
    current = {**stale, "version": 2}
    row = run_flow(
        "M2",
        [
            ("get_change", {"change_id": "C-17"}),
            ("apply_change", stale),
            ("get_change", {"change_id": "C-17"}),
            ("apply_change", current),
            ("apply_change", current),
            write_files({"receipt.json": json.dumps(receipt)}),
            ("final", "Change applied once after recovery."),
        ],
        tmp_path,
    )
    assert row["mcp_grade"]["passed"]
    assert row["environment_passed"] is True
    assert row["tool_errors"] == 2
    assert row["expected_tool_errors"] == 2
    assert row["avoidable_tool_errors"] == 0
    assert_public_mcp_outputs_have_no_private_audit(row)


def test_full_javascript_delivery_and_authored_tests(tmp_path):
    files = tasks.reference_files("B2", variant=1)
    files["tests/custom.test.js"] = """const {test}=require('node:test');
const assert=require('node:assert/strict');
const {convertJsonl}=require('../src/index.js');
test('unicode retained',()=>assert.deepEqual(JSON.parse(convertJsonl(
  '{"id":1,"name":"ação"}')), [{id:1,name:'ação'}]));
"""
    row = run_flow(
        "B2", [write_files(files),
               ("bash", {"command": "node --test", "description": "Run tests through candidate shell"}),
               ("final", "Implemented and tested.")], tmp_path
    )
    assert row["phases"][0]["authored_tests"]["additional_count"] >= 1
    assert row["environment_passed"] is True
    assert row["functional_correct"] is True
    assert row["authored_tests_passed"] is True
    assert row["agent_finished"] is True
    assert "node: command not found" not in (Path(row["run_dir"]) / "native.jsonl").read_text()


def test_continuation_reuses_session_and_preserves_both_deliveries(tmp_path):
    first = tasks.reference_files("D1", variant=1, phase=1)
    first["tests/test_agent.py"] = """import json,unittest
from exporter import render
class ExportTest(unittest.TestCase):
    def test_unicode(self):
        self.assertEqual(json.loads(render([{'name':'ação','count':2}])),
                         [{'name':'ação','count':2}])
"""
    second = tasks.reference_files("D1", variant=1, phase=2)
    second["tests/test_agent.py"] = (
        first["tests/test_agent.py"]
        + """
    def test_csv_quotes(self):
        import csv,io
        self.assertEqual(list(csv.reader(io.StringIO(render(
            [{'name':'a,b','count':2}], format='csv')))), [['name','count'],['a,b','2']])
"""
    )
    row = run_flow(
        "D1",
        [
            write_files(first),
            ("final", "JSON delivered."),
            write_files(second),
            ("final", "CSV added; JSON preserved."),
        ],
        tmp_path,
    )
    phases = row["driver_phases"]
    assert len(phases) == 2
    assert phases[0]["session_id"] == phases[1]["session_id"]
    assert all(phase["hidden"]["passed"] for phase in row["phases"])
    assert (Path(row["run_dir"]) / ".snapshot2.zip").is_file()
