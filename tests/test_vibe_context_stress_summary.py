import hashlib
import json
import subprocess
from pathlib import Path

from benchmark.summarize_vibe_context_stress import summarize_run


def test_grades_a_compacted_two_phase_continuation(tmp_path: Path):
    run = tmp_path / "20261011T000000Z"
    workspace = run / "workspace"
    workspace.mkdir(parents=True)
    for folder in ("output-phase-1", "output-phase-2"):
        (run / folder / "session/journal").mkdir(parents=True)
    (workspace / "test_result.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n", encoding="utf-8")
    (workspace / "README.md").write_text("synthetic fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "baseline",
    ], cwd=workspace, check=True)
    (workspace / "summary.md").write_text("archive_count: 32\nrecovery_key: GLACIER-47-MAPLE\n", encoding="utf-8")
    (workspace / "recovery.txt").write_text("GLACIER-47-MAPLE\n", encoding="utf-8")
    manifest = [
        f"archive-{i:02d}=" + hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper()
        for i in range(1, 33)
    ]
    (workspace / "archive_manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    export = {
        "outcome": "finished", "exit_code": 0, "steps": 2, "vibe_version": "2.26.1",
        "session_id": "session-1", "started_at": "2026-10-11T00:00:00Z", "ended_at": "2026-10-11T00:00:03Z",
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    }
    for folder in ("output-phase-1", "output-phase-2"):
        (run / folder / "export.json").write_text(json.dumps(export), encoding="utf-8")
    events = [{
        "type": "action_intent", "record_sha256": "compact-event",
        "payload": {"kind": "completion", "request": {"purpose": "compaction", "compaction_id": "compact-1"}},
    }]
    for i in range(1, 33):
        events.append({
            "type": "action_intent", "record_sha256": f"tool-{i}",
            "payload": {"kind": "tool", "action_id": f"action-{i}", "request": {
                "call": {"name": "file_system.read_file", "arguments": {"path": f"archive-{i:02d}.md"}},
            }},
        })
        events.append({
            "type": "action_result", "record_sha256": f"result-{i}",
            "payload": {"action_id": f"action-{i}", "result": {"type": "tool_succeeded"}},
        })
    journal = run / "output-phase-1/session/journal/0000000000000001.jsonl"
    journal.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    (run / "resources.jsonl").write_text(json.dumps({"cpu_util_pct": 20, "ram_used_mb": 1000, "gpu": {"vram_used_mb": "6000"}}) + "\n", encoding="utf-8")

    record = summarize_run(run, "abc123")
    assert record["quality_pass"] is True
    assert record["compaction_count"] == 1
    assert record["tool_calls"] == 32
    assert record["archive_files_read_count"] == 32
    assert record["phase2_archive_files_read_count"] == 0
    assert record["wall_s"] == 3.0
    assert record["vram_used_mb_peak"] == 6000.0

    events = [
        event for event in events
        if event.get("payload", {}).get("action_id") != "action-32"
    ]
    events.extend([
        {
            "type": "action_intent", "record_sha256": "failed-bulk-read-intent",
            "payload": {"kind": "tool", "action_id": "failed-bulk-read", "request": {
                "call": {"name": "run_typescript", "arguments": {
                    "command": "cat " + " ".join(f"archive-{i:02d}.md" for i in range(1, 33)),
                }},
            }},
        },
        {
            "type": "action_result", "record_sha256": "failed-bulk-read-result",
            "payload": {"action_id": "failed-bulk-read", "result": {"type": "tool_failed"}},
        },
    ])
    journal.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    failed_read = summarize_run(run, "abc123")
    assert failed_read["quality_pass"] is False
    assert failed_read["archive_files_read_count"] == 31

    continuation_journal = run / "output-phase-2/session/journal/0000000000000001.jsonl"
    continuation_journal.write_text(json.dumps({
        "type": "action_intent", "record_sha256": "reopened-archive",
        "payload": {"kind": "tool", "request": {"call": {
            "name": "file_system.read", "arguments": {"path": "archive-01.md"},
        }}},
    }) + "\n", encoding="utf-8")
    reopened = summarize_run(run, "abc123")
    assert reopened["quality_pass"] is False
    assert reopened["phase2_archive_files_read"] == [1]

    (workspace / "README.md").write_text("unexpected fixture edit\n", encoding="utf-8")
    rejected = summarize_run(run, "abc123")
    assert rejected["quality_pass"] is False
    assert "README.md" in rejected["content_changed_files"]
