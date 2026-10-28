"""Durable native-harness campaign after four quantization finalists qualify."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import statistics
import tempfile
import time

from benchmark import (
    practical_mcp_bridge,
    qwen_engines,
)
from benchmark import practical_tasks_v2 as tasks
from benchmark.linux_sandbox import (
    McpPolicy,
    ResourceLimits,
    RuntimeBind,
    SandboxSpec,
    SandboxSupervisor,
)
from benchmark.model_broker import BrokerPolicy
from benchmark.practical_policy import BudgetPolicy
from benchmark.practical_runtime_v2 import _phase_grade
from benchmark.qwen_engines import (
    CapacityUnsupported,
    ModelServer,
    ResourceUnavailable,
    gpu_free_mib,
    ram_available_mib,
)
from benchmark.qwen_native_runtime import stage_native_runtime
from benchmark.qwen_optimization import Campaign, fingerprint, now, write_json
from benchmark.qwen_quant_runner import LAB, REPORT, cached_artifact, stage_hot

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmark/configs/qwen-native-harness-v2.json"
OUT = LAB / "results/qwen-native-harness-comparison-v2"
INSTALL = ROOT / "results/reports/qwen-harness-refresh-20261025/installation.json"
ADAPTER_ROOT = ROOT / "benchmark/qwen_harness_adapters.py"


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def install_state():
    raw = json.loads(INSTALL.read_text())
    return raw


def quant_source():
    cfg = json.loads(CONFIG.read_text())
    if cfg["source_quant_protocol"] != "qwen-quant-harness-optimization-v4":
        raise RuntimeError("native comparison references an unexpected quant protocol")
    p = LAB / "results/qwen-quant-harness-optimization-v4/summary.json"
    if not p.is_file():
        raise RuntimeError("quantization summary is not complete")
    value = json.loads(p.read_text())
    chosen = {}
    for model in ("4B", "9B"):
        final = value["finalists"].get(model, {})
        if (
            final.get("status") != "selected"
            or not final.get("efficiency")
            or not final.get("context")
        ):
            raise RuntimeError(
                f"{model} lacks two qualified, distinct quantization finalists"
            )
        chosen[model] = list(
            {
                x["artifact_id"]: x for x in [final["efficiency"], final["context"]]
            }.values()
        )
        if len(chosen[model]) != 2:
            raise RuntimeError(f"{model} finalists must be distinct artifacts")
    return cfg, chosen, value


def native_frozen(cfg, chosen):
    paths = [
        CONFIG,
        ADAPTER_ROOT,
        ROOT / "benchmark/qwen_native_protocols.py",
        ROOT / "benchmark/qwen_native_gateway.py",
        ROOT / "benchmark/qwen_native_driver.py",
        ROOT / "benchmark/qwen_native_mcp.py",
        ROOT / "benchmark/qwen_native_runtime.py",
        ROOT / "scripts/check_qwen_native_readiness.py",
        ROOT / "benchmark/qwen_native_runner.py",
        ROOT / "benchmark/qwen_workloads.py",
        ROOT / "benchmark/practical_runtime_v2.py",
        ROOT / "benchmark/practical_tasks_v2.py",
        ROOT / "benchmark/linux_sandbox.py",
        ROOT / "benchmark/sandbox_bootstrap.py",
        ROOT / "benchmark/model_broker.py",
        ROOT / "benchmark/practical_mcp_bridge.py",
        ROOT / "benchmark/practical_mcp_grading_v2.py",
        ROOT / "benchmark/practical_grade_contract.py",
        INSTALL,
        REPORT / "qualification.json",
        REPORT / "native-readiness.json",
    ]
    return {
        "protocol_id": cfg["protocol_id"],
        "quant_finalists": chosen,
        "source_sha256": {str(p): file_sha(p) for p in paths},
        "sandbox_runtime": "current installed per-harness versions, local provider routes only",
    }


def prereq():
    qcfg, chosen, qsum = quant_source()
    qualification = json.loads(
        (
            ROOT / "results/reports/qwen-harness-refresh-20261025/qualification.json"
        ).read_text()
    )
    if not (
        ROOT / "results/reports/qwen-optimization-20261025/native-readiness.json"
    ).is_file():
        raise RuntimeError(
            "offline native-adapter and wire-protocol qualification gate is not passed"
        )
    nativeproof = json.loads(
        (
            ROOT / "results/reports/qwen-optimization-20261025/native-readiness.json"
        ).read_text()
    )
    if nativeproof.get("passed") is not True:
        raise RuntimeError("native-adapter gate not passed")
    if not qualification.get("items"):
        raise RuntimeError("offline install/CLI qualification report missing")
    (LAB / "tools/llama-bin/llama-server").stat()
    (LAB / "envs/qwen-engines-20261025/venv/bin/python").stat()
    return qcfg, chosen, qsum


def generate_schedule(cfg, chosen, stage="triage"):
    seeds = cfg["triage_seeds"] if stage == "triage" else cfg["deep_seeds"]
    tasks_to_run = cfg["tasks"] if stage == "triage" else tuple(cfg["tasks"]) * 6
    artifacts = [x for model in ("4B", "9B") for x in chosen[model]]
    units = []
    installation = install_state()
    from benchmark.qwen_harness_adapters import HARNESS_IDS

    for artifact in artifacts:
        for harness in HARNESS_IDS:
            status = prereq_static_adapter_status(harness, installation)
            for task_instance, task in enumerate(tasks_to_run):
                for seed in seeds:
                    unit = {
                        "stage": stage,
                        "artifact_id": artifact["artifact_id"],
                        "model_id": artifact["model_id"],
                        "engine": artifact["engine"],
                        "harness": harness,
                        "adapter_status": status["status"],
                        "adapter_reason": status.get("reason"),
                        "task": task,
                        "task_instance": task_instance,
                        "seed": seed,
                        "context": cfg["context_tokens"],
                        "output": cfg["output_tokens"],
                    }
                    unit["unit_id"] = fingerprint(unit)
                    units.append(unit)
    return units


def prereq_static_adapter_status(harness, installation):
    item = installation.get("items", {}).get(harness)
    if not item or item.get("status") not in {"installed", "staged"}:
        return {"status": "blocked", "reason": "installed prefix is unavailable"}
    if harness == "trueforge":
        return {
            "status": "blocked",
            "reason": "the TrueForge entry point is a REST-backed session server, not a one-shot coding CLI",
        }
    readiness_path = REPORT / "native-readiness.json"
    if readiness_path.is_file():
        wire = json.loads(readiness_path.read_text()).get("wire_smoke", {}).get(harness, {})
        if wire.get("status") == "blocked":
            return {
                "status": "blocked",
                "reason": wire.get("block_reason", "offline native harness smoke is blocked"),
            }
    return {
        "status": "candidate",
        "reason": "local endpoint path requires an in-episode adapter check",
    }


def safe_zip_snapshot(workspace, destination):
    import zipfile

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(Path(workspace).rglob("*")):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.name not in {".practical.json"}
                and not any(
                    x in {".git", "node_modules", "__pycache__"} for x in path.parts
                )
            ):
                rel = path.relative_to(workspace)
                if rel.is_absolute() or ".." in rel.parts:
                    raise ValueError("unsafe snapshot member")
                z.write(path, str(rel))


def local_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def broker_policy(port, seed, output):
    budget = BudgetPolicy(
        main=120, wall_seconds=1800, title=1, compaction=8, metadata=20
    )
    return BrokerPolicy(
        upstream_port=port,
        adapter_port=18888,
        model_allowlist=("local-qwen",),
        output_token_cap=8192,
        max_request_bytes=2 * 1024**2,
        max_response_bytes=32 * 1024**2,
        deadline_seconds=300,
        max_requests=budget.max_model_requests,
        frozen_generation={
            "temperature": 0.6,
            "top_p": 0.95,
            "min_p": 0.0,
            "presence_penalty": 0.0,
            "max_tokens": 8192,
            "seed": seed,
        },
        request_limits=budget.as_dict(),
        unclassified_request_category="main",
    )


TASK_MAP = {
    "python_fix": "B1",
    "javascript_fix": "B2",
    "authored_tests": "M1",
    "mcp": "C2",
    "continuation": "D1",
    "tool_recovery": "M2",
}


def bridge_events(root, task):
    path = Path(root) / "mcp-journal.json"
    if not path.exists():
        return []
    journal = json.loads(path.read_text())
    problem = practical_mcp_bridge.validate_journal(journal, task=task)
    if problem:
        raise RuntimeError("trusted MCP journal invalid: " + str(problem))
    return practical_mcp_bridge.trusted_calls(journal)


def adapter_inventory():
    state = install_state()
    result = {}
    from benchmark.qwen_harness_adapters import HARNESS_IDS, _installed_item

    for harness in HARNESS_IDS:
        item = _installed_item(state, harness)
        result[harness] = {
            "installed": bool(item),
            "version": None if item is None else item.get("version"),
            "status": "unreviewed",
        }
    return result


def execute_native(unit, artifact, installation, output):
    original = qwen_engines.llama_command
    if artifact["engine"] == "llama.cpp":
        qwen_engines.llama_command = lambda *args, **kwargs: (
            original(*args, **kwargs) + ["--top-k", "20"]
        )
    try:
        return _execute_native(unit, artifact, installation, output)
    finally:
        qwen_engines.llama_command = original


def _execute_native(unit, artifact, installation, output):
    from benchmark.campaign_readiness import _runtime_binds
    from benchmark.qwen_harness_adapters import prepare_adapter

    start = time.monotonic()
    task = TASK_MAP[unit["task"]]
    if unit["harness"] in {"trueforge"}:
        return {
            "status": "blocked",
            "failure": "trueforge_rest_session_adapter_unqualified",
            "model_failure": False,
            "reason": "TrueForge is an API session server, not a one-shot CLI; the bounded session API driver is pending.",
        }
    if task in {"C2", "M2"} and unit["harness"] != "opencode":
        return {
            "status": "blocked",
            "failure": "native_mcp_adapter_unqualified",
            "model_failure": False,
            "reason": "Installed-version MCP provider configuration is not qualified for this adapter.",
        }
    model_path = stage_hot(
        cached_artifact(
            artifact, json.loads((REPORT / "artifact-catalog-v2.json").read_text())
        ),
        artifact,
    )
    port = 18887
    task_contract = (
        tasks.M1_INDEPENDENT_CONTRACT if task == "M1" else tasks.HISTORICAL_CONTRACT
    )
    with tempfile.TemporaryDirectory(prefix="qwen-native-", dir="/tmp") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        workspace.mkdir()
        prompt = tasks.seed_task(
            task, workspace, with_skills=False, task_contract_id=task_contract
        )
        with ModelServer(
            model_path, artifact["engine"], root / "server", unit["context"]
        ) as server:
            adapter = prepare_adapter(
                unit["harness"],
                installation,
                model_alias=server.alias,
                endpoint_port=port,
                prompt=prompt,
                workspace="/workspace",
                mcp_port=18889 if task in {"C2", "M2"} else None,
            )
            if adapter["status"] != "ready":
                return {
                    "status": "blocked",
                    "failure": "native_adapter_configuration",
                    "model_failure": False,
                    "reason": adapter["reason"],
                }
            adapter.update(
                workspace="/workspace",
                evidence_dir="/workspace",
                model_alias=server.alias,
                gateway_port=port,
                output_cap=8192,
                generation={
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "min_p": 0.0,
                    "presence_penalty": 0.0,
                    "max_tokens": 8192,
                    "seed": unit["seed"],
                },
            )
            if unit["harness"] == "mistral-vibe":
                adapter["native_model_aliases"] = ["qwen-local"]
            if unit["harness"] == "openhands":
                adapter["native_model_aliases"] = ["openai/" + server.alias]
            native_runtime = stage_native_runtime(root, ROOT, adapter)
            broker_transcript_dir=root/'broker'
            broker_transcript_dir.mkdir(mode=0o700)
            binds = [RuntimeBind(native_runtime, "/opt/qwen-native")]
            binds.extend(_runtime_binds())
            for source, target in adapter["runtime_ro"]:
                source = Path(source)
                if not source.exists() or source.is_symlink():
                    return {
                        "status": "blocked",
                        "failure": "adapter_runtime_bind_missing",
                        "model_failure": False,
                        "reason": source.name,
                    }
                binds.append(RuntimeBind(source.resolve(), target))
            bridge = (
                practical_mcp_bridge.McpBridge(
                    task,
                    journal_path=root / "mcp-journal.json",
                    contract_id=task_contract,
                )
                if task in {"C2", "M2"}
                else None
            )
            spec = SandboxSpec(
                argv=(
                    "/usr/bin/python3.12",
                    "-B",
                    "-I",
                    "/opt/qwen-native/qwen_native_driver.py",
                    "/opt/qwen-native/adapter.json",
                ),
                workspace=workspace,
                workspace_exports=tasks.exports(task),
                runtime_ro=tuple(binds),
                env={"PYTHONDONTWRITEBYTECODE": "1"},
                limits=ResourceLimits(
                    memory_bytes=2 * 1024**3,
                    swap_bytes=512 * 1024**2,
                    cpu_quota_percent=100,
                    cpu_seconds=600,
                    pids=96,
                    wall_seconds=1800,
                    output_bytes=8 * 1024**2,
                    workspace_bytes=256 * 1024**2,
                    workspace_files=5000,
                    workspace_file_bytes=64 * 1024**2,
                    scratch_bytes=256 * 1024**2,
                ),
                broker=broker_policy(server.port, unit["seed"], root / "broker"),
                broker_transcript_dir=broker_transcript_dir,
                mcp=McpPolicy(18889) if bridge is not None else None,
                mcp_bridge=bridge,
            )
            try:
                result = SandboxSupervisor().run(spec)
            finally:
                if bridge is not None and not bridge.closed:
                    journal = bridge.close()
                    write_json(root / "mcp-journal.json", journal)
            stdout = result.output.decode("utf-8", errors="replace")
            packet = [
                line[len("QWEN_NATIVE_EPISODE:") :]
                for line in stdout.splitlines()
                if line.startswith("QWEN_NATIVE_EPISODE:")
            ]
            native = None
            if len(packet) == 1:
                try:
                    native = json.loads(packet[0])
                except ValueError:
                    pass
            if (
                result.infrastructure_error
                or not result.cleanup_verified
                or not result.namespace_evidence.get("isolated", {}).get("net")
            ):
                return {
                    "status": "blocked",
                    "failure": "sandbox_or_transport_infrastructure",
                    "model_failure": False,
                    "infrastructure_error": result.infrastructure_error,
                    "cleanup": result.cleanup_verified,
                }
            if result.timed_out:
                return {
                    "status": "blocked",
                    "failure": "native_cli_deadline_unattributed",
                    "model_failure": False,
                }
            if native is None:
                return {
                    "status": "blocked",
                    "failure": "native_driver_evidence_missing",
                    "model_failure": False,
                }
            outputs = root / "exports"
            outputs.mkdir(exist_ok=True)
            for path, data in result.workspace_outputs.items():
                target = outputs / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            snapshot = outputs / "phase-1.zip"
            safe_zip_snapshot(outputs, snapshot)
            phase = _phase_grade(
                task,
                1,
                snapshot,
                lab=LAB,
                mcp_events=bridge_events(root, task),
                task_contract_id=task_contract,
                mcp_journal=json.loads((root / "mcp-journal.json").read_text())
                if bridge
                else None,
            )
            if phase.get("hidden", {}).get("infrastructure") or phase.get(
                "hidden", {}
            ).get("contract_invalid"):
                return {
                    "status": "blocked",
                    "failure": "trusted_grade_infrastructure_or_contract",
                    "model_failure": False,
                    "grade_reason": phase.get("hidden", {}).get("reason"),
                }
            complete = phase["hidden"].get("passed") is True
            if bridge is not None:
                journal = json.loads((root / "mcp-journal.json").read_text())
                if journal.get("fault") or not journal.get("clean_close"):
                    return {
                        "status": "blocked",
                        "failure": "mcp_bridge_infrastructure",
                        "model_failure": False,
                        "reason": journal.get("fault")
                        or "MCP relay did not close cleanly",
                    }
            if (
                native.get("model_budget_exhausted")
                or native.get("wall_budget_exhausted")
                or native.get("tool_budget_exhausted")
            ):
                return {
                    "status": "model_failure",
                    "failure": "budget_exhausted",
                    "model_failure": True,
                    "full_completion": False,
                    "functional_correct": complete,
                    "native_protocol_requests": native["native_protocol_requests"],
                    "tool_calls": native["tool_calls_observed"],
                    "grade": phase,
                    "budget_reason": {
                        "model_api": native.get("model_budget_exhausted"),
                        "wall": native.get("wall_budget_exhausted"),
                        "tools": native.get("tool_budget_exhausted"),
                    },
                }
            if tasks.TASK_SPECS[task]["language"] != "mcp":
                authored = phase.get("authored_tests", {})
                from benchmark.practical_test_quality import assess_authored_regression

                quality = assess_authored_regression(
                    task, snapshot, lab=LAB, candidate=authored
                )
                phase["authored_test_quality"] = quality
                if complete and (
                    not authored.get("passed")
                    or authored.get("additional_count", 0) <= 0
                    or quality.get("quality") != "regression_detected"
                ):
                    complete = False
            return {
                "status": "complete"
                if complete and native["returncode"] == 0
                else "model_failure",
                "model_failure": not (complete and native["returncode"] == 0),
                "full_completion": complete and native["returncode"] == 0,
                "functional_correct": complete,
                "model_generations": native["model_generations"],
                "native_protocol_requests": native["native_protocol_requests"],
                "tool_calls": native["tool_calls_observed"],
                "seconds": time.monotonic() - start,
                "adapter_overrides": native["adapter_overrides"],
                "exit_code": native["returncode"],
                "grade": phase,
                "server_cleanup_verified": True,
            }


def native_units(cfg, chosen, stage, *, harnesses=None, best_artifacts=None):
    """Freeze each harness/model/quant/task/seed slot as a durable unit."""
    if stage == "triage":
        return generate_schedule(cfg, chosen, stage)
    selected = list(harnesses or [])
    if not selected:
        return []
    installation = install_state()
    artifacts = {}
    for model in ("4B", "9B"):
        for harness in selected:
            if best_artifacts and harness in best_artifacts.get(model, {}):
                artifacts[model, harness] = [
                    next(
                        a
                        for a in chosen[model]
                        if a["artifact_id"] == best_artifacts[model][harness]
                    )
                ]
            else:
                artifacts[model, harness] = chosen[model]
    tasks = cfg.get("deep_task_ids")
    if (
        not isinstance(tasks, list)
        or len(tasks) != cfg.get("deep_tasks")
        or len(set(tasks)) != len(tasks)
        or any(task not in TASK_MAP for task in tasks)
        or not cfg.get("deep_seeds")
        or len(set(cfg["deep_seeds"])) != len(cfg["deep_seeds"])
    ):
        return []
    rows = []
    for harness in selected:
        for model in ("4B", "9B"):
            for artifact in artifacts[model, harness]:
                for instance, task in enumerate(tasks):
                    for seed in cfg["deep_seeds"]:
                        row = {
                            "stage": stage,
                            "model_id": model,
                            "artifact_id": artifact["artifact_id"],
                            "engine": artifact["engine"],
                            "harness": harness,
                            "adapter_status": prereq_static_adapter_status(
                                harness, installation
                            )["status"],
                            "adapter_reason": prereq_static_adapter_status(
                                harness, installation
                            ).get("reason"),
                            "task": task,
                            "task_instance": instance,
                            "seed": seed,
                            "context": cfg["context_tokens"],
                        }
                        row["unit_id"] = fingerprint(row)
                        rows.append(row)
    return rows


def native_coverage(records, cfg, stage="triage"):
    """Compare identical complete task sets; retain per-harness feature blockers."""
    required = (
        tuple(cfg.get("deep_task_ids", ()))
        if stage == "deep"
        else ("python_fix", "javascript_fix", "authored_tests")
    )
    expected_seeds = tuple(
        cfg.get("deep_seeds", ()) if stage == "deep" else cfg.get("triage_seeds", (101,))
    )
    per_harness = {}
    best_artifact = {m: {} for m in ("4B", "9B")}
    for harness in cfg["harnesses"]:
        per_harness[harness] = {}
        for model in ("4B", "9B"):
            groups = {}
            for row in records:
                unit = row["unit"]
                if (
                    unit["stage"] == stage
                    and unit["harness"] == harness
                    and unit["model_id"] == model
                    and unit["task"] in required
                    and row.get("status") == "finished"
                ):
                    groups.setdefault(unit["artifact_id"], {}).setdefault(
                        unit["task"], {}
                    ).setdefault(unit["seed"], []).append(row["result"])
            eligible = []
            for artifact_id, cases in groups.items():
                if set(cases) != set(required) or any(
                    set(seed_cases) != set(expected_seeds)
                    or any(
                        len(results) != 1
                        or results[0].get("status") not in {"complete", "model_failure"}
                        for results in seed_cases.values()
                    )
                    for seed_cases in cases.values()
                ):
                    continue
                outcomes = [
                    cases[task][seed][0]
                    for task in required
                    for seed in expected_seeds
                ]
                success = sum(r.get("full_completion") is True for r in outcomes)
                secs = [
                    r.get("seconds")
                    for r in outcomes
                    if isinstance(r.get("seconds"), (int, float))
                ]
                eligible.append(
                    (
                        success / len(outcomes),
                        statistics.median(secs) if secs else 1800,
                        artifact_id,
                        success,
                        len(outcomes),
                    )
                )
            # Do not label a configuration a harness finalist if it solved
            # none of the common, scorable coding tasks for this model size.
            eligible = [row for row in eligible if row[3] >= 1]
            if eligible:
                score = sorted(eligible, key=lambda x: (-x[0], x[1], x[2]))[0]
                per_harness[harness][model] = {
                    "score": score[0],
                    "completion_count": score[3],
                    "episode_count": score[4],
                    "artifact_id": score[2],
                    "median_seconds": score[1],
                    "common_task_coverage": list(required),
                }
                best_artifact[model][harness] = score[2]
    ranked = [
        h for h in cfg["harnesses"] if all(m in per_harness[h] for m in ("4B", "9B"))
    ]
    ranked.sort(
        key=lambda h: (
            -(per_harness[h]["4B"]["score"] + per_harness[h]["9B"]["score"]) / 2,
            per_harness[h]["4B"]["median_seconds"]
            + per_harness[h]["9B"]["median_seconds"],
            h,
        )
    )
    return {
        "status": "selected"
        if len(ranked) >= cfg["best_harnesses"]
        else "insufficient_native_coverage",
        "stage": stage,
        "common_tasks": list(required),
        "harnesses": per_harness,
        "by_harness": per_harness,
        "finalists": ranked[: cfg["best_harnesses"]],
        "best_artifact_by_model_harness": best_artifact,
        "all_native_harnesses_reported": len(per_harness) == len(cfg["harnesses"]),
    }


def main():
    import argparse
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quant-output",
        type=Path,
        default=LAB / "results/qwen-quant-harness-optimization-v4",
    )
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--parent-held-gpu-lock", type=int)
    args = parser.parse_args()
    cfg, chosen, quant_report = prereq()
    installation = install_state()
    install_digest = file_sha(INSTALL)
    immutable = {
        "protocol_id": cfg["protocol_id"],
        "config": cfg,
        "quant_summary_sha256": file_sha(args.quant_output / "summary.json"),
        "finalists": chosen,
        "native_readiness_sha256": file_sha(REPORT / "native-readiness.json"),
        "harness_install_state_sha256": install_digest,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "supervisor.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.parent_held_gpu_lock is not None:
        parent = Path("/proc") / str(args.parent_held_gpu_lock)
        if (
            not parent.exists()
            or b"benchmark.qwen_quant_runner" not in (parent / "cmdline").read_bytes()
        ):
            raise RuntimeError(
                "claimed parent does not own the quantization GPU supervisor"
            )
    else:
        global_lock = (LAB / "state/qwen-optimization-gpu.lock").open("a")
        fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    queue = Campaign(args.output, immutable)
    if not queue.state["units"]:
        queue.add(native_units(cfg, chosen, "triage"))
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "units": len(queue.pending()),
                    "inference": False,
                }
            )
        )
        return 0
    (args.output / "supervisor.pid").write_text(str(os.getpid()))
    last_stage_summary = args.output / "native-summary.json"
    while True:
        if (args.output / "PAUSE").exists():
            queue.state["status"] = "paused_at_unit_boundary_for_offline_work"
            queue.save()
            time.sleep(15)
            continue
        pending = queue.pending()
        if not pending:
            records = queue.records()
            stages = {row["unit"]["stage"] for row in queue.state["units"]}
            if "deep" not in stages:
                triage = native_coverage(records, cfg)
                write_json(args.output / "triage-summary.json", triage)
                if triage["status"] != "selected":
                    queue.state["status"] = (
                        "native_triage_complete_with_insufficient_coverage"
                    )
                    queue.save()
                    write_json(last_stage_summary, triage)
                    return 0
                finalists = set(triage["finalists"])
                best_artifacts = {
                    model: {h: triage["best_artifact_by_model_harness"][model][h]
                            for h in finalists}
                    for model in ("4B", "9B")
                }
                if any(not best_artifacts[model] for model in ("4B", "9B")):
                    queue.state["status"] = (
                        "native_triage_complete_but_model_pairing_missing"
                    )
                    queue.save()
                    write_json(last_stage_summary, triage)
                    return 0
                deep_units = native_units(
                    cfg,
                    chosen,
                    "deep",
                    harnesses=finalists,
                    best_artifacts=best_artifacts,
                )
                if not deep_units:
                    blocked = {
                        "status": "native_deep_stage_not_prepared",
                        "reason": (
                            "Twelve distinct, oracle-qualified deep task IDs are required; "
                            "repeated triage tasks are not accepted as additional tasks."
                        ),
                        "triage": triage,
                    }
                    queue.state["status"] = blocked["status"]
                    queue.save()
                    write_json(last_stage_summary, blocked)
                    return 0
                queue.add(deep_units)
                queue.state["status"] = "native_deep_stage_scheduled"
                queue.save()
                continue
            deep = native_coverage(records, cfg, stage="deep")
            write_json(args.output / "deep-summary.json", deep)
            queue.state["status"] = "native_deep_complete_confirmation_tasks_pending"
            queue.save()
            write_json(last_stage_summary, deep)
            return 0
        unit = pending[0]
        if unit.get("adapter_status") == "blocked":
            queue.begin(unit)
            queue.finish(
                unit,
                {
                    "status": "blocked",
                    "failure": "native_adapter_not_qualified",
                    "model_failure": False,
                    "reason": unit.get("adapter_reason")
                    or "offline adapter qualification blocked this harness",
                },
            )
            continue
        if unit.get("task") == "continuation":
            queue.begin(unit)
            queue.finish(
                unit,
                {
                    "status": "blocked",
                    "failure": "native_session_resume_unqualified",
                    "model_failure": False,
                    "reason": "The installed CLI does not yet have a qualified staged-session continuation adapter.",
                },
            )
            continue
        task = TASK_MAP[unit["task"]]
        if (
            tasks.TASK_SPECS[task]["language"] == "mcp"
            and unit["harness"] != "opencode"
        ):
            queue.begin(unit)
            queue.finish(
                unit,
                {
                    "status": "blocked",
                    "failure": "native_mcp_adapter_unqualified",
                    "model_failure": False,
                    "reason": "Only the installed OpenCode MCP local-server config has passed the schema gate.",
                },
            )
            continue
        unit_started = time.monotonic()
        resources = {
            "gpu": gpu_free_mib(),
            "ram": ram_available_mib(),
            "disk": shutil.disk_usage(LAB).free,
        }
        if (
            resources["gpu"] < 7000
            or resources["ram"] < 1536
            or resources["disk"] < 8 * 1024**3
        ):
            queue.state["status"] = "waiting_for_user_resources"
            queue.save()
            time.sleep(30)
            continue
        artifact = next(
            row
            for model in ("4B", "9B")
            for row in chosen[model]
            if row["artifact_id"] == unit["artifact_id"]
        )
        record_dir = queue.begin(unit)
        try:
            result = execute_native(unit, artifact, installation, record_dir)
        except (CapacityUnsupported, ResourceUnavailable) as exc:
            result = {
                "status": "resource_blocked",
                "failure": "local_capacity_or_resources",
                "model_failure": False,
                "error": str(exc),
            }
        except Exception as exc:
            result = {
                "status": "blocked",
                "failure": "unattributed_native_harness_or_infrastructure",
                "model_failure": False,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "seconds": time.monotonic() - unit_started,
            }
        if result.get("status") == "resource_blocked":
            queue.wait_resources(unit, result, resources)
        else:
            queue.finish(unit, result)
        write_json(
            args.output / "last-progress.json",
            {"unit": unit, "status": result["status"], "at": now()},
        )
        print(
            json.dumps(
                {
                    "unit": unit["unit_id"],
                    "model": unit["model_id"],
                    "harness": unit["harness"],
                    "task": unit["task"],
                    "status": result["status"],
                    "seconds": result.get("seconds"),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
