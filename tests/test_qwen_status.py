import json
from types import SimpleNamespace

from benchmark.qwen_status import status


def test_pause_marker_is_reported_without_rewriting_recorded_queue_state(
    tmp_path, monkeypatch
):
    manifest = {
        "immutable": {"protocol_id": "qwen-quant-harness-optimization-v3"}
    }
    state = {"status": "running", "attempts": []}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "PAUSE").touch()
    monkeypatch.setattr(
        "benchmark.qwen_status.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="ActiveState=inactive\n"),
    )

    report = status(tmp_path)

    assert report["status"] == "paused"
    assert report["recorded_status"] == "running"
    assert report["pause_requested"] is True
    assert json.loads((tmp_path / "state.json").read_text())["status"] == "running"


def test_status_reports_prepared_schedule_size_before_first_attempt(tmp_path, monkeypatch):
    manifest = {
        "immutable": {"protocol_id": "qwen-quant-harness-optimization-v4"}
    }
    state = {
        "status": "prepared",
        "units": [
            {"unit_id": "a", "stage": "qualification"},
            {"unit_id": "b", "stage": "qualification"},
            {"unit_id": "c", "stage": "capacity"},
        ],
        "attempts": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        "benchmark.qwen_status.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="ActiveState=inactive\n"),
    )

    report = status(tmp_path)

    assert report["status"] == "prepared"
    assert report["scheduled_units"] == 3
    assert report["pending_units"] == 3
    assert report["scheduled_stages"] == {
        "qualification": {"scheduled": 2, "finished": 0, "pending": 2},
        "capacity": {"scheduled": 1, "finished": 0, "pending": 1},
    }

