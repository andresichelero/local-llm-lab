"""Campaign-specific entry point for the final Qwen quantization run."""

from __future__ import annotations

from pathlib import Path

from benchmark import qwen_quant_runner as runner


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "results/reports/qwen-optimization-final"
CONFIG = ROOT / "benchmark/configs/qwen-optimization-final.json"
DEFAULT_OUTPUT = Path(
    "/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final"
)


def main():
    """Run the shared campaign runner with this campaign's frozen inputs."""
    original = (runner.REPORT, runner.CONFIG, runner.DEFAULT_OUTPUT, runner.SOURCES)
    try:
        runner.REPORT = REPORT
        runner.CONFIG = CONFIG
        runner.DEFAULT_OUTPUT = DEFAULT_OUTPUT
        runner.SOURCES = tuple(runner.SOURCES) + ("qwen_final_runner.py",)
        return runner.main()
    finally:
        runner.REPORT, runner.CONFIG, runner.DEFAULT_OUTPUT, runner.SOURCES = original


if __name__ == "__main__":
    raise SystemExit(main())
