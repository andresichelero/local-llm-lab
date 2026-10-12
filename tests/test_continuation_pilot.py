"""Unit tests for OpenCode 32-file continuation pilot (Trilha B / Roadmap Tarefa 8)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from benchmark.continuation_pilot import (
    SECRET_KEY,
    generate_continuation_fixture,
    grade_continuation_workspace,
    summarize_continuation_results,
)


def test_generate_continuation_fixture(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    generate_continuation_fixture(workspace)

    # 32 archive files
    archives = list(workspace.glob("archive-*.md"))
    assert len(archives) == 32

    # Check canary in archive-07
    a7 = (workspace / "archive-07.md").read_text(encoding="utf-8")
    assert SECRET_KEY in a7

    # Check canary NOT in archive-01
    a1 = (workspace / "archive-01.md").read_text(encoding="utf-8")
    assert SECRET_KEY not in a1

    # Check test script exists
    assert (workspace / "test_result.py").is_file()


def test_grade_continuation_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    generate_continuation_fixture(workspace)

    # Incomplete workspace: should fail
    grade_empty = grade_continuation_workspace(workspace)
    assert not grade_empty["success"]
    assert grade_empty["manifest_count"] == 0
    assert not grade_empty["recovery_key_found"]

    # Generate expected valid outputs
    expected_lines = [
        f"archive-{i:02d}=" + hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper()
        for i in range(1, 33)
    ]
    (workspace / "archive_manifest.txt").write_text("\n".join(expected_lines) + "\n", encoding="utf-8")
    (workspace / "summary.md").write_text("# Summary\n\narchive_count: 32\nstatus: verified\n", encoding="utf-8")
    (workspace / "recovery.txt").write_text(f"{SECRET_KEY}\n", encoding="utf-8")

    grade_valid = grade_continuation_workspace(workspace)
    assert grade_valid["success"]
    assert grade_valid["manifest_count"] == 32
    assert grade_valid["recovery_key_found"]
    assert grade_valid["summary_valid"]


def test_summarize_continuation_results() -> None:
    records = [
        {
            "arm": "baseline",
            "pair": 1,
            "success": False,
            "manifest_count": 14,
            "recovery_key_found": True,
            "task_wall_seconds": 180.0,
            "peak_vram_mib": 4800,
        },
        {
            "arm": "checkpoint_manifest",
            "pair": 1,
            "success": True,
            "manifest_count": 32,
            "recovery_key_found": True,
            "task_wall_seconds": 95.0,
            "peak_vram_mib": 4820,
        },
    ]

    summary = summarize_continuation_results(records)
    assert "arms" in summary
    assert summary["arms"]["baseline"]["success_count"] == 0
    assert summary["arms"]["checkpoint_manifest"]["success_count"] == 1
    assert summary["arms"]["checkpoint_manifest"]["mean_manifest_count"] == 32.0
