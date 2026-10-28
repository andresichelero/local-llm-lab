"""Resumable replay of changed tasks, released only after the source finishes."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_runtime_v2 as runtime
from benchmark import practical_tasks_v2 as tasks
from benchmark.practical_queue import QueueRuntime

PROTOCOL = "practical-agent-selection-7bplus-corrected-v3"
AFFECTED_TASKS = frozenset({"B2", "C2", "M1", "M2", "D2", "H2"})
DEFAULT_SOURCE = runtime.LAB / "results/practical-selection-7bplus-v1"
DEFAULT_OUTPUT = runtime.LAB / "results/practical-selection-7bplus-corrected-v3"
BASELINE_TASKS = ('B2', 'C2', 'M1', 'M2', 'D2')


def daily_contract(lab: Path, *, day: str | None = None) -> dict[str, str]:
    day = day or datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    path = lab / 'state/runtime-updates' / f'daily-{day}.json'
    try:
        evidence = json.loads(path.read_text())
        if evidence.get('status') != 'complete' or evidence.get('date') != day:
            raise ValueError('incomplete daily update')
        contract = {'opencode': evidence['applications']['opencode'],
                    'llama_revision': evidence['llama_cpp']['commit']}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'daily runtime update required for {day}') from exc
    import re
    if (not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', str(contract['opencode']))
            or not re.fullmatch(r'[0-9a-f]{40}', str(contract['llama_revision']))):
        raise ValueError('invalid daily runtime evidence')
    return contract


def changed_schedule(source, stage, *, finalists=None, profiles=None):
    """Freeze each stage only after its own finalists and profiles are known."""
    if stage == 'baseline':
        return campaign.baseline_schedule(tuple(source['immutable']['models']),
                                          tasks=BASELINE_TASKS, protocol=PROTOCOL)
    if stage not in {'cache_on', 'context_32k', 'holdout'}:
        raise ValueError('unknown repair stage')
    if not finalists or len(set(finalists)) != 2:
        raise ValueError('two distinct repaired finalists required')
    if stage == 'cache_on':
        profiles = {m: campaign._profile_for_id('cache_on') for m in finalists}
    if not profiles or set(profiles) != set(finalists):
        raise ValueError('each finalist requires an explicit profile')
    task = 'H2' if stage == 'holdout' else 'D2'
    return [campaign._episode(m, task, repetition, profiles[m], stage=stage, protocol=PROTOCOL)
            for repetition in campaign.REPETITIONS for m in finalists]


def repair_schedule(source: dict[str, Any]) -> list[dict[str, Any]]:
    planned = []
    all_keys = set()
    for stage, entries in source["stage_schedules"].items():
        for entry in entries:
            key = tuple(entry["identity"])
            if key in all_keys:
                raise ValueError("duplicate source schedule identity")
            all_keys.add(key)
            protocol, model, profile, task, repetition = key
            if protocol != source["protocol_id"]:
                raise ValueError("source schedule protocol mismatch")
            if task not in AFFECTED_TASKS:
                continue
            source_seeds = source["immutable"].get("repetition_seeds", campaign.REPETITION_SEEDS)
            seed = source_seeds.get(str(repetition), source_seeds.get(repetition))
            if seed != campaign.REPETITION_SEEDS.get(repetition):
                raise ValueError("source generation seed differs from the pinned repair policy")
            config = entry["profile_config"]
            if config["id"] != profile:
                raise ValueError("source profile identity mismatch")
            row = campaign._episode(model, task, repetition, config, stage=stage,
                                    protocol=PROTOCOL)
            row["source_identity"] = list(key)
            planned.append(row)
    if not planned:
        raise ValueError("source has no affected tasks")
    campaign.ensure_unique_records(planned)
    return planned


def load_completed_source(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError("source campaign must be complete before any repair validation or inference")
    records = json.loads((source / "records.json").read_text())
    campaign.ensure_unique_records(records)
    expected = {tuple(entry["identity"]) for entries in manifest["stage_schedules"].values()
                for entry in entries}
    observed = {campaign.episode_key(row) for row in records if row.get("status") == "complete"}
    if not expected or expected != observed:
        raise ValueError("source coverage is incomplete or has unexpected records")
    repair_schedule(manifest)
    if manifest["immutable"].get("frozen_protocol", campaign.FROZEN_PROTOCOL) != campaign.FROZEN_PROTOCOL:
        # JSON round-trips integer seed keys as strings.
        if campaign._canonical(manifest["immutable"]["frozen_protocol"]) != campaign._canonical(campaign.FROZEN_PROTOCOL):
            raise ValueError("source generation policy differs from the repair policy")
    return manifest, records


def composite_records(source: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain historical provenance; never relabel unaffected evidence as a fresh run."""
    return [{**row, "inherited": True} for row in source if row["task"] not in AFFECTED_TASKS] + [
        {**row, "inherited": False} for row in fresh]


def _write_comparison(output: Path, source: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> None:
    combined = composite_records(source, fresh)
    campaign.atomic_write_json(output / "composite-records.json", combined)
    lines = ["# Comparação após correções", "",
             "Composição de evidências: tarefas não alteradas preservam o protocolo histórico; "
             "tarefas afetadas usam apenas resultados novos. Não é uma campanha inteiramente nova.", "",
             "| Modelo | Cobertura baseline | Funcionalmente corretas | Corretas e autônomas | "
             "Tempo total s | Herdadas / novas |", "|---|---:|---:|---:|---:|---:|"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded = campaign._review_tasks(combined)
    if excluded:
        lines.insert(4, "Tarefas excluídas de todos os modelos, aguardando revisão: " + ", ".join(sorted(excluded)) + ".\n")
    for row in campaign._scorable_rows(combined):
        if row.get("stage") == "baseline" and row.get("status") == "complete":
            groups[row["model"]].append(row)
    for model, rows in sorted(groups.items()):
        lines.append(f"| {model} | {len(rows)}/24 | {sum(bool(r.get('correct')) for r in rows)} | "
                     f"{sum(bool(r.get('correct') and r.get('autonomous')) for r in rows)} | "
                     f"{sum(float(r.get('seconds') or 0) for r in rows):.1f} | "
                     f"{sum(r['inherited'] for r in rows)} / {sum(not r['inherited'] for r in rows)} |")
    lines += ["", "Cobertura parcial não permite proclamar vencedor. As comparações de tempo "
              "incluem tentativas que falharam; memória e ferramentas permanecem nos registros individuais."]
    campaign.atomic_write_text(output / "comparison.md", "\n".join(lines) + "\n")


class RepairRuntime(QueueRuntime):
    stop_on_infrastructure = True

    def __init__(self, models: dict[str, Any], source: Path):
        super().__init__(models, source / "manifest.json")
        self.PROVENANCE_SOURCE_PATHS = (*self.PROVENANCE_SOURCE_PATHS, Path(__file__),
            runtime.ROOT / 'scripts/Start-LocalLLMRound.bat',
            runtime.ROOT / 'scripts/run-practical-repair.sh',
            runtime.ROOT / 'scripts/00_update_runtime.sh')


def build_manifest(source_path: Path, source: dict[str, Any], adapter: Any,
                   runtime_expectations: dict[str, str] | None = None) -> dict[str, Any]:
    manifest = campaign.build_manifest(source["immutable"]["models"], tasks_module=tasks,
                                       runtime_module=adapter, gpu_free_floor_mib=7000)
    planned = changed_schedule(source, 'baseline')
    immutable = manifest["immutable"]
    immutable["repair_source"] = {
        "path": str(source_path.resolve()), "protocol_id": source["protocol_id"],
        "immutable_sha256": source["immutable_sha256"],
        "records_sha256": campaign._sha256_file(source_path / "records.json"),
        "affected_tasks": sorted(AFFECTED_TASKS),
    }
    immutable["repair_schedule"] = planned
    immutable['profiles'].pop('context_32k', None)
    immutable['context_tuning'] = {'context_tokens': 32768, 'cache_policy': 'selected_per_finalist_after_D2_cache_test'}
    immutable['runtime_expectations'] = runtime_expectations
    immutable["schedule"] = {"repair_episodes": len(planned), 'maximum_episodes': 93,
                             "maximum_total_seconds": (sum(tasks.TASK_SPECS[r['task']]['seconds']
                                                           for r in planned) + 18 * 720)}
    manifest["immutable_sha256"] = campaign._hash_value(immutable)
    manifest["stage_status"] = {stage: "pending" for stage in source["stage_schedules"]}
    manifest["finalists"] = []
    return manifest


def execute_stages(source, original, *, output, rows, manifest, adapter):
    models = source['immutable']['models']

    def stage(name, profiles=None):
        schedule = changed_schedule(source, name, finalists=manifest.get('finalists'), profiles=profiles)
        if not campaign._run_stage(name, schedule, output=output, rows=rows, manifest=manifest,
                                   runtime=adapter, models=models, lab=runtime.LAB, tasks_module=tasks):
            raise campaign.CampaignBlocked('a repaired profile failed validation')
        return not manifest.get('task_quarantines')

    if not stage('baseline'):
        return 'review_required'
    combined = composite_records(original, rows)
    core = campaign.rank_models(combined, tuple(models), metric_tasks=campaign.CORE_TASKS)
    hard = campaign.rank_models(combined, tuple(models), metric_tasks=campaign.HARD_TASKS)
    finalists = campaign.select_finalists(core, hard)
    if len(finalists) != 2:
        raise campaign.CampaignBlocked('repaired baseline has fewer than two eligible finalists')
    manifest['finalists'] = finalists
    manifest['rankings'] = {'core': core, 'hard': hard, 'mixed_historical_baseline': True}
    campaign._save_manifest(output, manifest, rows=rows)
    if not stage('cache_on'):
        return 'review_required'
    selected_cache = campaign.select_profiles_per_model(rows, finalists, ('baseline', 'cache_on'), tasks=('D2',))
    manifest['selected_cache_profile'] = selected_cache
    context_profiles = {m: {'id': 'context_32k', 'context_tokens': 32768,
                            'cache_prompt': campaign._profile_for_id(selected_cache[m])['cache_prompt']}
                        for m in finalists}
    manifest['effective_context_profiles_by_model'] = context_profiles
    if not stage('context_32k', context_profiles):
        return 'review_required'
    candidates = {m: (selected_cache[m], 'context_32k') for m in finalists}
    selected = campaign.select_profiles_per_model(rows, finalists, candidates, tasks=('D2',))
    chosen = {m: context_profiles[m] if selected[m] == 'context_32k'
              else campaign._profile_for_id(selected[m]) for m in finalists}
    manifest['selected_profiles'] = selected
    manifest['effective_profiles_by_model'] = chosen
    if not stage('holdout', chosen):
        return 'review_required'
    manifest['holdout_advice'] = {'status': 'limited', 'tasks': ['H2'],
                                  'reason': 'H2 only; H1 was not rerun; historical baseline is mixed'}
    return 'complete'


def capacity_block(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """Only retry a pre-load capacity failure; other infrastructure errors stop."""
    blocked = [r for r in rows if r.get("status") == "blocked"]
    failures = list(manifest.get("probe_failures", {}).values())
    return bool(blocked or failures) and all(
        r.get("failure") == "infrastructure" and "GPU capacity gate failed" in str(r.get("error", ""))
        and not r.get("model_calls") for r in blocked
    ) and all(f.get("status") == "infrastructure"
              and "GPU capacity gate failed" in str(f.get("error") or f.get("reason") or "")
              for f in failures
              ) and not manifest.get("profile_blocks")


def run(source_path: Path, output: Path, *, wait_for_capacity: bool = False) -> dict[str, Any]:
    source, original = load_completed_source(source_path)
    if output.resolve() == source_path.resolve():
        raise ValueError("repair output must differ from historical source")
    campaign.PROTOCOL = runtime.PROTOCOL = PROTOCOL
    models = source["immutable"]["models"]
    adapter = RepairRuntime(models, source_path)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "repair.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("repair campaign is already running") from exc
        prior_path = output / 'manifest.json'
        prior = json.loads(prior_path.read_text()) if prior_path.is_file() else None
        expectations = (prior['immutable']['runtime_expectations'] if prior
                        else daily_contract(runtime.LAB))
        runtime.configure_runtime_contract(expectations)
        expected = build_manifest(source_path, source, adapter, expectations)
        manifest = campaign._load_or_create_manifest(output, expected)
        rows = campaign.load_records(output)
        adapter.configure_gpu_free_floor_mib(7000)
        validation = adapter.validate_environment()
        if not validation.get("passed"):
            raise ValueError(f"repair environment invalid: {validation}")
        campaign._freeze_runtime_versions(manifest, validation["runtime_versions"])
        manifest["environment_validation"] = validation
        try:
            while True:
                manifest["operator_retry_blocked"] = True
                manifest["status"] = "running"
                manifest.pop("error", None)
                manifest.pop("failure", None)
                campaign._save_manifest(output, manifest, rows=rows)
                try:
                    manifest["status"] = execute_stages(source, original, output=output, rows=rows,
                                                        manifest=manifest, adapter=adapter)
                    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
                    break
                except campaign.CampaignBlocked as exc:
                    manifest["status"] = "blocked"
                    manifest["error"] = str(exc)
                    campaign._save_manifest(output, manifest, rows=rows)
                    _write_comparison(output, original, rows)
                    if not wait_for_capacity or not capacity_block(manifest, rows):
                        break
                    time.sleep(15)
        except KeyboardInterrupt:
            manifest["status"] = "interrupted"
        finally:
            campaign._save_manifest(output, manifest, rows=rows)
            campaign._write_summaries(output, rows, tasks)
            _write_comparison(output, original, rows)
            campaign._write_recommendation(output, manifest, rows)
        return manifest


def execute_prepared_round(args) -> int:
    """Hold the lab admission lock across update, validation and inference."""
    state = runtime.LAB / 'state'
    state.mkdir(exist_ok=True, parents=True)
    with (state / 'practical-round.lock').open('a') as admission:
        try:
            fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another practical round owns the laboratory') from exc
        for proc in Path('/proc').glob('[0-9]*/comm'):
            try:
                if proc.read_text().strip() == 'llama-server':
                    raise ValueError('a llama-server is active; stop it before updating the runtime')
            except OSError:
                continue
        prior_path = args.output / 'manifest.json'
        prior = json.loads(prior_path.read_text()) if prior_path.is_file() else {}
        if not prior.get('runtime_versions'):
            subprocess.run(['bash', str(runtime.ROOT / 'scripts/00_update_runtime.sh')], check=True)
            runtime.configure_runtime_contract(daily_contract(runtime.LAB))
            print('Validating updated OpenCode, MCP, Python and JavaScript before GPU use...', flush=True)
            subprocess.run([str(runtime.LAB / 'envs/lab-validation/bin/python'), '-m', 'pytest', '-q',
                            'tests/test_practical_flows_v2.py', 'tests/test_practical_integration_v2.py',
                            'tests/test_practical_tool_guard.py'], cwd=runtime.ROOT,
                           env={**os.environ, 'RUN_PRACTICAL_INTEGRATION': '1'}, check=True)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        result = run(args.source, args.output, wait_for_capacity=args.wait_for_capacity)
        print(json.dumps({'status': result['status'], 'output': str(args.output)}))
        return 0 if result['status'] == 'complete' else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument("--wait-for-capacity", action="store_true")
    args = parser.parse_args()
    source, _ = load_completed_source(args.source)
    if not args.execute:
        pending = []
        prior_path = args.output / 'manifest.json'
        try:
            prior = json.loads(prior_path.read_text()) if prior_path.is_file() else None
            expectations = (prior['immutable']['runtime_expectations'] if prior else daily_contract(runtime.LAB))
            runtime.configure_runtime_contract(expectations)
        except (ValueError, KeyError) as exc:
            pending.append(str(exc))
        adapter = RepairRuntime(source['immutable']['models'], args.source)
        validation = adapter.validate_environment()
        if not validation.get('passed'):
            pending.append(validation.get('reason', 'runtime validation failed'))
        try:
            adapter.configure_gpu_free_floor_mib(7000)
            runtime._model_start_preflight(runtime.LAB)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            pending.append(str(exc))
        review_state = {}
        campaign._load_task_quarantines(runtime.LAB, review_state)
        if review_state.get('task_quarantines'):
            pending.append('tasks require review: ' + ', '.join(sorted(review_state['task_quarantines'])))
        print(json.dumps({'protocol': PROTOCOL, 'ready': not pending, 'pending': pending,
                          'baseline_episodes': 75, 'maximum_episodes': 93, 'output': str(args.output),
                          'runtime_validation': validation, 'affected_tasks': sorted(AFFECTED_TASKS),
                          'integration_before_execution': True, 'inference': False}, indent=2))
        return 0 if not pending else 2
    if args.prepare:
        parser.error('--prepare and --execute are mutually exclusive')
    return execute_prepared_round(args)


if __name__ == "__main__":
    raise SystemExit(main())
