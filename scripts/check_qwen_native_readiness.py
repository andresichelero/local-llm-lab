"""Offline mocked-wire/native-sandbox readiness gate; never loads an LLM."""

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
from benchmark.qwen_harness_adapters import HARNESS_IDS, READY_HARNESSES  # noqa: E402
from scripts.qwen_native_smoke import smoke_adapter  # noqa: E402

REPORT = ROOT / "results/reports/qwen-optimization-20261025"
INSTALL = ROOT / "results/reports/qwen-harness-refresh-20261025/installation.json"
NATIVE_FILES = (
    "qwen_native_smoke.py",
    "check_qwen_native_readiness.py",
    "qwen_native_runner.py",
    "qwen_native_gateway.py",
    "qwen_native_protocols.py",
    "qwen_native_driver.py",
    "qwen_native_mcp.py",
    "qwen_native_runtime.py",
    "qwen_harness_adapters.py",
    "qwen_engines.py",
    "qwen_optimization.py",
    "qwen_workloads.py",
    "linux_sandbox.py",
    "sandbox_bootstrap.py",
    "model_broker.py",
    "practical_mcp_bridge.py",
    "practical_mcp_grading_v2.py",
    "practical_runtime_v2.py",
    "practical_tasks_v2.py",
    "practical_grade_contract.py",
    "practical_python_checks.py",
    "practical_node_rpc.mjs",
    "practical_worker_guard.py",
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_path(name):
    root = (
        ROOT / "scripts"
        if name in {"qwen_native_smoke.py", "check_qwen_native_readiness.py"}
        else ROOT / "benchmark"
    )
    return root / name


def expected_block_reason(harness, evidence):
    diagnostics = evidence.get("diagnostics") or {}
    bind_error = diagnostics.get("bind_validation_error")
    candidate_output = str(diagnostics.get("candidate_output_tail") or "")
    if harness in {"deepseek-harness", "hermes"} and bind_error == (
        "runtime bind directory exceeds the metadata scan limit"
    ):
        return "Installed harness runtime exceeds the sandbox's bounded 50,000-entry bind audit."
    if (
        harness == "openhands"
        and diagnostics.get("returncode") == 0
        and evidence.get("model_calls") == 0
        and "out of pty devices" in candidate_output
    ):
        return "OpenHands needs pseudo-terminals that the current isolated sandbox does not provide."
    return None


def main():
    report = {
        "passed": False,
        "inference": False,
        "graders": False,
        "checks": [],
        "adapter_status": {},
    }
    state = json.loads(INSTALL.read_text())
    from benchmark.qwen_harness_adapters import _installed_item, prepare_adapter

    for harness in sorted(READY_HARNESSES):
        item = _installed_item(state, harness)
        if not item:
            report["adapter_status"][harness] = "blocked_installation"
            continue
        result = prepare_adapter(
            harness,
            state,
            model_alias="local-qwen",
            endpoint_port=18887,
            prompt="Static mocked-provider check; do not infer.",
            workspace="/workspace",
        )
        report["adapter_status"][harness] = result["status"]
        if result["status"] == "ready":
            if not result["argv"] or "https://" in json.dumps(result).lower():
                raise RuntimeError(
                    harness + " adapter has no command or includes a remote route"
                )
    if not {
        "pi",
        "opencode",
        "codex",
        "claude-code",
        "hermes",
        "mistral-vibe",
        "deepseek-harness",
        "qwen-code",
        "aider",
        "openhands",
    } <= {k for k, v in report["adapter_status"].items() if v == "ready"}:
        raise RuntimeError(
            "one or more supported local harness adapters did not qualify"
        )
    report["wire_smoke"] = {}
    smoke_failures = []
    blocked_harnesses = {}
    for harness, status in report["adapter_status"].items():
        if status != "ready":
            report["wire_smoke"][harness] = {"status": status, "model_inference": False}
            continue
        evidence = smoke_adapter(harness, state)
        block_reason = expected_block_reason(harness, evidence)
        if block_reason:
            evidence["observed_status"] = evidence.get("status")
            evidence["status"] = "blocked"
            evidence["block_reason"] = block_reason
            blocked_harnesses[harness] = block_reason
        report["wire_smoke"][harness] = evidence
        print("native provider smoke", harness, evidence.get("status"), flush=True)
        if evidence.get("status") != "pass":
            if evidence.get("status") != "blocked":
                smoke_failures.append(
                    {"harness": harness, "error": evidence.get("error")}
                )
    for harness in HARNESS_IDS:
        if harness not in READY_HARNESSES:
            reason = (
                "TrueForge is an API session server; its bounded local session adapter is not qualified."
            )
            report["adapter_status"][harness] = "blocked"
            report["wire_smoke"][harness] = {
                "status": "blocked",
                "model_inference": False,
                "block_reason": reason,
            }
            blocked_harnesses[harness] = reason
    mcp_evidence = smoke_adapter("opencode", state, with_mcp=True)
    mcp_block = expected_block_reason("opencode-mcp", mcp_evidence)
    if mcp_block:
        mcp_evidence["observed_status"] = mcp_evidence.get("status")
        mcp_evidence["status"] = "blocked"
        mcp_evidence["block_reason"] = mcp_block
        blocked_harnesses["opencode-mcp"] = mcp_block
    report["wire_smoke"]["opencode-mcp"] = mcp_evidence
    print("native MCP provider smoke", mcp_evidence.get("status"), flush=True)
    if mcp_evidence.get("status") not in {"pass", "blocked"}:
        smoke_failures.append(
            {"harness": "opencode-mcp", "error": mcp_evidence.get("error")}
        )
    report["smoke_failures"] = smoke_failures
    report["blocked_harnesses"] = blocked_harnesses
    write_json(REPORT / "native-readiness.json", report)
    tests = sorted(
        str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_qwen_*.py")
    )
    tests += [
        "tests/test_practical_mcp_bridge.py",
        "tests/test_practical_grade_contract.py",
        "tests/test_practical_runtime_v2.py",
        "tests/test_practical_tasks_v2.py",
        "tests/test_linux_sandbox.py",
        "tests/test_model_broker.py",
        "tests/test_qwen_native_runner.py",
    ]
    code = [str(source_path(name)) for name in NATIVE_FILES if name.endswith(".py")]
    checks = [
        (
            "native-mocked-tests",
            [sys.executable, "-m", "pytest", *tests, "-q", "--tb=short"],
        ),
        ("native-lint", ["/home/foxtrot/.local/bin/ruff", "check", *code, *tests]),
        ("native-compile", [sys.executable, "-m", "compileall", "-q", *code]),
    ]
    for name, command in checks:
        started = time.monotonic()
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        log = REPORT / (name + ".log")
        log.write_text(result.stdout)
        report["checks"].append(
            {
                "name": name,
                "returncode": result.returncode,
                "seconds": time.monotonic() - started,
                "log": str(log),
            }
        )
        print(name, result.returncode, result.stdout[-1200:], flush=True)
    report["source_sha256"] = {
        str(source_path(name)): digest(source_path(name))
        for name in NATIVE_FILES
    }
    report["adapters_ready"] = sorted(
        k for k, v in report["adapter_status"].items() if v == "ready"
    )
    report["mcp_contract"] = (
        "OpenCode stdio MCP loopback bridge passed a fake-provider roundtrip; other unqualified native MCP configs stay feature-blocked"
        if mcp_evidence.get("status") == "pass"
        else "OpenCode stdio MCP loopback bridge did not qualify; MCP-dependent units remain blocked"
    )
    report["codex_wire"] = (
        "Responses API through bounded loopback translator; no fallback provider"
    )
    report["claude_wire"] = (
        "Messages API through bounded loopback translator; non-Claude upstream unsupported by Anthropic policy"
    )
    report["trueforge_wire"] = (
        "API session wrapper remains blocked; offline API/control server route is not installed in this runner"
    )
    report["passed"] = not smoke_failures and all(
        item["returncode"] == 0 for item in report["checks"]
    )
    report["status"] = (
        "passed_with_explicit_harness_blocks"
        if report["passed"] and blocked_harnesses
        else "passed"
        if report["passed"]
        else "blocked_by_unresolved_qualification_failure"
    )
    write_json(REPORT / "native-readiness.json", report)
    print(json.dumps({"passed": report["passed"], "report": str(REPORT / "native-readiness.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
