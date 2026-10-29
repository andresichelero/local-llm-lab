import json

from benchmark import qwen_f1_diagnostic as runner
from benchmark.qwen_engines import ModelBudgetExceeded
from benchmark.qwen_f1_diagnostic import CONFIG, schedule


def test_schedule_contains_each_cell_and_alternates_arm_order():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    units = schedule(config)
    assert len(units) == 24
    assert len({(u["task"], u["seed"], u["arm"]) for u in units}) == 24
    assert [u["arm"] for u in units[:4]] == ["D1", "D2", "D2", "D1"]


def test_attempt_persists_budget_failure_and_counts(tmp_path, monkeypatch):
    class FakeTelemetry:
        def __init__(self, output):
            self.rows = [{"device_free_mib": 3000}, {"device_free_mib": 2000}]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeServer:
        port = 1234
        alias = "local-qwen"

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *args, **kwargs):
            pass

    def fail(client, task, output):
        (output / "episode-progress.json").write_text('{"calls": 3, "tools": 4, "seconds": 5}')
        raise ModelBudgetExceeded("compaction budget exhausted")

    monkeypatch.setattr(runner, "check_preflight", lambda config: None)
    monkeypatch.setattr(runner, "Telemetry", FakeTelemetry)
    monkeypatch.setattr(runner, "ModelServer", FakeServer)
    monkeypatch.setattr(runner, "ApiClient", FakeClient)
    monkeypatch.setattr(runner, "run_development", fail)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    result = runner.run_attempt(config, {"task": "python_fix", "seed": 101, "arm": "D2"}, tmp_path / "attempt")
    assert result["failure"] == "budget_exhausted"
    assert result["model_calls"] == 3 and result["tool_calls"] == 4
    assert result["peak_device_vram_mib"] == 6192
    assert json.loads((tmp_path / "attempt/attempt-result.json").read_text()) == result
