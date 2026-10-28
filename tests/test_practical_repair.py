"""The repair campaign must only replay affected tasks after the source ends."""
import json

import pytest

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_repair as repair


def source_manifest(status="complete"):
    models = {name: {"alias": name, "path": name + ".gguf", "sha256": "a" * 64,
                     "revision": "fixture"} for name in ("a", "b", "c", "d", "e")}
    schedule = campaign.baseline_schedule(tuple(models), protocol="historical")
    for profile in ("cache_on", "context_32k"):
        config = {"id": profile, "context_tokens": 32768 if profile == "context_32k" else 16384,
                  "cache_prompt": True}
        schedule += campaign.tuning_schedule(("a", "b"), config, stage=profile,
                                             protocol="historical")
    schedule += campaign.holdout_schedule(("a", "b"), {"a": campaign.BASELINE_PROFILE,
                                                       "b": campaign.BASELINE_PROFILE},
                                           protocol="historical")
    stages = {}
    for row in schedule:
        stages.setdefault(row["stage"], []).append({"identity": list(campaign.episode_key(row)),
                                                  "profile_config": row["profile_config"]})
    return {"status": status, "protocol_id": "historical", "immutable_sha256": "fixture",
            "immutable": {"models": models}, "stage_schedules": stages}, schedule


def test_repair_selects_only_changed_tasks_and_preserves_profile_and_seed():
    manifest, source = source_manifest()
    planned = repair.repair_schedule(manifest)
    assert len(planned) == 93
    assert {x["task"] for x in planned} == {"B2", "C2", "M1", "M2", "D2", "H2"}
    assert not {"B1", "C1", "D1", "H1"} & {x["task"] for x in planned}
    expected = {(x["model"], x["profile"], x["task"], x["repetition"]): x for x in source}
    for row in planned:
        old = expected[(row["model"], row["profile"], row["task"], row["repetition"])]
        assert row["profile_config"] == old["profile_config"]
        assert row["generation_seed"] == old["generation_seed"]
        assert row["protocol"] == repair.PROTOCOL


@pytest.mark.parametrize("state", ["planned", "running", "blocked", "interrupted"])
def test_inference_gate_requires_complete_source_campaign(tmp_path, state):
    manifest, _ = source_manifest(state)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="complete"):
        repair.load_completed_source(tmp_path)


def test_completion_gate_checks_records_not_just_status(tmp_path):
    manifest, rows = source_manifest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "records.json").write_text(json.dumps([{**x, "status": "complete"} for x in rows[:-1]]))
    with pytest.raises(ValueError, match="coverage"):
        repair.load_completed_source(tmp_path)


def test_complete_source_is_read_only_and_returns_pinned_models(tmp_path):
    manifest, rows = source_manifest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    records = [{**x, "status": "complete"} for x in rows]
    (tmp_path / "records.json").write_text(json.dumps(records))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    loaded, observed = repair.load_completed_source(tmp_path)
    assert loaded == manifest and observed == records
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_duplicate_schedule_identity_rejected():
    manifest, _ = source_manifest()
    manifest["stage_schedules"]["baseline"].append(manifest["stage_schedules"]["baseline"][1])
    with pytest.raises(ValueError, match="duplicate"):
        repair.repair_schedule(manifest)


def test_different_source_generation_seed_cannot_be_silently_replaced():
    manifest, _ = source_manifest()
    manifest["immutable"]["repetition_seeds"] = {"1": 999, "2": 202, "3": 303}
    with pytest.raises(ValueError, match="seed"):
        repair.repair_schedule(manifest)


def test_composite_does_not_relabel_or_reuse_affected_old_results():
    manifest, source = source_manifest()
    originals = [{**x, "status": "complete", "correct": True} for x in source]
    changed = repair.repair_schedule(manifest)[0]
    fresh = [{**changed, "status": "complete", "correct": False}]
    combined = repair.composite_records(originals, fresh)
    assert len(combined) == len(originals) - 93 + 1
    assert all(x["protocol"] == "historical" for x in combined if x["inherited"])
    assert not any(x["inherited"] and x["task"] in repair.AFFECTED_TASKS for x in combined)
    assert next(x for x in combined if not x["inherited"])["correct"] is False
    assert "inherited" not in originals[0]


def test_only_capacity_failures_are_automatically_retryable():
    capacity = {"status": "infrastructure", "error": "GPU capacity gate failed: 6900 < 7000"}
    manifest = {"probe_failures": {"a|baseline": capacity}}
    assert repair.capacity_block(manifest, [])
    assert repair.capacity_block({"probe_failures": {"a|baseline": {
        "status": "infrastructure", "reason": capacity["error"]}}}, [])
    assert not repair.capacity_block({"probe_failures": {"a|baseline": {
        "status": "infrastructure", "error": "MCP response invalid"}}}, [])
    assert not repair.capacity_block({"profile_blocks": {"a|baseline": {}}}, [])


def test_selective_campaign_resume_never_repeats_completed_episodes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    manifest, original = source_manifest()
    manifest['finalists'] = ['a', 'b']
    (source / "manifest.json").write_text(json.dumps(manifest))
    (source / "records.json").write_text(json.dumps([{**x, "status": "complete"} for x in original]))
    calls = []

    class FixtureRuntime:
        def __init__(self, models, source):
            self.models = models

        def configure_gpu_free_floor_mib(self, floor):
            assert floor == 7000

        def validate_environment(self):
            return {"passed": True, "runtime_versions": {"fixture": "1"}}

        def probe_profile(self, *args, **kwargs):
            return {"passed": True}

        def run_episode(self, model, task, profile, repetition, output, models, *, lab):
            calls.append((model, task, profile["id"], repetition))
            return {"correct": model in {'d', 'e'}, "autonomous": True,
                    "failure": 'passed' if model in {'d', 'e'} else 'wrong_result', "seconds": 1,
                    "model_contract": models[model], "tool_errors": 0, "model_calls": 1}

    monkeypatch.setattr(repair, "RepairRuntime", FixtureRuntime)
    monkeypatch.setattr(repair, 'daily_contract', lambda lab: {
        'opencode': '1.19.3', 'llama_revision': 'a' * 40})
    monkeypatch.setattr(repair.runtime, '_ACTIVE_RUNTIME_CONTRACT', None)
    monkeypatch.setattr(repair.runtime, 'LAB', tmp_path / 'lab')
    monkeypatch.setattr(campaign, "PROTOCOL", repair.PROTOCOL)
    monkeypatch.setattr(repair.runtime, "PROTOCOL", repair.PROTOCOL)
    target = tmp_path / "repair"
    assert repair.run(source, target)["status"] == "complete"
    assert len(calls) == 93
    assert len(set(calls)) == 93
    assert json.loads((target / 'manifest.json').read_text())['finalists'] == ['d', 'e']
    assert repair.run(source, target)["status"] == "complete"
    assert len(calls) == 93
    assert json.loads((source / "manifest.json").read_text()) == manifest
    corrected = json.loads((target / "records.json").read_text())
    assert all(row["task"] in repair.AFFECTED_TASKS for row in corrected)
