"""Durable single-GPU quantization campaign. Never retries a finished model failure.

Prepare freezes inputs. Execute requires offline qualification evidence and
continues across per-artifact blocks. Native harness stages have separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

from benchmark.qwen_artifacts import ArtifactError, ensure_artifact
from benchmark.qwen_engines import (
    ApiClient,
    CapacityUnsupported,
    ModelBudgetExceeded,
    ModelProtocolError,
    ModelServer,
    ResourceUnavailable,
    gpu_free_mib,
    ram_available_mib,
)
from benchmark.qwen_optimization import (
    Campaign,
    choose_finalists,
    make_units,
    now,
    seed_recovery_state,
    write_json,
)
from benchmark.qwen_probes import run_qualification
from benchmark.qwen_workloads import TASK_MAP, ModelBehaviorFailure, run_development

ROOT = Path(__file__).resolve().parents[1]
LAB = Path("/home/foxtrot/local-llm-benchmark")
REPORT = ROOT / "results/reports/qwen-optimization-v4-recovery-r3-dns"
CACHE = Path("/mnt/d/Usuario/Downloads/LLM/qwen-optimization-cache/models")
CONFIG = ROOT / "benchmark/configs/qwen-optimization-v4-recovery-r3-dns.json"
DEFAULT_OUTPUT = LAB / "results/qwen-quant-harness-optimization-v4-recovery-r3-dns"
SOURCES = (
    "qwen_quant_runner.py",
    "qwen_engines.py",
    "qwen_optimization.py",
    "qwen_probes.py",
    "qwen_workloads.py",
    "qwen_artifacts.py",
    "practical_runtime_v2.py",
    "practical_tasks_v2.py",
    "practical_grade_contract.py",
    "practical_python_checks.py",
    "practical_node_rpc.mjs",
    "practical_worker_guard.py",
    "practical_test_quality.py",
    "practical_mcp_bridge.py",
    "practical_mcp_v2.py",
    "practical_mcp_grading_v2.py",
    "linux_sandbox.py",
    "sandbox_bootstrap.py",
    "model_broker.py",
    "practical_policy.py",
    "practical_manual.py",
    "practical_tool_guard.py",
    "campaign_readiness.py",
    "safe_campaign.py",
    "model_quality_paired.py",
    "pristine_grading.py",
    "harness_runner.py",
    "provenance.py",
    "opencode_controlled_probe.py",
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frozen_inputs(catalog, config, recovery_origin_path=None):
    paths = [ROOT / "benchmark" / name for name in SOURCES]
    paths += [
        CONFIG,
        catalog,
        REPORT / "engines.json",
        REPORT / "foundation.json",
        REPORT / "cache-footprint.json",
        ROOT / "scripts/inspect_qwen_artifact.py",
        ROOT / "results/reports/qwen-harness-refresh-20261025/qualification.json",
    ]
    if recovery_origin_path is not None:
        paths.append(Path(recovery_origin_path))
    return {
        "protocol_id": config["protocol_id"],
        "config": config,
        "source_files": {str(path): sha(path) for path in paths},
        "runtime_binary_sha256": sha(LAB / "tools/llama-bin/llama-server"),
        "stage": "quantization-selection",
        "native_harness_scores": False,
    }


def prerequisites():
    refresh = json.loads(
        (
            ROOT / "results/reports/qwen-harness-refresh-20261025/installation.json"
        ).read_text()
    )
    if refresh["status"] not in {"installed", "installed_with_blocks"}:
        raise RuntimeError("harness refresh still incomplete")
    if not (
        ROOT / "results/reports/qwen-harness-refresh-20261025/qualification.json"
    ).is_file():
        raise RuntimeError("offline harness qualification missing")
    proof = REPORT / "foundation.json"
    if not proof.is_file() or json.loads(proof.read_text()).get("passed") is not True:
        raise RuntimeError("offline test/oracle foundation gate not passed")
    for path, digest in json.loads(proof.read_text()).get("source_sha256", {}).items():
        if sha(path) != digest:
            raise RuntimeError(
                "offline foundation source changed; rerun the non-inference gate"
            )


def eligible_artifact(artifact):
    if artifact["engine"] not in {"llama.cpp", "exllamav3"}:
        return "engine_requires_separate_hardware_architecture_qualification"
    if artifact.get("source_base", {}).get("status") not in {
        "verified",
        "publisher_declared",
    }:
        return "original_model_provenance_unverified"
    # This is a full-GPU operational experiment. A file-size exclusion alone
    # would misclassify mixed precision/MTP bundles, so actual load decides fit.
    if artifact["total_bytes"] > 16 * 1024**3:
        return "outside_safe_operational_storage_and_memory_envelope"
    return None


def validate_catalog(catalog):
    identities = set()
    for artifact in catalog["artifacts"]:
        if artifact["artifact_id"] in identities:
            raise ValueError("duplicate artifact identity")
        identities.add(artifact["artifact_id"])
        if artifact["engine"] == "llama.cpp" and len(artifact["files"]) != 1:
            groups = []
            for record in artifact["files"]:
                match = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})\.gguf", record["path"])
                if not match:
                    raise ValueError(
                        "distinct GGUF precisions cannot be grouped as model shards"
                    )
                groups.append(match.groups())
            totals = {int(g[2]) for g in groups}
            if (
                len({g[0] for g in groups}) != 1
                or totals != {len(groups)}
                or {int(g[1]) for g in groups} != set(range(1, len(groups) + 1))
            ):
                raise ValueError("GGUF shard group is incomplete or mixes variants")


def ordered_artifacts(artifacts):
    preferred = {
        "Q4_K_M": 0,
        "UD-Q4_K_XL": 1,
        "IQ4_XS": 2,
        "4.00bpw": 3,
        "Q5_K_M": 4,
        "Q6_K": 5,
        "Q8_0": 6,
    }
    control_sha = "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"
    return sorted(
        artifacts,
        key=lambda a: (
            not any(f["sha256"] == control_sha for f in a["files"]),
            preferred.get(a["quantfmt"].removeprefix("GGUF-").removeprefix("I1-"), 20),
            a["model_id"],
            a["repo_id"] != "unsloth/Qwen3.5-" + a["model_id"] + "-GGUF",
            a["total_bytes"],
            a["artifact_id"],
        ),
    )


def local_existing(artifact):
    path = LAB / "models/gguf/Qwen3.5-9B-Q4_K_M.gguf"
    if artifact["engine"] == "llama.cpp" and len(artifact["files"]) == 1:
        record = artifact["files"][0]
        if (
            path.exists()
            and path.stat().st_size == record["size"]
            and sha(path) == record["sha256"]
        ):
            return path
    return None


def _cache_usage(path):
    seen, size = set(), 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            stat = item.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity not in seen:
                seen.add(identity)
                size += stat.st_size
    return size


def cached_artifact(artifact, catalog):
    existing = local_existing(artifact)
    if existing:
        return existing
    if CACHE.is_symlink():
        raise ArtifactError("model cache root must not be a symlink")
    CACHE.mkdir(parents=True, exist_ok=True)
    if CACHE.resolve() != CACHE.absolute():
        raise ArtifactError("model cache ancestor redirects outside its absolute path")
    marker = CACHE / ".qwen-campaign-owned"
    if marker.is_symlink():
        raise ArtifactError("cache marker must not be a symlink")
    if marker.exists() and marker.read_text() != "qwen-quant-harness-optimization-v1\n":
        raise ArtifactError("foreign cache ownership marker")
    if not marker.exists():
        if any(p.name != ".qwen-campaign-owned" for p in CACHE.iterdir()):
            raise ArtifactError("refusing to adopt nonempty unowned model cache")
        marker.write_text("qwen-quant-harness-optimization-v1\n")
    # Dependency cache is frozen after installation. Rewalking ~10GB of small
    # DrvFS files before every unit made preparation stall on p9 metadata RPCs.
    parent_other = json.loads((REPORT / "cache-footprint.json").read_text())["bytes"]
    budget = max(0, 60 * 1024**3 - parent_other)
    needed = sum(
        r["size"]
        for r in artifact["files"]
        if not (CACHE / ".objects" / r["sha256"]).exists()
    )
    if _cache_usage(CACHE) + needed > budget:
        # Only immutable model downloads owned by this campaign are disposable.
        known = {a["artifact_id"] for a in catalog["artifacts"]}
        candidates = sorted(
            (
                p
                for p in CACHE.iterdir()
                if p.name in known
                and p.name != artifact["artifact_id"]
                and p.is_dir()
                and not p.is_symlink()
            ),
            key=lambda p: p.stat().st_mtime,
        )
        for path in candidates:
            if path.resolve().parent != CACHE.resolve():
                raise ArtifactError("cache eviction target escaped owned root")
            shutil.rmtree(path)
            objects = CACHE / ".objects"
            if objects.is_symlink():
                raise ArtifactError("cache content objects must not be a symlink")
            if objects.exists():
                for blob in objects.iterdir():
                    if (
                        blob.is_file()
                        and not blob.is_symlink()
                        and blob.stat().st_nlink == 1
                    ):
                        blob.unlink()
            if _cache_usage(CACHE) + needed <= budget:
                break
    return ensure_artifact(artifact, CACHE, max_cache_bytes=budget)


def stage_hot(path, artifact):
    if Path(path).resolve().is_relative_to((LAB / "models").resolve()):
        return path  # Preserved pre-existing control, already on ext4.
    root = LAB / "state/qwen-hot"
    active = root / "active"
    owner = root / "owner.json"
    if root.is_symlink() or active.is_symlink() or owner.is_symlink():
        raise ArtifactError("hot-cache root/active/owner must not be symlinks")
    root.mkdir(parents=True, exist_ok=True)
    if root.resolve() != root.absolute():
        raise ArtifactError(
            "hot-cache ancestor must not redirect outside its absolute path"
        )
    if owner.exists():
        previous = json.loads(owner.read_text())
        if previous.get("protocol_id") != "qwen-quant-harness-optimization-v1":
            raise ArtifactError("foreign hot-cache owner")
        if previous["artifact_id"] != artifact["artifact_id"]:
            for record in previous["files"]:
                target = active / record["path"]
                if (
                    not target.resolve().is_relative_to(active.resolve())
                    or target.is_symlink()
                ):
                    raise ArtifactError("hot-cache cleanup escaped owned root")
                target.unlink(missing_ok=True)
            for directory in sorted(
                (p for p in active.rglob("*") if p.is_dir()), reverse=True
            ):
                directory.rmdir()
            if any(active.iterdir()):
                raise ArtifactError("unrecognized files in hot-cache; preserved")
    elif active.exists() and any(active.iterdir()):
        raise ArtifactError("refusing to adopt pre-existing hot-cache files")
    active.mkdir(exist_ok=True)
    write_json(
        owner,
        {
            "protocol_id": "qwen-quant-harness-optimization-v1",
            "artifact_id": artifact["artifact_id"],
            "files": artifact["files"],
        },
    )
    for record in artifact["files"]:
        target = active / record["path"]
        if not target.resolve().is_relative_to(active.resolve()) or target.is_symlink():
            raise ArtifactError("invalid hot-cache destination")
        if (
            target.exists()
            and target.stat().st_size == record["size"]
            and sha(target) == record["sha256"]
        ):
            continue
        if shutil.disk_usage(LAB).free < record["size"] + 8 * 1024**3:
            raise ResourceUnavailable("hot-cache copy would cross 8 GiB ext4 floor")
        source = Path(path) if Path(path).is_file() else Path(path) / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open("rb") as incoming, target.open("wb") as outgoing:
            while block := incoming.read(4 * 1024**2):
                if shutil.disk_usage(LAB).free < 8 * 1024**3:
                    raise ResourceUnavailable("hot-cache reached 8 GiB ext4 floor")
                outgoing.write(block)
                digest.update(block)
        if (
            target.stat().st_size != record["size"]
            or digest.hexdigest() != record["sha256"]
        ):
            raise ArtifactError("hot-cache copy hash/size mismatch")
    return (
        active
        if artifact["engine"] != "llama.cpp" or len(artifact["files"]) > 1
        else active / artifact["files"][0]["path"]
    )


def recover_owned_servers(output):
    """Terminate only exact PID/starttime/argv matches from interrupted attempts."""
    for marker in Path(output).glob("units/*/*/server/server-process.json"):
        info = json.loads(marker.read_text())
        proc = Path("/proc") / str(info["pid"])
        try:
            start = (proc / "stat").read_text().split()[21]
            launch = json.loads((marker.parent / "launch.json").read_text())
            command = [
                x.decode() for x in (proc / "cmdline").read_bytes().split(b"\0") if x
            ]
            if start != info["starttime"] or command != launch["command"]:
                continue
            if os.getpgid(info["pid"]) != info["pid"]:
                raise RuntimeError("owned server process-group identity changed")
            os.killpg(info["pid"], signal.SIGTERM)
            for _ in range(50):
                if not proc.exists():
                    break
                time.sleep(0.1)
            if proc.exists() and (proc / "stat").read_text().split()[21] == start:
                os.killpg(info["pid"], signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            pass


class Telemetry:
    def __init__(self, output):
        self.output, self.rows = Path(output), []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.is_set():
            try:
                self.rows.append(
                    {
                        "at": now(),
                        "device_free_mib": gpu_free_mib(),
                        "host_available_ram_mib": ram_available_mib(),
                    }
                )
                write_json(self.output / "resource-samples.json", self.rows)
            except Exception as exc:
                self.rows.append({"at": now(), "error": str(exc)})
            self.stop.wait(1)

    def __enter__(self):
        self.output.mkdir(parents=True, exist_ok=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=20)


def capacity_check(client, context, output):
    reserved = min(4096, context // 4)
    target = context - reserved - 256
    markers = ["early-749a", "middle-139b", "late-827c"]
    prefix = (
        "Cold run "
        + os.urandom(8).hex()
        + ". Remember three keys in order. First key: "
        + markers[0]
        + "\n"
    )
    suffix = (
        "\nLast key: "
        + markers[2]
        + "\nReturn only a JSON array containing the first, middle, and last key, in order."
    )
    count = max(1, target // 2)
    prompt = ""
    tokens = []
    for _ in range(6):
        filler = " filler" * count
        prompt = (
            prefix + filler + "\nMiddle key: " + markers[1] + "\n" + filler + suffix
        )
        tokens = client.tokenize(prompt)
        if target * 0.97 <= len(tokens) <= target:
            break
        count = max(1, int(count * (target - 64) / max(1, len(tokens))))
    if not target * 0.95 <= len(tokens) <= target:
        raise ModelProtocolError(
            "tokenized capacity prompt outside fixed input envelope"
        )
    response = client.chat([{"role": "user", "content": prompt}], max_tokens=reserved)
    message = response["choices"][0]["message"]
    try:
        recovered = json.loads(message.get("content") or "") == markers
    except ValueError:
        recovered = False
    usage = response.get("usage") or {}
    observed = usage.get("prompt_tokens")
    verified = (
        recovered
        and isinstance(observed, int)
        and target * 0.95 <= observed <= context - reserved
    )
    result = {
        "status": "complete" if verified else "model_failure",
        "context_verified": verified,
        "context": context,
        "tokenized_text_tokens": len(tokens),
        "actual_prompt_tokens": observed,
        "generation_reserved": reserved,
        "recovered": recovered,
        "metrics": client.metrics[-1],
        "calls": client.calls,
        "metadata_calls": client.metadata_calls,
    }
    write_json(Path(output) / "result.json", result)
    return result


def measure(unit, artifact, catalog, output, engines, *, gpu_policy=None):
    policy = gpu_policy or {}
    gpu_floor = policy.get("gpu_free_floor_mib", 7000)
    gpu_reserve = policy.get("gpu_reserve_mib", 512)
    if any(type(x) is not int or x < 0 for x in (gpu_floor, gpu_reserve)):
        raise ValueError("GPU limits must be non-negative integer MiB")
    output.mkdir(parents=True, exist_ok=True)
    exclusion = eligible_artifact(artifact)
    if exclusion:
        return {"status": "blocked", "failure": exclusion, "model_failure": False}
    if (
        artifact["engine"] == "exllamav3"
        and engines.get("status") != "installed_import_qualified"
    ):
        return {
            "status": "blocked",
            "failure": "EXL3 runtime not qualified",
            "model_failure": False,
        }
    path = stage_hot(cached_artifact(artifact, catalog), artifact)
    if artifact["engine"] == "llama.cpp":
        python = LAB / "envs/qwen-engines-20261025/venv/bin/python"
        metadata = json.loads(
            subprocess.check_output(
                [
                    str(python),
                    str(ROOT / "scripts/inspect_qwen_artifact.py"),
                    str(path),
                ],
                text=True,
                timeout=90,
            )
        )
        write_json(output / "artifact-metadata.json", metadata)
        expected_hidden = 2560 if artifact["model_id"] == "4B" else 4096
        if (
            metadata["architecture"] != "qwen35"
            or metadata["embedding_length"] != expected_hidden
            or metadata["block_count"] != 32
        ):
            raise ArtifactError(
                "GGUF architecture/shape does not match the declared Qwen original"
            )
    if shutil.disk_usage(LAB).free < 8 * 1024**3:
        raise ResourceUnavailable("WSL disk below 8 GiB floor")
    with Telemetry(output) as telemetry:
        with ModelServer(
            path, artifact["engine"], output / "server", unit["context"],
            gpu_free_floor_mib=gpu_floor, gpu_reserve_mib=gpu_reserve,
        ) as server:
            warmup = ApiClient(
                server.port,
                output / "warmup",
                engine=artifact["engine"],
                model=server.alias,
                max_calls=1,
                max_tokens=64,
            )
            warmup.chat([{"role": "user", "content": "Reply OK."}])
            if gpu_free_mib() < gpu_reserve:
                raise CapacityUnsupported(
                    f"warmup left less than the frozen {gpu_reserve} MiB GPU reserve"
                )
            client = ApiClient(
                server.port,
                output / "client",
                engine=artifact["engine"],
                model=server.alias,
                seed=unit["seed"],
                context_tokens=unit["context"],
                max_tokens=unit.get("output_tokens", 4096),
            )
            if unit["stage"] == "qualification":
                result = run_qualification(client, output)
            elif unit["stage"] == "capacity":
                result = capacity_check(client, unit["context"], output)
            elif unit["stage"] == "development":
                result = run_development(client, unit["task"], output)
            else:
                raise RuntimeError("unknown quantization stage")
    samples = [r["device_free_mib"] for r in telemetry.rows if "device_free_mib" in r]
    result["telemetry_complete"] = len(samples) >= 2 and not any(
        "error" in r for r in telemetry.rows
    )
    result["peak_device_vram_mib"] = (
        8192 - min(samples) if result["telemetry_complete"] else None
    )
    if result["telemetry_complete"] and min(samples) < gpu_reserve:
        result = {
            "status": "resource_blocked",
            "failure": "gpu_reserve_breached_during_episode",
            "model_failure": False,
            "observed_model_result": result,
            "peak_device_vram_mib": 8192 - min(samples),
            "telemetry_complete": True,
        }
    result["resource_scope"] = (
        "whole device; includes Windows baseline; not process-attributed"
    )
    result["warmup"] = {
        "calls": warmup.calls,
        "excluded_from_measurement": True,
        "metrics": warmup.metrics,
    }
    result["cleanup_verified"] = server.process.poll() is not None
    result["generation_classes"] = dict(client.counts)
    result["metadata_calls"] = client.metadata_calls
    if not result["cleanup_verified"]:
        raise RuntimeError("server cleanup unverified")
    return result


def extend_schedule(queue, artifacts, config):
    records = queue.records()
    for row in records:
        unit, result = row["unit"], row["result"]
        if (
            unit["stage"] == "qualification"
            and result.get("passed", 0) >= 10
            and result.get("protocol_valid") is True
        ):
            artifact = artifacts[unit["artifact_id"]]
            queue.add(
                make_units(
                    [artifact],
                    "capacity",
                    contexts=config["contexts"],
                    seeds=(101, 202, 303),
                    output_tokens=config["initial_output_tokens"],
                )
            )
            queue.add(
                make_units(
                    [artifact],
                    "development",
                    tasks=tuple(TASK_MAP),
                    seeds=(101,),
                    output_tokens=config["initial_output_tokens"],
                )
            )


def summarize(queue, config):
    rows = []
    latest = {r["unit_id"]: r for r in queue.records()}
    records = list(latest.values())
    for artifact_id in {r["unit"]["artifact_id"] for r in records}:
        own = [r for r in records if r["unit"]["artifact_id"] == artifact_id]
        qualifications = [r for r in own if r["unit"]["stage"] == "qualification"]
        dev = [r for r in own if r["unit"]["stage"] == "development"]
        capacities = [
            r
            for r in own
            if r["unit"]["stage"] == "capacity"
            and r["result"].get("context_verified") is True
        ]
        verified_contexts = [
            c
            for c in config["contexts"]
            if sum(r["unit"]["context"] == c for r in capacities) == 3
        ]
        if not qualifications:
            continue
        first = qualifications[0]
        valid_dev = len(dev) == 6 and all(
            r["result"]["status"] in {"complete", "model_failure"} for r in dev
        )
        peaks = [r["result"].get("peak_device_vram_mib") for r in own]
        peaks = [x for x in peaks if isinstance(x, (float, int))]
        rows.append(
            {
                "artifact_id": artifact_id,
                "model_id": first["unit"]["model_id"],
                "engine": first["unit"]["engine"],
                "protocol_ids": sorted(
                    {r.get("protocol_id", queue.protocol_id) for r in own}
                ),
                "qualification_passed": first["result"].get("passed", 0),
                "protocol_valid": valid_dev,
                "development_total": len(dev),
                "development_complete": sum(
                    r["result"].get("full_completion") is True for r in dev
                ),
                "median_seconds": statistics.median(r["result"]["seconds"] for r in dev)
                if valid_dev
                else None,
                "max_context": max(verified_contexts, default=0),
                "context_verified": bool(verified_contexts),
                "peak_vram_mib": max(peaks) if peaks else None,
            }
        )
    protocol_counts = {}
    for record in records:
        protocol_id = record.get("protocol_id", queue.protocol_id)
        protocol_counts[protocol_id] = protocol_counts.get(protocol_id, 0) + 1
    mixed_protocols = len(protocol_counts) > 1
    summary = {
        "scope": "quantization selection only; native harness comparison pending",
        "updated_at": now(),
        "records": len(records),
        "pending": len(queue.pending()),
        "resource_waiting": queue.state.get("resource_wait", {}),
        "protocol_cohorts": protocol_counts,
        "protocols_are_mixed": mixed_protocols,
        "protocol_note": (
            "Mixed protocol records are not a homogeneous benchmark; review cohorts separately."
            if mixed_protocols
            else "All records use one protocol."
        ),
        "artifacts": rows,
        "finalists": (
            {"status": "mixed_protocols_requires_review"}
            if mixed_protocols
            else choose_finalists(rows)
        ),
    }
    write_json(queue.output / "summary.json", summary)
    return summary


def resources_now():
    return {
        "gpu": gpu_free_mib(),
        "ram": ram_available_mib(),
        "disk": shutil.disk_usage(LAB).free,
    }


def resource_improved(current, previous):
    return (
        current["gpu"] >= previous["gpu"] + 256
        or current["ram"] >= previous["ram"] + 512
        or current["disk"] >= previous["disk"] + 1024**3
    )


def confirmed_server_oom(output):
    """Only classify an OOM if the server had exited before cleanup and reported it."""
    server = Path(output) / "server"
    try:
        exit_info = json.loads((server / "server-exit.json").read_text())
        code = exit_info.get("pre_cleanup_returncode")
        if type(code) is not int:
            return False
        log = (server / "server.log").read_text(errors="replace").lower()
        return any(text in log for text in (
            "out of memory", "cudamalloc failed", "not enough memory",
            "failed to allocate cuda",
        ))
    except (OSError, ValueError, TypeError):
        return False


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--catalog", type=Path, default=REPORT / "artifact-catalog-v2.json"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--recover-from",
        type=Path,
        help="seed a new protocol output from a stopped campaign state",
    )
    parser.add_argument(
        "--requeue-dns-failures",
        action="store_true",
        help="requeue only confirmed DNS-blocked infrastructure attempts in a new recovery output",
    )
    parser.add_argument(
        "--continue-pipeline",
        action="store_true",
        help="after quantization, start separately qualified native stage",
    )
    args = parser.parse_args()
    if args.requeue_dns_failures and args.recover_from is None:
        parser.error("--requeue-dns-failures requires --recover-from")
    config = json.loads(CONFIG.read_text())
    catalog = json.loads(args.catalog.read_text())
    validate_catalog(catalog)
    prerequisites()
    if args.recover_from is not None:
        seed_recovery_state(
            args.recover_from,
            args.output,
            config["protocol_id"],
            requeue_dns_failures=args.requeue_dns_failures,
        )
    else:
        args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "supervisor.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    global_lock = LAB / "state/qwen-optimization-gpu.lock"
    global_lock.parent.mkdir(exist_ok=True)
    gpu_lock = global_lock.open("a")
    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    recovery_origin = args.output / "recovery-origin.json"
    origin_path = recovery_origin if recovery_origin.is_file() else None
    immutable = frozen_inputs(args.catalog, config, origin_path)
    queue = Campaign(args.output, immutable)
    recover_owned_servers(args.output)
    artifacts = {a["artifact_id"]: a for a in catalog["artifacts"]}
    queue.add(
        make_units(
            ordered_artifacts(catalog["artifacts"]),
            "qualification",
            output_tokens=config["initial_output_tokens"],
        )
    )
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
    engines = json.loads((REPORT / "engines.json").read_text())
    while True:
        if frozen_inputs(args.catalog, config, origin_path) != immutable:
            raise RuntimeError(
                "frozen measurement source changed; refusing contaminated continuation"
            )
        if (args.output / "PAUSE").exists():
            queue.state["status"] = "paused_at_unit_boundary_for_offline_work"
            queue.save()
            time.sleep(15)
            continue
        extend_schedule(queue, artifacts, config)
        pending = queue.pending()
        if not pending:
            queue.state["status"] = "quantization_complete_native_harness_stage_pending"
            queue.save()
            summarize(queue, config)
            if args.continue_pipeline:
                ready = REPORT / "native-readiness.json"
                while (
                    not ready.exists()
                    or json.loads(ready.read_text()).get("passed") is not True
                ):
                    queue.state["status"] = (
                        "quantization_complete_waiting_for_native_stage_qualification"
                    )
                    queue.save()
                    time.sleep(30)
                return subprocess.call(
                    [
                        sys.executable,
                        "-m",
                        "benchmark.qwen_native_runner",
                        "--quant-output",
                        str(args.output),
                        "--execute",
                    ],
                    cwd=ROOT,
                )
            return 0
        resources = resources_now()
        waiting = queue.state.get("resource_wait", {})
        runnable = [
            u
            for u in pending
            if u["unit_id"] not in waiting
            or resource_improved(resources, waiting[u["unit_id"]])
        ]
        if not runnable:
            queue.state["status"] = "waiting_for_resources_with_preserved_pending_units"
            queue.save()
            summarize(queue, config)
            if args.once:
                return 0
            time.sleep(30)
            continue
        unit = runnable[0]
        artifact = artifacts[unit["artifact_id"]]
        gpu_policy = config.get("resource_limits", {})
        if eligible_artifact(artifact) is None and (
            gpu_free_mib() < gpu_policy.get("gpu_free_floor_mib", 7000)
            or ram_available_mib() < 1536
        ):
            queue.state["status"] = "waiting_for_resources"
            queue.save()
            time.sleep(30)
            continue
        unit_resources = resources_now()
        output = queue.begin(unit)
        unit_started = time.monotonic()
        try:
            result = measure(unit, artifact, catalog, output, engines, gpu_policy=gpu_policy)
        except (ModelBudgetExceeded, ModelBehaviorFailure) as exc:
            progress_path = output / "episode-progress.json"
            elapsed = (
                json.loads(progress_path.read_text())["seconds"]
                if progress_path.exists()
                else time.monotonic() - unit_started
            )
            result = {
                "status": "model_failure",
                "failure": "budget_exhausted"
                if isinstance(exc, ModelBudgetExceeded)
                else "model_no_progress",
                "error": str(exc),
                "full_completion": False,
                "seconds": elapsed,
                "seconds_scope": "task"
                if progress_path.exists()
                else "unit_including_setup",
            }
        except CapacityUnsupported as exc:
            result = {
                "status": "blocked",
                "failure": "fixed_profile_capacity_unavailable",
                "error": str(exc),
                "model_failure": False,
                "reason": "The engine could not satisfy the frozen memory policy or allocate this profile; inspect server evidence.",
            }
        except (ResourceUnavailable, ArtifactError) as exc:
            result = {
                "status": "resource_blocked"
                if isinstance(exc, ResourceUnavailable)
                else "blocked",
                "failure": "infrastructure",
                "error": str(exc),
                "model_failure": False,
            }
            if isinstance(exc, ResourceUnavailable):
                queue.wait_resources(unit, result, resources_now())
                summarize(queue, config)
                if args.once:
                    return 0
                continue
        except ModelProtocolError as exc:
            result = {
                "status": "blocked",
                "failure": "transport_or_configuration_review",
                "error": str(exc),
                "model_failure": False,
            }
            if confirmed_server_oom(output):
                result.update(failure="confirmed_server_oom", reason="Server exited and reported allocation failure")
            metrics_path = output / "client/metrics.json"
            metrics = (
                json.loads(metrics_path.read_text()) if metrics_path.exists() else []
            )
            if (
                not confirmed_server_oom(output)
                and any(
                    code in str(exc) for code in ("HTTP 502:", "HTTP 503:", "HTTP 504:")
                )
                and len(metrics) <= 1
                and not any(r.get("stream_complete") for r in metrics)
            ):
                queue.defer(unit, result)
                if args.once:
                    return 0
                time.sleep(2)
                continue
        except Exception as exc:
            result = {
                "status": "blocked",
                "failure": "unattributed_review",
                "error": f"{type(exc).__name__}: {exc}",
                "model_failure": False,
            }
            if confirmed_server_oom(output):
                result.update(failure="confirmed_server_oom", reason="Server exited and reported allocation failure")
        if result.get("status") == "resource_blocked":
            queue.wait_resources(unit, result, unit_resources)
        else:
            queue.finish(unit, result)
        summarize(queue, config)
        print(
            json.dumps(
                {
                    "unit": unit["unit_id"],
                    "artifact": artifact["artifact_id"],
                    "stage": unit["stage"],
                    "status": result["status"],
                    "at": now(),
                }
            ),
            flush=True,
        )
        if args.once:
            return 0


if __name__ == "__main__":

    def _stop(signum, frame):
        raise KeyboardInterrupt(
            "supervisor terminated; current attempt stays recoverable"
        )

    signal.signal(signal.SIGTERM, _stop)
    raise SystemExit(main())
