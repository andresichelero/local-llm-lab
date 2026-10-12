"""32-File Continuation Pilot for OpenCode 16K (Trilha B / Roadmap Tarefa 8).

Evaluates session stability and multi-file processing under 16K context:
- Baseline: raw prompt without intermediate state tracking.
- Intervened: structured compact checkpoint manifest recording visited file hashes and fingerprints.

Measures:
- Completed archive count (out of 32)
- Secret recovery key extraction (canary in archive-07.md)
- Wall-clock time and token consumption
- Deterministic verification via test_result.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.provenance import git_provenance  # noqa: E402

SECRET_KEY = "GLACIER-47-MAPLE"
EXPERIMENT = "continuation-pilot-20261012-trilha-b"
WORDS = ["amber", "birch", "cobalt", "delta", "ember", "frost", "granite", "harbor", "indigo", "juniper"]


def generate_fingerprints() -> list[str]:
    """Generates the 32 deterministic fingerprint strings."""
    return [
        hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper()
        for i in range(1, 33)
    ]


def generate_continuation_fixture(workspace: Path) -> None:
    """Generates the 32 archive files, test script, and instructions in workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    fingerprints = generate_fingerprints()

    for i in range(1, 33):
        lines: list[str] = []
        for j in range(28):
            a = WORDS[(i + j) % len(WORDS)]
            b = WORDS[(i * 3 + j * 2) % len(WORDS)]
            lines.append(
                f"Record {i}-{j}: {a} {b} {a}-{j} is a synthetic benchmark record used only "
                "to create deterministic repository context. Its value has no operational meaning. "
                "Verify indexes before using it."
            )
        lines.append(f"ARCHIVE FINGERPRINT: {fingerprints[i - 1]}. Record this exact value in the manifest.")
        if i == 7:
            lines.append(f"ARCHIVE RECOVERY KEY: {SECRET_KEY}. Preserve this exact value for the final verification.")

        content = f"# Archive {i}\n\n" + "\n".join(lines) + ("\n" if i == 7 else "") + "\n"
        (workspace / f"archive-{i:02d}.md").write_text(content, encoding="utf-8")

    (workspace / "README.md").write_text(
        "# Continuation Stress Fixture\n\nSynthetic archive files for local context continuation testing.\n",
        encoding="utf-8",
    )

    test_content = (
        "from pathlib import Path\n"
        "import unittest\n\n"
        "class ResultTests(unittest.TestCase):\n"
        "    def test_summary_exists(self):\n"
        "        p = Path(__file__).with_name('summary.md')\n"
        "        self.assertTrue(p.exists(), 'summary.md missing')\n"
        "        self.assertIn('archive_count: 32', p.read_text(encoding='utf-8'))\n\n"
        "    def test_manifest_has_every_fingerprint(self):\n"
        "        import hashlib\n"
        "        expected = [f'archive-{i:02d}=' + hashlib.sha256(f'pi-context-stress-2026|archive-{i:02d}'.encode()).hexdigest()[:12].upper() for i in range(1, 33)]\n"
        "        p = Path(__file__).with_name('archive_manifest.txt')\n"
        "        self.assertTrue(p.exists(), 'archive_manifest.txt missing')\n"
        "        self.assertEqual(p.read_text(encoding='utf-8').splitlines(), expected)\n\n"
        "    def test_recovery_key(self):\n"
        "        p = Path(__file__).with_name('recovery.txt')\n"
        "        self.assertTrue(p.exists(), 'recovery.txt missing')\n"
        f"        self.assertIn('{SECRET_KEY}', p.read_text(encoding='utf-8'))\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    (workspace / "test_result.py").write_text(test_content, encoding="utf-8")


def grade_continuation_workspace(workspace: Path) -> dict[str, Any]:
    """Grades the outputs in workspace against continuation contract."""
    manifest_path = workspace / "archive_manifest.txt"
    summary_path = workspace / "summary.md"
    recovery_path = workspace / "recovery.txt"

    expected_fps = generate_fingerprints()
    correct_manifest_count = 0

    if manifest_path.is_file():
        lines = [line.strip() for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        for idx, expected_fp in enumerate(expected_fps, start=1):
            expected_line = f"archive-{idx:02d}={expected_fp}"
            if any(line == expected_line for line in lines):
                correct_manifest_count += 1

    summary_valid = False
    if summary_path.is_file():
        content = summary_path.read_text(encoding="utf-8", errors="replace")
        summary_valid = "archive_count: 32" in content

    recovery_key_found = False
    if recovery_path.is_file():
        rec_content = recovery_path.read_text(encoding="utf-8", errors="replace")
        recovery_key_found = SECRET_KEY in rec_content

    test_passed = False
    test_file = workspace / "test_result.py"
    if test_file.is_file():
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "test_result.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        test_passed = res.returncode == 0

    success = correct_manifest_count == 32 and summary_valid and recovery_key_found and test_passed

    return {
        "success": success,
        "manifest_count": correct_manifest_count,
        "summary_valid": summary_valid,
        "recovery_key_found": recovery_key_found,
        "unit_tests_passed": test_passed,
    }


def summarize_continuation_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarizes metrics across continuation arms."""
    arms: dict[str, Any] = {}
    for arm in ("baseline", "checkpoint_manifest"):
        arm_recs = [r for r in records if r.get("arm") == arm]
        if not arm_recs:
            continue
        successes = [r for r in arm_recs if r.get("success")]
        manifest_counts = [r.get("manifest_count", 0) for r in arm_recs]
        recovery_found = [r for r in arm_recs if r.get("recovery_key_found")]
        walls = [r["task_wall_seconds"] for r in arm_recs if "task_wall_seconds" in r]
        vrams = [r["peak_vram_mib"] for r in arm_recs if "peak_vram_mib" in r and r["peak_vram_mib"] > 0]

        arms[arm] = {
            "trials": len(arm_recs),
            "success_count": len(successes),
            "success_pct": round(len(successes) / len(arm_recs) * 100, 1),
            "mean_manifest_count": round(statistics.mean(manifest_counts), 1) if manifest_counts else 0.0,
            "recovery_rate_pct": round(len(recovery_found) / len(arm_recs) * 100, 1),
            "median_wall_seconds": round(statistics.median(walls), 2) if walls else 0.0,
            "peak_vram_mib": max(vrams) if vrams else 0,
        }

    git_sha, dirty = git_provenance(REPO_ROOT)
    return {
        "experiment": EXPERIMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "source_dirty": dirty,
        "total_trials": len(records),
        "arms": arms,
    }


BENCHMARK_ROOT = Path(os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
SERVER_URL = "http://127.0.0.1:8080"
CONTEXT = 16384


def build_continuation_profile(model_alias: str = "Qwen3.5-9B-Q4_K_M") -> dict[str, Any]:
    """Generates an OpenCode profile pointing to local llama-server."""
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"local/{model_alias}",
        "small_model": f"local/{model_alias}",
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Local llama-server",
                "options": {
                    "baseURL": f"{SERVER_URL}/v1",
                },
                "models": {
                    model_alias: {
                        "name": model_alias,
                        "contextWindow": CONTEXT,
                        "maxTokens": 4096,
                    }
                },
            }
        },
        "permission": {
            "bash": "allow",
            "read": "allow",
            "edit": "allow",
        },
    }


def run_continuation_trial(
    binary: Path,
    install_root: Path,
    arm: str,
    pair_idx: int,
    output_root: Path,
    model_alias: str = "Qwen3.5-9B-Q4_K_M",
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Runs a single continuation trial under OpenCode."""
    output_root = output_root.resolve()
    run_dir = (output_root / "runs" / f"pair_{pair_idx:02d}_{arm}").resolve()
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    workspace = (run_dir / "workspace").resolve()
    generate_continuation_fixture(workspace)

    # Initialize fixture as a clean git repo
    subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Local LLM Lab", "-c", "user.email=lab@example.invalid", "commit", "--quiet", "-m", "fixture baseline"],
        cwd=workspace,
        check=True,
    )

    if arm == "checkpoint_manifest":
        init_state = {
            "total_archives": 32,
            "processed": [],
            "pending": [f"archive-{i:02d}.md" for i in range(1, 33)],
            "recovery_key_found": False,
        }
        (workspace / "checkpoint_state.json").write_text(json.dumps(init_state, indent=2) + "\n", encoding="utf-8")
        prompt = (
            "Inspect every file archive-01.md through archive-32.md using your tools. "
            "Maintain a compact progress checkpoint in archive_manifest.txt by recording each file's ARCHIVE FINGERPRINT "
            "as 'archive-NN=FINGERPRINT' immediately after inspecting each file, and recording your progress in checkpoint_state.json. "
            "Find the exact ARCHIVE RECOVERY KEY in archive-07.md and preserve it in recovery.txt. "
            "Include exactly archive_count: 32 in summary.md. "
            "Run python3 test_result.py and fix every mismatch. Do not claim completion unless the tests pass."
        )
    else:
        prompt = (
            "Inspect every file archive-01.md through archive-32.md using your tools. "
            "For each file, copy its exact ARCHIVE FINGERPRINT to archive_manifest.txt as one line archive-NN=FINGERPRINT, in numeric order. "
            "Find the exact ARCHIVE RECOVERY KEY in archive-07.md and preserve it in recovery.txt. "
            "Include exactly archive_count: 32 in summary.md. "
            "Run python3 test_result.py and fix every mismatch by inspecting the relevant archive. "
            "Do not claim completion unless the tests pass."
        )

    profile = build_continuation_profile(model_alias)
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    from benchmark.harness_runner import (
        _isolated_environment,
        _read_jsonl,
        summarize_resources,
        summarize_usage,
    )
    env = _isolated_environment("opencode", run_dir, install_root, workspace)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"

    event_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"

    command = [
        str(binary), "run", "--format", "json", "--agent", "build", "--model",
        f"local/{model_alias}", "--dir", str(workspace), prompt,
    ]

    task_start = time.monotonic()
    sampler_cmd = [
        sys.executable,
        str(REPO_ROOT / "benchmark/resource_sampler.py"),
        "--output", str(resource_path),
        "--interval", "0.5",
    ]
    sampler = subprocess.Popen(sampler_cmd, cwd=workspace, start_new_session=True)

    agent_proc = subprocess.Popen(
        command,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=event_path.open("w", encoding="utf-8"),
        stderr=stderr_path.open("w", encoding="utf-8"),
        start_new_session=True,
    )

    try:
        agent_proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        agent_proc.kill()
        agent_proc.wait()

    try:
        sampler.terminate()
        sampler.wait(timeout=2.0)
    except Exception:
        sampler.kill()

    task_wall = time.monotonic() - task_start
    events = _read_jsonl(event_path)
    res_rows = _read_jsonl(resource_path)
    res_summary = summarize_resources(res_rows)
    usage = summarize_usage("opencode", events)
    grade = grade_continuation_workspace(workspace)

    return {
        "arm": arm,
        "pair": pair_idx,
        "model": model_alias,
        "context": CONTEXT,
        "success": grade["success"],
        "manifest_count": grade["manifest_count"],
        "summary_valid": grade["summary_valid"],
        "recovery_key_found": grade["recovery_key_found"],
        "unit_tests_passed": grade["unit_tests_passed"],
        "task_wall_seconds": round(task_wall, 3),
        "steps": len([e for e in events if e.get("type") == "step_finish"]),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "peak_vram_mib": int(res_summary.get("vram_used_mb_peak", 0) or 0),
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCode 32-file Continuation Pilot")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--single-agent-release", action="store_true")
    parser.add_argument("--pairs", type=int, default=1, help="Number of baseline/checkpoint pairs (default: 1 for 6-min pilot)")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "results/raw/continuation-pilot-20261012")
    args = parser.parse_args()

    if not args.execute:
        print("[continuation-pilot] Dry run complete. Specify --execute and --single-agent-release to run.")
        return 0

    if not args.single_agent_release:
        print("[continuation-pilot] Error: --execute requires --single-agent-release.")
        return 1

    args.output_root = args.output_root.resolve()
    args.output_root.mkdir(parents=True, exist_ok=True)
    records_file = args.output_root / "records.jsonl"
    summary_file = args.output_root / "summary.json"

    install_root = Path.home() / "local-llm-benchmark"
    server_bin = install_root / "tools/llama-bin/llama-server"
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    if not binary.is_file():
        alt_binary = install_root / "tools/opencode-bin/opencode"
        if alt_binary.is_file():
            binary = alt_binary

    if not binary.is_file():
        raise FileNotFoundError(f"OpenCode binary not found at {binary}")

    from benchmark.cascade_routing_matrix import LlamaServerManager
    server_mgr = LlamaServerManager(server_bin, install_root, args.output_root)

    records: list[dict[str, Any]] = []
    print(f"[continuation-pilot] Starting OpenCode continuation pilot: {args.pairs} pairs across 32 files...")

    try:
        swap_time = server_mgr.ensure_model("qwen3.5-9b")
        print(f"[continuation-pilot] Qwen3.5-9B ready (ready in {swap_time:.2f}s, 16K context)")

        for pair_idx in range(1, args.pairs + 1):
            for arm in ("baseline", "checkpoint_manifest"):
                print(f"[continuation-pilot] Running Pair {pair_idx} Arm '{arm}'...")
                record = run_continuation_trial(
                    binary=binary,
                    install_root=install_root,
                    arm=arm,
                    pair_idx=pair_idx,
                    output_root=args.output_root,
                )
                records.append(record)
                with records_file.open("a", encoding="utf-8") as rf:
                    rf.write(json.dumps(record) + "\n")
                status = "PASS" if record["success"] else "FAIL"
                print(
                    f"[continuation-pilot] Pair {pair_idx} {arm}: {status} "
                    f"(manifest={record['manifest_count']}/32, recovery={record['recovery_key_found']}, "
                    f"wall={record['task_wall_seconds']:.1f}s, peak_vram={record['peak_vram_mib']}MiB)"
                )
    finally:
        server_mgr.stop()

    summary = summarize_continuation_results(records)
    summary_file.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[continuation-pilot] Completed {len(records)} trials. Summary written to {summary_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
