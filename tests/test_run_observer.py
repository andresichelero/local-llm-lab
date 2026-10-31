from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


def _observer_module():
    spec = importlib.util.find_spec("benchmark.run_observer")
    assert spec is not None, "the passive run observer module is not implemented"
    return importlib.import_module("benchmark.run_observer")


def _manifest(**overrides):
    manifest = {
        "schema_version": "1",
        "protocol_id": "observer-test-v1",
        "hash_allowlist": [],
        "snapshot_hash_allowlist": [],
    }
    manifest.update(overrides)
    return manifest


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_events_have_correlated_identity_and_exactly_one_terminal_record(tmp_path: Path) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    observer = observer_module.RunObserver(run_dir, _manifest())
    phase_id = observer.start_phase("initial_agent", agent_id="initial-agent", source="cascade")
    observer.end_phase(phase_id, "completed", agent_id="initial-agent", source="cascade")
    observer.finalize("pass", "complete", source="cascade")

    events = _jsonl(run_dir / "observer-events.jsonl")
    required = {
        "event_id", "run_id", "event_seq", "event_type", "phase_id", "agent_id",
        "parent_agent_id", "turn_id", "source", "timestamp_utc", "monotonic_ns",
    }
    assert all(required.issubset(event) for event in events)
    assert [event["event_seq"] for event in events] == list(range(1, len(events) + 1))
    assert len({event["run_id"] for event in events}) == 1
    assert all(isinstance(event["monotonic_ns"], int) for event in events)
    assert sum(event["event_type"] == "run_end" for event in events) == 1
    assert events[-1]["event_type"] == "run_end"
    with pytest.raises(RuntimeError):
        observer.finalize("pass", "complete", source="cascade")


def test_manifest_hashes_only_explicit_files_without_absolute_paths(tmp_path: Path) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    repo = tmp_path / "repo"
    run_dir.mkdir()
    source = repo / "benchmark/source.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"SOURCE_BYTES")
    (repo / ".env").write_text("DO_NOT_READ_OR_HASH", encoding="utf-8")

    observer_module.RunObserver(
        run_dir,
        _manifest(hash_allowlist=[{
            "category": "source",
            "path": "benchmark/source.py",
            "file": source,
        }]),
    )

    manifest_text = (run_dir / "observer-manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["hashes"] == [{
        "category": "source",
        "path": "benchmark/source.py",
        "size_bytes": len(b"SOURCE_BYTES"),
        "sha256": hashlib.sha256(b"SOURCE_BYTES").hexdigest(),
        "status": "measured",
        "reason": None,
    }]
    assert str(source) not in manifest_text
    assert str(repo / ".env") not in manifest_text
    assert "DO_NOT_READ_OR_HASH" not in manifest_text


def test_snapshot_records_metadata_and_allowlisted_hash_without_reading_other_contents(
    tmp_path: Path,
) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    run_dir.mkdir()
    (workspace / "src").mkdir(parents=True)
    (workspace / "secret-store").mkdir()
    (workspace / ".git").mkdir()
    fixture = workspace / "src/original.py"
    fixture.write_text("FIXTURE_HASHED_ONLY", encoding="utf-8")
    (workspace / "src/notes.txt").write_text("GENERAL_CONTENT_NOT_READ", encoding="utf-8")
    (workspace / ".env").write_text("ENV_SECRET_SENTINEL", encoding="utf-8")
    (workspace / "secret-store/access_token.txt").write_text("TOKEN_SECRET_SENTINEL", encoding="utf-8")
    (workspace / "src/private.pem").write_text("KEY_SECRET_SENTINEL", encoding="utf-8")
    (workspace / ".git/config").write_text("GIT_METADATA_NOT_SNAPSHOTTED", encoding="utf-8")
    outside.write_text("SYMLINK_TARGET_CONTENT", encoding="utf-8")
    (workspace / "src/external-link.py").symlink_to(outside)

    observer = observer_module.RunObserver(
        run_dir,
        _manifest(snapshot_hash_allowlist=["src/original.py"]),
    )
    result = observer.snapshot("before_initial_agent", workspace, agent_id="initial-agent", source="cascade")

    assert result["status"] == "complete"
    snapshot_text = (run_dir / "workspace-snapshots.jsonl").read_text(encoding="utf-8")
    snapshot = _jsonl(run_dir / "workspace-snapshots.jsonl")[0]
    for field in (
        "run_id", "event_id", "event_seq", "phase_id", "agent_id", "parent_agent_id",
        "turn_id", "source", "timestamp_utc", "monotonic_ns",
    ):
        assert field in snapshot
    assert str(snapshot["event_seq"]) == snapshot["event_id"].rsplit(":", 1)[-1]
    paths = {entry["path"]: entry for entry in snapshot["entries"]}
    assert paths["src/original.py"]["sha256"] == hashlib.sha256(
        b"FIXTURE_HASHED_ONLY"
    ).hexdigest()
    assert paths["src/external-link.py"]["kind"] == "symlink"
    for forbidden in (
        "GENERAL_CONTENT_NOT_READ", "ENV_SECRET_SENTINEL", "TOKEN_SECRET_SENTINEL",
        "KEY_SECRET_SENTINEL", "GIT_METADATA_NOT_SNAPSHOTTED", "SYMLINK_TARGET_CONTENT",
        str(outside), "secret-store", ".env", "private.pem", "access_token.txt",
    ):
        assert forbidden not in snapshot_text
    assert os.path.abspath(workspace) not in snapshot_text


def test_snapshot_marks_traversal_failure_incomplete_without_emitting_path_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    workspace = tmp_path / "workspace"
    blocked = workspace / "blocked-dir"
    run_dir.mkdir()
    blocked.mkdir(parents=True)
    (blocked / "item.txt").write_text("content", encoding="utf-8")
    observer = observer_module.RunObserver(run_dir, _manifest())
    real_scandir = observer_module.os.scandir

    def failing_scandir(path):
        if Path(path) == blocked:
            raise PermissionError("synthetic traversal failure")
        return real_scandir(path)

    monkeypatch.setattr(observer_module.os, "scandir", failing_scandir)
    result = observer.snapshot("after_initial_agent", workspace, agent_id="initial-agent", source="cascade")

    assert result["status"] == "incomplete"
    text = (run_dir / "workspace-snapshots.jsonl").read_text(encoding="utf-8")
    assert "blocked-dir" not in text
    assert "synthetic traversal failure" not in text


def test_observer_refuses_existing_owned_artifacts_without_overwriting_them(tmp_path: Path) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    owned = run_dir / "observer-events.jsonl"
    owned.write_text("preserve-this-artifact\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        observer_module.RunObserver(run_dir, _manifest())

    assert owned.read_text(encoding="utf-8") == "preserve-this-artifact\n"
    assert not (run_dir / "observer-manifest.json").exists()


def test_hash_allowlist_rejects_absolute_windows_paths(tmp_path: Path) -> None:
    observer_module = _observer_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source = tmp_path / "source.py"
    source.write_text("safe", encoding="utf-8")

    with pytest.raises(ValueError):
        observer_module.RunObserver(
            run_dir,
            _manifest(hash_allowlist=[{
                "category": "source",
                "path": r"C:\Users\someone\secret.py",
                "file": source,
            }]),
        )
