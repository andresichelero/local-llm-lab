"""Task 8 sweep tests: census verification, append-only regrade, derived files."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from benchmark import post_audit_v9_regrade as sweep
from benchmark import practical_runtime_v2 as runtime
from benchmark import practical_tasks_v2 as tasks
from benchmark.practical_campaign_v2 import _hash_value


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(payload_text + ("\n" if not payload_text.endswith("\n") else ""),
                    encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fake_episode_record(tmp_path: Path, output_dir: Path, *, task: str = "B2") -> tuple[Path, dict]:
    run_dir = output_dir / "runs" / "ep-1"
    run_dir.mkdir(parents=True)
    (run_dir / "native.jsonl").write_bytes(b'{"event":"x"}\n')
    (run_dir / "execution.json").write_text("{}", encoding="utf-8")
    (run_dir / ".snapshot1.zip").write_bytes(b"snap-bytes")
    record = {"task": task, "model": "model-a", "protocol": "p-v1",
              "repetition": 1, "profile": "baseline", "correct": True,
              "autonomous": True, "failure": "passed"}
    _write(run_dir / "record.json", record)
    return run_dir, record


def _census(tmp_path: Path, run_dirs: list[Path], *, regradable: bool = True,
            output_name: str = "out-1") -> dict:
    output_dir = tmp_path / output_name
    immutable = {"protocol_id": "p-v1", "repetition_seeds": {"1": 101}}
    manifest = {"immutable": immutable, "immutable_sha256": _hash_value(immutable),
                "protocol_id": "p-v1"}
    _write(output_dir / "manifest.json", manifest)
    runs = []
    for run_dir in run_dirs:
        evidence = {}
        for name in ("record.json", "native.jsonl", "execution.json", ".snapshot1.zip"):
            path = run_dir / name
            if path.is_file():
                evidence[name] = {"bytes": path.stat().st_size, "sha256": _digest(path)}
        runs.append({
            "run_dir": str(run_dir),
            "references": [{"output": output_name, "status": "review_required",
                            "failure": "budget_exhausted", "correct": True,
                            "autonomous": True, "model": "model-a",
                            "profile": "baseline", "repetition": 1}],
            "evidence": evidence,
            "regradable": regradable,
        })
    census = {"created_at_utc": "now", "outputs": [
        {"output": str(output_dir), "protocol": "p-v1", "status": "review_required",
         "rows": len(runs), "immutable_hash_valid": True}], "runs": runs}
    census_path = tmp_path / "inventory.json"
    _write(census_path, census)
    return census_path


def _fake_regrade(monkeypatch, corrections: dict[str, bool] | None = None):
    """Replace runtime._regrade_record with an append-only fake verdict."""
    calls = []

    def fake_regrade(run_dir, row, *, task_contract_id, verdict_profile, evaluation_producer=None):
        calls.append(run_dir)
        row["task"] = row.get("task") or "B2"
        good = bool((corrections or {}).get(row.get("task"), True))
        value = {
            "task": row.get("task"), "model": row.get("model"),
            "phases": [{'phase':phase,'hidden':{'passed':good,'reason':None if good else 'fixture wrong result'}}
                       for phase in range(1,tasks.TASK_SPECS[row['task']]['phases']+1)],
            "task_contract_id": task_contract_id, "verdict_profile": verdict_profile,
            "record_task_contract_id": tasks.HISTORICAL_CONTRACT, "mcp_grade": None,
            "correct": good, "original_score_preserved": True,
            'evaluation_producer':evaluation_producer,
        }
        from benchmark.practical_evidence import append_verdict

        value["evaluation_path"] = str(append_verdict(run_dir, value))
        return value

    monkeypatch.setattr(runtime, "_regrade_record", fake_regrade)
    return calls


def test_sweep_appends_one_verdict_and_writes_the_collection(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    calls = _fake_regrade(monkeypatch)
    collection = tmp_path / "collection"

    summary = sweep.run_sweep(census_path=census_path, collection_dir=collection)

    assert calls == [run_dir]
    assert summary["counters"] == {"regraded": 1}
    assert summary["counters"].get("recovered") is None
    ledger = [json.loads(line) for line in
              (collection / "regrades-j2.jsonl").open(encoding="utf-8") if line.strip()]
    assert len(ledger) == 1
    row = ledger[0]
    assert row["run_dir"] == str(run_dir)
    assert row["protocol"] == "p-v1"
    assert row["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert row["verdict_profile"] == "main"
    assert row["regraded_correct"] is True
    assert row["functional_change_from_original"] is False
    assert row["recovered"] is False
    envelope = json.loads((collection / "collection.json").read_text(encoding="utf-8"))
    assert envelope["counters"] == {"regraded": 1}
    assert envelope["inference_started"] is False
    assert envelope["artifacts"]["regrades-j2.jsonl"]["rows"] == 1
    assert envelope["artifacts"]["review-required.json"]["records"] == 0
    # The appended verdict lives under this exact grader-source version.
    evaluation = json.loads(Path(row["evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation["task_contract_id"] == tasks.HISTORICAL_CONTRACT
    assert "practical_runtime_v2.py" in evaluation["grader_hashes"]


def test_sweep_reports_mutated_evidence_and_unknown_tasks_as_review(tmp_path, monkeypatch):
    run_dir, record = _fake_episode_record(tmp_path, tmp_path / "out-1")
    mutated = tmp_path / "out-1" / "runs" / "ep-2" / "record.json"
    mutated.parent.mkdir(parents=True, exist_ok=True)
    (mutated.parent / ".snapshot1.zip").write_bytes(b"snap")
    (mutated.parent / "native.jsonl").write_bytes(b"x\n")
    _write(mutated, {**record, "task": "B2", "correct": False})
    foreign = tmp_path / "out-1" / "runs" / "ep-3" / "record.json"
    foreign.parent.mkdir(parents=True)
    (foreign.parent / ".snapshot1.zip").write_bytes(b"snap")
    (foreign.parent / "native.jsonl").write_bytes(b"x\n")
    _write(foreign, {**record, "task": "legacy-bugfix", "protocol": "p-v1"})
    snapshotless = tmp_path / "out-1" / "runs" / "ep-4" / "record.json"
    snapshotless.parent.mkdir(parents=True)
    (snapshotless.parent / "native.jsonl").write_bytes(b"x\n")
    _write(snapshotless, record)
    census_path = _census(tmp_path, [run_dir, mutated.parent, foreign.parent, snapshotless.parent])
    # The audit recorded ep-2 bytes; simulate drift after the audit's snapshot.
    (mutated.parent / "native.jsonl").write_bytes(b"changed-after-audit\n")
    calls = _fake_regrade(monkeypatch)
    collection = tmp_path / "collection"

    summary = sweep.run_sweep(census_path=census_path, collection_dir=collection)

    assert calls == [run_dir]
    assert summary["counters"] == {"regraded": 1, "review": 3}
    problems = {item["run_dir"]: item["problem"] for item in summary["review_required"]}
    assert problems[str(mutated.parent)] == "evidence changed since the audit: native.jsonl"
    assert problems[str(foreign.parent)].endswith("outside the v2 task catalog")
    assert problems[str(snapshotless.parent)] == (
        "no snapshot on disk despite the census marking it regradable")
    review = json.loads((collection / "review-required.json").read_text(encoding="utf-8"))
    assert len(review) == 3
    assert len(json.loads((collection / "out-of-scope-records.json").read_text(encoding="utf-8"))) == 0


def test_sweep_marks_non_regradable_census_rows_out_of_scope(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir], regradable=False)
    calls = _fake_regrade(monkeypatch)

    summary = sweep.run_sweep(census_path=census_path, collection_dir=tmp_path / "collection")

    assert summary["counters"] == {"out_of_scope": 1}
    assert calls == []
    out_of_scope = json.loads(
        (tmp_path / "collection" / "out-of-scope-records.json").read_text(encoding="utf-8"))
    assert out_of_scope == [{"run_dir": str(run_dir), "census_status": ["review_required"],
                             "census_failures": ["budget_exhausted"], "status": "out_of_scope"}]


def test_sweep_is_crash_safe_and_never_appends_twice(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    calls = _fake_regrade(monkeypatch)
    collection = tmp_path / "collection"

    sweep.run_sweep(census_path=census_path, collection_dir=collection)
    resumend = sweep.run_sweep(census_path=census_path, collection_dir=collection)

    assert calls == [run_dir]                      # no duplicate grading
    assert resumend["counters"] == {"regraded": 1, "recovered": 1}
    ledger = [json.loads(line) for line in (collection / "regrades-j2.jsonl")
              .open(encoding="utf-8") if line.strip()]
    assert len(ledger) == 1 and ledger[0]["recovered"] is True


def test_dry_run_verifies_and_writes_nothing(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir], regradable=False)
    calls = _fake_regrade(monkeypatch)

    summary = sweep.run_sweep(dry_run=True, census_path=census_path,
                              collection_dir=tmp_path / "collection")

    assert summary["counters"] == {"out_of_scope": 1, "would_regrade": 0}
    assert not (tmp_path / "collection").exists()
    assert calls == []


def test_locked_output_records_the_name_and_grades_nothing(tmp_path, monkeypatch, capsys):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    calls = _fake_regrade(monkeypatch)

    from contextlib import contextmanager

    @contextmanager
    def contended(_output):
        raise RuntimeError("review replay is already running")
        yield

    monkeypatch.setattr(sweep, "output_lock", contended)

    summary = sweep.run_sweep(census_path=census_path, collection_dir=tmp_path / "collection")

    assert summary["locked_outputs"], summary
    assert calls == []
    assert summary["counters"] == {}
    assert len(summary["regraded"]) == 0


def test_counterexample_confirmation_separates_confirmed_from_divergent(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    _fake_regrade(monkeypatch, corrections={"B2": False})
    collection = tmp_path / "collection"
    sweep.run_sweep(census_path=census_path, collection_dir=collection)

    affected = [{"run_dir": str(run_dir), "task": "B2", "model": "model-a",
                 "protocol": "p-v1", "repetition": 1, "correct": True,
                 "autonomous": True, "failure": "passed", "reasons": ["audit_reason"]},
                {"run_dir": str(tmp_path / "missing"), "task": "B2",
                 "correct": True, "reasons": ["orphan"]}]
    summary_path = tmp_path / "summary.json"
    _write(summary_path, {"affected_positive_episodes": affected})

    report = sweep.confirm_counterexamples(summary_path=summary_path, collection_dir=collection)

    assert report["counts"] == {"affected": 2, "confirmed": 1, "divergent": 0, "unmatched": 1}
    assert report["confirmed"][0]["run_dir"] == str(run_dir)
    assert report["confirmed"][0]["regraded_correct"] is False
    confirmation = json.loads((collection / "counterexamples-confirmation.json")
                              .read_text(encoding="utf-8"))
    assert confirmation["counts"]["confirmed"] == 1
    envelope = json.loads((collection / "collection.json").read_text(encoding="utf-8"))
    assert envelope["counterexamples"] == {"affected": 2, "confirmed": 1,
                                           "divergent": 0, "unmatched": 1}
    assert envelope["artifacts"]["counterexamples-confirmation.json"]["records"] == 1


def test_counterexample_divergence_is_reported_not_hidden(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    _fake_regrade(monkeypatch, corrections={"B2": True})
    collection = tmp_path / "collection"
    sweep.run_sweep(census_path=census_path, collection_dir=collection)
    summary_path = tmp_path / "summary.json"
    _write(summary_path, {"affected_positive_episodes": [
        {"run_dir": str(run_dir), "task": "B2", "correct": True, "reasons": ["a"]}]})

    report = sweep.confirm_counterexamples(summary_path=summary_path, collection_dir=collection)

    assert report["counts"] == {"affected": 1, "confirmed": 0, "divergent": 1, "unmatched": 0}
    assert report["divergent"][0]["needs_explanation"]


def test_legacy_v1_verdicts_reuse_only_on_identical_hashes(tmp_path, monkeypatch):
    fake_root = tmp_path
    (tmp_path / "benchmark").mkdir()
    for name, blob in (("practical_selection.py", "grader-a"), ("practical_tasks.py", "grader-b")):
        (tmp_path / "benchmark" / name).write_text(blob, encoding="utf-8")
    evidence = tmp_path / "evidence" / "record.json"
    _write(evidence, {"task": "bugfix"})
    monkeypatch.setattr(sweep, "ROOT", fake_root)

    legacy_path = tmp_path / "legacy-v1.json"
    _write(legacy_path, {
        "grader_sha256": {"practical_selection.py": _digest(tmp_path / "benchmark" / "practical_selection.py"),
                          "practical_tasks.py": _digest(tmp_path / "benchmark" / "practical_tasks.py")},
        "legacy_v1_separate_protocol": True, "note": "keep",
        "records": [{"task": "bugfix", "model": "q", "run_dir": str(evidence.parent),
                     "source_output": "out-v1", "correct": True, "failure": "passed",
                     "evidence_sha256": {str(evidence): _digest(evidence)}},
                    {"task": "mcp_report", "model": "q", "run_dir": str(evidence.parent),
                     "source_output": "out-v1", "correct": True, "failure": "passed",
                     "evidence_sha256": {str(evidence): "0" * 64}}]})

    report = sweep.legacy_v1_reuse_report(legacy_path=legacy_path, collection_dir=tmp_path / "c")

    assert report["grader_identical"] is True
    assert [row["reused"] for row in report["records"]] == [True, False]
    assert report["decision"] == "not reused; would require a new legacy v1 regrade"
    reuse = json.loads((tmp_path / "c" / "legacy-v1-reuse.json").read_text(encoding="utf-8"))
    assert reuse["decision"] == report["decision"]


def test_changed_evidence_under_the_audit_never_gets_graded(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    (run_dir / ".snapshot1.zip").write_bytes(b"tampered-after-audit")
    calls = _fake_regrade(monkeypatch)

    summary = sweep.run_sweep(census_path=census_path, collection_dir=tmp_path / "collection")

    assert summary["counters"] == {"review": 1}
    assert calls == []
    assert summary["review_required"][0]["problem"].endswith(".snapshot1.zip")


def _evidence_for(run_dir: Path) -> dict[str, dict[str, int | str]]:
    """Census-style evidence map over the files an episode actually keeps."""
    evidence = {}
    for name in ("record.json", "native.jsonl", "execution.json", ".snapshot1.zip"):
        path = run_dir / name
        if path.is_file():
            evidence[name] = {"bytes": path.stat().st_size, "sha256": _digest(path)}
    return evidence


def _transport_census(tmp_path: Path, runs: list[dict]) -> Path:
    census_path = tmp_path / "transport-inventory.json"
    _write(census_path, {"created_at_utc": "now", "outputs": [], "runs": runs})
    return census_path


def test_transport_qualification_reports_the_verified_facts(tmp_path):
    # Episode 1: the Qwen 4B C1 r1 SIGTERM shape — empty native, no snapshots,
    # the broker transcript proving the chat posts all reached the upstream.
    qwen_run = tmp_path / "sel-v2-r1" / "runs" / "qwen-ep"
    qwen_run.mkdir(parents=True)
    (qwen_run / "native.jsonl").write_bytes(b"")
    _write(qwen_run / "record.json", {
        "task": "C1", "model": "qwen3.5-4b", "repetition": 1,
        "correct": False, "failure": "wrong_result", "model_calls": 8,
        "deadline_exceeded": False,
        "sandbox": {"resource_evidence": {"candidate_returncode": -15}}})
    broker = qwen_run / "broker"
    broker.mkdir()
    posts = [
        {"path": "/v1/chat/completions", "status": 200,
         "upstream_started_utc": "2026-10-18T22:39:36.547731+00:00",
         "completed_utc": "2026-10-18T22:40:19.031604+00:00"},
        {"path": "/v1/chat/completions", "status": 200,
         "upstream_started_utc": "2026-10-18T22:39:38+00:00",
         "completed_utc": "2026-10-18T22:40:21+00:00"},
        {"path": "/v1/health", "status": 200, "completed_utc": "2026-10-18T22:41:00+00:00"},
    ]
    # Transcript lines are not guaranteed chronological: this later line
    # records an earlier start, so the window must take the minimum.
    posts.append({"path": "/v1/chat/completions", "status": 200,
                  "upstream_started_utc": "2026-10-18T22:39:35.004330+00:00",
                  "completed_utc": "2026-10-18T22:40:17+00:00"})
    (broker / "transcript.jsonl").write_text(
        "".join(json.dumps(post, ensure_ascii=False) + "\n" for post in posts),
        encoding="utf-8")
    qwen_sibling = tmp_path / "sel-v2-r3" / "runs" / "qwen-r3"
    qwen_sibling.mkdir(parents=True)
    _write(qwen_sibling / "record.json", {
        "task": "C1", "model": "qwen3.5-4b", "repetition": 1,
        "correct": False, "failure": "call_limit", "model_calls": 21})
    # Episode 2: the Bonsai 9B D2 transport shape — API socket outage plus a
    # snapshot whose files are still the task's own stubs.
    bonsai_run = tmp_path / "repair-r2" / "runs" / "bonsai-ep"
    bonsai_run.mkdir(parents=True)
    (bonsai_run / "native.jsonl").write_text(json.dumps({
        "type": "error", "error": {"name": "APIError", "data": {
            "message": "Cannot connect to API: socket closed unexpectedly",
            "isRetryable": True}}}, ensure_ascii=False) + "\n", encoding="utf-8")
    _write(bonsai_run / "record.json", {
        "task": "D2", "model": "bonsai-2-9b", "repetition": 1,
        "correct": False, "failure": "configuration", "agent_finished": False,
        "model_calls": 45, "environment_passed": True,
        "phases": [{"phase": 1, "authored_tests": {"count": 1}}]})
    with zipfile.ZipFile(bonsai_run / ".snapshot1.zip", "w") as archive:
        archive.writestr("src/ledger.js", "throw new Error('not implemented');")
        archive.writestr("src/index.js", "staging();")
    bonsai_sibling = tmp_path / "repair-v1" / "runs" / "bonsai-sib"
    bonsai_sibling.mkdir(parents=True)
    _write(bonsai_sibling / "record.json", {
        "task": "D2", "model": "bonsai-2-9b", "repetition": 1,
        "correct": False, "failure": "call_limit", "model_calls": 61})

    runs = [
        {"run_dir": str(qwen_run),
         "references": [{"output": "practical-selection-v2-r1", "model": "qwen3.5-4b",
                         "task": "C1", "repetition": 1, "failure": "wrong_result"}],
         "evidence": _evidence_for(qwen_run), "regradable": False},
        {"run_dir": str(qwen_sibling),
         "references": [{"output": "practical-selection-v2-r3", "model": "qwen3.5-4b",
                         "task": "C1", "repetition": 1, "failure": "call_limit",
                         "model_calls": 21}],
         "evidence": _evidence_for(qwen_sibling), "regradable": True},
        {"run_dir": str(bonsai_run),
         "references": [{"output": "practical-selection-7bplus-repair-r2",
                         "model": "bonsai-2-9b", "task": "D2", "repetition": 1,
                         "failure": "configuration"}],
         "evidence": _evidence_for(bonsai_run), "regradable": True},
        {"run_dir": str(bonsai_sibling),
         "references": [{"output": "practical-selection-7bplus-v1", "model": "bonsai-2-9b",
                         "task": "D2", "repetition": 1, "failure": "call_limit",
                         "model_calls": 61}],
         "evidence": _evidence_for(bonsai_sibling), "regradable": True},
    ]
    collection = tmp_path / "collection"

    report = sweep.transport_qualifications(
        census_path=_transport_census(tmp_path, runs), collection_dir=collection)

    assert report["counts"] == {"episodes": 2}
    assert report["inference_started"] is False
    cases = {episode["case_id"]: episode for episode in report["episodes"]}
    qwen = cases["qwen-4b-c1-r1-sigterm"]
    assert qwen["evidence_verified"] is True and qwen["evidence_drift"] is None
    assert qwen["record_failure"] == "wrong_result"
    assert qwen["candidate_returncode"] == -15
    assert qwen["recorded_signal_name"] == "SIGTERM"
    assert qwen["native_capture_bytes"] == 0
    assert qwen["broker_chat_posts"] == 3           # the health probe is not a chat post
    assert qwen["broker_chat_posts_status_200"] == 3
    assert qwen["broker_window_utc"] == ["2026-10-18T22:39:35.004330+00:00",
                                         "2026-10-18T22:40:21+00:00"]
    assert qwen["snapshots_present"] == []
    assert "SIGTERM" in qwen["qualification"]
    assert qwen["sibling_executions"] == [{
        "output": "practical-selection-v2-r3", "run_dir": str(qwen_sibling),
        "record_failure": "call_limit", "model_calls": 21,
        "evidence_files": ["record.json"]}]
    bonsai = cases["bonsai-9b-d2-r1-transport"]
    assert bonsai["evidence_verified"] is True
    assert bonsai["record_failure"] == "configuration"   # the label is preserved
    assert len(bonsai["api_error_events"]) == 1
    assert bonsai["api_error_events"][0]["name"] == "APIError"
    assert bonsai["api_error_events"][0]["retryable"] is True
    assert bonsai["native_mcp_tool_events"] == 0
    assert "src/ledger.js" in bonsai["snapshot_stub_markers"]
    assert bonsai["authored_test_count"] == 1
    assert bonsai["qualification"].startswith("transport_severed_mislabeled_configuration")
    assert "success" not in bonsai["qualification"]
    written = json.loads(
        (collection / "transport-qualifications.json").read_text(encoding="utf-8"))
    assert written["schema"] == sweep.TRANSPORT_SCHEMA
    envelope = json.loads((collection / "collection.json").read_text(encoding="utf-8"))
    assert envelope["transport_qualifications"] == {"episodes": 2}


def test_sweep_reasks_review_when_the_census_entry_has_no_evidence_map(tmp_path, monkeypatch):
    run_dir, _ = _fake_episode_record(tmp_path, tmp_path / "out-1")
    census_path = _census(tmp_path, [run_dir])
    # A regradable entry whose evidence map went missing must not be graded.
    inventory = json.loads(census_path.read_text(encoding="utf-8"))
    inventory["runs"][0].pop("evidence")
    _write(census_path, inventory)
    calls = _fake_regrade(monkeypatch)

    summary = sweep.run_sweep(census_path=census_path, collection_dir=tmp_path / "collection")

    assert summary["counters"] == {"review": 1}
    assert calls == []
    assert summary["review_required"][0]["problem"] == (
        "census entry lists no evidence hashes")


def test_transport_qualification_is_withheld_when_evidence_drifts(tmp_path):
    bonsai_run = tmp_path / "repair-r2" / "runs" / "bonsai-ep"
    bonsai_run.mkdir(parents=True)
    (bonsai_run / "native.jsonl").write_text(json.dumps({
        "type": "error", "error": {"name": "APIError", "data": {
            "message": "Cannot connect to API: socket closed", "isRetryable": True}}},
        ensure_ascii=False) + "\n", encoding="utf-8")
    _write(bonsai_run / "record.json", {
        "task": "D2", "model": "bonsai-2-9b", "repetition": 1,
        "correct": False, "failure": "configuration"})
    with zipfile.ZipFile(bonsai_run / ".snapshot1.zip", "w") as archive:
        archive.writestr("src/ledger.js", "throw new Error('not implemented');")
    runs = [{"run_dir": str(bonsai_run),
             "references": [{"output": "practical-selection-7bplus-repair-r2",
                             "model": "bonsai-2-9b", "task": "D2", "repetition": 1,
                             "failure": "configuration"}],
             "evidence": _evidence_for(bonsai_run), "regradable": True}]
    # Drift after the audit: the snapshot's bytes move.
    (bonsai_run / ".snapshot1.zip").write_bytes(b"tampered-after-audit")

    report = sweep.transport_qualifications(
        census_path=_transport_census(tmp_path, runs), collection_dir=tmp_path / "collection")

    episode = next(term for term in report["episodes"]
                   if term["case_id"] == "bonsai-9b-d2-r1-transport")
    assert episode["evidence_verified"] is False
    assert episode["evidence_drift"] == ".snapshot1.zip"
    assert "qualification" not in episode          # no verdict is rendered on drift
    assert episode["record_failure"] == "configuration"   # census identity only
