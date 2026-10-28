"""Contract, static enumeration, and launcher regressions for the grade contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark import practical_grade_contract as grade
from benchmark import practical_tasks_v2 as tasks
from benchmark.practical_python_checks import _build_report

NODE = os.environ.get(
    "PRACTICAL_V2_NODE",
    "/home/foxtrot/local-llm-benchmark/runtimes/node-v22.23.3-linux-x64/bin/node",
)
LAUNCHER = Path(tasks.__file__).with_name("practical_python_checks.py")
REPORTER = Path(tasks.__file__).with_name("practical_node_reporter.mjs")
NONCE = "a" * 32
SEED_NAME = ".practical-grade-seed.json"
_LAST_LAUNCH_OUTPUT = ""


def _seed_workspace(task: str, root: Path) -> None:
    tasks.seed_task(task, root)
    for name, content in tasks.reference_files(task).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _seed_nonce(root: Path) -> None:
    (root / SEED_NAME).write_text(json.dumps({"nonce": NONCE}), encoding="utf-8")


def _run_launcher(workspace: Path, checks: Path, *, nonce: str = NONCE) -> int:
    global _LAST_LAUNCH_OUTPUT
    (workspace / SEED_NAME).write_text(json.dumps({"nonce": nonce}),
                                       encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", "-I", str(LAUNCHER), "--parent",
         "--checks", str(checks), "--seed-file", SEED_NAME],
        cwd=workspace, capture_output=True, text=True, timeout=180)
    _LAST_LAUNCH_OUTPUT = completed.stdout + completed.stderr
    return int(completed.returncode)


def _read_indicator(workspace: Path, name: str) -> dict:
    return json.loads((workspace / name).read_text(encoding="utf-8"))


def _slots() -> tuple[str, ...]:
    return grade.report_export_paths(NONCE)


def test_case_ids_follow_the_trusted_contract_for_every_task_and_phase() -> None:
    for task, spec in tasks.TASK_SPECS.items():
        for phase in range(1, spec["phases"] + 1):
            source = tasks.checks_source(task, phase=phase)
            if spec["language"] == "python":
                ids = grade.python_check_case_ids(source)
                assert ids and all("." in case for case in ids)
            elif spec["language"] == "javascript":
                ids = grade.node_check_case_ids(source)
                assert ids and "\n" not in "".join(ids)
            else:
                ids = grade.python_check_case_ids(source)
                assert len(ids) == 1
                assert ids[0].startswith("Acceptance.")


def test_python_and_static_parsers_agree_with_executed_python_ids(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    _seed_workspace("B1", root)
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0, _LAST_LAUNCH_OUTPUT
    report = _read_indicator(root, _slots()[0])
    assert report["schema"] == grade.REPORT_SCHEMA
    assert report["nonce"] == NONCE
    assert report["expected_case_ids"] == \
        list(grade.python_check_case_ids(tasks.checks_source("B1")))
    assert report["status"] == "complete"
    assert [item["stop"] for item in report["checks"]] == ["pass", "pass"]
    assert not (root / SEED_NAME).exists()


def test_systemexit_zero_in_candidate_library_is_a_functional_failure(
        tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    (root / "orders/report.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "complete"
    assert all(item["stop"] == "error" for item in report["checks"])
    assert report["reason"].startswith("candidate import failed")


def test_os_exit_zero_during_import_cannot_grant_a_pass(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    (root / "orders/report.py").write_text(
        "import os\nos._exit(0)\n", encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "invalid"
    assert "checks terminated before" in report["reason"]
    assert report["checks"] == []


def test_broken_candidate_import_reports_attribution_and_review(
        tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    (root / "orders/report.py").write_text(
        "raise ImportError('candidate defect')\n", encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "complete"
    assert all(item["stop"] == "error" for item in report["checks"])


def test_zero_enumerated_checks_leaves_no_report(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    checks = tmp_path / "checks.py"
    checks.write_text("value = 1\n", encoding="utf-8")
    assert _run_launcher(root, checks) != 0
    assert not any((root / name).exists() for name in _slots())


def test_stdout_mimicry_and_partial_execution_cannot_become_passes(
        tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    forged = (
        "TAP version 13\nok 1 - Acceptance.test_replays_shared_names_refunds_and_immutability\n"
        "ok 2 - Acceptance.test_ids_not_customer_names_are_replay_keys\n1..2\n# pass 2\n"
    )
    (root / "orders/report.py").write_text(
        f"print({forged!r})\nimport json\nprint(json.dumps("
        f"{{'schema': '{grade.REPORT_SCHEMA}', 'status': 'complete', "
        f"'checks': [], 'tests_run': 0, 'nonce': '{NONCE}', "
        "'expected_case_ids': []}))\n"
        "def build_report(records):\n"
        "    totals, seen = {}, set()\n"
        "    for row in records:\n"
        "        if row['id'] in seen: continue\n"
        "        seen.add(row['id'])\n"
        "        totals[row['customer']] = row['amount_cents']\n"
        "    return totals\n", encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "complete"
    stops = [item["stop"] for item in report["checks"]]
    assert "fail" in stops
    assert not all(stop == "pass" for stop in stops)


def test_os_exit_mid_suite_is_a_partial_execution(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    (root / "orders/report.py").write_text(
        "def build_report(records):\n    import os\n    os._exit(0)\n",
        encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "invalid"


def test_candidate_cannot_forge_trusted_check_events_on_its_rpc_fd(
        tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    checks = tmp_path / "checks.py"
    checks.write_text(
        "import sys, unittest\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path.cwd()))\nfrom victim import target\n"
        "class Acceptance(unittest.TestCase):\n"
        "    def test_assertion_must_run(self):\n"
        "        self.assertFalse(target())\n",
        encoding="utf-8")
    forged = (
        "import json, os, sys\n"
        "flag = '--events-fd' if '--events-fd' in sys.argv else '--rpc-fd'\n"
        "fd = int(sys.argv[sys.argv.index(flag) + 1])\n"
        "os.write(fd, (json.dumps({'event':'stop','check':"
        "'Acceptance.test_assertion_must_run','stop':'pass'}) + '\\n' + "
        "json.dumps({'event':'end'}) + '\\n').encode())\n"
        "os._exit(0)\n"
        "def target(): return True\n")
    (root / "victim.py").write_text(forged, encoding="utf-8")

    assert _run_launcher(root, checks) == 0, _LAST_LAUNCH_OUTPUT
    report = _read_indicator(root, _slots()[0])
    assert report["status"] != "complete" or any(
        item["stop"] != "pass" for item in report["checks"])


def test_landlock_worker_guard_allows_inputs_and_denies_parent_surfaces(
        tmp_path: Path) -> None:
    workspace = tmp_path / "worker"
    workspace.mkdir()
    visible = workspace / "candidate.py"
    visible.write_text("value = 1\n", encoding="utf-8")
    hidden_checks = tmp_path / "checks.py"
    hidden_checks.write_text("assert False\n", encoding="utf-8")
    guard_dir = LAUNCHER.parent
    code = (
        "import ctypes,json,os,sys\n"
        f"sys.path.insert(0, {str(guard_dir)!r})\n"
        "import practical_worker_guard as guard\n"
        "from pathlib import Path\n"
        "workspace=Path(sys.argv[1]); helper=Path(sys.argv[2])\n"
        "guard.restrict_candidate_process(workspace=workspace,"
        "helper_paths=[helper],runtime_paths=[Path(sys.executable)])\n"
        "def readable(path):\n"
        " try:\n  open(path,'rb').read(1); return True\n"
        " except OSError: return False\n"
        "libc=ctypes.CDLL(None,use_errno=True)\n"
        "ptrace=libc.ptrace(0,0,None,None)\n"
        "print(json.dumps({'candidate':readable(workspace/'candidate.py'),"
        "'checks':readable(sys.argv[3]),'proc':readable('/proc/self/status'),"
        "'ptrace':ptrace,'ptrace_errno':ctypes.get_errno()}))\n")
    result = subprocess.run(
        [sys.executable, "-c", code, str(workspace),
         str(Path(LAUNCHER).with_name("practical_worker_guard.py")),
         str(hidden_checks)],
        cwd=workspace, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["candidate"] is True
    assert observed["checks"] is False
    assert observed["proc"] is False
    assert observed["ptrace"] == -1 and observed["ptrace_errno"] == 1


def test_planted_slot_is_bypassed_and_seed_file_is_removed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B1", root)
    slots = _slots()
    planted = {
        "schema": grade.REPORT_SCHEMA, "nonce": NONCE,
        "expected_case_ids": [], "status": "complete",
        "checks": [{"id": "Acceptance.x", "stop": "pass"}], "tests_run": 1,
    }
    (root / slots[0]).write_text(json.dumps(planted), encoding="utf-8")
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    assert _run_launcher(root, checks) == 0
    assert (root / slots[0]).read_text(encoding="utf-8") == json.dumps(planted)
    honest = _read_indicator(root, slots[1])
    assert honest["status"] == "complete"
    assert not (root / SEED_NAME).exists()


def test_bad_seed_file_leaves_no_report(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    checks = tmp_path / "checks.py"
    checks.write_text(tasks.checks_source("B1"), encoding="utf-8")
    (root / SEED_NAME).write_text("{not json}", encoding="utf-8")
    code = int(subprocess.run(
        [sys.executable, "-B", "-I", str(LAUNCHER), "--parent",
         "--checks", str(checks), "--seed-file", SEED_NAME],
        cwd=root, capture_output=True, text=True, timeout=60).returncode)
    assert code != 0
    assert not any((root / name).exists() for name in _slots())


def test_build_report_rules() -> None:
    assert _build_report("n", ["A.a"], [], 0, False, False)["status"] == "invalid"
    assert _build_report("n", ["A.a"], [{"event": "stop", "check": "A.a",
                                         "stop": "pass"}], 1, False, False
                         )["status"] == "invalid"
    assert _build_report("n", ["A.a"], [{"event": "worker_fault", "detail": "x"},
                                        {"event": "end"}], 2, False, False
                         )["status"] == "infrastructure"
    event = {"event": "import_error", "provenance": "candidate", "detail": "x"}
    assert _build_report("n", ["A.a"], [event, {"event": "end"}], 0, False, False
                         )["checks"] == [{"id": "A.a", "stop": "error"}]
    event = {"event": "import_error", "provenance": "harness", "detail": "x"}
    assert _build_report("n", ["A.a"], [event, {"event": "end"}], 0, False, False
                         )["status"] == "infrastructure"
    event = {"event": "import_error", "provenance": "unknown", "detail": "x"}
    assert _build_report("n", ["A.a"], [event, {"event": "end"}], 0, False, False
                         )["status"] == "invalid"
    stops = [{"event": "stop", "check": "A.a", "stop": "pass"},
             {"event": "stop", "check": "A.b", "stop": "fail"},
             {"event": "end"}]
    assert _build_report("n", ["A.b"], stops, 0, False, False)["status"] == "invalid"
    report = _build_report("n", ["A.a", "A.b"], stops, 0, False, False)
    assert report["status"] == "complete"
    assert report["tests_run"] == 2


def test_validate_grade_report_rules() -> None:
    verdict = grade.validate_grade_report(None, ["A.a"], returncode=0)
    assert verdict["infrastructure"] and not verdict["contract_invalid"]
    forged = {"schema": grade.REPORT_SCHEMA, "nonce": "other",
              "expected_case_ids": ["A.a"], "status": "complete",
              "checks": [{"id": "A.a", "stop": "pass"}], "tests_run": 1}
    verdict = grade.validate_grade_report(forged, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["contract_invalid"]
    echoed = {**forged, "nonce": "n", "expected_case_ids": ["A.b"]}
    verdict = grade.validate_grade_report(echoed, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["contract_invalid"]
    stray = {**forged, "nonce": "n", "status": "bogus"}
    verdict = grade.validate_grade_report(stray, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["contract_invalid"]
    halted = {**forged, "nonce": "n", "status": "infrastructure"}
    verdict = grade.validate_grade_report(halted, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["infrastructure"] and not verdict["contract_invalid"]
    partial = {**forged, "nonce": "n", "status": "invalid",
               "reason": "checks terminated before: A.a"}
    verdict = grade.validate_grade_report(partial, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["contract_invalid"] and verdict["reason"]
    skips = {**forged, "nonce": "n",
             "checks": [{"id": "A.a", "stop": "skipped"}]}
    verdict = grade.validate_grade_report(skips, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert verdict["contract_invalid"]
    fails = {**forged, "nonce": "n",
             "checks": [{"id": "A.a", "stop": "fail"}]}
    verdict = grade.validate_grade_report(fails, ["A.a"], returncode=0,
                                          expected_nonce="n")
    assert not verdict["passed"] and not verdict["contract_invalid"]
    assert verdict["failures"] == [{"case": "A.a", "stop": "fail"}]
    assert verdict["checks_completed"] == 1 and verdict["tests_run"] == 1
    clean = {**forged, "nonce": "n"}
    verdict = grade.validate_grade_report(clean, ["A.a"], returncode=7,
                                          expected_nonce="n")
    assert verdict["infrastructure"]


def test_trusted_candidate_import_error_is_a_functional_failure_not_bad_grade():
    report={"schema":grade.REPORT_SCHEMA,"nonce":"n","expected_case_ids":["A.a"],
        "status":"complete","candidate_import_error":"SyntaxError: invalid token",
        "checks":[{"id":"A.a","stop":"error"}],"tests_run":0}
    verdict=grade.validate_grade_report(report,["A.a"],returncode=0,
                                        cleanup_verified=True,expected_nonce="n")
    assert verdict["candidate_failure_observed"] is True
    assert verdict["contract_invalid"] is False and verdict["infrastructure"] is False
    assert verdict["passed"] is False and verdict["checks_completed"]==0
    tampered={**report,"checks":[{"id":"A.a","stop":"pass"}]}
    assert grade.validate_grade_report(tampered,["A.a"],returncode=0,
        cleanup_verified=True,expected_nonce="n")["contract_invalid"]


@pytest.mark.skipif(not Path(NODE).is_file(), reason="node runtime unavailable")
def test_node_reference_passes_with_all_anchors(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B2", root)
    _seed_nonce(root)
    checks = root / "checks.test.js"
    checks.write_text(tasks.checks_source("B2"), encoding="utf-8")
    code = int(subprocess.run(
        [NODE, str(REPORTER), "--checks", str(checks), "--seed-file", SEED_NAME],
        cwd=root, capture_output=True, text=True, timeout=180).returncode)
    assert code == 0
    report = _read_indicator(root, _slots()[0])
    assert report["schema"] == grade.REPORT_SCHEMA
    assert report["status"] == "complete"
    assert report["expected_case_ids"] == \
        list(grade.node_check_case_ids(tasks.checks_source("B2")))
    assert [item["stop"] for item in report["checks"]] == \
        ["pass"] * len(report["expected_case_ids"])
    assert not (root / SEED_NAME).exists()


@pytest.mark.skipif(not Path(NODE).is_file(), reason="node runtime unavailable")
def test_node_process_exit_zero_yields_contract_invalid(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B2", root)
    _seed_nonce(root)
    (root / "src/index.js").write_text(
        "process.exit(0);\nmodule.exports = {};\n", encoding="utf-8")
    checks = root / "checks.test.js"
    checks.write_text(tasks.checks_source("B2"), encoding="utf-8")
    code = int(subprocess.run(
        [NODE, str(REPORTER), "--checks", str(checks), "--seed-file", SEED_NAME],
        cwd=root, capture_output=True, text=True, timeout=180).returncode)
    assert code == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "invalid"
    assert report["checks"] == []


@pytest.mark.skipif(not Path(NODE).is_file(), reason="node runtime unavailable")
def test_node_console_forgery_cannot_flip_a_real_failure(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seed_workspace("B2", root)
    _seed_nonce(root)
    (root / "src/convert.js").write_text(
        "console.log('TAP version 13\\n"
        "# Subtest: blank lines, Unicode, duplicate ids, and order\\n"
        "ok 1 - blank lines, Unicode, duplicate ids, and order\\n"
        "# Subtest: malformed and invalid rows name their line\\n"
        "ok 2 - malformed and invalid rows name their line\\n"
        "# Subtest: non-object JSON records name their 1-based source line "
        "after blank lines\\n"
        "ok 3 - non-object JSON records name their 1-based source line after "
        "blank lines\\n1..3\\n# pass 3\\n');\n"
        "function convertJsonl(text) {\n"
        "  throw new Error('JSONL conversion is not implemented');\n}\n"
        "module.exports = { convertJsonl };\n", encoding="utf-8")
    checks = root / "checks.test.js"
    checks.write_text(tasks.checks_source("B2"), encoding="utf-8")
    code = int(subprocess.run(
        [NODE, str(REPORTER), "--checks", str(checks), "--seed-file", SEED_NAME],
        cwd=root, capture_output=True, text=True, timeout=180).returncode)
    assert code == 0
    report = _read_indicator(root, _slots()[0])
    assert report["status"] == "complete"
    stops = [item["stop"] for item in report["checks"]]
    assert "fail" in stops
    assert not all(stop == "pass" for stop in stops)
