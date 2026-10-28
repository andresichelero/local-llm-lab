import hashlib
from pathlib import Path
import sys

from benchmark import qwen_quant_runner


def test_import_does_not_patch_shared_runner_and_exposes_campaign_paths():
    from benchmark import qwen_final_runner

    assert qwen_final_runner.REPORT == (
        qwen_final_runner.ROOT / "results/reports/qwen-optimization-final"
    )
    assert qwen_final_runner.CONFIG == (
        qwen_final_runner.ROOT / "benchmark/configs/qwen-optimization-final.json"
    )
    assert qwen_final_runner.DEFAULT_OUTPUT == Path(
        "/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final"
    )
    assert qwen_quant_runner.REPORT != qwen_final_runner.REPORT
    assert qwen_quant_runner.CONFIG != qwen_final_runner.CONFIG
    assert qwen_quant_runner.DEFAULT_OUTPUT != qwen_final_runner.DEFAULT_OUTPUT


def test_main_temporarily_configures_shared_runner_and_freezes_wrapper(
    monkeypatch,
):
    from benchmark import qwen_final_runner

    original = (
        qwen_quant_runner.REPORT,
        qwen_quant_runner.CONFIG,
        qwen_quant_runner.DEFAULT_OUTPUT,
        qwen_quant_runner.SOURCES,
    )
    observed = {}

    def fake_main():
        observed["report"] = qwen_quant_runner.REPORT
        observed["config"] = qwen_quant_runner.CONFIG
        observed["default_output"] = qwen_quant_runner.DEFAULT_OUTPUT
        observed["sources"] = qwen_quant_runner.SOURCES
        observed["argv"] = sys.argv[:]
        return 37

    monkeypatch.setattr(qwen_quant_runner, "main", fake_main)
    monkeypatch.setattr(
        sys,
        "argv",
        ["qwen_final_runner", "--output", str(qwen_final_runner.DEFAULT_OUTPUT)],
    )

    assert qwen_final_runner.main() == 37

    assert observed["report"] == qwen_final_runner.REPORT
    assert observed["config"] == qwen_final_runner.CONFIG
    assert observed["default_output"] == qwen_final_runner.DEFAULT_OUTPUT
    assert "qwen_final_runner.py" in observed["sources"]
    assert observed["argv"] == [
        "qwen_final_runner",
        "--output",
        str(qwen_final_runner.DEFAULT_OUTPUT),
    ]
    assert (
        qwen_quant_runner.REPORT,
        qwen_quant_runner.CONFIG,
        qwen_quant_runner.DEFAULT_OUTPUT,
        qwen_quant_runner.SOURCES,
    ) == original


def test_wrapper_is_present_in_source_fingerprint(tmp_path, monkeypatch):
    from benchmark import qwen_final_runner

    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    wrapper_source = benchmark_dir / "qwen_final_runner.py"
    wrapper_source.write_bytes(Path(qwen_final_runner.__file__).read_bytes())
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "inspect_qwen_artifact.py").write_text("# fixture\n")
    qualification = (
        tmp_path
        / "results/reports/qwen-harness-refresh-20261025/qualification.json"
    )
    qualification.parent.mkdir(parents=True)
    qualification.write_text("{}")
    report = tmp_path / "report"
    report.mkdir()
    for name in ("engines.json", "foundation.json", "cache-footprint.json"):
        (report / name).write_text("{}")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")
    lab = tmp_path / "lab"
    runtime = lab / "tools/llama-bin/llama-server"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"runtime")

    monkeypatch.setattr(qwen_quant_runner, "ROOT", tmp_path)
    monkeypatch.setattr(qwen_quant_runner, "LAB", lab)
    monkeypatch.setattr(qwen_quant_runner, "REPORT", report)
    monkeypatch.setattr(qwen_quant_runner, "SOURCES", ("qwen_final_runner.py",))
    monkeypatch.setattr(qwen_quant_runner, "CONFIG", config_path)

    frozen = qwen_quant_runner.frozen_inputs(catalog, {"protocol_id": "test"})

    assert frozen["source_files"][str(wrapper_source)] == hashlib.sha256(
        wrapper_source.read_bytes()
    ).hexdigest()
