"""Authored-test regression quality, separated from mechanical test counts.

The graded authored sandbox still owns test presence: an episode keeps the
existing mechanical signals (suite passed, test count above baseline).  This
module adds the regression diagnosis from the design's ``Testes próprios``
section: the submitted tests must pass against the candidate's phase snapshot
and fail, with per-test failure evidence, against the original seed restored
into an isolated copy.

Decision table (one quality per phase):

- ``regression_detected``: the candidate suite ran and passed, and the same
  submitted suite, with only the original seed sources restored, failed with
  at least one per-test failure reported by the pinned runner.
- ``weak``: the restored seed also passes the submitted suite; the tests do
  not distinguish the stated regression from a full solution.
- ``not_applicable``: the task language carries no authored suite (mcp) or
  the submission added no tests beyond the baseline.
- ``unverified``: everything else — candidate or seed sandbox infrastructure,
  timeouts, missing or unsafe snapshots, import/setup failures (a seed run
  that collected zero tests), or a failing candidate suite whose severity a
  passing-on-seed comparison cannot interpret.

The diagnosis detects the single seeded regression named by the task; it is
not a statement about total test coverage, and a counted number of failed
seed assertions is never a ranking device.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from benchmark import practical_tasks_v2
from benchmark.linux_sandbox import ResourceLimits, RuntimeBind, SandboxSpec

REGRESSION_DETECTED = "regression_detected"
WEAK = "weak"
UNVERIFIED = "unverified"
NOT_APPLICABLE = "not_applicable"
QUALITIES = (REGRESSION_DETECTED, WEAK, UNVERIFIED, NOT_APPLICABLE)

# Per-test failure evidence as reported by the two pinned runners: TAP marks
# each failing subtest with a top-level ``not ok``; unittest records each
# failing or erroring test with a top-level ``FAIL:``/``ERROR:`` line.  Both
# marks are runner outcomes, never infrastructure text.
_FAILURE_EVIDENCE = (r"(?m)^not ok ", r"(?m)^FAIL: ", r"(?m)^ERROR: ")


def _collection_or_setup_failure(output: str) -> bool:
    """Framework collection/hooks do not demonstrate a regression assertion.

    Counted _FailedTest instances and hooks can increase the suite's count;
    that is not evidence that the submitted test body executed.
    """
    patterns = (
        r"unittest\.loader\._FailedTest",
        r"(?m)^ERROR:\s+(?:setUpClass|tearDownClass|setUpModule|tearDownModule)\b",
        r"(?m)^\s+File .*, in (?:setUp|tearDown|setUpClass|tearDownClass)\b",
        r"(?m)^(?:ModuleNotFoundError|ImportError):",
        r"\bcode:\s*['\"](?:MODULE_NOT_FOUND|ERR_MODULE_NOT_FOUND)['\"]",
        r"\bfailureType:\s*['\"]hookFailed['\"]",
    )
    return any(re.search(pattern, output) for pattern in patterns)

# Mirrors the graded authored-test sandbox from practical_runtime_v2 exactly
# (same argv, mounts, environment, and limits): the restored seed is judged on
# the same constrained box as the candidate suite.  A wiring test asserts the
# two sandbox specs stay identical, so drift between the copies is caught.
_SUCCESS_PRECEDENCE = {NOT_APPLICABLE: 0, REGRESSION_DETECTED: 1, WEAK: 2, UNVERIFIED: 3}


def _runtime_module():
    """Lazy runtime import: tests patch ``runtime.SandboxSupervisor`` and the
    two modules keep a one-directional import graph at load time."""
    from benchmark import practical_runtime_v2 as runtime_module

    return runtime_module


def _suite_bounds(task: str) -> tuple[tuple[str, ...], tuple[RuntimeBind, ...], str, int]:
    language = practical_tasks_v2.TASK_SPECS[task]["language"]
    if language == "javascript":
        argv = ("/opt/node/bin/node", "--test", "--test-reporter=tap")
        runtime_binds = (
            RuntimeBind(_runtime_module().NODE_ROOT.resolve(strict=True), "/opt/node"),)
        count_pattern = r"(?:^|\n)#\s+tests\s+(\d+)(?:\n|$)|\u2139\s+tests\s+(\d+)"
        baseline = 1 if task in {"B2", "M1", "D2"} else 0
    elif language == "mcp":
        raise ValueError("mcp tasks carry no authored test suite")
    else:
        argv = ("/usr/bin/python3", "-B", "-m", "unittest", "discover", "-s", "tests")
        runtime_binds = ()
        count_pattern = r"Ran\s+(\d+)\s+tests?"
        baseline = 1 if task in {"B1", "C1", "D1", "H1"} else 0
    return argv, runtime_binds, count_pattern, baseline


def run_seed_suite(task: str, workspace: Path, *, lab: Path) -> dict[str, Any]:
    """Run the submitted suite on a restored seed with the graded sandbox."""
    runtime_module = _runtime_module()
    argv, runtime_binds, count_pattern, baseline = _suite_bounds(task)
    result = runtime_module.SandboxSupervisor().run(SandboxSpec(
        argv=argv, workspace=workspace,
        runtime_ro=tuple(runtime_module.campaign_readiness._runtime_binds()) + runtime_binds,
        env={"PYTHONDONTWRITEBYTECODE": "1"}, limits=_suite_limits()))
    text = result.output.decode("utf-8", errors="replace")
    matches = re.search(count_pattern, text)
    count = int(next((group for group in matches.groups() if group), "0")) if matches else 0
    return {"suite_passed": bool(result.returncode == 0 and not result.timed_out and count > 0),
            "count": count, "baseline_count": baseline,
            "additional_count": max(0, count - baseline),
            "returncode": result.returncode, "timed_out": result.timed_out,
            "cleanup_verified": result.cleanup_verified,
            "infrastructure": bool(result.infrastructure_error or not result.cleanup_verified),
            "reason": result.infrastructure_error,
            "output": text[-8000:]}


def _suite_limits() -> ResourceLimits:
    """Identical limits to the graded authored sandbox (see wiring test)."""
    return ResourceLimits(memory_bytes=768 * 1024**2, swap_bytes=256 * 1024**2,
                          cpu_quota_percent=100, cpu_seconds=25, pids=48, wall_seconds=30,
                          output_bytes=64 * 1024, workspace_bytes=256 * 1024**2,
                          workspace_files=5000, workspace_file_bytes=64 * 1024**2,
                          scratch_bytes=128 * 1024**2, file_bytes=64 * 1024**2,
                          open_files=256, export_file_bytes=2 * 1024**2,
                          export_total_bytes=2 * 1024**2, rootfs_bytes=32 * 1024**2,
                          startup_seconds=10, stop_grace_seconds=2)


def make_assessment(task: str, quality: str, reason: str, *,
                    candidate: Mapping[str, Any] | None = None,
                    seed: Mapping[str, Any] | None = None,
                    provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One authored-test quality verdict with its separate observations."""
    if quality not in QUALITIES:
        raise ValueError(f"unknown authored-test quality {quality!r}")
    return {"task": task, "quality": quality, "reason": reason,
            "candidate": candidate, "seed": seed,
            "provenance": provenance if provenance is not None
            else {"snapshot_sha256": None, "restored_seed_sha256": {}}}


def aggregate_qualities(qualities) -> str:
    """Dependency-conservative episode aggregate over per-phase qualities.

    A single unverified phase caps the whole verdict at ``unverified``: the
    episode only claims the quality every phase measurement supports.  Items
    outside the known vocabulary (including ``None``) count as ``unverified``
    rather than being silently dropped, and an empty sequence is
    ``not_applicable``.
    """
    values = [quality if quality in QUALITIES else UNVERIFIED for quality in qualities]
    if not values:
        return NOT_APPLICABLE
    return max(values, key=_SUCCESS_PRECEDENCE.get)


def assess_authored_regression(task: str, snapshot_path: Path, *, lab: Path,
                               candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assess whether the submitted suite detects the task's stated regression.

    ``candidate`` is the graded authored-suite result of the same phase (the
    ``authored_tests`` entry from ``_phase_grade``).  Nothing is ever restored
    into the caller's inputs: the snapshot is copied to a temporary workspace
    and only the stated seed sources are overwritten there, with the suite
    files kept exactly as submitted.
    """
    language = practical_tasks_v2.TASK_SPECS[task]["language"]
    if language == "mcp":
        return make_assessment(task, NOT_APPLICABLE, "mcp tasks carry no authored test suite")
    if candidate is None:
        return make_assessment(task, UNVERIFIED, "no authored-test result for this phase")
    candidate = dict(candidate)
    baseline = int(candidate.get("baseline_count") or 0)
    count = int(candidate.get("count") or 0)
    if count <= baseline:
        return make_assessment(task, NOT_APPLICABLE, "no authored tests beyond the baseline",
                               candidate=candidate)
    if candidate.get("infrastructure"):
        return make_assessment(task, UNVERIFIED, "candidate suite sandbox infrastructure error",
                               candidate=candidate)
    suite_passed = candidate.get("suite_passed", candidate.get("passed"))
    if candidate.get("timed_out") or not suite_passed:
        return make_assessment(
            task, UNVERIFIED,
            "candidate suite did not pass; a failing suite cannot be scored for regression",
            candidate=candidate)
    snapshot = Path(snapshot_path)
    try:
        raw = snapshot.read_bytes()
    except OSError:
        return make_assessment(task, UNVERIFIED, "phase snapshot unavailable",
                               candidate=candidate)
    provenance = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                  "restored_seed_sha256": {}}
    runtime_module = _runtime_module()
    with tempfile.TemporaryDirectory(prefix="practical-v2-seedcheck-") as temporary:
        workspace = Path(temporary) / "seed-state"
        try:
            runtime_module._safe_extract_snapshot(raw, workspace)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            return make_assessment(task, UNVERIFIED,
                                   f"snapshot restore failed: {type(exc).__name__}",
                                   candidate=candidate, provenance=provenance)
        for name, content in practical_tasks_v2.seed_sources(task).items():
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            provenance["restored_seed_sha256"][name] = hashlib.sha256(
                target.read_bytes()).hexdigest()
        seed = run_seed_suite(task, workspace, lab=lab)
    if seed["infrastructure"]:
        return make_assessment(task, UNVERIFIED, "seed suite sandbox infrastructure error",
                               candidate=candidate, seed=seed, provenance=provenance)
    if seed["timed_out"]:
        return make_assessment(task, UNVERIFIED, "seed suite timed out",
                               candidate=candidate, seed=seed, provenance=provenance)
    if seed["returncode"] == 0:
        return make_assessment(task, WEAK,
                               "submitted suite passes on the restored original seed too",
                               candidate=candidate, seed=seed, provenance=provenance)
    if seed["count"] <= 0:
        return make_assessment(task, UNVERIFIED,
                               "seed run collected no tests; import or setup failure",
                               candidate=candidate, seed=seed, provenance=provenance)
    if _collection_or_setup_failure(seed["output"]):
        return make_assessment(task, UNVERIFIED,
                               "seed suite failed during import, collection or setup",
                               candidate=candidate, seed=seed, provenance=provenance)
    if not any(re.search(pattern, seed["output"]) for pattern in _FAILURE_EVIDENCE):
        return make_assessment(task, UNVERIFIED,
                               "seed failure without per-test failure evidence",
                               candidate=candidate, seed=seed, provenance=provenance)
    return make_assessment(task, REGRESSION_DETECTED,
                           "submitted suite fails on the restored original seed only",
                           candidate=candidate, seed=seed, provenance=provenance)

