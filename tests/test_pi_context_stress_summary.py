import json
from pathlib import Path

from benchmark.summarize_pi_context_stress import load_records, quality_pass, read_archive_ids


def test_reads_archive_paths_from_pi_tool_calls(tmp_path: Path):
    session = tmp_path / "session.jsonl"
    entries = [
        {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "name": "read", "arguments": {"path": "archive-07.md"}},
            {"type": "toolCall", "name": "read", "arguments": {"path": "archive-32.md"}},
        ]}},
    ]
    session.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    assert read_archive_ids({"session_stats": {"sessionFile": str(session)}}) == [7, 32]


def test_quality_gate_rejects_unverified_summary_only_pass():
    apparent_pass = {
        "source_tree_dirty": False,
        "summary_exists": True,
        "key_preserved_in_summary": True,
        "recovery_exact_match": True,
        "test_exit_code": 0,
        "compaction_event_count": 2,
    }
    assert not quality_pass(apparent_pass, list(range(1, 8)))
    assert not quality_pass({**apparent_pass, "manifest_exact": False}, list(range(1, 33)))
    assert quality_pass({**apparent_pass, "manifest_exact": True}, list(range(1, 33)))


def test_loader_summarizes_actual_reads_and_completeness(tmp_path: Path):
    session = tmp_path / "session.jsonl"
    calls = [
        {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "name": "read", "arguments": {"path": f"archive-{n:02d}.md"}}
            for n in range(1, 33)
        ]}},
    ]
    session.write_text("\n".join(json.dumps(entry) for entry in calls), encoding="utf-8")
    raw = tmp_path / "raw.jsonl"
    raw.write_text(json.dumps({
        "timestamp": "2026-10-11T00:00:00Z",
        "session_stats": {"sessionFile": str(session)},
        "source_tree_dirty": False,
        "summary_exists": True,
        "manifest_exact": True,
        "key_preserved_in_summary": True,
        "recovery_exact_match": True,
        "test_exit_code": 0,
        "compaction_event_count": 1,
    }) + "\n", encoding="utf-8")
    record = load_records([raw])[0]
    assert record["archive_files_read_count"] == 32
    assert record["quality_pass"] is True
