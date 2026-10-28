"""Run the offline foundation gate and save exact commands/hashes; no inference."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.qwen_optimization import write_json  # noqa: E402
from benchmark.qwen_quant_runner import REPORT, SOURCES  # noqa: E402


def main():
    tests = sorted(
        str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_qwen_*.py")
    )
    tests += [
        "tests/test_harness_refresh.py",
        "tests/test_post_validation_repairs.py",
        "tests/test_practical_mcp_bridge.py",
        "tests/test_practical_grade_contract.py",
    ]
    code = sorted(
        str(p.relative_to(ROOT)) for p in (ROOT / "benchmark").glob("qwen_*.py")
    )
    code += [
        "scripts/check_qwen_readiness.py",
        "scripts/prepare_qwen_engines.py",
        "scripts/inspect_qwen_artifact.py",
    ]
    report = {"passed": False, "inference": False, "checks": [], "source_sha256": {}}
    for name, command in [
        ("tests", [sys.executable, "-m", "pytest", *tests, "-q", "--tb=short"]),
        ("lint", ["/home/foxtrot/.local/bin/ruff", "check", *code, *tests]),
        ("compile", [sys.executable, "-m", "compileall", "-q", *code]),
    ]:
        started = time.monotonic()
        run = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
        log = REPORT / ("foundation-" + name + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(run.stdout)
        report["checks"].append(
            {
                "name": name,
                "command": command,
                "returncode": run.returncode,
                "seconds": time.monotonic() - started,
                "log": str(log),
            }
        )
        print(name, run.returncode, run.stdout[-500:], flush=True)
        if run.returncode:
            write_json(REPORT / "foundation.json", report)
            return 1
    for name in SOURCES:
        path = ROOT / "benchmark" / name
        report["source_sha256"][str(path)] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    report["passed"] = True
    write_json(REPORT / "foundation.json", report)
    print(json.dumps({"passed": True, "report": str(REPORT / "foundation.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
