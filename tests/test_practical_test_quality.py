"""Task 6 controls: authored-test regression quality is measured, never assumed."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark import practical_runtime_v2 as runtime
from benchmark import practical_tasks_v2 as tasks
from benchmark import practical_test_quality as quality
from benchmark.practical_evidence import VERIFIED_TEST_QUALITIES


def _result(**overrides):
    values = {"returncode": 0, "timed_out": False, "cleanup_verified": True,
              "output": b"", "workspace_outputs": {}, "infrastructure_error": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def _install_supervisor(monkeypatch, exporter):
    """Patch runtime.SandboxSupervisor; returns (spec calls, shared captures)."""
    calls = []
    captures = {}

    class Supervisor:
        def run(self, spec):
            calls.append(spec)
            return exporter(spec, captures)

    monkeypatch.setattr(runtime, "SandboxSupervisor", Supervisor)
    return calls, captures


def _make_snapshot(directory: Path, files: dict[str, str]) -> Path:
    """Snapshot bytes laid out exactly like the driver's workspace snapshot."""
    source_root = directory / "workspace"
    for name, content in files.items():
        target = source_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    snapshot = directory / ".snapshot1.zip"
    with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(source_root.rglob("*")):
            if source.is_file():
                archive.write(source, str(source.relative_to(source_root)))
    return snapshot


def _capture_seed_files(spec, captures) -> None:
    captures["seed_files"] = {
        path.relative_to(spec.workspace).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(spec.workspace.rglob("*")) if path.is_file()}


def _candidate(**overrides):
    values = {"passed": True, "suite_passed": True, "count": 2, "baseline_count": 1,
              "additional_count": 1, "returncode": 0, "timed_out": False,
              "cleanup_verified": True, "infrastructure": False, "reason": None,
              "output": "# tests 2\n# pass 2\n"}
    values.update(overrides)
    return values


B1_CANDIDATE_FILES = {
    "orders/report.py": """def build_report(records):
    totals = {}
    seen = set()
    for record in records:
        if record['id'] in seen:
            continue
        seen.add(record['id'])
        customer = record['customer']
        totals[customer] = totals.get(customer, 0) + record['amount_cents']
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

M1_CANDIDATE_FILES = {
    "src/config/merge.js": """function isPlain(value) {
  return Object.prototype.toString.call(value) === '[object Object]';
}


function clone(value) {
  if (Array.isArray(value)) return value.map(clone);
  if (isPlain(value)) {
    const out = {};
    for (const key of Object.keys(value)) {
      out[key] = isPlain(value[key]) || Array.isArray(value[key]) ? clone(value[key]) : value[key];
    }
    return out;
  }
  return value;
}
function mergeConfig(base, override) {
  const out = clone(base);
  for (const key of Object.keys(override)) {
    if (override[key] === undefined) continue;
    out[key] = isPlain(override[key]) && isPlain(out[key]) ? mergeConfig(out[key], override[key]) : clone(override[key]);
  }
  return out;
}
module.exports = { mergeConfig };
""",
    "tests/test_agent.test.js": """const {test}=require('node:test'); const a=require('node:assert/strict');
const {resolveConfig}=require('../src/config');
test('arrays stay independent', () => {
  const base = resolveConfig({});
  base.tags.push('x');
  assert.deepEqual(resolveConfig({}).tags, ['default']);
});
""",
}


def test_real_counted_import_error_is_not_regression_quality(tmp_path):
    """unittest counts _FailedTest as one test; that is not a killed regression."""
    workspace = tmp_path / 'candidate'
    tasks.seed_task('B1', workspace)
    files = tasks.reference_files('B1')
    files['orders/report.py'] += '\ndef added_helper(): return 42\n'
    files['tests/test_agent.py'] = (
        'import unittest\nfrom orders.report import added_helper\n'
        'class AgentTests(unittest.TestCase):\n'
        ' def test_added_helper(self): self.assertEqual(added_helper(),42)\n')
    for name, content in files.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    candidate = quality.run_seed_suite('B1', workspace, lab=runtime.LAB)
    assert candidate['suite_passed'], candidate
    snapshot = tmp_path / 'candidate.zip'
    with zipfile.ZipFile(snapshot, 'w') as archive:
        for path in workspace.rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(workspace))
    result = quality.assess_authored_regression('B1', snapshot, lab=runtime.LAB,
                                               candidate=candidate)
    assert result['seed']['count'] > 0, result
    assert '_FailedTest' in result['seed']['output'], result
    assert result['quality'] == quality.UNVERIFIED, result


# --- the Gemma M1 r3 analog: suite passes on the candidate and on the seed ------


def test_smoke_suite_passing_on_both_sides_is_weak_and_never_verified(
        monkeypatch, tmp_path):
    """A suite that also passes on the buggy seed (Gemma M1 r3) earns no verified quality."""
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("M1"), **M1_CANDIDATE_FILES})
    before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    calls, _ = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        output=b"TAP version 13\nok 1 - arrays stay independent\n# tests 2\n# pass 2\n"))

    assessment = quality.assess_authored_regression(
        "M1", snapshot, lab=tmp_path, candidate=_candidate())

    assert assessment["quality"] == "weak"
    assert assessment["reason"] == "submitted suite passes on the restored original seed too"
    assert assessment["seed"]["returncode"] == 0 and assessment["seed"]["count"] == 2
    assert assessment["seed"]["suite_passed"] is True
    assert len(calls) == 1 and "seedcheck" in str(calls[0].workspace)
    assert assessment["quality"] not in VERIFIED_TEST_QUALITIES
    # The original snapshot bytes are untouched by the assessment.
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == before


def test_seed_restoration_runs_on_the_graded_authored_sandbox_shape(
        monkeypatch, tmp_path):
    """Seed suite shares argv, mounts, environment and limits with the graded
    authored sandbox: both measurements run on the same constrained box."""
    calls, _captures = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        output=b"Ran 2 tests in 0.001s\n\nOK\n"))
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    authored = runtime._authored_test_result("B1", workspace, lab=tmp_path)
    assert authored["passed"] is True and authored["count"] == 2

    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1")})
    quality.assess_authored_regression("B1", snapshot, lab=tmp_path,
                                       candidate=_candidate())

    assert len(calls) == 2
    graded_box, seed_box = calls[0], calls[1]
    assert seed_box.argv == graded_box.argv
    assert seed_box.env == graded_box.env
    assert seed_box.limits == graded_box.limits
    assert [(str(bind.source), str(bind.target), bind.symlinks_within_source)
            for bind in seed_box.runtime_ro] == \
        [(str(bind.source), str(bind.target), bind.symlinks_within_source)
         for bind in graded_box.runtime_ro]
    assert str(seed_box.workspace) != str(graded_box.workspace)
    assert "seedcheck" in str(seed_box.workspace) and "seedcheck" not in str(graded_box.workspace)


# --- the regression side: seed asserts differ from the candidate ----------------


def test_python_assert_failure_on_the_restored_seed_detects_the_regression(
        monkeypatch, tmp_path):
    """Submitted suite passes on the candidate and fails the buggy seed on asserts."""
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1"), **B1_CANDIDATE_FILES})
    provenance_before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    calls, captures = _install_supervisor(monkeypatch, lambda spec, seen: (
        _capture_seed_files(spec, seen),
        _result(returncode=1,
                output=b"Ran 2 tests in 0.001s\n\nFAILED (failures=1)\n"
                       b"FAIL: test_first_delivery_wins_and_refunds_sum "
                       b"(tests.test_agent.AgentAuthoredTest)\n"))[-1])

    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())

    assert assessment["quality"] == "regression_detected"
    assert assessment["seed"]["returncode"] == 1 and assessment["seed"]["count"] == 2
    assert assessment["candidate"]["passed"] is True
    assert assessment["quality"] in VERIFIED_TEST_QUALITIES
    # The restored seed is byte-identical to a fresh seed, and the submitted
    # tests survived the restore untouched.
    restored = captures["seed_files"]
    for name, content in tasks.seed_sources("B1").items():
        assert restored[name] == content
        assert assessment["provenance"]["restored_seed_sha256"][name] == \
            hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert restored["tests/test_agent.py"] == B1_CANDIDATE_FILES["tests/test_agent.py"]
    assert assessment["provenance"]["snapshot_sha256"] == provenance_before
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == provenance_before
    assert len(calls) == 1


def test_tap_failure_evidence_detects_the_regression_for_node_tasks(
        monkeypatch, tmp_path):
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("M1"), **M1_CANDIDATE_FILES})
    _install_supervisor(monkeypatch, lambda spec, seen: _result(
        returncode=1,
        output=b"TAP version 13\nok 1 - arrays stay independent\n"
               b"not ok 2 - alias regression\n# tests 2\n# pass 1\n# fail 1\n"))

    assessment = quality.assess_authored_regression(
        "M1", snapshot, lab=tmp_path, candidate=_candidate())

    assert assessment["quality"] == "regression_detected"
    assert assessment["seed"]["returncode"] == 1 and assessment["seed"]["count"] == 2
    assert assessment["seed"]["infrastructure"] is False


def test_seed_run_that_collected_no_tests_is_import_setup_not_regression(
        monkeypatch, tmp_path):
    """Both genuine import-error output and runner output without per-test
    failure marks leave the quality unverified."""
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1"), **B1_CANDIDATE_FILES})
    calls, _ = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        returncode=1,
        output=b"Traceback (most recent call last):\n"
               b"ModuleNotFoundError: No module named 'orders'\n"))
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())
    assert assessment["quality"] == "unverified"
    assert assessment["reason"] == "seed run collected no tests; import or setup failure"
    assert assessment["seed"]["count"] == 0

    no_evidence = "seed failure without per-test failure evidence"
    _install_supervisor(monkeypatch, lambda spec, seen: _result(
        returncode=1,
        output=b"Ran 2 tests in 0.001s\n\nFAILED (failures=1)\n"
               b"Traceback text truncated before any per-test header\n"))
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())
    assert assessment["quality"] == "unverified"
    assert assessment["reason"] == no_evidence


# --- unverifiable sides: no quality is invented for either sandbox --------------


def test_candidate_side_failures_never_enter_the_seed_sandbox(
        monkeypatch, tmp_path):
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1"), **B1_CANDIDATE_FILES})
    calls, _ = _install_supervisor(
        monkeypatch, lambda spec, seen: pytest.fail("seed suite must not launch"))

    infrastructure = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path,
        candidate=_candidate(infrastructure=True, suite_passed=False))
    assert infrastructure["quality"] == "unverified"
    assert infrastructure["reason"] == "candidate suite sandbox infrastructure error"

    failed_suite = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path,
        candidate=_candidate(passed=False, suite_passed=False, returncode=1))
    assert failed_suite["quality"] == "unverified"
    assert failed_suite["reason"].startswith("candidate suite did not pass")

    no_tests = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate(count=1, passed=True))
    assert no_tests["quality"] == "not_applicable"
    assert no_tests["reason"] == "no authored tests beyond the baseline"

    absent = quality.assess_authored_regression("B1", snapshot, lab=tmp_path,
                                                candidate=None)
    assert absent["quality"] == "unverified"
    assert absent["reason"] == "no authored-test result for this phase"
    assert calls == []


def test_unreadable_or_missing_snapshots_stay_unverified(monkeypatch, tmp_path):
    calls, _ = _install_supervisor(
        monkeypatch, lambda spec, seen: pytest.fail("seed suite must not launch"))
    missing = quality.assess_authored_regression(
        "B1", tmp_path / ".snapshot1.zip", lab=tmp_path, candidate=_candidate())
    assert missing["quality"] == "unverified"
    assert missing["reason"] == "phase snapshot unavailable"

    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"PK-corrupted-not-a-zip")
    broken = quality.assess_authored_regression("B1", corrupt, lab=tmp_path,
                                                candidate=_candidate())
    assert broken["quality"] == "unverified"
    assert broken["reason"].startswith("snapshot restore failed:")
    assert calls == []


def test_seed_infrastructure_and_timeouts_stay_unverified(monkeypatch, tmp_path):
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1"), **B1_CANDIDATE_FILES})
    calls, _ = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        infrastructure_error="namespace setup failed"))
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())
    assert assessment["quality"] == "unverified"
    assert assessment["reason"] == "seed suite sandbox infrastructure error"

    calls = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        cleanup_verified=False))[0]
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())
    assert assessment["quality"] == "unverified"
    assert assessment["reason"] == "seed suite sandbox infrastructure error"

    calls = _install_supervisor(monkeypatch, lambda spec, seen: _result(
        returncode=124, timed_out=True,
        output=b"Ran 2 tests in 29.9s\nFAIL: test_x (tests.test_agent.AgentAuthoredTest)\n"))[0]
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=_candidate())
    assert assessment["quality"] == "unverified"
    assert assessment["reason"] == "seed suite timed out"
    assert len(calls) == 1


def test_mcp_language_has_no_authored_suite_to_assess(monkeypatch, tmp_path):
    calls, _ = _install_supervisor(
        monkeypatch, lambda spec, seen: pytest.fail("seed suite must not launch"))
    assessment = quality.assess_authored_regression("C2", tmp_path, lab=tmp_path,
                                                    candidate=None)
    assert assessment["quality"] == "not_applicable"
    assert calls == []
    weak_candidate = quality.assess_authored_regression(
        "C2", tmp_path, lab=tmp_path,
        candidate={"passed": None, "count": 0, "baseline_count": 0})
    assert weak_candidate["quality"] == "not_applicable"


def test_missing_suite_passed_flag_falls_back_to_the_passed_field(
        monkeypatch, tmp_path):
    snapshot = _make_snapshot(tmp_path, {**tasks.seed_sources("B1")})
    calls, _ = _install_supervisor(
        monkeypatch, lambda spec, seen: pytest.fail("seed suite must not launch"))
    failed = _candidate(passed=False)
    del failed["suite_passed"]
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=failed)
    assert assessment["quality"] == "unverified"
    assert calls == []

    strong = _candidate()
    del strong["suite_passed"]
    _install_supervisor(monkeypatch, lambda spec, seen: _result(
        output=b"Ran 2 tests in 0.001s\n\nOK\n"))
    assessment = quality.assess_authored_regression(
        "B1", snapshot, lab=tmp_path, candidate=strong)
    assert assessment["quality"] == "weak"


# --- aggregation and factory contracts -----------------------------------------


def test_aggregate_is_conservatively_ranked():
    assert quality.aggregate_qualities([]) == "not_applicable"
    assert quality.aggregate_qualities(
        ["regression_detected", "regression_detected"]) == "regression_detected"
    assert quality.aggregate_qualities(
        ["regression_detected", "weak"]) == "weak"
    assert quality.aggregate_qualities(
        ["regression_detected", "not_applicable"]) == "regression_detected"
    assert quality.aggregate_qualities(
        ["regression_detected", "weak", "unverified"]) == "unverified"
    assert quality.aggregate_qualities(["not_applicable"]) == "not_applicable"
    # Unknown vocabulary (including a missing phase value) caps at unverified.
    assert quality.aggregate_qualities([None]) == "unverified"
    assert quality.aggregate_qualities(["junk"]) == "unverified"


def test_make_assessment_rejects_unknown_quality():
    with pytest.raises(ValueError, match="unknown authored-test quality"):
        quality.make_assessment("B1", "verified_strong", "n/a")
    recorded = quality.make_assessment("B1", quality.WEAK, "reason")
    assert recorded["provenance"] == {"snapshot_sha256": None,
                                      "restored_seed_sha256": {}}
