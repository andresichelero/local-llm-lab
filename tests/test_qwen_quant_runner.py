import hashlib
import json
from pathlib import Path
import sys

import pytest

from benchmark import qwen_quant_runner as runner


def test_capacity_requires_actual_usage_and_correct_retrieval(tmp_path):
    class Client:
        calls = 0
        metadata_calls = 0
        metrics = [{"seconds": 1}]

        def tokenize(self, text):
            self.metadata_calls += 1
            return [0] * len(text.split())

        def chat(self, messages, max_tokens=None):
            self.calls += 1
            return {
                "choices": [
                    {"message": {"content": '["early-749a","middle-139b","late-827c"]'}}
                ],
                "usage": {"prompt_tokens": len(messages[0]["content"].split())},
            }

    result = runner.capacity_check(Client(), 16384, tmp_path)
    assert result["context_verified"]

    class MissingUsage(Client):
        def chat(self, *args, **kwargs):
            value = super().chat(*args, **kwargs)
            value["usage"] = None
            return value

    result = runner.capacity_check(MissingUsage(), 16384, tmp_path)
    assert not result["context_verified"]


def test_hot_cache_only_replaces_its_own_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LAB", tmp_path / "lab")
    cold = tmp_path / "cold.gguf"
    cold.write_bytes(b"first")
    artifact = {
        "artifact_id": "first",
        "engine": "llama.cpp",
        "files": [
            {
                "path": "model.gguf",
                "size": 5,
                "sha256": hashlib.sha256(b"first").hexdigest(),
            }
        ],
    }
    target = runner.stage_hot(cold, artifact)
    assert target.read_bytes() == b"first"
    assert cold.read_bytes() == b"first"
    cold.write_bytes(b"next")
    artifact = {
        "artifact_id": "next",
        "engine": "llama.cpp",
        "files": [
            {
                "path": "second.gguf",
                "size": 4,
                "sha256": hashlib.sha256(b"next").hexdigest(),
            }
        ],
    }
    target2 = runner.stage_hot(cold, artifact)
    assert target2.read_bytes() == b"next"
    assert not target.exists()


def test_hot_cache_does_not_adopt_foreign_data(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LAB", tmp_path / "lab")
    active = runner.LAB / "state/qwen-hot/active"
    active.mkdir(parents=True)
    (active / "foreign").write_text("preserve")
    with pytest.raises(runner.ArtifactError, match="pre-existing"):
        runner.stage_hot(
            Path("/tmp/unused"),
            {"artifact_id": "a", "engine": "llama.cpp", "files": []},
        )
    assert (active / "foreign").read_text() == "preserve"


def test_resource_retry_requires_observed_improvement():
    initial = {"gpu": 7000, "ram": 2500, "disk": 20 * 1024**3}
    assert not runner.resource_improved(dict(initial), initial)
    assert runner.resource_improved(dict(initial, gpu=7300), initial)


def test_hot_cache_rejects_symlink_root_before_any_write(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LAB", tmp_path / "lab")
    root = runner.LAB / "state/qwen-hot"
    root.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(runner.ArtifactError, match="symlink"):
        runner.stage_hot(
            tmp_path / "unused",
            {"artifact_id": "x", "files": [], "engine": "llama.cpp"},
        )
    assert not list(outside.iterdir())


def test_distinct_precisions_cannot_reach_measurement_as_shards():
    catalog = {
        "artifacts": [
            {
                "artifact_id": "bad",
                "engine": "llama.cpp",
                "files": [
                    {"path": "Qwen3.5-9B-Q4_K_M.gguf"},
                    {"path": "Qwen3.5-9B-Q4_K_S.gguf"},
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="distinct GGUF"):
        runner.validate_catalog(catalog)


def test_capacity_unsupported_finalizes_attempt_once(tmp_path, monkeypatch):
    report = tmp_path / "report"
    report.mkdir()
    (report / "engines.json").write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "protocol_id": "qwen-quant-harness-optimization-test",
        "initial_output_tokens": 16,
        "contexts": [16384],
    }))
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({
        "artifacts": [{
            "artifact_id": "candidate",
            "model_id": "4B",
            "engine": "llama.cpp",
            "repo_id": "fixture/candidate",
            "quantfmt": "Q2_K",
            "total_bytes": 1,
            "source_base": {"status": "verified"},
            "files": [{"path": "candidate.gguf", "size": 1, "sha256": "0" * 64}],
        }]
    }))
    output = tmp_path / "output"

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "LAB", tmp_path / "lab")
    (runner.LAB / "state").mkdir(parents=True)
    monkeypatch.setattr(runner, "REPORT", report)
    monkeypatch.setattr(runner, "CONFIG", config_path)
    monkeypatch.setattr(runner, "SOURCES", ())
    monkeypatch.setattr(
        runner,
        "frozen_inputs",
        lambda catalog, config, recovery_origin_path=None: {
            "protocol_id": config["protocol_id"],
            "config": config,
            "recovery_origin_path": str(recovery_origin_path) if recovery_origin_path else None,
        },
    )
    monkeypatch.setattr(runner, "prerequisites", lambda: None)
    monkeypatch.setattr(runner, "recover_owned_servers", lambda _output: None)
    monkeypatch.setattr(runner, "gpu_free_mib", lambda: 8192)
    monkeypatch.setattr(runner, "ram_available_mib", lambda: 8192)
    monkeypatch.setattr(
        runner,
        "resources_now",
        lambda: {"gpu": 8192, "ram": 8192, "disk": 100 * 1024**3},
    )

    def capacity_failure(*_args, **_kwargs):
        raise runner.CapacityUnsupported("model leaves less than reserve")

    monkeypatch.setattr(runner, "measure", capacity_failure)
    monkeypatch.setattr(
        sys,
        "argv",
        ["qwen_quant_runner", "--output", str(output), "--catalog", str(catalog_path), "--execute", "--once"],
    )

    assert runner.main() == 0
    state = json.loads((output / "state.json").read_text())
    assert len(state["attempts"]) == 1
    assert state["attempts"][0]["status"] == "finished"
    assert state["attempts"][0]["result"]["status"] == "blocked"
    assert state["attempts"][0]["result"]["failure"] == "fixed_profile_capacity_unavailable"


def test_summary_marks_recovery_protocol_cohorts_separately(tmp_path):
    from benchmark.qwen_quant_runner import summarize
    from benchmark.qwen_optimization import Campaign, make_units

    queue = Campaign(tmp_path / "output", {"protocol_id": "recovery-v1"})
    units = make_units([{"artifact_id": "a", "model_id": "4B", "engine": "llama.cpp"},
                        {"artifact_id": "b", "model_id": "4B", "engine": "llama.cpp"}],
                       "qualification")
    queue.add(units)
    queue.begin(units[0])
    queue.finish(units[0], {"status": "complete", "passed": 11, "total": 12,
                            "protocol_valid": True, "seconds": 10})
    queue.state["attempts"][0]["protocol_id"] = "qwen-quant-harness-optimization-v4"
    queue.begin(units[1])
    queue.finish(units[1], {"status": "complete", "passed": 11, "total": 12,
                            "protocol_valid": True, "seconds": 10})

    summary = summarize(queue, {"contexts": [16384]})

    assert summary["protocol_cohorts"] == {
        "qwen-quant-harness-optimization-v4": 1,
        "recovery-v1": 1,
    }
    assert summary["protocols_are_mixed"] is True
    assert "not a homogeneous benchmark" in summary["protocol_note"]
    assert summary["finalists"]["status"] == "mixed_protocols_requires_review"
