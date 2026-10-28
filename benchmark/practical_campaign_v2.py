"""Deterministic, resumable scheduler for the practical-agent v2 campaign."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import signal
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
LAB = Path("/home/foxtrot/local-llm-benchmark")
from benchmark.practical_evidence import mechanical_success  # noqa: E402
DEFAULT_OUTPUT = LAB / "results/practical-selection-v2-tool-review-v1"
PROTOCOL = "practical-agent-limits-skills-v8"
DEFAULT_GPU_FREE_FLOOR_MIB = 7168
MIN_GPU_FREE_FLOOR_MIB = 7000
TASKS = ("B1", "B2", "C1", "C2", "M1", "M2", "D1", "D2")
HOLDOUTS = ("H1", "H2")
CORE_TASKS = TASKS[:6]
HARD_TASKS = TASKS[6:]
REPETITIONS = (1, 2, 3)
REPETITION_SEEDS = {1: 101, 2: 202, 3: 303}
BASELINE_PROFILE = {"id": "baseline", "context_tokens": 16384, "cache_prompt": False}

FROZEN_PROTOCOL = {
    "context_tokens": 16384,
    "max_output_tokens": 4096,
    "temperature": 0.2,
    "top_p": 0.95,
    "repetition_seeds": REPETITION_SEEDS,
    "kv_cache_type": "q4_0",
    "flash_attention": True,
    "slots_per_model": 1,
    "reasoning": False,
    "speculation": False,
    "baseline_prompt_cache": False,
    "opencode_input_limit_explicit": True,
    "compaction_reserved_tokens": 6144,
    "tool_output_max_bytes": 6000,
    "tool_output_max_lines": 200,
    "phase_deadline_shared": True,
    "phase_one_deadline_fraction_max": 0.45,
}


class CampaignBlocked(RuntimeError):
    """Raised internally when execution must stop while preserving its state."""


def _canonical(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "size_bytes": len(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted((_jsonable(item) for item in value), key=_canonical)
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _rotate(values: Sequence[Any], offset: int) -> tuple[Any, ...]:
    items = tuple(values)
    if not items:
        return items
    offset %= len(items)
    return items[offset:] + items[:offset]


def profile_catalog(*, context_32k_cache_prompt: bool) -> dict[str, dict[str, Any]]:
    """Return the only approved profile variants, with the selected cache setting."""
    return {
        "baseline": dict(BASELINE_PROFILE),
        "cache_on": {"id": "cache_on", "context_tokens": 16384, "cache_prompt": True},
        "context_32k": {
            "id": "context_32k",
            "context_tokens": 32768,
            "cache_prompt": bool(context_32k_cache_prompt),
        },
    }


def _profile_id(profile: str | Mapping[str, Any]) -> str:
    if isinstance(profile, str):
        return profile
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("profile must include a non-empty id")
    return profile_id


def episode_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, int]:
    """Full identity prevents collisions across protocols and profiles."""
    repetition = row.get("repetition")
    if not isinstance(repetition, int) or isinstance(repetition, bool):
        raise ValueError("repetition must be an integer")
    required = ("protocol", "model", "task")
    if any(not isinstance(row.get(field), str) or not row[field] for field in required):
        raise ValueError("episode identity is incomplete")
    return (row["protocol"], row["model"], _profile_id(row.get("profile")), row["task"], repetition)


def ensure_unique_records(rows: Iterable[Mapping[str, Any]]) -> None:
    seen = set()
    for row in rows:
        key = episode_key(row)
        if key in seen:
            raise ValueError(f"duplicate episode identity: {key}")
        seen.add(key)


def _episode(
    model: str,
    task: str,
    repetition: int,
    profile: str | Mapping[str, Any],
    *,
    stage: str,
    protocol: str,
) -> dict[str, Any]:
    profile_id = _profile_id(profile)
    config = dict(profile) if isinstance(profile, Mapping) else None
    row = {
        "protocol": protocol,
        "model": model,
        "profile": profile_id,
        "task": task,
        "repetition": repetition,
        "generation_seed": REPETITION_SEEDS[repetition],
        "stage": stage,
    }
    if config is not None:
        row["profile_config"] = config
    return row


def baseline_schedule(
    models: Sequence[str],
    *,
    tasks: Sequence[str] = TASKS,
    protocol: str | None = None,
    task_contracts: Mapping[str,str] | None = None,
) -> list[dict[str, Any]]:
    """Build the 3-pass baseline matrix, rotating both task and model order."""
    protocol = protocol or PROTOCOL
    model_list, task_list = tuple(models), tuple(tasks)
    if not model_list or len(set(model_list)) != len(model_list):
        raise ValueError("models must be non-empty and unique")
    if not task_list or len(set(task_list)) != len(task_list):
        raise ValueError("tasks must be non-empty and unique")
    rows = []
    for repetition in REPETITIONS:
        for task in _rotate(task_list, repetition - 1):
            for model in _rotate(model_list, repetition - 1):
                episode=_episode(model, task, repetition, BASELINE_PROFILE,
                                 stage="baseline", protocol=protocol)
                if task_contracts is not None:
                    episode['task_contract_id']=task_contracts[task]
                rows.append(episode)
    ensure_unique_records(rows)
    return rows


def tuning_schedule(
    finalists: Sequence[str],
    profile: Mapping[str, Any] | Mapping[str, Mapping[str, Any]],
    *,
    tasks: Sequence[str] = HARD_TASKS,
    stage: str = "tuning",
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Schedule one tuning profile on D1/D2 for two finalists, three repeats."""
    protocol = protocol or PROTOCOL
    final_list, task_list = tuple(finalists), tuple(tasks)
    if len(final_list) != 2 or len(set(final_list)) != 2:
        raise ValueError("tuning requires exactly two distinct finalists")
    if "id" in profile:
        profile_by_model = {model: profile for model in final_list}
    else:
        profile_by_model = dict(profile)
        if set(profile_by_model) != set(final_list):
            raise ValueError("each finalist needs a tuning profile")
    if any(_profile_id(item) not in {"cache_on", "context_32k"} for item in profile_by_model.values()):
        raise ValueError("tuning profile must be cache_on or context_32k")
    if task_list != HARD_TASKS and set(task_list) != set(HARD_TASKS):
        raise ValueError("tuning is restricted to D1/D2")
    rows = []
    for repetition in REPETITIONS:
        for task in _rotate(task_list, repetition - 1):
            for model in _rotate(final_list, repetition - 1):
                rows.append(_episode(model, task, repetition, profile_by_model[model],
                                     stage=stage, protocol=protocol))
    ensure_unique_records(rows)
    return rows


def holdout_schedule(
    finalists: Sequence[str],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    tasks: Sequence[str] = HOLDOUTS,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Build holdouts separately, preserving the selected profile per finalist."""
    protocol = protocol or PROTOCOL
    final_list, task_list = tuple(finalists), tuple(tasks)
    if len(final_list) != 2 or len(set(final_list)) != 2:
        raise ValueError("holdouts require exactly two distinct finalists")
    if set(task_list) != set(HOLDOUTS):
        raise ValueError("holdouts are restricted to H1/H2")
    if set(profiles) != set(final_list):
        raise ValueError("each finalist needs exactly one selected profile")
    rows = []
    for repetition in REPETITIONS:
        for task in _rotate(task_list, repetition - 1):
            for model in _rotate(final_list, repetition - 1):
                rows.append(_episode(model, task, repetition, profiles[model],
                                     stage="holdout", protocol=protocol))
    ensure_unique_records(rows)
    return rows


def _resource(row: Mapping[str, Any], name: str) -> float | None:
    direct = row.get(name)
    if isinstance(direct, (int, float)):
        return float(direct)
    peaks = row.get("resource_peaks") or {}
    if isinstance(peaks, Mapping):
        value = peaks.get(name)
        if value is None and name == "vram_mib":
            value = peaks.get("vram_used_mb")
        if isinstance(value, Mapping):
            value = value.get("value")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _terminal(row: Mapping[str, Any]) -> bool:
    return row.get("status") == "complete"


def _review_tasks(rows):
    return {row.get("task") for row in rows if row.get("review_required")
            or row.get("status") in {"review_required", "skipped_review"}}


def _scorable_rows(rows):
    excluded = _review_tasks(rows)
    return [row for row in rows if row.get("task") not in excluded]


def rank_models(
    rows: Sequence[Mapping[str, Any]],
    models: Sequence[str],
    *,
    metric_tasks: Sequence[str] = CORE_TASKS,
    required_tasks: Sequence[str] = TASKS,
    repetitions: Sequence[int] = REPETITIONS,
    profile: str = "baseline",
) -> list[dict[str, Any]]:
    """Rank baseline models by core completions, 3/3 tasks, time, then VRAM."""
    ensure_unique_records(rows)
    rows = _scorable_rows(rows)
    ranked = []
    for model in models:
        selected = [row for row in rows if row.get("model") == model and row.get("profile") == profile]
        by_task_repeat = {
            (row.get("task"), row.get("repetition")): row
            for row in selected
            if _terminal(row)
        }
        expected = {(task, repetition) for task in required_tasks for repetition in repetitions}
        covered = expected.intersection(by_task_repeat)
        coverage_complete = covered == expected
        core_rows = [
            row for row in selected
            if row.get("task") in metric_tasks and row.get("repetition") in repetitions
            and row.get("status") not in {"interrupted", "pending"}
        ]
        completed = sum(mechanical_success(row) for row in core_rows)
        core_3_of_3 = sum(
            all(
                (row := by_task_repeat.get((task, repetition))) is not None
                and mechanical_success(row)
                for repetition in repetitions
            )
            for task in metric_tasks
        )
        elapsed = round(sum(float(row.get("seconds") or 0) for row in core_rows), 3)
        resource_rows = [row for row in selected if row.get("status") not in {"interrupted", "pending"}]
        vram_values = [value for row in resource_rows if (value := _resource(row, "vram_mib")) is not None]
        ranked.append({
            "model": model,
            "core_completed": completed,
            "core_3_of_3": core_3_of_3,
            "core_elapsed_seconds": elapsed,
            "vram_mib": max(vram_values) if vram_values else None,
            "coverage_count": len(covered),
            "coverage_expected": len(expected),
            "coverage_complete": coverage_complete,
            "eligible": coverage_complete,
        })
    return sorted(ranked, key=lambda item: (
        not item["eligible"], -item["core_completed"], -item["core_3_of_3"],
        item["core_elapsed_seconds"], item["vram_mib"] if item["vram_mib"] is not None else math.inf,
    ))


def select_finalists(
    core_ranking: Sequence[Mapping[str, Any]],
    hard_ranking: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Use the core leader and the hard leader, falling back to core rank 2."""
    core = [str(item["model"]) for item in core_ranking if item.get("eligible")]
    if not core:
        return []
    primary = core[0]
    hard = [str(item["model"]) for item in hard_ranking if item.get("eligible")]
    alternate = next((model for model in hard if model != primary), None)
    if alternate is None:
        alternate = next((model for model in core[1:] if model != primary), None)
    return [primary] + ([alternate] if alternate else [])


def rank_profiles(
    rows: Sequence[Mapping[str, Any]],
    models: Sequence[str],
    profile_ids: Sequence[str],
    *,
    tasks: Sequence[str] = HARD_TASKS,
    repetitions: Sequence[int] = REPETITIONS,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Compare profiles only on shared D1/D2 episodes and full coverage."""
    protocol = protocol or PROTOCOL
    ensure_unique_records(rows)
    rows = _scorable_rows(rows)
    result = []
    expected = {(model, task, repetition) for model in models for task in tasks for repetition in repetitions}
    for profile_id in profile_ids:
        selected = [
            row for row in rows
            if row.get("protocol") == protocol and row.get("profile") == profile_id
            and row.get("model") in models and row.get("task") in tasks
            and row.get("repetition") in repetitions and _terminal(row)
        ]
        covered = {(row["model"], row["task"], row["repetition"]) for row in selected}
        vram = [value for row in selected if (value := _resource(row, "vram_mib")) is not None]
        result.append({
            "profile": profile_id,
            "completed": sum(mechanical_success(row) for row in selected),
            "elapsed_seconds": round(sum(float(row.get("seconds") or 0) for row in selected), 3),
            "vram_mib": max(vram) if vram else None,
            "coverage_count": len(covered),
            "coverage_expected": len(expected),
            "eligible": covered == expected,
        })
    return sorted(result, key=lambda item: (
        not item["eligible"], -item["completed"], item["elapsed_seconds"],
        item["vram_mib"] if item["vram_mib"] is not None else math.inf,
    ))


def select_profile(
    rows: Sequence[Mapping[str, Any]],
    models: Sequence[str],
    profile_ids: Sequence[str],
    *,
    tasks: Sequence[str] = HARD_TASKS,
    repetitions: Sequence[int] = REPETITIONS,
) -> str:
    ranked = rank_profiles(rows, models, profile_ids, tasks=tasks, repetitions=repetitions)
    winner = next((item["profile"] for item in ranked if item["eligible"]), None)
    if winner is None:
        raise ValueError("no profile has complete coverage for the requested episodes")
    return winner


def select_profiles_per_model(
    rows: Sequence[Mapping[str, Any]],
    models: Sequence[str],
    profile_ids: Sequence[str] | Mapping[str, Sequence[str]],
    *,
    tasks: Sequence[str] = HARD_TASKS,
) -> dict[str, str]:
    return {
        model: select_profile(
            rows, (model,), profile_ids[model] if isinstance(profile_ids, Mapping) else profile_ids,
            tasks=tasks,
        )
        for model in models
    }


def atomic_write_json(path: Path, value: Any) -> None:
    """Persist JSON by replacement so a crash cannot leave a partial document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(_jsonable(value), stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def atomic_write_text(path: Path, value: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _difficulty(tasks_module: Any, task: str) -> str:
    if task in HOLDOUTS:
        return "holdout"
    spec = tasks_module.TASK_SPECS.get(task, {})
    return str(spec.get("difficulty", "holdout" if task in HOLDOUTS else "unknown")).lower()


def _model_artifact_summary(items: Sequence[Mapping[str, Any]], model: str) -> dict[str, Any]:
    contract = next((row.get("model_contract") for row in items
                     if isinstance(row.get("model_contract"), Mapping)), {})
    artifact = next((row.get("artifact_identity") for row in reversed(items)
                     if isinstance(row.get("artifact_identity"), Mapping)), {})
    basename = Path(str(contract.get("path", ""))).name or None
    model_sha = contract.get("sha256") or artifact.get("model_sha256")
    quantization = contract.get("quantization") or contract.get("quantization_type")
    if not quantization:
        haystack = " ".join(str(value) for value in (
            contract.get("alias", ""), contract.get("path", ""), model,
        ))
        match = re.search(
            r"(?i)(IQ\d+_[A-Z0-9_]+|Q\d+_K_[A-Z0-9]+|Q\d+_[A-Z0-9]+|q\d+_\d+|fp\d+|bf16|f16)",
            haystack,
        )
        quantization = match.group(0).upper() if match else "unspecified"
    return {
        "model_artifact_basename": basename,
        "model_sha256": model_sha,
        "quantization": str(quantization),
    }


def _summary_rows(rows: Sequence[Mapping[str, Any]], tasks_module: Any) -> list[dict[str, Any]]:
    difficulty_names = ("basic", "everyday", "medium", "hard", "holdout")
    rows = _scorable_rows(rows)
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("stage", "")), str(row.get("profile", "")),
                           str(row.get("model", ""))), []).append(row)
    summaries = []
    for (stage, profile_id, model), items in sorted(groups.items()):
        measured = [row for row in items if row.get("status") != "pending"]
        finished = [row for row in measured if row.get("status") in {"complete", "blocked", "interrupted"}]
        successful = [row for row in finished
                      if mechanical_success(row)]
        summary: dict[str, Any] = {
            "stage": stage,
            "profile": profile_id,
            "model": model,
            "episodes_attempted": len(measured),
            "episodes_completed": sum(row.get("status") == "complete" for row in items),
            "correct_autonomous": len(successful),
            # functional_correct counts only recorded verdicts; legacy rows
            # missing the field are exported as unverified, never inferred.
            "functional_correct": sum(row.get("functional_correct") is True
                                      for row in finished),
            "functional_correct_evaluated": sum(
                type(row.get("functional_correct")) is bool for row in finished),
            "authored_tests_passed": sum(row.get("authored_tests_passed") is True for row in finished),
            "authored_tests_evaluated": sum(type(row.get("authored_tests_passed")) is bool
                                           for row in finished),
            "agent_finished": sum(row.get("agent_finished") is True for row in finished),
            "agent_finished_evaluated": sum(type(row.get("agent_finished")) is bool for row in finished),
            "autonomous_count": sum(bool(row.get("autonomous")) for row in finished),
        }
        for difficulty in difficulty_names:
            tasks_at_level = {
                task for task in tasks_module.TASK_SPECS
                if _difficulty(tasks_module, task) == difficulty
            }
            level_rows = [row for row in finished if row.get("task") in tasks_at_level]
            summary[f"{difficulty}_completed"] = sum(
                mechanical_success(row)
                for row in level_rows
            )
            summary[f"{difficulty}_episodes"] = len(level_rows)
            successful_tasks = 0
            for task in tasks_at_level:
                repetitions = [
                    row for row in level_rows
                    if row.get("task") == task and row.get("status") == "complete"
                ]
                by_repeat = {row.get("repetition"): row for row in repetitions}
                if all(
                    repetition in by_repeat
                    and mechanical_success(by_repeat[repetition])
                    for repetition in REPETITIONS
                ):
                    successful_tasks += 1
            summary[f"{difficulty}_3_of_3"] = successful_tasks
        durations = [float(row.get("seconds") or 0) for row in measured]
        successful_durations = [
            float(row.get("seconds") or 0)
            for row in finished
            if row.get("status") == "complete" and mechanical_success(row)
        ]
        summary["all_time_seconds"] = round(sum(durations), 3)
        summary["median_episode_seconds"] = round(statistics.median(durations), 3) if durations else None
        summary["median_success_seconds"] = (
            round(statistics.median(successful_durations), 3) if successful_durations else None
        )
        summary["tasks_3_of_3"] = sum(
            summary[f"{difficulty}_3_of_3"] for difficulty in difficulty_names
        )
        summary["tool_errors"] = sum(int(row.get("tool_errors") or 0) for row in measured)
        for metric in ("expected_tool_errors", "avoidable_tool_errors", 'model_tool_errors',
                       'infrastructure_tool_errors', 'unattributed_tool_errors'):
            known = [row.get(metric) for row in measured if type(row.get(metric)) is int]
            summary[metric] = sum(known) if known else None
        summary["model_calls"] = sum(int(row.get("model_calls") or 0) for row in measured)
        for category in ('main', 'title', 'compaction', 'unknown'):
            summary[f'model_calls_{category}'] = sum(
                int(row.get('model_call_breakdown', {}).get(category, 0)) for row in measured)
        for metric in ("vram_mib", "ram_mib"):
            values = [value for row in measured if (value := _resource(row, metric)) is not None]
            summary[metric] = max(values) if values else None
        configs = [row.get("profile_config") for row in items if isinstance(row.get("profile_config"), Mapping)]
        config = dict(configs[-1]) if configs else {}
        summary["context_tokens"] = config.get("context_tokens")
        summary["cache_prompt"] = config.get("cache_prompt")
        summary["max_output_tokens"] = FROZEN_PROTOCOL["max_output_tokens"]
        summary["kv_cache_type"] = FROZEN_PROTOCOL["kv_cache_type"]
        summary["flash_attention"] = FROZEN_PROTOCOL["flash_attention"]
        summary.update(_model_artifact_summary(items, model))
        summary["config_artifact_identity"] = _canonical({
            "model_artifact_basename": summary["model_artifact_basename"],
            "model_sha256": summary["model_sha256"],
            "quantization": summary["quantization"],
            "profile_config": config,
            "max_output_tokens": summary["max_output_tokens"],
            "kv_cache_type": summary["kv_cache_type"],
            "flash_attention": summary["flash_attention"],
        })
        summaries.append(summary)
    return summaries


def _write_summaries(output: Path, rows: Sequence[Mapping[str, Any]], tasks_module: Any) -> None:
    summaries = _summary_rows(rows, tasks_module)
    fields = [
        "stage", "profile", "model", "episodes_attempted", "episodes_completed", "correct_autonomous",
        "basic_completed", "everyday_completed", "medium_completed", "hard_completed", "holdout_completed",
        "basic_3_of_3", "everyday_3_of_3", "medium_3_of_3", "hard_3_of_3", "holdout_3_of_3",
        "tasks_3_of_3", "autonomous_count", "all_time_seconds", "median_episode_seconds",
        "median_success_seconds", "tool_errors", "expected_tool_errors", "avoidable_tool_errors",
        'model_tool_errors', 'infrastructure_tool_errors', 'unattributed_tool_errors',
        'model_calls_main', 'model_calls_title', 'model_calls_compaction', 'model_calls_unknown',
        "functional_correct", "authored_tests_passed", "authored_tests_evaluated",
        "agent_finished", "agent_finished_evaluated", "model_calls", "vram_mib", "ram_mib",
        "model_artifact_basename", "model_sha256", "quantization", "context_tokens", "cache_prompt",
        "max_output_tokens", "kv_cache_type", "flash_attention", "config_artifact_identity",
    ]
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(summaries)
    atomic_write_text(output / "summary.csv", csv_buffer.getvalue())

    columns = (
        ("model", "Model"), ("profile", "Profile"), ("stage", "Stage"),
        ("basic_fraction", "Basic"), ("everyday_fraction", "Everyday"),
        ("medium_fraction", "Medium"), ("hard_fraction", "Hard"),
        ("holdout_fraction", "Holdout"), ("tasks_3_of_3", "Tasks 3/3"),
        ("functional_fraction", "Functional correct"), ("total_fraction", "Correct and autonomous"),
        ("authored_fraction", "Own tests passed"), ("finished_fraction", "Agent finished"),
        ("median_success_seconds", "Median success s"),
        ("tool_errors", "Raw tool errors"), ("expected_tool_errors", "Expected recovery errors"),
        ("avoidable_tool_errors", "Other tool errors"), ("memory_mib", "VRAM/RAM MiB"),
        ("model_artifact", "Model artifact"),
        ("profile_config", "Context/cache/output/quant"),
    )
    lines = ["# Practical agent v2 campaign results", "", "| " + " | ".join(label for _, label in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for summary in summaries:
        values = []
        for key, _label in columns:
            if key == "functional_fraction":
                value = f"{summary['functional_correct']}/{summary['episodes_attempted']}"
            elif key == "authored_fraction":
                known = summary["authored_tests_evaluated"]
                value = f"{summary['authored_tests_passed']}/{known}" if known else "n/a"
            elif key == "finished_fraction":
                known = summary["agent_finished_evaluated"]
                value = f"{summary['agent_finished']}/{known}" if known else "n/a"
            elif key == "total_fraction":
                value = f"{summary['correct_autonomous']}/{summary['episodes_attempted']}"
            elif key.endswith("_fraction"):
                difficulty = key[:-9]
                value = f"{summary[f'{difficulty}_completed']}/{summary[f'{difficulty}_episodes']}"
            elif key == "memory_mib":
                vram, ram = summary.get("vram_mib"), summary.get("ram_mib")
                value = f"{vram if vram is not None else ''}/{ram if ram is not None else ''}"
            elif key == "profile_config":
                cache = "cache-on" if summary.get("cache_prompt") is True else "cache-off"
                value = (f"{summary.get('context_tokens')}/{cache}/"
                         f"{summary.get('max_output_tokens')}/{summary.get('kv_cache_type')}/"
                         f"{summary.get('quantization')}")
            elif key == "model_artifact":
                basename = summary.get("model_artifact_basename") or "unknown artifact"
                digest = summary.get("model_sha256")
                value = f"{basename} {str(digest)[:12] if digest else 'no-sha'}"
            else:
                value = summary.get(key)
            rendered = "" if value is None else str(value)
            rendered = rendered.replace("|", "\\|").replace("\n", " ")
            values.append(rendered)
        lines.append("| " + " | ".join(values) + " |")
    atomic_write_text(output / "summary.md", "\n".join(lines) + "\n")


def _write_status(output: Path, manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], latest: Mapping[str, Any] | None = None) -> None:
    by_stage = {}
    stages = tuple(dict.fromkeys(("baseline", "cache_on", "context_32k", "holdout",
                                  *manifest.get("stage_status", {}).keys())))
    for stage in stages:
        stage_rows = [row for row in rows if row.get("stage") == stage]
        by_stage[stage] = {
            "records": len(stage_rows),
            "complete": sum(row.get("status") == "complete" for row in stage_rows),
            "blocked": sum(row.get("status") == "blocked" for row in stage_rows),
            "interrupted": sum(row.get("status") == "interrupted" for row in stage_rows),
            'review_required': sum(row.get('status') == 'review_required' for row in stage_rows),
            'skipped_review': sum(row.get('status') == 'skipped_review' for row in stage_rows),
        }
    payload = {
        "protocol_id": manifest.get("protocol_id"),
        "status": manifest.get("status", "planned"),
        "current_stage": next((name for name, state in manifest.get("stage_status", {}).items() if state == "running"), None),
        "stage_status": manifest.get("stage_status", {}),
        "records": len(rows),
        "completed_episodes": sum(row.get("status") == "complete" for row in rows),
        "episodes_by_stage": by_stage,
        "profile_blocks": manifest.get("profile_blocks", {}),
        'task_quarantines': manifest.get('task_quarantines', {}),
        'coverage_complete': _all_scheduled_complete(manifest, rows),
        'last_completed_budget': manifest.get('last_completed_budget'),
        'outcome_counts': {name: sum(row.get('failure') == name for row in rows)
                           for name in ('passed', 'wrong_result', 'budget_exhausted', 'model_no_progress',
                                        'model_tool_error', 'infrastructure', 'contract_error')},
        'maximum_episodes': manifest.get('immutable', {}).get('schedule', {}).get('maximum_episodes'),
        "scheduled_episodes": sum(len(value) for value in manifest.get("stage_schedules", {}).values()),
        "scheduled_complete": len({
            tuple(item["identity"])
            for values in manifest.get("stage_schedules", {}).values()
            for item in values
        } & {
            episode_key(row) for row in rows if row.get("status") == "complete"
        }),
        "finalists": manifest.get("finalists", []),
        "latest_episode": {
            key: latest.get(key) for key in ("model", "profile", "task", "repetition", "status", "failure", "seconds")
        } if latest else manifest.get("latest_episode"),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_path": "manifest.json",
    }
    atomic_write_json(output / "status.json", payload)


def _save_manifest(
    output: Path,
    manifest: dict[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]] = (),
    latest: Mapping[str, Any] | None = None,
) -> None:
    manifest["record_count"] = len(rows)
    if latest:
        if latest.get('budget_ledger'):
            manifest['last_completed_budget'] = latest['budget_ledger']
        manifest["latest_episode"] = {
            key: latest.get(key) for key in ("model", "profile", "task", "repetition", "status", "failure", "seconds")
        }
    atomic_write_json(output / "manifest.json", manifest)
    _write_status(output, manifest, rows, latest)


def load_records(output: Path) -> list[dict[str, Any]]:
    """Load the aggregate and recover rows saved beside individual episodes."""
    output = Path(output)
    aggregate = output / "records.json"
    rows: list[dict[str, Any]] = []
    aggregate_error = None
    if aggregate.exists():
        try:
            payload = json.loads(aggregate.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("records.json must contain a JSON list")
            rows.extend(dict(row) for row in payload)
        except (json.JSONDecodeError, ValueError) as exc:
            aggregate_error = exc
    by_key = {episode_key(row): row for row in rows}
    for path in sorted((output / "runs").glob("*/record.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        key = episode_key(row)
        if key not in by_key:
            rows.append(row)
            by_key[key] = row
        elif row.get("status") == "complete" and by_key[key].get("status") != "complete":
            rows[rows.index(by_key[key])] = row
            by_key[key] = row
    ensure_unique_records(rows)
    if aggregate_error is not None and not rows:
        raise ValueError(f"records.json is unreadable and no per-episode records can recover it: {aggregate_error}")
    return rows


def _episode_dir(output: Path, row: Mapping[str, Any]) -> Path:
    digest = _hash_value(episode_key(row))[:20]
    return output / "runs" / digest


def _save_record(
    output: Path,
    record: Mapping[str, Any],
    rows: list[dict[str, Any]],
    *,
    tasks_module: Any,
    manifest: dict[str, Any],
) -> None:
    key = episode_key(record)
    updated = [row for row in rows if episode_key(row) != key]
    updated.append(dict(record))
    ensure_unique_records(updated)
    updated.sort(key=lambda row: (
        row.get("stage", ""), row.get("repetition", 0), row.get("task", ""), row.get("model", ""),
        _profile_id(row.get("profile")),
    ))
    atomic_write_json(output / "records.json", updated)
    atomic_write_json(_episode_dir(output, record) / "record.json", record)
    rows[:] = updated
    _write_summaries(output, rows, tasks_module)
    _save_manifest(output, manifest, rows=rows, latest=record)


def _task_manifest(tasks_module: Any) -> tuple[dict[str, Any], dict[str, str]]:
    task_ids = tuple(tasks_module.TASKS)
    holdout_ids = tuple(tasks_module.HOLDOUTS)
    specs = tasks_module.TASK_SPECS
    expanded: dict[str, Any] = {}
    for task in (*task_ids, *holdout_ids):
        spec = specs[task]
        phase_count = int(spec.get("phases", 1))
        with tempfile.TemporaryDirectory(prefix="practical-v2-manifest-") as workspace:
            prompt = tasks_module.seed_task(task, Path(workspace))
        checks = {
            str(phase): _hash_value(tasks_module.checks_source(task, phase=phase))
            for phase in range(1, phase_count + 1)
        }
        references = {}
        for phase in range(1, phase_count + 1):
            for variant in (0, 1):
                references[f"phase_{phase}_variant_{variant}"] = _hash_value(
                    tasks_module.reference_files(task, variant=variant, phase=phase)
                )
        expanded[task] = {
            'task_contract_id':getattr(tasks_module,'TASK_CONTRACTS',{}).get(task,'historical-v2'),
            "spec": _jsonable(spec),
            "seed_prompt_sha256": _hash_value(prompt),
            "followup_prompt_sha256": _hash_value(tasks_module.followup_prompt(task)),
            "checks_sha256_by_phase": checks,
            "reference_sha256_by_phase_variant": references,
            "wrong_files_sha256": _hash_value(tasks_module.wrong_files(task)),
        }
    task_hashes = {task: _hash_value(payload) for task, payload in expanded.items()}
    return expanded, task_hashes


def _source_hashes(tasks_module: Any, runtime_module: Any) -> dict[str, str]:
    candidates: list[Path] = [Path(__file__), Path(__file__).resolve().parents[1] / "benchmark" / "practical_selection.py"]
    candidates.extend(p for p in (ROOT/'benchmark').glob('practical_*') if p.suffix in {'.py','.mjs'})
    for module in (tasks_module, runtime_module):
        module_path = getattr(module, "__file__", None)
        if module_path:
            candidates.append(Path(module_path))
    defaults = (
        "benchmark/practical_driver_v2.py",
        "benchmark/practical_tool_guard.py",
        "benchmark/practical_policy.py",
        "benchmark/practical_policy_plugin.mjs",
        "benchmark/practical_manual.py",
        "benchmark/practical_review_replay.py",
        "benchmark/practical_evidence.py",
        "benchmark/configs/limits-skills-experiments-v1.json",
        "benchmark/practical_mcp_v2.py",
        "benchmark/practical_mcp_grading_v2.py",
        "benchmark/practical_grade_contract.py",
        "benchmark/practical_python_checks.py",
        "benchmark/practical_node_reporter.mjs",
        "benchmark/linux_sandbox.py",
        "benchmark/sandbox_bootstrap.py",
        "benchmark/model_broker.py",
        "benchmark/provenance.py",
        "benchmark/campaign_readiness.py",
        "benchmark/model_quality_paired.py",
        "benchmark/safe_campaign.py",
        "scripts/run-practical-selection-v2.sh",
        "scripts/Start-LocalLLMRound.bat",
        "scripts/local_llm_snapshot.py",
        "scripts/Watch-LocalLLM.ps1",
    )
    candidates.extend(ROOT / path for path in defaults)
    candidates.extend((ROOT / 'agent-manual').rglob('*.md'))
    candidates.extend((ROOT / 'tests').glob('test_practical*.py'))
    candidates.extend(ROOT / name for name in ('tests/test_model_broker.py', 'tests/test_linux_sandbox.py',
                                              'tests/test_local_llm_monitor.py', 'tests/test_policy_wall_watch.py',
                                              'tests/test_practical_tool_guard.py'))
    candidates.extend(ROOT / name for name in (
        'tests/test_trusted_grader_boundary.py', 'tests/test_post_validation_repairs.py',
        'tests/test_post_validation_sweep.py', 'tests/test_post_audit_v9_regrade.py',
        'tests/test_m1_v9_preparation.py'))
    candidates.append(ROOT / 'tests/test_resilient_replay.py')
    extra = getattr(runtime_module, "PROVENANCE_SOURCE_PATHS", ())
    for item in extra:
        path = Path(item)
        candidates.append(path if path.is_absolute() else ROOT / path)
    result = {}
    for path in candidates:
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        try:
            label = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            label = resolved.as_posix()
        result[label] = _sha256_file(resolved)
    return dict(sorted(result.items()))


def _model_artifacts(models: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    keys = ("alias", "path", "revision", "sha256", "runtime", "quantization")
    return {
        model: {key: info[key] for key in keys if key in info}
        for model, info in sorted(models.items())
    }


def build_manifest(
    models: Mapping[str, Mapping[str, Any]],
    *,
    tasks_module: Any,
    runtime_module: Any,
    gpu_free_floor_mib: int = DEFAULT_GPU_FREE_FLOOR_MIB,
    created_at: str | None = None,
) -> dict[str, Any]:
    if (type(gpu_free_floor_mib) is not int
            or not MIN_GPU_FREE_FLOOR_MIB <= gpu_free_floor_mib <= DEFAULT_GPU_FREE_FLOOR_MIB):
        raise ValueError(
            f"GPU free floor must be between {MIN_GPU_FREE_FLOOR_MIB} and "
            f"{DEFAULT_GPU_FREE_FLOOR_MIB} MiB"
        )
    task_data, task_hashes = _task_manifest(tasks_module)
    source_hashes = _source_hashes(tasks_module, runtime_module)
    artifacts = _model_artifacts(models)
    immutable = {
        "protocol_id": PROTOCOL,
        "frozen_protocol": FROZEN_PROTOCOL,
        "source_hashes": source_hashes,
        "task_hashes": task_hashes,
        "task_data": task_data,
        "models": artifacts,
        "gpu_free_floor_mib": gpu_free_floor_mib,
        "repetition_seeds": REPETITION_SEEDS,
        "schedule": {
            "baseline_episodes": len(models) * len(tasks_module.TASKS) * len(REPETITIONS),
            "maximum_tuning_episodes": 24,
            "holdout_episodes": 12,
            "maximum_baseline_seconds": sum(
                int(tasks_module.TASK_SPECS[task]["seconds"]) for task in tasks_module.TASKS
            ) * len(models) * len(REPETITIONS),
            "maximum_tuning_seconds": 24 * max(int(tasks_module.TASK_SPECS[task]["seconds"]) for task in HARD_TASKS),
            "maximum_holdout_seconds": len(tasks_module.HOLDOUTS) * 2 * len(REPETITIONS) * max(
                (int(tasks_module.TASK_SPECS[task]["seconds"]) for task in tasks_module.HOLDOUTS), default=0),
            "maximum_total_seconds": (
                sum(int(tasks_module.TASK_SPECS[task]["seconds"]) for task in tasks_module.TASKS)
                * len(models) * len(REPETITIONS)
                + 24 * max(int(tasks_module.TASK_SPECS[task]["seconds"]) for task in HARD_TASKS)
                + len(HOLDOUTS) * 2 * len(REPETITIONS)
                * max((int(tasks_module.TASK_SPECS[task]["seconds"]) for task in tasks_module.HOLDOUTS), default=0)
            ),
        },
        "profiles": profile_catalog(context_32k_cache_prompt=False),
    }
    return {
        "schema_version": 2,
        "protocol_id": PROTOCOL,
        "status": "planned",
        "created_at_utc": created_at or datetime.now(timezone.utc).isoformat(),
        "immutable_sha256": _hash_value(immutable),
        "immutable": immutable,
        "runtime_versions": None,
        "runtime_versions_sha256": None,
        "probe_results": {},
        "profile_diagnostics": {},
        "probe_failures": {},
        "profile_blocks": {},
        "stage_schedules": {},
        "stage_status": {
            "baseline": "pending",
            "cache_on": "pending",
            "context_32k": "pending",
            "holdout": "pending",
        },
        "records_path": "records.json",
        "finalists": [],
        "selected_cache_profile": None,
        "selected_profiles": {},
        "holdout_advice": None,
    }


def _load_or_create_manifest(output: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    path = output / "manifest.json"
    if not path.exists():
        manifest = dict(expected)
        _save_manifest(output, manifest)
        return manifest
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL or manifest.get("immutable_sha256") != expected.get("immutable_sha256"):
        raise ValueError("frozen campaign inputs changed; use a new output directory and protocol id")
    return manifest


def _freeze_runtime_versions(manifest: dict[str, Any], versions: Mapping[str, Any]) -> None:
    current = _jsonable(versions)
    frozen = manifest.get("runtime_versions")
    if frozen is not None and _canonical(frozen) != _canonical(current):
        raise CampaignBlocked("runtime versions differ from the frozen campaign manifest")
    manifest["runtime_versions"] = current
    manifest["runtime_versions_sha256"] = _hash_value(current)


def _probe_key(model: str, profile: str) -> str:
    return f"{model}|{profile}"


def _profile_for_id(profile_id: str, *, context_cache_prompt: bool = False) -> dict[str, Any]:
    catalog = profile_catalog(context_32k_cache_prompt=context_cache_prompt)
    if profile_id not in catalog:
        raise ValueError(f"unknown profile: {profile_id}")
    return catalog[profile_id]


def _profile_probe(
    model: str,
    profile: Mapping[str, Any],
    *,
    output: Path,
    manifest: dict[str, Any],
    runtime: Any,
    lab: Path,
    transient_skips: set[str],
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    key = _probe_key(model, _profile_id(profile))
    manifest.setdefault("probe_results", {})
    manifest.setdefault("profile_diagnostics", {})
    manifest.setdefault("profile_blocks", {})
    manifest.setdefault("probe_failures", {})
    if key in manifest["probe_results"] or key in manifest["profile_diagnostics"]:
        return True
    if key in manifest["profile_blocks"] or key in transient_skips:
        return False
    probe_path = output / "probes" / _hash_value(key)[:20]
    try:
        result = runtime.probe_profile(model, dict(profile), lab=lab, output=probe_path)
        result = _jsonable(result)
    except Exception as exc:
        result = {
            "passed": False,
            "status": "infrastructure",
            "failure": "infrastructure",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if isinstance(result, Mapping) and result.get("passed") is True:
        manifest["probe_results"][key] = result
        manifest["probe_failures"].pop(key, None)
        _save_manifest(output, manifest, rows=rows)
        return True
    status = result.get("status") if isinstance(result, Mapping) else None
    if status == "capability_diagnostic":
        manifest["profile_diagnostics"][key] = result
        manifest["probe_failures"].pop(key, None)
        _save_manifest(output, manifest, rows=rows)
        return True
    if status == "incompatible":
        manifest["profile_blocks"][key] = result
    else:
        # Infrastructure failures are diagnostic only: a later resume may
        # probe again after a transient server, sandbox, or capacity fault.
        manifest["probe_failures"][key] = result
        transient_skips.add(key)
    _save_manifest(output, manifest, rows=rows)
    return False


def _infrastructure_failure(result: Mapping[str, Any]) -> bool:
    return result.get("failure") == "infrastructure" or bool(result.get("infrastructure_error"))


def _attempt_summary(result: Mapping[str, Any], number: int) -> dict[str, Any]:
    return {
        "attempt": number,
        "failure": result.get("failure"),
        "seconds": float(result.get("seconds") or 0),
        "tool_errors": int(result.get("tool_errors") or 0),
        "expected_tool_errors": (int(result["expected_tool_errors"])
                                 if type(result.get("expected_tool_errors")) is int else None),
        "avoidable_tool_errors": (int(result["avoidable_tool_errors"])
                                  if type(result.get("avoidable_tool_errors")) is int else None),
        "model_calls": int(result.get("model_calls") or 0),
        "vram_mib": _resource(result, "vram_mib"),
        "ram_mib": _resource(result, "ram_mib"),
        "artifact_identity": _jsonable(result.get("artifact_identity")),
    }


def _combined_record(
    episode: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    *,
    status: str,
    final: Mapping[str, Any],
) -> dict[str, Any]:
    record = {**episode, **_jsonable(final)}
    for field in ("protocol", "model", "profile", "task", "repetition", "stage", "generation_seed", "profile_config"):
        if field in episode:
            record[field] = episode[field]
    record["status"] = status
    record["attempt_count"] = len(attempts)
    record["attempts"] = list(attempts)
    record["seconds"] = round(sum(float(item.get("seconds") or 0) for item in attempts), 3)
    if len(attempts) > 1:
        record['infrastructure_retried'] = any(item.get('failure') == 'infrastructure' for item in attempts[:-1])
        record['review_retried'] = any(item.get('failure') == 'task_review' for item in attempts[:-1])
    record["tool_errors"] = sum(int(item.get("tool_errors") or 0) for item in attempts)
    for metric in ("expected_tool_errors", "avoidable_tool_errors"):
        known = [item[metric] for item in attempts if type(item.get(metric)) is int]
        record[metric] = sum(known) if len(known) == len(attempts) else None
    record["model_calls"] = sum(int(item.get("model_calls") or 0) for item in attempts)
    for metric in ("vram_mib", "ram_mib"):
        values = [value for item in attempts if (value := _resource(item, metric)) is not None]
        if values:
            record[metric] = max(values)
    return record


def _load_task_quarantines(lab, manifest):
    path = Path(lab) / "results/task-review-registry.json"
    try:
        registry = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as exc:
        raise CampaignBlocked("task review registry is unreadable") from exc
    if (not isinstance(registry, dict) or any(
            not isinstance(entry, dict) or type(entry.get("active", True)) is not bool
            for entry in registry.values())):
        raise CampaignBlocked("task review registry is invalid")
    active = {task: entry for task, entry in registry.items() if entry.get("active", True)}
    quarantines = manifest.setdefault("task_quarantines", {})
    for task, entry in registry.items():
        if entry.get("active") is False:
            if not entry.get("review_reason"):
                raise CampaignBlocked("inactive task review registry entry requires review_reason")
            quarantines.pop(task, None)
            manifest.setdefault("task_reviews", {})[task] = entry
    quarantines.update(active)
    return registry


def _quarantine_task(episode, result, *, lab, output, manifest):
    registry = _load_task_quarantines(lab, manifest)
    task = episode["task"]
    entry = {"active": True, "task": task, "source_output": str(output),
             "trigger_identity": list(episode_key(episode)),
             "reason": (result.get("tool_review") or {}).get("reason", "tool_error_review"),
             "evidence": result.get("tool_review"),
             "created_at_utc": datetime.now(timezone.utc).isoformat()}
    registry[task] = entry
    atomic_write_json(Path(lab) / "results/task-review-registry.json", registry)
    manifest.setdefault("task_quarantines", {})[task] = entry


def _run_episode(
    episode: Mapping[str, Any],
    *,
    output: Path,
    rows: list[dict[str, Any]],
    runtime: Any,
    models: Mapping[str, Mapping[str, Any]],
    lab: Path,
    tasks_module: Any,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    existing = next((row for row in rows if episode_key(row) == episode_key(episode)), None)
    attempts = list(existing.get("attempts", [])) if existing else []
    raw_results = list(existing.get("attempt_results", [])) if existing else []
    episode_output = _episode_dir(output, episode)
    profile = dict(episode["profile_config"])
    rearmed = (existing and existing.get("status") == "blocked"
               and existing.get("failure") == "infrastructure"
               and manifest.get("operator_retry_blocked"))
    reviewed = existing and existing.get('status') == 'review_required'
    offset = len(attempts) if rearmed or reviewed else 0
    for attempt_number in range(len(attempts) + 1, offset + 3):
        running = _combined_record(
            episode, attempts, status="running",
            final={"failure": None, "correct": False, "autonomous": False},
        )
        _save_record(output, running, rows, tasks_module=tasks_module, manifest=manifest)
        try:
            contract_kwargs = ({'task_contract_id':episode['task_contract_id']}
                               if episode.get('task_contract_id') else {})
            result = runtime.run_episode(
                episode["model"], episode["task"], profile, episode["repetition"],
                episode_output, models, lab=lab, **contract_kwargs,
            )
        except KeyboardInterrupt:
            interrupted = _combined_record(
                episode, attempts, status="interrupted",
                final={"failure": "interrupted", "correct": False, "autonomous": False},
            )
            interrupted["attempt_results"] = [_jsonable(item) for item in raw_results]
            _save_record(output, interrupted, rows, tasks_module=tasks_module, manifest=manifest)
            raise
        except Exception as exc:
            failed = _combined_record(
                episode, attempts, status="failed",
                final={"failure": "configuration", "correct": False, "autonomous": False,
                       "error": f"{type(exc).__name__}: {exc}"},
            )
            failed["block_reason"] = "runtime adapter raised before returning an episode result"
            _save_record(output, failed, rows, tasks_module=tasks_module, manifest=manifest)
            raise CampaignBlocked(failed["block_reason"]) from exc
        if not isinstance(result, Mapping):
            result = {"failure": "configuration", "correct": False, "autonomous": False,
                      "error": "runtime adapter returned a non-mapping result"}
        result = dict(result)
        attempts.append(_attempt_summary(result, attempt_number))
        raw_results.append(_jsonable(result))
        model_stop = (result.get('failure') in {'model_tool_error', 'model_no_progress'}
                      or ((result.get('tool_review') or {}).get('reason') in {'model_tool_error_threshold', 'model_no_progress'}
                          and result.get('failure') not in {'contract_error', 'infrastructure'}))
        if model_stop:
            result.update(review_required=False, scoring_eligible=True, autonomous=False)
            result['failure'] = 'model_no_progress' if (result.get('tool_review') or {}).get('reason') == 'model_no_progress' else 'model_tool_error'
            record = _combined_record(episode, attempts, status='complete', final=result)
            record['attempt_results'] = list(raw_results)
            _save_record(output, record, rows, tasks_module=tasks_module, manifest=manifest)
            return record
        if result.get("review_required"):
            _quarantine_task(episode, result, lab=lab, output=output, manifest=manifest)
            record = _combined_record(episode, attempts, status="review_required", final=result)
            record.update(review_required=True, scoring_eligible=False, autonomous=False)
            record["attempt_results"] = list(raw_results)
            _save_record(output, record, rows, tasks_module=tasks_module, manifest=manifest)
            return record
        if (_infrastructure_failure(result) and attempt_number == offset + 1
                and not getattr(runtime, 'stop_on_infrastructure', False)):
            progress = _combined_record(episode, attempts, status="running", final=result)
            progress["attempt_results"] = list(raw_results)
            _save_record(output, progress, rows, tasks_module=tasks_module, manifest=manifest)
            continue
        if _infrastructure_failure(result):
            record = _combined_record(episode, attempts, status="blocked", final=result)
            record["failure"] = "infrastructure"
            record["block_reason"] = ('infrastructure failed; fix before resuming'
                                      if getattr(runtime, 'stop_on_infrastructure', False)
                                      else 'infrastructure retry exhausted for this episode')
            record["attempt_results"] = list(raw_results)
            _save_record(output, record, rows, tasks_module=tasks_module, manifest=manifest)
            raise CampaignBlocked(record["block_reason"])
        record = _combined_record(episode, attempts, status="complete", final=result)
        record["attempt_results"] = list(raw_results)
        _save_record(output, record, rows, tasks_module=tasks_module, manifest=manifest)
        return record
    if attempts:
        record = _combined_record(
            episode, attempts, status="blocked",
            final={"failure": "infrastructure", "correct": False, "autonomous": False},
        )
        record["block_reason"] = "infrastructure retry exhausted for this episode"
        record["attempt_results"] = list(raw_results)
        _save_record(output, record, rows, tasks_module=tasks_module, manifest=manifest)
        raise CampaignBlocked(record["block_reason"])
    raise AssertionError("episode retry loop did not return")


def _run_stage(
    name: str,
    schedule: Sequence[Mapping[str, Any]],
    *,
    output: Path,
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    runtime: Any,
    models: Mapping[str, Mapping[str, Any]],
    lab: Path,
    tasks_module: Any,
    continue_model_blocks: bool = False,
) -> bool:
    contracts=manifest.get('immutable',{}).get('task_contracts',{})
    for episode in schedule:
        if episode['task'] in contracts and episode.get('task_contract_id') != contracts[episode['task']]:
            raise CampaignBlocked('episode task contract differs from frozen manifest')
    manifest.setdefault("stage_schedules", {})
    signature = [
        {"identity": list(episode_key(episode)), "profile_config": episode.get("profile_config"),
         **({'task_contract_id':episode['task_contract_id']} if 'task_contract_id' in episode else {})}
        for episode in schedule
    ]
    prior_signature = manifest["stage_schedules"].get(name)
    if prior_signature is not None and _canonical(prior_signature) != _canonical(signature):
        raise CampaignBlocked(f"{name} schedule changed after it was frozen")
    manifest["stage_schedules"][name] = signature
    manifest["stage_status"][name] = "running"
    _save_manifest(output, manifest, rows=rows)
    blocked_profiles = False
    transient_skips: set[str] = set()
    blocked_models: set[str] = set()
    _load_task_quarantines(lab, manifest)
    for episode in schedule:
        key = episode_key(episode)
        existing = next((row for row in rows if episode_key(row) == key), None)
        if episode["task"] in manifest.get("task_quarantines", {}):
            if existing is None or existing.get("status") not in {"complete", "review_required", "skipped_review"}:
                skipped = {**episode, "status": "skipped_review", "failure": "task_review",
                           "review_required": True, "scoring_eligible": False,
                           "correct": False, "autonomous": False, "seconds": 0,
                           "tool_review": manifest["task_quarantines"][episode["task"]]}
                _save_record(output, skipped, rows, tasks_module=tasks_module, manifest=manifest)
            continue
        if existing is not None and existing.get("status") == "complete":
            continue
        if episode['model'] in blocked_models:
            continue
        try:
            admission = getattr(runtime, 'check_model_admission', None)
            if admission is not None:
                admission()
            if existing is not None and existing.get("status") in {"blocked", "failed"}:
                if not (manifest.get("operator_retry_blocked")
                        and existing.get("status") == "blocked"
                        and existing.get("failure") == "infrastructure"):
                    raise CampaignBlocked("episode blocked; fix infrastructure and resume with --retry-blocked")
            profile = episode.get("profile_config") or _profile_for_id(episode["profile"])
            if not _profile_probe(episode["model"], profile, output=output,
                                  manifest=manifest, runtime=runtime, lab=lab,
                                  transient_skips=transient_skips, rows=rows):
                if continue_model_blocks or (getattr(runtime, 'stop_on_infrastructure', False)
                        and manifest.get('probe_failures')):
                    raise CampaignBlocked('profile probe blocked this model; see probe evidence')
                blocked_profiles = True
                continue
            _run_episode(episode, output=output, rows=rows, runtime=runtime, models=models, lab=lab,
                         tasks_module=tasks_module, manifest=manifest)
        except CampaignBlocked as exc:
            if not continue_model_blocks:
                raise
            blocked_profiles = True
            blocked_models.add(episode['model'])
            manifest.setdefault('model_blocks', {}).setdefault(episode['model'], []).append({
                'at_utc': datetime.now(timezone.utc).isoformat(), 'stage':name,
                'identity':list(key), 'reason':str(exc), 'inference_retry_automatic':False})
            _save_manifest(output, manifest, rows=rows)
    manifest["stage_status"][name] = ("blocked" if blocked_profiles else
        "review_required" if manifest.get("task_quarantines") else "complete")
    _save_manifest(output, manifest, rows=rows)
    return not blocked_profiles


def _holdout_advice(rows: Sequence[Mapping[str, Any]], finalists: Sequence[str]) -> dict[str, Any]:
    rows = _scorable_rows(rows)
    outcomes = {}
    winners = []
    for task in HOLDOUTS:
        counts = {
            model: sum(
                mechanical_success(row)
                for row in rows
                if row.get("stage") == "holdout" and row.get("task") == task
                and row.get("model") == model and row.get("status") == "complete"
            )
            for model in finalists
        }
        outcomes[task] = counts
        if counts and max(counts.values()) > 0:
            best = max(counts.values())
            leaders = [model for model, count in counts.items() if count == best]
            winners.append(leaders[0] if len(leaders) == 1 else None)
        else:
            winners.append(None)
    consistent = bool(winners) and winners[0] is not None and all(winner == winners[0] for winner in winners)
    return {
        "status": "consistent" if consistent else "inconclusive",
        "model": winners[0] if consistent else None,
        "per_task_completed": outcomes,
        "contradictory": all(winner is not None for winner in winners) and len(set(winners)) > 1,
    }


def _all_scheduled_complete(manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> bool:
    completed = {
        episode_key(row)
        for row in rows
        if row.get("status") == "complete"
    }
    schedules = manifest.get("stage_schedules", {})
    planned = [tuple(item['identity']) for entries in schedules.values() for item in entries]
    actual = [episode_key(row) for row in rows]
    return (bool(planned) and len(planned) == len(set(planned))
            and len(actual) == len(set(actual)) and set(planned) == set(actual) == completed)


def _write_recommendation(output: Path, manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    advice = manifest.get("holdout_advice") or _holdout_advice(rows, manifest.get("finalists", []))
    coverage_complete = _all_scheduled_complete(manifest, rows)
    if manifest.get('task_quarantines') or _review_tasks(rows):
        status = 'inconclusive'
        reason = 'one or more tasks require review'
        candidate_model = None
    elif not coverage_complete:
        status = "inconclusive"
        reason = "scheduled campaign coverage is incomplete"
        candidate_model = None
    elif advice.get('status') == 'limited':
        status = 'limited_evidence'
        reason = advice.get('reason', 'only a subset of holdout tasks was rerun')
        candidate_model = None
    elif advice.get("status") != "consistent":
        status = "inconclusive"
        reason = "the two holdout tasks do not support the same finalist"
        candidate_model = None
    else:
        status = "consistent_signal"
        reason = "both holdout tasks favor the same finalist"
        candidate_model = advice.get("model")
    atomic_write_json(output / "recommendation.json", {
        "status": status,
        "candidate_model": candidate_model,
        "reason": reason,
        "finalists": manifest.get("finalists", []),
        "selected_profiles": manifest.get("selected_profiles", {}),
        "holdout_advice": advice,
        "campaign_status": manifest.get("status"),
    })


def run_campaign(
    output: Path,
    *,
    models: Mapping[str, Mapping[str, Any]],
    tasks_module: Any,
    runtime: Any,
    lab: Path = LAB,
    retry_blocked: bool = False,
    gpu_free_floor_mib: int = DEFAULT_GPU_FREE_FLOOR_MIB,
) -> dict[str, Any]:
    """Run or resume all approved stages; callers supply the real adapter."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    expected = build_manifest(
        models, tasks_module=tasks_module, runtime_module=runtime,
        gpu_free_floor_mib=gpu_free_floor_mib,
    )
    manifest = _load_or_create_manifest(output, expected)
    configure_gpu_floor = getattr(runtime, "configure_gpu_free_floor_mib", None)
    if callable(configure_gpu_floor):
        configure_gpu_floor(gpu_free_floor_mib)
    manifest["operator_retry_blocked"] = bool(retry_blocked)
    records = load_records(output)
    ensure_unique_records(records)

    def stop_for_task_review() -> bool:
        if not manifest.get("task_quarantines"):
            return False
        manifest["status"] = "review_required"
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return True

    if manifest.get("status") == "complete":
        _write_summaries(output, records, tasks_module)
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return manifest
    previous_sigterm = None
    try:
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
    except (ValueError, OSError):
        previous_sigterm = None
    try:
        if manifest.get("status") == "running":
            manifest["status"] = "interrupted"
            manifest["interrupted_recovery"] = True
            _save_manifest(output, manifest, rows=records)
        for row in list(records):
            if row.get("status") == "running":
                interrupted = {**row, "status": "interrupted", "failure": "interrupted",
                               "recovered_after_process_exit": True}
                _save_record(output, interrupted, records, tasks_module=tasks_module, manifest=manifest)
        if tuple(tasks_module.TASKS) != TASKS or tuple(tasks_module.HOLDOUTS) != HOLDOUTS:
            raise CampaignBlocked("task module does not match the frozen v2 task ids")
        validation = runtime.validate_environment(lab=lab)
        if not isinstance(validation, Mapping) or validation.get("passed") is not True:
            manifest["status"] = "blocked"
            manifest["failure"] = "environment_validation_failed"
            manifest["environment_validation"] = _jsonable(validation)
            _save_manifest(output, manifest, rows=records)
            _write_recommendation(output, manifest, records)
            return manifest
        try:
            _freeze_runtime_versions(manifest, validation.get("runtime_versions") or {})
        except CampaignBlocked as exc:
            manifest["status"] = "blocked"
            manifest["failure"] = "runtime_versions_changed"
            manifest["error"] = str(exc)
            _save_manifest(output, manifest, rows=records)
            _write_recommendation(output, manifest, records)
            return manifest
        manifest["environment_validation"] = _jsonable(validation)
        manifest["status"] = "running"
        _save_manifest(output, manifest, rows=records)

        baseline = baseline_schedule(tuple(models))
        baseline_complete = _run_stage(
            "baseline", baseline, output=output, rows=records, manifest=manifest,
            runtime=runtime, models=models, lab=lab, tasks_module=tasks_module,
        )
        if not baseline_complete:
            raise CampaignBlocked("baseline coverage is incomplete because a model profile could not be probed")
        if stop_for_task_review():
            return manifest
        core_ranking = rank_models(records, tuple(models), metric_tasks=CORE_TASKS)
        hard_ranking = rank_models(records, tuple(models), metric_tasks=HARD_TASKS)
        finalists = select_finalists(core_ranking, hard_ranking)
        if len(finalists) != 2:
            raise CampaignBlocked("fewer than two models have complete baseline coverage")
        manifest["rankings"] = {"core": core_ranking, "hard": hard_ranking}
        manifest["finalists"] = finalists
        _save_manifest(output, manifest, rows=records)

        cache_schedule = tuning_schedule(finalists, _profile_for_id("cache_on"), stage="cache_on")
        _run_stage(
            "cache_on", cache_schedule, output=output, rows=records, manifest=manifest,
            runtime=runtime, models=models, lab=lab, tasks_module=tasks_module,
        )
        if stop_for_task_review():
            return manifest
        selected_cache_by_model = select_profiles_per_model(
            records, finalists, ("baseline", "cache_on"), tasks=HARD_TASKS,
        )
        manifest["selected_cache_profile"] = selected_cache_by_model
        _save_manifest(output, manifest, rows=records)

        context_profiles = {
            model: {
                "id": "context_32k",
                "context_tokens": 32768,
                "cache_prompt": _profile_for_id(selected_cache_by_model[model])["cache_prompt"],
            }
            for model in finalists
        }
        context_schedule = tuning_schedule(finalists, context_profiles, stage="context_32k")
        _run_stage(
            "context_32k", context_schedule, output=output, rows=records, manifest=manifest,
            runtime=runtime, models=models, lab=lab, tasks_module=tasks_module,
        )
        if stop_for_task_review():
            return manifest
        selected_profile_ids = {
            model: (selected_cache_by_model[model], "context_32k")
            for model in finalists
        }
        selected_by_model = select_profiles_per_model(
            records, finalists, selected_profile_ids, tasks=HARD_TASKS,
        )
        profile_cache_by_model = {
            model: _profile_for_id(selected_cache_by_model[model])["cache_prompt"]
            for model in finalists
        }
        chosen_profiles = {
            model: (
                {"id": "context_32k", "context_tokens": 32768,
                 "cache_prompt": profile_cache_by_model[model]}
                if selected_by_model[model] == "context_32k"
                else _profile_for_id(selected_by_model[model])
            )
            for model in finalists
        }
        manifest["selected_profiles"] = selected_by_model
        _save_manifest(output, manifest, rows=records)

        holdouts = holdout_schedule(finalists, chosen_profiles, tasks=tuple(tasks_module.HOLDOUTS))
        _run_stage(
            "holdout", holdouts, output=output, rows=records, manifest=manifest,
            runtime=runtime, models=models, lab=lab, tasks_module=tasks_module,
        )
        if stop_for_task_review():
            return manifest
        manifest["holdout_advice"] = _holdout_advice(records, finalists)
        complete = _all_scheduled_complete(manifest, records) and all(
            status == "complete" for status in manifest["stage_status"].values()
        )
        manifest["record_count"] = len(records)
        manifest["status"] = "complete" if complete else "blocked"
        if not complete:
            manifest["failure"] = "incomplete_coverage"
            manifest["error"] = "one or more scheduled profiles or episodes did not complete"
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return manifest
    except CampaignBlocked as exc:
        manifest["status"] = "blocked"
        manifest["failure"] = manifest.get("failure") or "campaign_blocked"
        manifest["error"] = str(exc)
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return manifest
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["interrupted_at_utc"] = datetime.now(timezone.utc).isoformat()
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return manifest
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failure"] = type(exc).__name__
        manifest["error"] = str(exc)
        _save_manifest(output, manifest, rows=records)
        _write_recommendation(output, manifest, records)
        return manifest
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)


def _load_runtime_and_tasks() -> tuple[Any, Any]:
    from benchmark import practical_runtime_v2, practical_tasks_v2

    return practical_runtime_v2, practical_tasks_v2


def _configure_output_runtime_contract(output: Path, runtime_module: Any) -> None:
    manifest_path = Path(output) / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("campaign manifest must be an object")
    if "immutable" not in manifest:
        return
    immutable = manifest["immutable"]
    if not isinstance(immutable, Mapping):
        raise ValueError("campaign immutable section must be an object")
    if "runtime_expectations" not in immutable:
        return
    if manifest.get("immutable_sha256") != _hash_value(immutable):
        raise ValueError("campaign immutable_sha256 does not match the immutable section")
    expectations = immutable["runtime_expectations"]
    if not isinstance(expectations, Mapping):
        raise ValueError("frozen runtime expectations must be an object")
    configure = getattr(runtime_module, "configure_runtime_contract", None)
    if not callable(configure):
        raise ValueError("runtime module cannot configure a frozen runtime contract")
    configure(expectations)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the campaign using the local runtime")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true", help="run non-inference environment checks only")
    parser.add_argument("--regrade-run", action="store_true", help="regrade saved episode evidence without inference")
    parser.add_argument("--retry-blocked", action="store_true", help="explicitly retry blocked infrastructure after repair")
    parser.add_argument(
        "--gpu-free-floor-mib", type=int, default=DEFAULT_GPU_FREE_FLOOR_MIB,
        help="per-model-load VRAM floor (7000-7168 MiB), frozen in the campaign manifest",
    )
    args = parser.parse_args(argv)
    if sum((args.execute, args.validate_only, args.regrade_run)) > 1:
        parser.error("--execute, --validate-only, and --regrade-run are mutually exclusive")
    if not MIN_GPU_FREE_FLOOR_MIB <= args.gpu_free_floor_mib <= DEFAULT_GPU_FREE_FLOOR_MIB:
        parser.error(
            f"--gpu-free-floor-mib must be between {MIN_GPU_FREE_FLOOR_MIB} and "
            f"{DEFAULT_GPU_FREE_FLOOR_MIB}"
        )
    try:
        runtime, tasks_module = _load_runtime_and_tasks()
    except ImportError as exc:
        parser.error(f"v2 runtime and task modules are required: {exc}")
    if args.regrade_run:
        regrade = getattr(runtime, "regrade_run", None)
        if not callable(regrade):
            parser.error("the v2 runtime does not expose regrade_run(output_dir)")
        try:
            episodes = regrade(args.output)
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
            return 2
        payload = {
            "protocol_id": PROTOCOL,
            "episodes": _jsonable(episodes),
            "episode_count": len(episodes) if isinstance(episodes, Sequence) else None,
            "inference_started": False,
        }
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_write_json(args.output / "regrades.json", payload)
        print(json.dumps({"status": "complete", "episode_count": payload["episode_count"],
                          "output": str(args.output / "regrades.json"), "inference_started": False},
                         indent=2, sort_keys=True))
        return 0
    if args.validate_only:
        try:
            _configure_output_runtime_contract(args.output, runtime)
            result = runtime.validate_environment(lab=LAB)
        except (OSError, TypeError, ValueError) as exc:
            result = {"passed": False, "status": "configuration",
                      "failure": "runtime_contract_invalid",
                      "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                      "runtime_versions": {}}
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 0 if isinstance(result, Mapping) and result.get("passed") is True else 2
    from benchmark import practical_selection

    models = practical_selection.contracts()
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=True)
        expected = build_manifest(
            models, tasks_module=tasks_module, runtime_module=runtime,
            gpu_free_floor_mib=args.gpu_free_floor_mib,
        )
        manifest = _load_or_create_manifest(args.output, expected)
        records = load_records(args.output)
        _write_summaries(args.output, records, tasks_module)
        _save_manifest(args.output, manifest, rows=records)
        schedule = expected["immutable"]["schedule"]
        print(json.dumps({
            "status": manifest.get("status", "planned"),
            "protocol_id": PROTOCOL,
            "baseline_episodes": schedule["baseline_episodes"],
            "maximum_tuning_episodes": schedule["maximum_tuning_episodes"],
            "holdout_episodes": schedule["holdout_episodes"],
            "maximum_total_seconds": schedule["maximum_total_seconds"],
            "maximum_total_hours": round(schedule["maximum_total_seconds"] / 3600, 2),
            "output": str(args.output),
            "inference_started": False,
        }, indent=2, sort_keys=True))
        return 0
    manifest = run_campaign(args.output, models=models, tasks_module=tasks_module, runtime=runtime,
                            retry_blocked=args.retry_blocked,
                            gpu_free_floor_mib=args.gpu_free_floor_mib)
    print(json.dumps({
        "status": manifest.get("status"),
        "protocol_id": PROTOCOL,
        "output": str(args.output),
        "record_count": manifest.get("record_count", len(load_records(args.output))),
        "finalists": manifest.get("finalists", []),
    }, indent=2, sort_keys=True))
    return 0 if manifest.get("status") == "complete" else (130 if manifest.get("status") == "interrupted" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
