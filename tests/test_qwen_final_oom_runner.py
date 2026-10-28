from pathlib import Path
from benchmark import qwen_quant_runner


def test_oom_runner_selects_its_own_frozen_inputs(monkeypatch):
    from benchmark import qwen_final_oom_runner as wrapper

    original = (qwen_quant_runner.REPORT, qwen_quant_runner.CONFIG, qwen_quant_runner.DEFAULT_OUTPUT, qwen_quant_runner.SOURCES)
    observed = {}

    def fake_main():
        observed.update(report=qwen_quant_runner.REPORT, config=qwen_quant_runner.CONFIG, output=qwen_quant_runner.DEFAULT_OUTPUT, sources=qwen_quant_runner.SOURCES)
        return 0

    monkeypatch.setattr(qwen_quant_runner, "main", fake_main)
    assert wrapper.main() == 0
    assert observed["report"] == wrapper.ROOT / "results/reports/qwen-optimization-final-oom-v2"
    assert observed["config"] == wrapper.ROOT / "benchmark/configs/qwen-optimization-final-oom-v2.json"
    assert observed["output"] == Path("/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final-oom-v2")
    assert "qwen_final_oom_runner.py" in observed["sources"]
    assert (qwen_quant_runner.REPORT, qwen_quant_runner.CONFIG, qwen_quant_runner.DEFAULT_OUTPUT, qwen_quant_runner.SOURCES) == original
