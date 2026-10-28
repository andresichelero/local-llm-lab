import json

import pytest
from benchmark.qwen_optimization import fingerprint


def test_recovery_requeues_only_artificial_reserve_blocks(tmp_path):
    from scripts.qwen_final_oom_recover import prepare_recovery

    source = tmp_path / "source"
    source.mkdir()
    (source / "supervisor.lock").touch()
    immutable = {"protocol_id": "final"}
    (source / "manifest.json").write_text(json.dumps({"immutable": immutable, "input_digest": fingerprint(immutable)}))
    units = [{"unit_id": str(i), "artifact_id": f"a{i}"} for i in range(5)]
    def item(idx, status, result=None):
        return {"unit_id": str(idx), "unit": units[idx], "number": 1, "status": status, "result": result or {}}
    block = {"status": "blocked", "failure": "fixed_profile_capacity_unavailable", "error": "model loaded but leaves less than 512 MiB GPU reserve"}
    model = {"status": "model_failure"}
    oom = {"status": "blocked", "failure": "fixed_profile_capacity_unavailable", "error": "engine reports allocation failure; preserve server.log"}
    attempts = [item(0, "finished", block), item(1, "finished", model), item(2, "running"), item(3, "finished", oom), item(4, "finished", block), item(4, "finished", model)]
    original = json.dumps({"units": units, "attempts": attempts, "status": "running"})
    (source / "state.json").write_text(original)
    dest = tmp_path / "dest"
    summary = prepare_recovery(source, dest, "final-oom-v2")
    state = json.loads((dest / "state.json").read_text())
    assert summary["requeued_unit_ids"] == ["0"]
    assert not any(a["unit_id"] == "0" for a in state["attempts"])
    assert next(a for a in state["attempts"] if a["unit_id"] == "1")["result"] == model
    assert next(a for a in state["attempts"] if a["unit_id"] == "2")["status"] == "interrupted"
    assert next(a for a in state["attempts"] if a["unit_id"] == "3")["result"] == oom
    assert len([a for a in state["attempts"] if a["unit_id"] == "4"]) == 2
    assert json.loads((dest / "reserve-requeued-history.json").read_text())[0]["result"] == block
    assert (source / "state.json").read_text() == original
    with pytest.raises(FileExistsError):
        prepare_recovery(source, dest, "final-oom-v2")
