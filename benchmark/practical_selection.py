"""Resumable, short local-agent selection using CPython and real MCP stdio."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import statistics
import subprocess
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath

from benchmark import campaign_readiness, model_candidate_screen, model_quality_paired, practical_tasks, safe_campaign
from benchmark.linux_sandbox import ResourceLimits, RuntimeBind, SandboxSpec, SandboxSupervisor
from benchmark.model_broker import BrokerPolicy

ROOT = Path(__file__).resolve().parents[1]
LAB = Path('/home/foxtrot/local-llm-benchmark')
DEFAULT_OUTPUT = LAB / 'results/practical-selection-v1-r1'
PROTOCOL = 'practical-agent-selection-v1'
GENERATION = {'temperature': 0, 'seed': 1234, 'max_tokens': 2048}
STAGES = (('bugfix', 'feature', 'mcp_report'), ('recovery', 'maintenance', 'continuation'))


def contracts():
    from benchmark.ornith9b_coding_probe import MODEL

    base = {key: dict(value) for key, value in model_quality_paired.MODELS.items()}
    base['ornith-1.0-9b'] = dict(MODEL)
    base['granite-4.2-8b'] = json.loads(model_candidate_screen.CONFIG_PATH.read_text())['models']['granite-4.2-8b']
    base['gemma-4-12b'] = {
        'alias': 'gemma-4-12b-it-qat-q4_0', 'path': 'models/gguf/gemma-4-12b/gemma-4-12b-it-qat-q4_0.gguf',
        'revision': 'local-artifact-origin-unresolved',
        'sha256': 'faff1a63667fac17ac5e777f47114688fcefea96e220e211aaa8d62c2c4561f1',
    }
    return base


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def completed_keys(rows):
    return {(r['model'], r['task']) for r in rows if r.get('failure') != 'infrastructure'}


def load_records(output):
    """Recover a completed task even if interrupted before aggregate save."""
    path = output / 'records.json'
    rows = json.loads(path.read_text()) if path.exists() else []
    recorded = {r.get('run_dir') for r in rows}
    for record in sorted((output / 'runs').glob('*/record.json')):
        row = json.loads(record.read_text())
        if row.get('run_dir') not in recorded:
            rows.append(row)
    return rows


def preflight(lab):
    from benchmark.opencode_controlled_probe import _assert_free_resources

    _assert_free_resources(lab)
    result = subprocess.run(['/usr/lib/wsl/lib/nvidia-smi', '--query-gpu=memory.free,memory.total',
                             '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10, check=True)
    free, total = [int(v.strip()) for v in result.stdout.splitlines()[0].split(',')]
    if free < 7168 or total < 8192:
        raise RuntimeError(f'GPU capacity: {free} MiB free; need 7168 MiB before loading')


def restore_archived_models(models, lab):
    """Restore the known cold-archive asset only; never download or overwrite weights."""
    archived = {'qwen3.5-4b': Path('/mnt/e/LocalLLMLabArchive/models/bartowski-Qwen_Qwen3.5-4B-GGUF') /
                '4168f45a16a1290d65a4ec0fa312ae917a4c15d6/Qwen_Qwen3.5-4B-Q4_K_M.gguf'}
    for model, contract in models.items():
        target = lab / contract['path']
        if target.is_file():
            continue
        source = archived.get(model)
        if source is None or not source.is_file():
            raise RuntimeError(f'missing local model: {model}; no download attempted')
        if shutil.disk_usage(lab).free - source.stat().st_size < 8 * 1024**3:
            raise RuntimeError(f'not enough SSD space to restore {model} with 8 GiB remaining')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.restoring')
        print(json.dumps({'restoring_from_archive': model}), flush=True)
        shutil.copyfile(source, temporary)
        if campaign_readiness._sha256_file(temporary) != contract['sha256']:
            raise RuntimeError(f'archive copy hash mismatch: {model}')
        if target.exists():
            raise RuntimeError('target appeared during restore; refusing overwrite')
        temporary.replace(target)


def rank_models(rows):
    groups = {}
    for row in rows:
        if row.get('failure') == 'infrastructure' or 'seconds' not in row:
            continue
        groups.setdefault(row['model'], []).append(row)
    result = []
    for model, items in groups.items():
        good = [r for r in items if r.get('correct') and r.get('autonomous')]
        result.append({'model': model, 'completed': len(good), 'attempted': len(items),
                       'code_correct': sum(bool(r.get('correct')) for r in items),
                       'total_seconds': round(sum(r['seconds'] for r in items), 3),
                       'median_success_seconds': round(statistics.median(r['seconds'] for r in good), 3) if good else None,
                       'tool_errors': sum(r.get('tool_errors', 0) for r in items),
                       'vram_mib': max((r.get('vram_mib') or 0 for r in items), default=0) or None,
                       'ram_mib': max((r.get('ram_mib') or 0 for r in items), default=0) or None})
    return sorted(result, key=lambda r: (-r['completed'], r['total_seconds'], r['vram_mib'] or float('inf')))


def extract_snapshot(raw, target):
    """Extract only bounded regular workspace files; never execute them on host."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 512 or sum(m.file_size for m in members) > 8 * 1024**2:
            raise ValueError('workspace snapshot too large')
        names = set()
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename
                    or member.filename in names or (mode & 0o170000) == 0o120000):
                raise ValueError('invalid snapshot path')
            names.add(member.filename)
        for member in members:
            path = target / member.filename
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member))


def profile(model, models):
    value = model_candidate_screen._profile_for_model(model, models)
    value['agent']['build']['steps'] = 30
    value['provider']['local']['options']['baseURL'] = 'http://127.0.0.1:18888/v1'
    value['provider']['local']['models'][models[model]['alias']]['limit']['output'] = 2048
    value['mcp'] = {'lab': {'type': 'local', 'command': ['/usr/bin/python3', '-B',
                      '/opt/practical/mcp.py', '/scratch/practical-mcp-state.json'], 'enabled': True, 'timeout': 10000}}
    value['permission'] = {'*': 'allow', 'task': 'deny', 'external_directory': 'deny',
                           'webfetch': 'deny', 'websearch': 'deny', 'question': 'deny'}
    return value


def run_agent(workspace, run_dir, model, models, prompts, *, lab=LAB, upstream_port=8080, seconds=300):
    binary = lab / 'envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode'
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'broker').mkdir(mode=0o700, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='practical-runtime-') as temp:
        runtime = Path(temp)
        shutil.copyfile(ROOT / 'benchmark/practical_driver.py', runtime / 'driver.py')
        shutil.copyfile(ROOT / 'benchmark/practical_mcp.py', runtime / 'mcp.py')
        write_json(runtime / 'driver.json', {'model': f"local/{models[model]['alias']}",
                                           'prompts': prompts, 'seconds': seconds - 20})
        write_json(runtime / 'opencode.json', profile(model, models))
        limits = replace(safe_campaign._agent_limits(), wall_seconds=seconds, cpu_seconds=seconds + 30,
                         output_bytes=1024**2, export_file_bytes=8 * 1024**2, export_total_bytes=20 * 1024**2,
                         memory_bytes=3 * 1024**3, scratch_bytes=512 * 1024**2)
        spec = SandboxSpec(
            argv=('/usr/bin/python3', '-B', '/opt/practical/driver.py'), workspace=workspace,
            workspace_exports=('.practical.json', '.snapshot1.zip', '.snapshot2.zip'),
            runtime_ro=campaign_readiness._runtime_binds(benchmark_root=lab, opencode_binary=binary,
                                                        include_provider=True) +
                       (RuntimeBind(runtime, '/opt/practical'),),
            env={'OPENCODE_CONFIG': '/opt/practical/opencode.json', 'OPENCODE_DISABLE_AUTOUPDATE': '1',
                 'PYTHONDONTWRITEBYTECODE': '1'}, limits=limits,
            broker=BrokerPolicy(upstream_port=upstream_port, model_allowlist=(models[model]['alias'],),
                                output_token_cap=2048, frozen_generation=GENERATION, max_requests=30,
                                deadline_seconds=min(seconds, 180)),
            broker_transcript_dir=run_dir / 'broker',
        )
        result = SandboxSupervisor().run(spec)
    (run_dir / 'native.jsonl').write_bytes(result.output)
    for name, raw in result.workspace_outputs.items():
        (run_dir / name).write_bytes(raw)
    write_json(run_dir / 'execution.json', {
        'returncode': result.returncode, 'timed_out': result.timed_out,
        'infrastructure_error': result.infrastructure_error, 'cleanup_verified': result.cleanup_verified,
        'resource_evidence': dict(result.resource_evidence),
        'broker_events': [e.__dict__ for e in result.broker_events]})
    return result


def grade(workspace, task, *, phase=1, output=None):
    """Real CPython, fresh namespace; acceptance tests never mounted during agent run."""
    with tempfile.TemporaryDirectory(prefix='practical-checks-') as temp:
        runtime = Path(temp)
        (runtime / 'checks.py').write_text(practical_tasks.checks_source(task, phase=phase))
        limits = ResourceLimits(wall_seconds=30, cpu_seconds=25, memory_bytes=512 * 1024**2,
                                swap_bytes=128 * 1024**2, pids=32)
        result = SandboxSupervisor().run(SandboxSpec(
            argv=('/usr/bin/python3', '-B', '/opt/checks.py'), workspace=workspace,
            runtime_ro=campaign_readiness._runtime_binds() + (RuntimeBind(runtime / 'checks.py', '/opt/checks.py'),),
            env={'PYTHONDONTWRITEBYTECODE': '1'}, limits=limits))
    if output:
        output.write_bytes(result.output)
    if result.infrastructure_error or not result.cleanup_verified:
        raise RuntimeError(f'CPython grader infrastructure: {result.infrastructure_error}')
    return result.returncode == 0 and not result.timed_out


def resource_peaks(evidence, run_dir):
    peaks = {'vram_mib': None, 'ram_mib': None}
    for path in (run_dir / 'resources').rglob('*.jsonl'):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                metrics = row.get('metrics', row)
                for key, source in [('vram_mib', 'vram_used_mb'), ('ram_mib', 'wsl_ram_used_mib')]:
                    value = metrics.get(source)
                    if isinstance(value, dict):
                        value = value.get('value')
                    if isinstance(value, (int, float)):
                        peaks[key] = max(peaks[key] or 0, value)
            except ValueError:
                continue
    return peaks


def mcp_workflow(task, workspace, events):
    if task not in {'mcp_report', 'recovery', 'tiebreak'}:
        return True
    calls = [e.get('part', {}) for e in events if e.get('type') == 'tool_use'
             and str(e.get('part', {}).get('tool', '')).startswith('lab_')]
    if not calls:
        return False
    if task == 'recovery':
        read = any(c['tool'] == 'lab_get_change' for c in calls)
        applied = False
        for call in calls:
            if call['tool'] != 'lab_apply_change':
                continue
            try:
                value = json.loads(call.get('state', {}).get('output', ''))
                applied |= value == {'change_id': 'C-17', 'applied': True, 'version': 2}
            except ValueError:
                pass
        state_path = workspace / '.mcp-state.json'
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        return read and applied and state.get('apply_count') == 1 and state.get('temporary_seen')
    # Follow the observed returned chain, permitting any valid page size.
    expected, seen, ended = None, set(), False
    for call in calls:
        state = call.get('state', {})
        if call['tool'] != 'lab_list_issues' or state.get('status') != 'completed':
            continue
        if (state.get('input', {}).get('cursor') or None) != expected:
            continue
        try:
            value = json.loads(state.get('output', ''))
            seen.update(item['id'] for item in value['items'])
            expected = value['next_cursor']
            ended = expected is None
        except (ValueError, KeyError, TypeError):
            continue
        if ended:
            break
    return ended and seen == {101, 102, 103, 104, 105, 106}


def phase_complete(details, task):
    code_task = task not in {'mcp_report', 'recovery'}
    tests = details.get('authored_tests', {})
    return (details['exit_code'] == 0 and bool(details['final_text'].strip())
            and (not code_task or (tests.get('passed') is True and tests.get('count', 0) > 1)))


def regrade_run(run_dir):
    """Re-evaluate preserved snapshots without loading any model or rewriting raw scores."""
    row = json.loads((run_dir / 'record.json').read_text())
    results = []
    for phase in (1, 2):
        snapshot = run_dir / f'.snapshot{phase}.zip'
        if not snapshot.is_file():
            break
        # Temporary candidate-only workspace remains outside the repository.
        with tempfile.TemporaryDirectory(prefix='practical-regrade-') as temp:
            workspace = Path(temp)
            extract_snapshot(snapshot.read_bytes(), workspace)
            results.append(grade(workspace, row['task'], phase=phase))
    value = {'task': row['task'], 'model': row['model'], 'phases_correct': results,
             'original_score_preserved': True}
    write_json(run_dir / 'regrade.json', value)
    return value


def run_task(model, task, output, models, *, lab=LAB):
    run_dir = output / 'runs' / f'{model}-{task}-{time.time_ns()}'
    workspace = run_dir / 'input'
    prompt = practical_tasks.seed_task(task, workspace)
    prompts = [prompt]
    if task == 'continuation':
        prompts.append(practical_tasks.followup_prompt(task))
    start = time.monotonic()
    monitor, monitor_status = safe_campaign._resource_monitor_start(
        run_dir / 'resources', run_id=run_dir.name, phase_id='agent', agent_id='opencode')
    row = {'model': model, 'task': task, 'correct': False, 'autonomous': False,
           'failure': 'infrastructure', 'run_dir': str(run_dir), 'model_contract': models[model]}
    try:
        result = run_agent(workspace, run_dir, model, models, prompts, lab=lab)
        row['seconds'] = round(time.monotonic() - start, 3)
        stopped = safe_campaign._resource_monitor_stop(monitor, monitor_status)
        row.update(resource_peaks(stopped, run_dir))
        if result.infrastructure_error or not result.cleanup_verified:
            raise RuntimeError(result.infrastructure_error or 'sandbox cleanup failed')
        metadata_raw = result.workspace_outputs.get('.practical.json')
        if not metadata_raw:
            row['failure'] = 'timeout' if result.timed_out else 'agent'
            return row
        if any(e.method == 'POST' and (e.status >= 500 or e.status == 400)
               for e in result.broker_events):
            raise RuntimeError('model endpoint rejected request or failed; inspect preserved broker response')
        metadata = json.loads(metadata_raw)
        events = []
        for line in result.output.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        row['tool_errors'] = sum(e.get('type') == 'tool_use' and
                                 e.get('part', {}).get('state', {}).get('status') == 'error' for e in events)
        row['model_calls'] = sum(e.method == 'POST' for e in result.broker_events)
        row['phases'] = metadata['phases']
        correctness = []
        workflow = []
        for phase, details in enumerate(metadata['phases'], 1):
            restored = run_dir / f'phase{phase}'
            extract_snapshot(result.workspace_outputs[f'.snapshot{phase}.zip'], restored)
            correctness.append(grade(restored, task, phase=phase, output=run_dir / f'grade{phase}.txt'))
            workflow.append(phase_complete(details, task) and mcp_workflow(task, restored, events))
            mcp_state = restored / '.mcp-state.json'
            if mcp_state.is_file():
                row['tool_errors'] = max(row['tool_errors'], json.loads(mcp_state.read_text()).get('error_count', 0))
        row['correct'] = len(correctness) == len(prompts) and all(correctness)
        row['autonomous'] = (len(workflow) == len(prompts) and all(workflow) and not result.timed_out
                             and not result.output_limited and not any(e.get('type') == 'error' for e in events))
        row['failure'] = ('passed' if row['correct'] and row['autonomous'] else
                          'wrong_result' if not row['correct'] else 'workflow')
    except (ValueError, KeyError, zipfile.BadZipFile) as exc:
        row['failure'] = 'agent'
        row['error'] = f'{type(exc).__name__}: {str(exc)[:400]}'
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {str(exc)[:400]}'
    finally:
        stopped = safe_campaign._resource_monitor_stop(monitor, monitor_status)
        row.update(resource_peaks(stopped, run_dir))
        row.setdefault('seconds', round(time.monotonic() - start, 3))
        write_json(run_dir / 'record.json', row)
    return row


def report(output, rows, *, finalists=None, state='running'):
    ranking = rank_models(rows)
    write_json(output / 'status.json', {'state': state, 'finalists': finalists, 'ranking': ranking,
                                      'finished_tasks': len(completed_keys(rows))})
    models = contracts()
    fields = ['model', 'artifact', 'stage', 'completed', 'attempted', 'code_correct', 'total_seconds',
              'median_success_seconds', 'tool_errors', 'vram_mib', 'ram_mib', 'context_tokens', 'max_output_tokens']
    with (output / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows({**r, 'artifact': models.get(r['model'], {}).get('alias'),
                          'stage': 'finalist' if r['model'] in (finalists or []) else 'screen',
                          'context_tokens': 16384, 'max_output_tokens': 2048} for r in ranking)


def protocol(models):
    sources = ['practical_selection.py', 'practical_tasks.py', 'practical_mcp.py', 'practical_driver.py']
    return {'protocol_id': PROTOCOL, 'models': models, 'generation': GENERATION,
            'context_tokens': 16384, 'kv_cache': 'q4_0', 'seconds_per_task': 300,
            'max_model_calls_per_task': 30, 'stages': STAGES,
            'source_hashes': {p: hashlib.sha256((ROOT / 'benchmark' / p).read_bytes()).hexdigest() for p in sources},
            'runtime_revision': model_quality_paired.RUNTIME_REVISION,
            'opencode_version': model_quality_paired.HARNESS_VERSION,
            'memory_scope': 'system-wide WSL RAM and GPU VRAM sampled each second'}


def run(output, *, lab=LAB):
    models = contracts()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.running'
    # flock is released by the kernel even after interruption.
    import fcntl
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        restore_archived_models(models, lab)
        frozen = protocol(models)
        frozen_path = output / 'protocol.json'
        if frozen_path.exists() and json.loads(frozen_path.read_text()) != json.loads(json.dumps(frozen)):
            raise RuntimeError('protocol changed; use a fresh output directory')
        write_json(frozen_path, frozen)
        records_path = output / 'records.json'
        rows = load_records(output)
        write_json(records_path, rows)
        finalists_path = output / 'finalists.json'
        finalists = json.loads(finalists_path.read_text()) if finalists_path.exists() else None
        for stage, tasks in enumerate(STAGES):
            selected = list(models) if stage == 0 else finalists
            for model in selected:
                todo = [task for task in tasks if (model, task) not in completed_keys(rows)]
                if not todo:
                    continue
                # One capacity check and one owned server per model session.
                preflight(lab)
                process, log = model_candidate_screen._start_screen_server(lab, model, output, models[model])
                try:
                    probe_dir = output / 'compatibility' / f'{model}-{time.time_ns()}'
                    probe_workspace = probe_dir / 'input'
                    probe_workspace.mkdir(parents=True)
                    probe = run_agent(probe_workspace, probe_dir, model, models,
                                      ['Call the lab MCP list_issues tool once. Then reply READY.'], lab=lab, seconds=75)
                    probe_events = [json.loads(line) for line in probe.output.splitlines() if line.startswith(b'{')]
                    if not any(e.get('type') == 'tool_use' and 'lab_' in str(e.get('part', {}).get('tool', ''))
                               and e.get('part', {}).get('state', {}).get('status') == 'completed' for e in probe_events):
                        raise RuntimeError(f'{model}: MCP/tool compatibility needs adapter repair; no quality score assigned')
                    for task in todo:
                        row = run_task(model, task, output, models, lab=lab)
                        rows.append(row)
                        write_json(records_path, rows)
                        report(output, rows, finalists=finalists)
                        print(json.dumps({k: row.get(k) for k in ('model', 'task', 'failure', 'seconds')}), flush=True)
                        if row['failure'] == 'infrastructure':
                            raise RuntimeError(row.get('error', 'infrastructure failure'))
                finally:
                    safe_campaign._stop_server(process)
            if stage == 0:
                finalists = [r['model'] for r in rank_models(rows)[:2]]
                write_json(finalists_path, finalists)
        # A genuine tie means equal quality, elapsed time at reported precision, and memory.
        final_rows = [r for r in rows if r['model'] in finalists]
        leaders = rank_models(final_rows)
        if len(leaders) == 2 and all(leaders[0][key] == leaders[1][key]
                                     for key in ('completed', 'total_seconds', 'vram_mib')):
            for model in finalists:
                if (model, 'tiebreak') not in completed_keys(rows):
                    process, _ = model_candidate_screen._start_screen_server(lab, model, output, models[model])
                    try:
                        rows.append(run_task(model, 'tiebreak', output, models, lab=lab))
                        write_json(records_path, rows)
                    finally:
                        safe_campaign._stop_server(process)
        report(output, rows, finalists=finalists, state='complete')
        write_json(output / 'recommendation.json', {'finalists': rank_models([r for r in rows if r['model'] in finalists]),
                                                   'screen': rank_models([r for r in rows if r['task'] in STAGES[0]])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--regrade-run', type=Path)
    args = parser.parse_args()
    if args.regrade_run:
        print(json.dumps(regrade_run(args.regrade_run), indent=2))
    elif args.execute:
        run(args.output)
    else:
        print(json.dumps(protocol(contracts()), indent=2))


if __name__ == '__main__':
    main()
