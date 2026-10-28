import pytest
from benchmark import qwen_engines


def test_oom_policy_attempts_server_even_when_gpu_free_below_old_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(qwen_engines, "gpu_free_mib", lambda: 100)
    monkeypatch.setattr(qwen_engines, "ram_available_mib", lambda: 4096)
    with pytest.raises(qwen_engines.ResourceUnavailable, match="unsupported engine"):
        qwen_engines.ModelServer(
            tmp_path / "model", "not-supported", tmp_path / "out", 16384,
            gpu_free_floor_mib=0, gpu_reserve_mib=0,
        ).__enter__()


def test_default_policy_keeps_existing_gpu_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(qwen_engines, "gpu_free_mib", lambda: 100)
    monkeypatch.setattr(qwen_engines, "ram_available_mib", lambda: 4096)
    with pytest.raises(qwen_engines.ResourceUnavailable, match="capacity gate"):
        qwen_engines.ModelServer(
            tmp_path / "model", "not-supported", tmp_path / "out", 16384,
        ).__enter__()


def test_measure_keeps_model_result_when_zero_reserve_policy(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from benchmark import qwen_quant_runner as runner

    class FakeTelemetry:
        def __init__(self, _output):
            self.rows = [{"device_free_mib": 100}, {"device_free_mib": 90}]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeServer:
        def __init__(self, *args, **kwargs):
            assert kwargs["gpu_reserve_mib"] == 0
            assert kwargs["gpu_free_floor_mib"] == 0
            self.port = 1
            self.alias = "local"
            self.process = SimpleNamespace(poll=lambda: 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0
            self.metrics = []
            self.metadata_calls = 0
            self.counts = {"main": 0}

        def chat(self, *args, **kwargs):
            self.calls += 1
            return {}

    monkeypatch.setattr(runner, "eligible_artifact", lambda _a: None)
    monkeypatch.setattr(runner, "cached_artifact", lambda *_a: tmp_path / "model")
    monkeypatch.setattr(runner, "stage_hot", lambda p, _a: p)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda _p: SimpleNamespace(free=20 * 1024**3))
    monkeypatch.setattr(runner, "gpu_free_mib", lambda: 100)
    monkeypatch.setattr(runner, "Telemetry", FakeTelemetry)
    monkeypatch.setattr(runner, "ModelServer", FakeServer)
    monkeypatch.setattr(runner, "ApiClient", FakeClient)
    monkeypatch.setattr(runner, "run_qualification", lambda *_a: {"status": "complete", "passed": 11})
    result = runner.measure(
        {"stage": "qualification", "context": 16384, "seed": 101},
        {"engine": "test"}, {}, tmp_path / "episode", {},
        gpu_policy={"gpu_free_floor_mib": 0, "gpu_reserve_mib": 0},
    )
    assert result["status"] == "complete"
    assert result["peak_device_vram_mib"] == 8192 - 90
    assert result["telemetry_complete"] is True


def test_oom_classification_requires_reported_oom_and_precleanup_exit(tmp_path):
    import json
    from benchmark import qwen_quant_runner as runner

    server = tmp_path / "server"
    server.mkdir()
    (server / "server.log").write_text("CUDA out of memory")
    (server / "server-exit.json").write_text(json.dumps({"pre_cleanup_returncode": None}))
    assert runner.confirmed_server_oom(tmp_path) is False
    (server / "server-exit.json").write_text(json.dumps({"pre_cleanup_returncode": -9}))
    assert runner.confirmed_server_oom(tmp_path) is True
    (server / "server.log").write_text("socket closed")
    assert runner.confirmed_server_oom(tmp_path) is False


def test_server_exit_records_crash_before_cleanup(tmp_path):
    import json
    from types import SimpleNamespace

    server = qwen_engines.ModelServer(tmp_path / "model", "llama.cpp", tmp_path, 16384)
    server.process = SimpleNamespace(poll=lambda: -9)
    server.__exit__(None, None, None)
    evidence = json.loads((tmp_path / "server-exit.json").read_text())
    assert evidence["pre_cleanup_returncode"] == -9
    assert evidence["final_returncode"] == -9
