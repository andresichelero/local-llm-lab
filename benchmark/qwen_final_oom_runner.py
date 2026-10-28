"""Run the final Qwen campaign under the explicit OOM-only GPU policy."""
from pathlib import Path
from benchmark import qwen_quant_runner as runner

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "results/reports/qwen-optimization-final-oom-v2"
CONFIG = ROOT / "benchmark/configs/qwen-optimization-final-oom-v2.json"
DEFAULT_OUTPUT = Path("/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final-oom-v2")


def main():
    original = (runner.REPORT, runner.CONFIG, runner.DEFAULT_OUTPUT, runner.SOURCES)
    try:
        runner.REPORT = REPORT
        runner.CONFIG = CONFIG
        runner.DEFAULT_OUTPUT = DEFAULT_OUTPUT
        runner.SOURCES = tuple(runner.SOURCES) + ("qwen_final_oom_runner.py",)
        return runner.main()
    finally:
        runner.REPORT, runner.CONFIG, runner.DEFAULT_OUTPUT, runner.SOURCES = original


if __name__ == "__main__":
    raise SystemExit(main())
