"""Prepare the independent-copy M1 campaign; execution requires --execute."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_runtime_v2 as runtime
from benchmark import practical_tasks_v2 as tasks
from benchmark.practical_queue import QueueRuntime
from benchmark.practical_policy import BudgetPolicy
from benchmark.practical_manual import manual_evidence
from benchmark.practical_evidence import paired_task_summary, outcome_summary

PROTOCOL = "practical-agent-limits-skills-v9-m1-independent"
REVIEW_TASKS = ("B2", "C2", "M1")
DEFAULT_TASKS = ('M1',)
DEFAULT_CONTRACTS = {'M1':tasks.M1_INDEPENDENT_CONTRACT}
SOURCE_MANIFEST = runtime.LAB / "results/practical-selection-7bplus-corrected-v3/manifest.json"
DEFAULT_OUTPUT = runtime.LAB / 'results' / PROTOCOL
CPU_REPORT = runtime.ROOT / 'results/reports/limits-skills-v9-m1-independent-cpu.json'


def frozen_models(source_manifest: Path = SOURCE_MANIFEST) -> dict:
    source = json.loads(Path(source_manifest).read_text())
    if source.get("protocol_id") != "practical-agent-selection-7bplus-corrected-v3":
        raise ValueError("review replay source must be the corrected-v3 manifest")
    models = source.get("immutable", {}).get("models")
    expected = {"bonsai-2-27b", "bonsai-2-9b", "gemma-4-12b", "ornith-1.0-9b", "qwen3.5-9b"}
    if not isinstance(models, dict) or set(models) != expected:
        raise ValueError("corrected-v3 model contracts do not match the frozen five-model matrix")
    return models


class LimitsRuntime(QueueRuntime):
    stop_on_infrastructure = True

    def check_model_admission(self):
        if _active_llama_servers():
            raise campaign.CampaignBlocked('a model server remains active; next model cannot load safely')

    def __init__(self, models, mode='benchmark', with_skills=True, budget_multiplier=1, task_contracts=None):
        super().__init__(models, SOURCE_MANIFEST)
        self.mode = mode
        self.with_skills, self.budget_multiplier = with_skills, budget_multiplier
        self.task_contracts = dict(DEFAULT_CONTRACTS if task_contracts is None else task_contracts)
        self.PROVENANCE_SOURCE_PATHS = (*self.PROVENANCE_SOURCE_PATHS, Path(__file__))

    def run_episode(self, *args, **kwargs):
        kwargs.setdefault('task_contract_id',self.task_contracts.get(args[1],tasks.HISTORICAL_CONTRACT))
        return runtime.run_episode(*args, **kwargs, policy_mode=self.mode,
                                   with_skills=self.with_skills, budget_multiplier=self.budget_multiplier)


def make_adapter(models, mode='benchmark', with_skills=True, budget_multiplier=1, task_contracts=None):
    return LimitsRuntime(models, mode, with_skills, budget_multiplier, task_contracts)


def frozen_expectations():
    return json.loads(SOURCE_MANIFEST.read_text())['immutable']['runtime_expectations']


def _active_llama_servers() -> list[str]:
    """Running llama-server processes, wherever they were started."""
    servers = []
    for proc in Path('/proc').glob('[0-9]*/comm'):
        try:
            if proc.read_text(errors='ignore').strip() == 'llama-server':
                servers.append(str(proc))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return servers


@contextmanager
def _laboratory_ownership():
    state=runtime.LAB/'state'
    state.mkdir(parents=True,exist_ok=True)
    with (state/'practical-round.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise campaign.CampaignBlocked('another practical round owns the laboratory') from exc
        if _active_llama_servers():
            raise campaign.CampaignBlocked('a model server is active')
        yield


class _CapacityProbe:
    """Readiness probe with zero model calls and no server lifecycle change.

    It only observes: an active llama-server holding capacity, and the GPU
    start preflight. Failures are infrastructure reasons, never verdicts
    about a model.
    """

    def __init__(self, lab: Path | None = None):
        self.lab = runtime.LAB if lab is None else Path(lab)
        self.reason: str | None = None

    def __call__(self) -> bool:
        servers = _active_llama_servers()
        if servers:
            self.reason = 'a model server is active; prepared queue must remain stopped'
            return False
        try:
            runtime._model_start_preflight(self.lab)
        except (RuntimeError, OSError) as exc:
            self.reason = 'capacity preflight: ' + str(exc)
            return False
        self.reason = None
        return True


def _capacity_probe(lab=None) -> _CapacityProbe:
    return _CapacityProbe(lab)


def select_recovery(source, schedule, models):
    source = Path(source).resolve()
    manifest_path = source/'manifest.json'
    original = json.loads(manifest_path.read_text())
    if original.get('status') not in {'complete', 'review_required', 'blocked', 'interrupted'}:
        raise ValueError('recovery source must be stopped')
    if original.get('immutable', {}).get('models') != models:
        raise ValueError('recovery requires the same frozen model catalogue')
    condition = original.get('immutable', {})
    expected_contracts = {e['task']:e.get('task_contract_id',tasks.HISTORICAL_CONTRACT) for e in schedule}
    for task in {tuple(e['identity'])[3] for e in original.get('stage_schedules',{}).get('baseline',[])}:
        if condition.get('task_contracts',{}).get(task,tasks.HISTORICAL_CONTRACT) != expected_contracts.get(task):
            raise ValueError('recovery requires matching task contracts; a new task cannot inherit old completions')
    if (condition.get('run_mode', 'benchmark') != 'benchmark'
            or condition.get('with_skills', True) is not True
            or condition.get('budget_multiplier', 1) != 1):
        raise ValueError('recovery requires matching baseline conditions')
    planned = original.get('stage_schedules', {}).get('baseline', [])
    qualified = {tuple(e['identity']) for e in planned}
    if any(identity[0] != original['protocol_id'] for identity in qualified):
        raise ValueError('recovery source schedule contains a foreign protocol')
    identities = {tuple(e['identity'][1:]) for e in planned}
    available = {campaign.episode_key(e)[1:] for e in schedule}
    if not identities or not identities <= available or len(identities) != len(planned):
        raise ValueError('invalid recovery source schedule')
    rows = campaign.load_records(source)
    if any(campaign.episode_key(e) not in qualified for e in rows):
        raise ValueError('recovery source contains foreign episode records')
    completed = {campaign.episode_key(e)[1:] for e in rows if e.get('status') == 'complete'}
    selected = [e for e in schedule if campaign.episode_key(e)[1:] in identities-completed]
    selected.sort(key=lambda episode: campaign.episode_key(episode)[1:])
    if not selected:
        raise ValueError('no pending episodes to recover')
    return selected, {'source_output': str(source), 'source_protocol':original['protocol_id'],
        'manifest_sha256':runtime._sha256(manifest_path),
        'ancestor_recovery':original.get('immutable', {}).get('recovery'),
        'records_sha256':campaign._hash_value(rows), 'previous_complete':len(completed & identities),
        'selected': [list(campaign.episode_key(e)[1:]) for e in selected],
        'rule':'Only missing or non-complete episodes; completed model failures are retained.'}


def build_replay(models=None, runtime_expectations=None, mode='benchmark', with_skills=True, budget_multiplier=1, recovery_from=None, *, task_ids=None, task_contracts=None):
    if budget_multiplier not in (1, 2, 4) or (mode == 'operational' and budget_multiplier != 1):
        raise ValueError('calibration multipliers require benchmark mode')
    models = models or frozen_models()
    chosen = tuple(DEFAULT_TASKS if task_ids is None else task_ids)
    if not chosen or len(set(chosen))!=len(chosen) or any(t not in tasks.ALL_TASKS for t in chosen):
        raise ValueError('selected tasks must be nonempty, unique, and known')
    contracts = {t:tasks.resolve_task_contract(t,
        (task_contracts or {}).get(t,DEFAULT_CONTRACTS.get(t) if task_ids is None else None)) for t in chosen}
    base = PROTOCOL if chosen==DEFAULT_TASKS and contracts==DEFAULT_CONTRACTS else (
        'practical-agent-limits-skills-v9-taskset-'+campaign._hash_value([chosen,contracts])[:12])
    protocol = base + ('-recovery' if recovery_from else '') + ('-operational' if mode == 'operational' else '') + ('-core-only' if not with_skills else '') + (f'-budget-{budget_multiplier}x' if budget_multiplier != 1 else '')
    campaign.PROTOCOL = runtime.PROTOCOL = protocol
    task_module = SimpleNamespace(**vars(tasks))
    task_module.TASKS = chosen
    task_module.HOLDOUTS = ()
    task_module.TASK_CONTRACTS = contracts
    task_module.TASK_SPECS = {t: {**s, 'base_max_requests':s['max_requests'], 'seconds':s['seconds']*budget_multiplier,
                               'max_requests':s['max_requests']*budget_multiplier} for t,s in tasks.TASK_SPECS.items()}
    task_module.seed_task = lambda task, workspace: tasks.seed_task(task, workspace, with_skills=with_skills,task_contract_id=contracts.get(task))
    task_module.checks_source = lambda task, phase=1: tasks.checks_source(task,phase,task_contract_id=contracts.get(task))
    task_module.reference_files = lambda task, variant=0, phase=1: tasks.reference_files(task,variant,phase,task_contract_id=contracts.get(task))
    expected = campaign.build_manifest(models, tasks_module=task_module, runtime_module=make_adapter(models, mode, with_skills, budget_multiplier,contracts),
                                        gpu_free_floor_mib=7000)
    schedule = campaign.baseline_schedule(tuple(models), tasks=chosen, protocol=protocol,task_contracts=contracts)
    if recovery_from:
        if mode != 'benchmark' or not with_skills or budget_multiplier != 1:
            raise ValueError('recovery preserves the baseline benchmark condition')
        schedule, recovery = select_recovery(recovery_from, schedule, models)
        expected['immutable']['recovery'] = recovery
    selected_tasks = tuple(dict.fromkeys(e['task'] for e in schedule))
    immutable = expected["immutable"]
    immutable['task_contracts'] = contracts
    immutable['policy_version'] = 'limits-skills-v2'
    immutable['worker_isolation'] = {'minimum_landlock_abi':4,'candidate_executes_checks':False,
                                     'process_inspection':'denied','candidate_network':'denied'}
    immutable['test_reserve_seconds'] = {t:25 if task_module.TASK_SPECS[t]['language']!='mcp' else 5 for t in chosen}
    immutable['preparation'] = {
        'maximum_profile_probes':len(models),'scored':False,
        'probe_policy':BudgetPolicy.for_task({'max_requests':5,'seconds':75}).as_dict(),
        'probe_repetition':1,'probe_output_tokens':4096,
        'probe_resume':'reuse recorded passed or capability_diagnostic for the same model/profile',
        'warmup':'pinned server startup defaults only; no separate scored warmup task',
        'cost_evidence':'probe model_calls/model_call_requests, startup log and load_seconds; excluded from scored episodes',
        'prepare_starts_inference':False}
    immutable["review_replay"] = {
        "source_protocol": "practical-agent-selection-7bplus-corrected-v3",
        "source_manifest": str(SOURCE_MANIFEST),
        "tasks": list(selected_tasks), "repetitions": sorted({e['repetition'] for e in schedule}),
        "episodes": len(schedule),
    }
    immutable['run_mode'] = mode
    immutable['with_skills'], immutable['budget_multiplier'] = with_skills, budget_multiplier
    immutable['policies'] = {t: BudgetPolicy.for_task(task_module.TASK_SPECS[t], mode=mode).as_dict() for t in chosen}
    immutable['manual_hashes'] = {t: manual_evidence(t, with_skills=with_skills) for t in chosen}
    immutable["runtime_expectations"] = runtime_expectations or frozen_expectations()
    immutable["schedule"] = {
        "review_replay_tasks": list(selected_tasks),
        "review_replay_episodes": len(schedule), 'maximum_episodes': len(schedule),
        "maximum_seconds": sum(int(task_module.TASK_SPECS[e['task']]['seconds']) for e in schedule)
        * (2 if mode == 'operational' else 1),
    }
    expected["immutable_sha256"] = campaign._hash_value(immutable)
    expected["stage_status"] = {"baseline": "pending"}
    expected['stage_schedules'] = {'baseline': [{'identity': list(campaign.episode_key(e)),
                                               'profile_config': e['profile_config'],
                                               'task_contract_id':e['task_contract_id']} for e in schedule]}
    return expected, schedule


def cpu_evidence_current(expected):
    if not CPU_REPORT.is_file():
        return False
    try:
        value = json.loads(CPU_REPORT.read_text())
    except (OSError, ValueError):
        return False
    return (value.get('passed') is True
            and value.get('source_digest') == campaign._hash_value(expected['immutable']['source_hashes'])
            and bool(expected.get('immutable_sha256'))
            and value.get('immutable_sha256') == expected['immutable_sha256'])


def prepare(output=DEFAULT_OUTPUT, mode='benchmark', *, verify_assets=True, with_skills=True, budget_multiplier=1, recovery_from=None, _admission_held=False):
    if not _admission_held:
        with _laboratory_ownership():
            return prepare(output,mode,verify_assets=verify_assets,with_skills=with_skills,
                budget_multiplier=budget_multiplier,recovery_from=recovery_from,_admission_held=True)
    expected, schedule = build_replay(mode=mode, with_skills=with_skills, budget_multiplier=budget_multiplier, recovery_from=recovery_from)
    runtime.configure_runtime_contract(expected['immutable']['runtime_expectations'])
    adapter = make_adapter(expected['immutable']['models'], mode, with_skills, budget_multiplier)
    pending, assets, capacity_pending = [], {}, []
    validation = adapter.validate_environment()
    if validation.get('passed') is not True:
        pending.append(validation.get('reason', 'invalid runtime'))
    runtime.configure_gpu_free_floor_mib(7000)
    probe = _capacity_probe()
    if not probe():
        capacity_pending.append(probe.reason)
    for name, contract in adapter.models.items():
        path = runtime.LAB / contract['path']
        passed = path.is_file() and (not verify_assets or runtime._sha256(path) == contract['sha256'])
        assets[name] = {'present': path.is_file(), 'hash_verified': passed if verify_assets else None}
        if not passed:
            pending.append('missing or mismatched model asset: ' + name)
    review_state = {}
    campaign._load_task_quarantines(runtime.LAB, review_state)
    if review_state.get('task_quarantines'):
        pending.append('unresolved task reviews: ' + ','.join(review_state['task_quarantines']))
    if not cpu_evidence_current(expected):
        pending.append('CPU validation missing, failed or stale')
    engineering = not pending
    if engineering:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        with (output/'review-replay.lock').open('a') as ownership:
            try:
                fcntl.flock(ownership,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise campaign.CampaignBlocked('review replay is already running') from exc
            manifest = campaign._load_or_create_manifest(output, expected)
            campaign._save_manifest(output, manifest, rows=campaign.load_records(output))
    return {'protocol': expected['protocol_id'], 'engineering_ready': engineering, 'comparison_ready': False,
            'execution_capacity_ready': not capacity_pending, 'capacity_pending': capacity_pending,
            'inference_smoke_pending': True, 'ready': engineering, 'pending': pending,
            'models': assets, 'tasks': expected['immutable']['review_replay']['tasks'], 'episodes': len(schedule),
            'output': str(output), 'mode': mode, 'inference': False}


def _archive_stale_error(manifest: dict) -> None:
    """Move a superseded error out of the active status field, keep history."""
    error = manifest.get('error')
    if not error:
        return
    resolved = list(manifest.get('resolved_errors') or [])
    resolved.append({
        'resolved_at_utc': datetime.now(timezone.utc).isoformat(),
        'error': error,
        'status': manifest.get('status'),
    })
    manifest['resolved_errors'] = resolved
    manifest['error'] = None


class _AuthorizationAudit:
    """Append-only log of every blocked-retry authorization decision.

    Opened only while the caller holds the replay lock; ``authorization-in-use.json``
    is the live marker for operators, removed exactly once at close.
    """

    def __init__(self, output: Path):
        self.path = Path(output) / 'authorization-audit.jsonl'
        self.backup = Path(output) / 'authorization-in-use.json'

    def _emit(self, event: dict) -> None:
        line = json.dumps(event, sort_keys=True, ensure_ascii=False)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(line + '\n')

    def open(self, *, retry_blocked: bool) -> None:
        self._emit({
            'event': 'opened', 'at_utc': datetime.now(timezone.utc).isoformat(),
            'retry_blocked': bool(retry_blocked), 'pid': os.getpid(),
        })
        campaign.atomic_write_json(self.backup, {
            'at_utc': datetime.now(timezone.utc).isoformat(),
            'retry_blocked': bool(retry_blocked), 'pid': os.getpid(),
        })

    def event(self, name: str, **fields) -> None:
        self._emit({'event': name, 'at_utc': datetime.now(timezone.utc).isoformat(), **fields})

    def close(self, *, status: str | None = None, error: str | None = None) -> None:
        self._emit({
            'event': 'closed', 'at_utc': datetime.now(timezone.utc).isoformat(),
            'status': status, 'error': error,
        })
        self.backup.unlink(missing_ok=True)


def run(output: Path = DEFAULT_OUTPUT, *, mode='benchmark', with_skills=True, budget_multiplier=1,
        recovery_from=None, retry_blocked=False, continue_model_blocks=False, _admission_held=False) -> dict:
    if not _admission_held:
        with _laboratory_ownership():
            return run(output,mode=mode,with_skills=with_skills,budget_multiplier=budget_multiplier,
                recovery_from=recovery_from,retry_blocked=retry_blocked,
                continue_model_blocks=continue_model_blocks,_admission_held=True)
    output = Path(output)
    prior_path = output / "manifest.json"
    prior = json.loads(prior_path.read_text()) if prior_path.is_file() else {}
    expectations = (prior.get("immutable", {}).get("runtime_expectations")
                    or frozen_expectations())
    expected, schedule = build_replay(runtime_expectations=expectations, mode=mode, with_skills=with_skills, budget_multiplier=budget_multiplier, recovery_from=recovery_from)
    adapter = make_adapter(expected['immutable']['models'], mode, with_skills, budget_multiplier)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "review-replay.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise campaign.CampaignBlocked("review replay is already running") from exc
        audit = _AuthorizationAudit(output)
        manifest: dict = {}
        rows: list = []
        # Ownership starts only after the authorization gate: a refusal must
        # leave the manifest and records byte-identical.
        enforceable = False
        try:
            audit.open(retry_blocked=retry_blocked)
            manifest = campaign._load_or_create_manifest(output, expected)
            rows = campaign.load_records(output)
            if manifest.get("status") == "complete":
                return manifest
            if manifest.get("status") == "blocked" and not retry_blocked:
                audit.event('refused', status='blocked', error=manifest.get('error'),
                            detail='a blocked replay continues only once, with explicit --retry-blocked')
                raise campaign.CampaignBlocked(
                    "review replay is blocked; rerun once with --retry-blocked")
            _archive_stale_error(manifest)
            manifest["operator_retry_blocked"] = bool(retry_blocked)
            enforceable = True
            runtime.configure_runtime_contract(expectations)
            runtime.configure_gpu_free_floor_mib(7000)
            validation = adapter.validate_environment(lab=runtime.LAB)
            if validation.get("passed") is not True:
                raise campaign.CampaignBlocked(f"review replay environment invalid: {validation}")
            campaign._freeze_runtime_versions(manifest, validation["runtime_versions"])
            manifest["environment_validation"] = validation
            manifest["status"] = "running"
            campaign._save_manifest(output, manifest, rows=rows)
            if not continue_model_blocks:
                for name in dict.fromkeys(e['model'] for e in schedule):
                    if not campaign._profile_probe(name, campaign.BASELINE_PROFILE, output=output,
                         manifest=manifest, runtime=adapter, lab=runtime.LAB, transient_skips=set(), rows=rows):
                        raise campaign.CampaignBlocked('profile probe failed: ' + name)
            manifest['continue_model_blocks'] = bool(continue_model_blocks)
            passed = campaign._run_stage("baseline", schedule, output=output, rows=rows,
                                manifest=manifest, runtime=adapter, models=adapter.models,
                                lab=runtime.LAB, tasks_module=tasks,
                                **({'continue_model_blocks':True} if continue_model_blocks else {}))
            done = passed and campaign._all_scheduled_complete(manifest, rows)
            manifest["status"] = "complete" if done else "review_required"
            if done:
                manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        except campaign.CampaignBlocked as exc:
            # Without ownership (the authorization refusal) the on-disk state
            # stays exactly as the owner left it; the refusal lives in the audit.
            if enforceable:
                manifest.update(status='blocked', error=str(exc))
        except KeyboardInterrupt:
            manifest["status"] = "interrupted"
            manifest["interrupted_at_utc"] = datetime.now(timezone.utc).isoformat()
        finally:
            audit.close(status=manifest.get('status') if manifest else None,
                        error=manifest.get('error') if manifest else None)
            if enforceable:
                campaign._save_manifest(output, manifest, rows=rows)
                campaign._write_summaries(output, rows, tasks)
                campaign.atomic_write_json(output/'task-reliability.json', {
                    'coverage_complete': campaign._all_scheduled_complete(manifest, rows),
                    'outcomes': outcome_summary(rows, schedule),
                    'task_cells': paired_task_summary(rows), 'general_winner_supported': False})
        return manifest


def execute_prepared(output: Path, mode='benchmark', with_skills=True, budget_multiplier=1,
                     recovery_from=None, *, retry_blocked=False, continue_model_blocks=False) -> int:
    state = runtime.LAB / "state"
    state.mkdir(exist_ok=True, parents=True)
    with (state / "practical-round.lock").open("a") as admission:
        try:
            fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise campaign.CampaignBlocked("another practical round owns the laboratory") from exc
        if _active_llama_servers():
            raise campaign.CampaignBlocked("a llama-server is active")
        check = prepare(output, mode, with_skills=with_skills, budget_multiplier=budget_multiplier, recovery_from=recovery_from,_admission_held=True)
        if not check['engineering_ready']:
            print(json.dumps(check, indent=2))
            return 2
        # Preparation wait, not model budget: no inference call happens here
        # and the probe never starts, stops or retunes a server.
        probe = _capacity_probe()
        started_at = datetime.now(timezone.utc).isoformat()
        clock_started = time.monotonic()
        ready = runtime.capacity_guard(probe)
        report = {
            'started_at_utc': started_at,
            'finished_at_utc': datetime.now(timezone.utc).isoformat(),
            'waited_seconds': round(time.monotonic() - clock_started, 3),
            'poll_seconds': runtime.CAPACITY_POLL_SECONDS,
            'stable_samples_required': runtime.CAPACITY_STABLE_SAMPLES,
            'ready': ready,
            'outcome': 'ready' if ready else 'probe_never_ready',
            'note': (probe.reason
                     or f'laboratory capacity stayed ready for {runtime.CAPACITY_STABLE_SAMPLES} samples'),
        }
        campaign.atomic_write_json(Path(output) / 'capacity-wait.json', report)
        if not ready and not continue_model_blocks:
            print(json.dumps(report, indent=2))
            return 2
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        result = run(output, mode=mode, with_skills=with_skills, budget_multiplier=budget_multiplier,
                                recovery_from=recovery_from, retry_blocked=retry_blocked,
                                **({'continue_model_blocks':True} if continue_model_blocks else {}),
                                _admission_held=True)
        print(json.dumps({"status": result["status"], "output": str(output)}), flush=True)
        return 0 if result["status"] == "complete" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--execute", action="store_true")
    group.add_argument("--prepare", action="store_true")
    parser.add_argument('--mode', choices=('benchmark', 'operational'), default='benchmark')
    parser.add_argument('--skills', choices=('on','off'), default='on')
    parser.add_argument('--budget-multiplier', type=int, choices=(1,2,4), default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument('--recover-from', type=Path, help='Stopped source campaign; retry only missing/non-complete episodes')
    parser.add_argument('--retry-blocked', action='store_true',
                        help='authorize one replay continuation of a blocked manifest')
    parser.add_argument('--continue-model-blocks', action='store_true',
                        help='record a blocked model and attempt remaining models once; preserve all safety gates')
    args = parser.parse_args()
    if args.mode == 'operational' and args.budget_multiplier != 1:
        parser.error('operational mode already has its own bounded extensions')
    expected, _ = build_replay(mode=args.mode, with_skills=args.skills=='on', budget_multiplier=args.budget_multiplier, recovery_from=args.recover_from)
    output = args.output or DEFAULT_OUTPUT.with_name(expected['protocol_id'])
    if args.execute:
        return execute_prepared(output, args.mode, args.skills=='on', args.budget_multiplier,
                                args.recover_from, retry_blocked=args.retry_blocked,
                                continue_model_blocks=args.continue_model_blocks)
    result = prepare(output, args.mode, with_skills=args.skills=='on', budget_multiplier=args.budget_multiplier, recovery_from=args.recover_from)
    print(json.dumps(result, indent=2))
    return 0 if result['engineering_ready'] else 2


if __name__ == "__main__":
    raise SystemExit(main())
