"""Long-task OpenCode experiment. Run on the Linux lab host only."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import sqlite3
import statistics
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from benchmark import opencode_baseline as baseline
from benchmark.harness_runner import summarize_usage

CONFIG = baseline.ROOT / 'benchmark/configs/qwen-4b-long-tasks.json'
HEADROOM_ROOT = Path('/home/foxtrot/local-llm-benchmark/envs/node-harnesses-update-20261028/headroom-opencode/node_modules')
HEADROOM = Path('/home/foxtrot/local-llm-benchmark/envs/python-refresh-20261028/headroom-python-3.14/bin/headroom')


def load_config():
    config = baseline.load_config()
    config.update(json.loads(CONFIG.read_text(encoding='utf-8')))
    return config


def schedule(config):
    arms = list(config['arms'])
    marathons = list(config['marathons'])
    if len(arms) != 4 or len(marathons) != 2:
        raise ValueError('expected four arms and two marathons')
    ordered = arms + [arms[1], arms[0], arms[3], arms[2]]
    return [{'arm': arm, 'marathon': marathons[index % 2], 'repetition': 1}
            for index, arm in enumerate(ordered)]


def regressions(history):
    counts = {key: 0 for row in history for key in row}
    previous = {}
    for row in history:
        for key, value in row.items():
            if value is None:
                continue
            if previous.get(key) is True and value is False:
                counts[key] += 1
            previous[key] = value
    return counts


def context_series(rows):
    result = []
    for row in rows:
        timing = row.get('timings', [])
        last = timing[-1] if timing else {}
        prompt, cached = last.get('prompt_n'), last.get('cache_n')
        result.append(prompt + cached if isinstance(prompt, (int, float))
                      and isinstance(cached, (int, float)) else None)
    return result


@contextlib.contextmanager
def request_clock(proxy, started):
    times, stop = [], threading.Event()

    def observe():
        while not stop.wait(0.05):
            while len(times) < len(proxy.rows):
                times.append(time.monotonic() - started)

    thread = threading.Thread(target=observe, daemon=True)
    thread.start()
    try:
        yield times
    finally:
        stop.set()
        thread.join()
        while len(times) < len(proxy.rows):
            times.append(time.monotonic() - started)


def run_sequence(objectives, execute, reset):
    phases = []
    session = None
    reset_sessions = set()
    for objective in objectives:
        phase = execute(objective, None if reset else session)
        phases.append(phase)
        if len(phase.get('session_ids', [])) > 1:
            phase['session_error'] = 'multiple_sessions'
            break
        if reset:
            observed = phase.get('session')
            if not observed:
                phase['session_error'] = 'missing_session'
            elif observed in reset_sessions:
                phase['session_error'] = 'reset_reused_session'
            else:
                reset_sessions.add(observed)
            if phase.get('session_error'):
                break
        if not reset:
            observed = phase.get('session')
            if not observed:
                phase['session_error'] = 'session_unobserved' if session else 'missing_session'
                break
            if session and observed != session:
                phase['session_error'] = 'session_mismatch'
                break
            session = observed
        if phase.get('stop'):
            break
    return phases


def count_compactions(home, sessions):
    database = home / '.local/share/opencode/opencode.db'
    if not database.is_file() or not sessions:
        return None
    try:
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as conn:
            rows = conn.execute('SELECT session_id, data FROM part').fetchall()
        return sum(1 for session, data in rows if session in sessions
                   and json.loads(data).get('type') == 'compaction')
    except (sqlite3.Error, ValueError, AttributeError):
        return None


SUPERVISOR_FILES = ('TASK.md', 'verify.py', 'visible.py', 'verify_phase1.py',
                    'visible_phase1.py', 'tool.py')


def objective_parts(objective):
    task, _, phase = objective.partition(':')
    return task, phase


def prepare_combined(config, objectives, workspace):
    task_ids = list(dict.fromkeys(objective_parts(item)[0] for item in objectives))
    baseline.prepare_workspace(config, task_ids[0], workspace)
    for task in task_ids[1:]:
        patch = baseline.CORPUS / 'tasks' / task / 'bug.patch'
        if patch.stat().st_size:
            subprocess.run(['git', 'apply', '--whitespace=nowarn', str(patch)],
                           cwd=workspace, check=True)
    for name in SUPERVISOR_FILES:
        (workspace / name).unlink(missing_ok=True)


def release_objective(objective, workspace):
    task_id, phase = objective_parts(objective)
    task_dir = baseline.CORPUS / 'tasks' / task_id
    task = json.loads((task_dir / 'task.json').read_text(encoding='utf-8'))
    for name in SUPERVISOR_FILES:
        (workspace / name).unlink(missing_ok=True)
    if phase == '2':
        return baseline.release_followup(task_id, workspace)
    for name in (('verify_phase1.py', 'visible_phase1.py') if phase == '1'
                 else ('verify.py', 'visible.py')):
        shutil.copy2(task_dir / name, workspace / name)
    if task['class'] in {'mcp', 'tool_recovery'}:
        shutil.copy2(baseline.CORPUS / 'stubs' / task_id / 'tool.py', workspace / 'tool.py')
    prompt = baseline.task_prompt(task)
    (workspace / 'TASK.md').write_text(prompt, encoding='utf-8')
    return prompt


def run_cli(config, workspace, home, prompt, session, timeout, headroom=False):
    executable = Path(config['opencode']).resolve(strict=True).name
    args = ['/opt/opencode/' + executable, 'run', '--format', 'json',
            '--agent', 'build', '--model', 'local/local-qwen', '--dir', '/workspace']
    if not headroom:
        args.append('--pure')
    if session:
        args += ['--session', session]
    args.append(prompt)
    command = baseline.bwrap_command(config, workspace, home, args)
    if headroom:
        index = command.index('--')
        command[index:index] = ['--ro-bind', str(HEADROOM_ROOT), '/opt/headroom/node_modules']
    env = baseline.sandbox_environment()
    env['OPENCODE_DISABLE_MODELS_FETCH'] = 'true'
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=max(0.01, timeout))
        code = process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        code = 124
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    sessions = {event['sessionID'] for event in events if event.get('sessionID')}
    return {'code': code, 'session': next(iter(sessions)) if len(sessions) == 1 else None,
            'session_ids': sorted(sessions), 'events': events, 'stderr': stderr.decode(errors='replace'),
            'seconds': time.monotonic() - started}


def sandbox_check(config, objective, workspace, output, timeout, visible=False):
    task, phase = objective_parts(objective)
    output.mkdir(parents=True, exist_ok=True)
    if visible:
        return baseline.check_visible(config, task, workspace, phase1=phase == '1', timeout=timeout)
    return baseline.grade(config, task, workspace, output, timeout=timeout)


def grade_objective(config, objective, workspace, output, timeout):
    if objective_parts(objective)[1] == '1':
        return {'passed': None, 'status': 'no_private_phase1_oracle'}
    return sandbox_check(config, objective, workspace, output, timeout)


def write_progress(workspace, outcomes):
    subprocess.run(['git', 'add', '-N', '--all'], cwd=workspace, check=True,
                   capture_output=True)
    stat = subprocess.run(['git', 'diff', '--stat', 'HEAD'], cwd=workspace, check=True,
                          capture_output=True, text=True).stdout
    lines = ['# Progress', '', 'Previous objectives and visible checks:']
    lines.extend(f"- {entry['objective']}: {entry['description']} — visible: {entry['visible']['passed']}"
                 for entry in outcomes)
    lines += ['', 'Changed files (git diff --stat):', '```', stat, '```', '']
    (workspace / 'PROGRESS.md').write_text('\n'.join(lines), encoding='utf-8')


def prepare_home(config, home):
    target = home / '.config/opencode'
    target.mkdir(parents=True)
    cache = Path(config['provider_cache'])
    shutil.copytree(cache, target / 'node_modules')
    for name in ('package.json', 'package-lock.json'):
        source = cache.parent / name
        if source.is_file():
            shutil.copy2(source, target / name)


def init_git(workspace):
    subprocess.run(['git', 'init', '-q'], cwd=workspace, check=True, capture_output=True)
    subprocess.run(['git', 'add', '--all'], cwd=workspace, check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Benchmark', '-c', 'user.email=benchmark@localhost',
                    'commit', '-q', '-m', 'Initial buggy workspace'], cwd=workspace,
                   check=True, capture_output=True)


@contextlib.contextmanager
def headroom_proxy(upstream, output):
    port = baseline.free_port()
    command = [str(HEADROOM), 'proxy', '--host', '127.0.0.1', '--port', str(port),
               '--openai-api-url', f'http://127.0.0.1:{upstream}', '--no-telemetry',
               '--stateless', '--no-cache', '--disable-kompress', '--no-subscription-tracking']
    baseline.write_json(output / 'headroom-command.json', command)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(output), 'HF_HUB_OFFLINE': '1',
           'TRANSFORMERS_OFFLINE': '1', 'HEADROOM_TELEMETRY': 'off'}
    with (output / 'headroom.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=output, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('headroom exited during startup')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=1):
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError('headroom health timeout')
            yield port
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def assess_all(config, objectives, workspace, output, deadline, released):
    results = {}
    for index, objective in enumerate(objectives):
        if index >= released:
            results[objective] = {'passed': None, 'status': 'not_started'}
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results[objective] = {'passed': None, 'status': 'wall_timeout'}
        else:
            results[objective] = grade_objective(config, objective, workspace,
                                                output / f'{index + 1:02d}', min(60, remaining))
    return results


def run_attempt(config, unit, output, server, smoke=False):
    output.mkdir(parents=True, exist_ok=False)
    workspace, home = output / 'workspace', output / 'home'
    objectives = config['marathons'][unit['marathon']]
    if smoke:
        objectives = objectives[:2]
    started = time.monotonic()
    deadline = started + config['wall_seconds']
    stop, samples = threading.Event(), []
    sampler = threading.Thread(target=baseline.sample_vram, args=(stop, samples), daemon=True)
    sampler.start()
    result = {'unit': unit, 'failure': 'unexpected_error', 'objectives': objectives}
    try:
        prepare_combined(config, objectives, workspace)
        before = baseline.snapshot(workspace)
        init_git(workspace)
        prepare_home(config, home)
        release_objective(objectives[0], workspace)
        proof = baseline.verify_isolation(config, workspace, home, objective_parts(objectives[0])[0])
        baseline.write_json(output / 'isolation-probe.json', proof)
        if proof['returncode'] or not all(proof[key] for key in
                ('workspace_readable', 'oracle_denied', 'mnt_d_denied', 'home_denied')):
            raise RuntimeError('bubblewrap isolation probe failed')
        log_offset = server.path.stat().st_size
        arm = config['arms'][unit['arm']]
        headroom = unit['arm'] == 'L-headroom'
        history, visible_history = [], []
        with baseline.Proxy(server.port) as proxy, request_clock(proxy, started) as request_times:
            metric_port = proxy.server.server_address[1]
            manager = headroom_proxy(metric_port, output) if headroom else contextlib.nullcontext(metric_port)
            with manager as provider_port:
                profile = baseline.profile(config, arm, provider_port)
                profile['compaction'] = {'auto': True}
                if headroom:
                    profile['plugin'] = [[
                        '/opt/headroom/node_modules/headroom-opencode/dist/index.js',
                        {'proxyUrl': f'http://127.0.0.1:{provider_port}'}]]
                baseline.write_json(home / '.config/opencode/opencode.json', profile)

                def execute_one(objective, session):
                    index = len(history)
                    prompt = release_objective(objective, workspace)
                    if unit['arm'] == 'L-reset':
                        write_progress(workspace, visible_history)
                        prompt += '\nRead PROGRESS.md before working.\n'
                    remaining = deadline - time.monotonic() - 90
                    if remaining <= 0:
                        return {'code': None, 'session': session, 'events': [],
                                'stderr': 'supervisor reserve reached', 'seconds': 0,
                                'stop': True, 'supervisor_deadline': True}
                    phase = run_cli(config, workspace, home, prompt, session, remaining, headroom)
                    visible = sandbox_check(config, objective, workspace,
                        output / 'visible' / f'{index + 1:02d}',
                        timeout=max(0.01, min(30, deadline - time.monotonic())), visible=True)
                    visible_history.append({'objective': objective, 'description': prompt.strip(),
                                            'visible': visible})
                    assessment = assess_all(config, objectives, workspace,
                                            output / 'after' / f'{index + 1:02d}', deadline, index + 1)
                    history.append(assessment)
                    phase['visible'] = visible
                    phase['objective'] = objective
                    if phase['code'] == 124 or time.monotonic() >= deadline - 60:
                        phase['stop'] = True
                    return phase

                phases = run_sequence(objectives, execute_one, unit['arm'] == 'L-reset')
                final = assess_all(config, objectives, workspace, output / 'final', deadline,
                                   len(visible_history))
        events = [event for phase in phases for event in phase['events']]
        (output / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        after = baseline.snapshot(workspace)
        for name in (*SUPERVISOR_FILES, 'PROGRESS.md'):
            before.pop(name, None)
            after.pop(name, None)
        diff = baseline.workspace_diff(before, after)
        (output / 'workspace.diff').write_text(diff, encoding='utf-8')
        task_data = [json.loads((baseline.CORPUS / 'tasks' / objective_parts(o)[0] / 'task.json').read_text())
                     for o in objectives]
        policy = {'writable_files': list({p for t in task_data for p in t['writable_files']}),
                  'relevant_files': list({p for t in task_data for p in t['relevant_files']})}
        quality = baseline.diff_quality(before, after, policy)
        diffs = {name: baseline.workspace_diff({name: before[name]} if name in before else {},
                 {name: after[name]} if name in after else {}) for name in quality['files_touched']}
        raw = server.path.read_bytes()[log_offset:].decode(errors='replace')
        (output / 'server-segment.log').write_text(raw, encoding='utf-8')
        usage = summarize_usage('opencode', events)
        finishes = [event for event in events if event.get('type') == 'step_finish']
        if not finishes or any(not baseline.usage_available(event) for event in finishes):
            usage['prompt_tokens'] = usage['completion_tokens'] = None
        sessions = list({p['session'] for p in phases if p.get('session')})
        seen = count_compactions(home, sessions)
        failures = [baseline.phase_failure(phase, raw, server.process.poll() is None) for phase in phases]
        failure = baseline.first_failure(failures)
        if failure not in {'server_exited', 'server_http_error'} and any(phase.get('session_error') for phase in phases):
            failure = 'harness_session_error'
        failure = baseline.timeout_failure(failure, any(phase['code'] == 124 or phase.get('supervisor_deadline')
                                                       for phase in phases), 'supervisor_wall_budget')
        if len(visible_history) < len(objectives) and not failure:
            failure = 'supervisor_wall_budget' if any(p.get('stop') for p in phases) else 'harness_incomplete'
        if not failure and any(value['status'] in {'infrastructure', 'wall_timeout'} for value in final.values()):
            failure = 'grader_infrastructure'
        if not failure and any(value['passed'] is False for value in final.values()):
            failure = 'model_oracle_failed'
        error_text = '\n'.join(phase['stderr'] for phase in phases)
        overflow_pattern = re.compile(r'exceeds? (?:the )?available context|context (?:size|length|window).{0,50}(?:exceed|overflow|too (?:large|long))', re.IGNORECASE)
        overflow_count = sum(bool(overflow_pattern.search(json.dumps(event))) for event in events)
        overflow_count += sum(bool(overflow_pattern.search(phase['stderr'])) for phase in phases)
        if not failure and any(entry['visible'].get('passed') is None for entry in visible_history):
            failure = 'grader_infrastructure'
        if not failure and any(entry['visible']['passed'] is False for entry in visible_history):
            failure = 'model_visible_failed'
        visible_final = {'passed': all(entry['visible']['passed'] is True for entry in visible_history)}
        scored = [value for value in final.values() if value['status'] not in
                  {'not_started', 'no_private_phase1_oracle'}]
        oracle_final = {'passed': (all(value['passed'] is True for value in scored)
                                   if scored and len(visible_history) == len(objectives) else None)}
        taxonomy = baseline.failure_taxonomy(failure, visible_final, oracle_final, quality, events,
                    config['steps'], max((sum(e.get('type') == 'step_finish' for e in p['events'])
                                          for p in phases), default=0), error_text)
        contexts = context_series(proxy.rows)
        ttfts = [row['ttft_ms'] for row in proxy.rows if row.get('ttft_ms') is not None]
        timeline = [{'request': index + 1, 'elapsed_completion_observed_seconds':
                     request_times[index] if index < len(request_times) else None, 'context_tokens': value}
                    for index, value in enumerate(contexts)]
        result.update(failure=failure,
            phases=[{k: v for k, v in phase.items() if k != 'events'} for phase in phases],
            after_each=history, final=final, regressions=regressions(
                [{k: v['passed'] for k, v in row.items()} for row in [*history, final]]),
            passed_final=sum(v['passed'] is True for v in final.values()),
            private_oracles_available=len(scored), usage=usage,
            compactions=seen, compaction_observation='SQLite compaction parts requested; completion not established',
            resets=max(0, len(phases) - 1) if unit['arm'] == 'L-reset' else 0,
            context_by_request=timeline, proxy_requests=proxy.rows,
            request_metrics=baseline.request_metrics(proxy.rows), diff_quality=quality,
            median_ttft_ms=statistics.median(ttfts) if ttfts else None,
            tokens_after_last_edit=baseline.tokens_after_last_edit(events, diffs),
            server_metrics=baseline.parse_server_metrics(raw), taxonomy=taxonomy,
            oom_evidence=bool(re.search(r'out of memory|cudamalloc failed|failed to allocate cuda', raw, re.IGNORECASE)),
            context_overflow_events=overflow_count)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        stop.set()
        sampler.join(timeout=10)
        result['total_seconds'] = time.monotonic() - started
        result['resource_samples'] = samples
        result['resources'] = baseline.resource_summary(samples)
        result['peak_vram_mib'] = result['resources']['vram_mib']['max']
        baseline.write_json(output / 'result.json', result)
    return result


def execute(config, units, smoke):
    root = Path(config['output'])
    output = root / ('smoke' if smoke else 'campaign')
    output.mkdir(parents=True, exist_ok=True)
    with (root / 'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_gpu_free()
        manifest = baseline.manifest(baseline.load_config())
        manifest.update(protocol_id=config['protocol_id'], config=config, schedule=units,
                        server_lifecycle='one server process per marathon',
                        long_tasks_sha256=baseline.digest(Path(__file__)),
                        long_config_sha256=baseline.digest(CONFIG),
                        headroom_sha256=baseline.digest(HEADROOM),
                        headroom_plugin_sha256=baseline.digest(
                            HEADROOM_ROOT / 'headroom-opencode/dist/index.js'))
        baseline.ensure_manifest(output / 'manifest.json', manifest)
        for unit in units:
            unit_dir = output / f"{unit['arm']}-{unit['marathon']}-r{unit['repetition']}"
            if unit_dir.exists():
                previous = unit_dir / 'attempt-01/result.json'
                if not previous.is_file():
                    raise RuntimeError(f'incomplete existing result: {unit_dir}')
                saved = json.loads(previous.read_text(encoding='utf-8'))
                if saved.get('error') or saved.get('failure') in {
                    'unexpected_error', 'server_exited', 'server_http_error',
                    'harness_configuration_error', 'grader_infrastructure', 'harness_session_error', 'harness_incomplete',
                }:
                    raise RuntimeError(f'infrastructure result needs review: {unit_dir}')
                print(json.dumps({'unit': unit, 'status': 'already_completed'}), flush=True)
                continue
            check_gpu_free()
            with baseline.Server(config, config['arms'][unit['arm']], unit_dir / 'server') as server:
                result = run_attempt(config, unit, unit_dir / 'attempt-01', server, smoke)
            print(json.dumps({'unit': unit, 'failure': result['failure'],
                              'error': result.get('error'), 'passed_final': result.get('passed_final')}),
                  flush=True)
            if result.get('error') or result['failure'] in {
                'unexpected_error', 'server_exited', 'server_http_error',
                'harness_configuration_error', 'grader_infrastructure', 'harness_session_error', 'harness_incomplete',
            }:
                raise RuntimeError(f'infrastructure failure: {unit}')


def check_gpu_free():
    stage = subprocess.run(['pgrep', '-f', '[o]pencode_baseline --stage'],
                           capture_output=True, text=True, check=False)
    if stage.returncode != 1:
        raise RuntimeError('baseline stage active or process inspection failed')
    running = subprocess.run(['pgrep', '-x', 'llama-server'], capture_output=True,
                             text=True, check=False)
    if running.returncode != 1:
        raise RuntimeError('another llama-server is running or process inspection failed')


def main(argv=None):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    config = load_config()
    units = schedule(config)
    if args.dry_run:
        for index, unit in enumerate(units, 1):
            print(f"{index:03d} {unit['arm']} {unit['marathon']} rep=1")
        print(f'Total: {len(units)}')
        return
    if args.smoke:
        units = [unit for unit in units if unit['marathon'] == 'M1'
                 and unit['arm'] in ('L-reset', 'L-compact')]
    execute(config, units, args.smoke)


if __name__ == '__main__':
    main()
