"""Stage 5 wrapper. Never run this while another llama-server is active."""
from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from benchmark import opencode_baseline as baseline

CONFIG = baseline.ROOT / 'benchmark/configs/qwen-4b-opencode-stage5.json'
CONTEXTS_9B = (65536, 49152, 32768, 16384, 8192)


def load_config(config_path=CONFIG):
    config = baseline.load_config()
    stage = json.loads(Path(config_path).read_text(encoding='utf-8'))
    models = {'q4': config['models']['q4'], **stage.pop('models')}
    config.update(stage)
    config['models'] = models
    return config


def should_escalate(result):
    failure = result.get('failure')
    if failure in baseline.INFRASTRUCTURE_FAILURES - {'grader_infrastructure'} or str(failure).startswith('harness_'):
        return False
    if failure and failure.startswith('model_') and failure != 'model_oracle_failed':
        return True
    if failure in {'model_oracle_failed', 'grader_infrastructure', None}:
        return (result.get('visible', {}).get('passed') is False or
                any(row.get('passed') is False for row in result.get('phase1_visible', [])))
    return False


CLIENT_ABORTS = {'ConnectionResetError', 'BrokenPipeError', 'CancelledError'}


def server_side_error(row, failure):
    # Killing the CLI at the wall timeout resets the in-flight request; that is not a server fault.
    if failure == 'model_wall_timeout' and row.get('status', 0) < 500 and row.get('error') in CLIENT_ABORTS:
        return False
    return bool(row.get('error') or row.get('status', 0) >= 500)


def run_cascade(run, fallback):
    started = time.monotonic()
    first = run('control')
    escalated = should_escalate(first)
    attempts = [first]
    extra_started = time.monotonic()
    if escalated:
        attempts.append(run(fallback))
    return {'attempts': attempts, 'escalated': escalated,
            'first_pass': first.get('category') == 'success',
            'final_pass': attempts[-1].get('category') == 'success',
            'total_seconds': time.monotonic() - started,
            'escalation_extra_seconds': time.monotonic() - extra_started if escalated else 0.0}


def summarize_cascades(rows):
    count = len(rows)
    return {'units': count,
            'first_pass_rate': sum(row['first_pass'] for row in rows) / count if count else None,
            'final_pass_rate': sum(row['final_pass'] for row in rows) / count if count else None,
            'escalations': sum(row['escalated'] for row in rows),
            'total_seconds': sum(row['total_seconds'] for row in rows),
            'escalation_extra_seconds': sum(row['escalation_extra_seconds'] for row in rows)}


@contextlib.contextmanager
def tool_hooks(config, arm):
    old_profile = baseline.profile
    old_bwrap = baseline.bwrap_command
    old_env = baseline.sandbox_environment
    old_grade = baseline.grade

    def grade(*args, **kwargs):
        try:
            return old_grade(*args, **kwargs)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return {'passed': None, 'status': 'infrastructure', 'error': str(exc)}

    def profile(c, a, port):
        value = old_profile(c, a, port)
        if arm.get('lsp'):
            value['lsp'] = True
        return value

    def bwrap(c, workspace, home, command):
        command = list(command)
        if arm.get('lsp') and len(command) > 1 and command[1] == 'run':
            bindir = home / '.local/bin'
            bindir.mkdir(parents=True, exist_ok=True)
            for name in ('pyright-langserver', 'typescript-language-server'):
                wrapper = bindir / name
                wrapper.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name}" >> /episode-home/lsp-starts.log\n'
                                   f'exec /opt/lsp/node_modules/.bin/{name} "$@"\n', encoding='utf-8')
                wrapper.chmod(0o755)
        if arm.get('rtk') and len(command) > 1 and command[1] == 'run':
            command = [item for item in command if item != '--pure']
            target = home / '.config/opencode/plugins/rtk.ts'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c['rtk_plugin'], target)
        result = old_bwrap(c, workspace, home, command)
        if arm.get('lsp'):
            index = result.index('--')
            result[index:index] = ['--dir', '/opt/lsp', '--ro-bind',
                                   str(Path(c['lsp_prefix']) / 'node_modules'), '/opt/lsp/node_modules']
        if arm.get('rtk'):
            index = result.index('--')
            result[index:index] = ['--dir', '/opt/rtk', '--ro-bind', c['rtk_binary'], '/opt/rtk/rtk']
        return result

    def environment():
        env = old_env()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['OPENCODE_DISABLE_MODELS_FETCH'] = 'true'
        if arm.get('lsp'):
            env['PATH'] = '/episode-home/.local/bin:/opt/lsp/node_modules/.bin:' + env['PATH']
        if arm.get('lsp_tool'):
            env['OPENCODE_EXPERIMENTAL_LSP_TOOL'] = 'true'
        if arm.get('rtk'):
            env['PATH'] = '/opt/rtk:' + env['PATH']
        return env

    baseline.profile, baseline.bwrap_command, baseline.sandbox_environment, baseline.grade = profile, bwrap, environment, grade
    try:
        yield
    finally:
        baseline.profile, baseline.bwrap_command, baseline.sandbox_environment, baseline.grade = old_profile, old_bwrap, old_env, old_grade


def lsp_evidence(output):
    events_path = output / 'events.jsonl'
    count = 0
    if events_path.exists():
        for line in events_path.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            part = event.get('part', {})
            if event.get('type') == 'tool_use' and part.get('tool') == 'lsp':
                count += 1
    logs = list((output / 'home/.local/share/opencode/log').glob('*.log'))
    evidence = []
    for path in logs:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if 'lsp' in line.lower():
                evidence.append(line)
    (output / 'lsp.log').write_text('\n'.join(evidence) + ('\n' if evidence else ''), encoding='utf-8')
    starts = output / 'home/lsp-starts.log'
    launches = starts.read_text(encoding='utf-8').splitlines() if starts.exists() else []
    return {'lsp_tool_calls': count, 'lsp_log_lines': len(evidence), 'lsp_launches': launches,
            'lsp_started': None}


def manifest(config, config_path=CONFIG):
    value = baseline.manifest(config)
    config_path = Path(config_path).resolve()
    try:
        config_name = config_path.relative_to(baseline.ROOT).as_posix()
    except ValueError:
        config_name = config_path.as_posix()
    value['files_sha256'][config_name] = baseline.digest(config_path)
    value['files_sha256'][str(Path(__file__).relative_to(baseline.ROOT))] = baseline.digest(__file__)
    prefix = Path(config['lsp_prefix'])
    modules = prefix / 'node_modules'
    value['lsp_files_sha256'] = {
        p.relative_to(prefix).as_posix(): ('link:' + str(p.readlink()) + ':' + baseline.digest(p)
                                          if p.is_symlink() else baseline.digest(p))
        for p in sorted(modules.rglob('*')) if p.is_file()
    }
    value['lsp_files_sha256']['package-lock.json'] = baseline.digest(prefix / 'package-lock.json')
    value['rtk_files_sha256'] = {name: baseline.digest(config[name]) for name in ('rtk_binary', 'rtk_plugin')}
    value['server_lifecycle'] = 'one process per arm, restarted for cascade escalation'
    return value


def free_vram_mib():
    proc = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                          capture_output=True, text=True, timeout=5, check=True)
    return int(proc.stdout.splitlines()[0])


def vram_capacity_and_free():
    proc = subprocess.run(['nvidia-smi', '--query-gpu=memory.total,memory.free',
                           '--format=csv,noheader,nounits'], capture_output=True, text=True,
                          timeout=5, check=True)
    total, free = proc.stdout.splitlines()[0].split(',')
    return int(total.strip()), int(free.strip())


def minimum_headroom(total, free, peak):
    if peak is None:
        return None
    return min(free, total - peak)


class ServerPool:
    def __init__(self, config, output):
        self.config, self.output = config, output
        self.server = None
        self.key = None
        self.effective_arm = None
        self.epoch = max((int(p.name.removeprefix('server-')) for p in output.glob('server-*')
                          if p.name.removeprefix('server-').isdigit()), default=0)
        self.switches = []

    def close(self):
        if self.server is not None:
            self.server.__exit__(None, None, None)
            self.server = None
            self.key = None
            self.effective_arm = None

    def get(self, variant):
        key = json.dumps(variant, sort_keys=True)
        if self.server is not None and self.server.process.poll() is None and self.key == key:
            return self.server, self.effective_arm
        started = time.monotonic()
        self.close()
        unloaded = time.monotonic()
        contexts = ([value for value in CONTEXTS_9B if value <= variant['context']]
                    if variant.get('fit_9b') else [variant['context']])
        for context in contexts:
            arm = {**variant, 'context': context}
            self.epoch += 1
            directory = self.output / f'server-{self.epoch:03d}'
            candidate = baseline.Server(self.config, arm, directory)
            try:
                candidate.__enter__()
                free = free_vram_mib() if arm.get('fit_9b') else None
                if free is not None and free < 500:
                    candidate.__exit__(None, None, None)
                    self.switches.append({'context': context, 'free_mib': free, 'status': 'insufficient_headroom'})
                    continue
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                if candidate.process is not None and candidate.process.poll() is None:
                    candidate.__exit__(None, None, None)
                raw = (directory / 'server.log').read_text(errors='replace') if (directory / 'server.log').exists() else ''
                self.switches.append({'context': context, 'status': 'startup_failed', 'error': str(exc),
                                      'oom_evidence': bool(re.search(
                                          r'out of memory|cudamalloc failed|failed to allocate cuda', raw, re.IGNORECASE))})
                if not arm.get('fit_9b') or not self.switches[-1]['oom_evidence']:
                    raise
                continue
            self.server, self.key, self.effective_arm = candidate, key, arm
            self.switches.append({'context': context, 'free_mib': free, 'status': 'ready',
                                  'unload_seconds': unloaded - started,
                                  'load_seconds': time.monotonic() - unloaded})
            return candidate, arm
        raise RuntimeError('9B did not meet 500 MiB headroom at any configured context')


def execute(config, units, config_path=CONFIG):
    output = Path(config['output'])
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        baseline.ensure_manifest(output / 'manifest.json', manifest(config, config_path))
        running = subprocess.run(['pgrep', '-x', 'llama-server'], capture_output=True, check=False)
        if running.returncode != 1:
            raise RuntimeError('another llama-server is running or process inspection failed')
        for name in dict.fromkeys(unit['arm'] for unit in units):
            arm = config['arms'][name]
            arm_output = output / 'units' / name
            arm_output.mkdir(parents=True, exist_ok=True)
            pool = ServerPool(config, arm_output)
            try:
                for unit in (item for item in units if item['arm'] == name):
                    unit_output = arm_output / f"{unit['task']}-r{unit['repetition']}"
                    unit_output.mkdir(exist_ok=True)
                    if (unit_output / 'cascade.json').exists():
                        continue
                    if list(unit_output.glob('attempt-*/result.json')):
                        raise RuntimeError(f'incomplete unit requires manual review: {unit_output}')
                    counter = 0

                    def attempt(variant, arm=arm, pool=pool, name=name, unit=unit, unit_output=unit_output):
                        nonlocal counter
                        selected = copy.deepcopy(arm)
                        if variant == 'think':
                            selected['thinking'] = True
                        elif variant == '9b':
                            selected.update(model='q9', context=65536, fit_9b=True)
                        while True:
                            try:
                                server, selected = pool.get(selected)
                            finally:
                                baseline.write_json(unit_output / 'model-switches.json', pool.switches)
                            runtime_config = copy.deepcopy(config)
                            runtime_config['arms'][name] = selected
                            if variant == '9b' and selected['context'] <= runtime_config['output_tokens']:
                                runtime_config['output_tokens'] = selected['context'] // 2
                            counter += 1
                            target = unit_output / f'attempt-{counter:02d}'
                            offset = server.path.stat().st_size if server.path.is_file() else 0
                            with tool_hooks(runtime_config, selected):
                                result = baseline.run_attempt(runtime_config, unit, target,
                                                              server.process, server.port, server.path)
                            if server.path.is_file():
                                with server.path.open('rb') as stream:
                                    stream.seek(offset)
                                    segment = stream.read().decode(errors='replace')
                                result['oom_evidence'] = bool(result.get('oom_evidence') or re.search(
                                    r'out of memory|cudamalloc failed|failed to allocate cuda', segment, re.IGNORECASE))
                            # A timed-out CLI must not hide an independently observed server failure.
                            if server.process is not None and server.process.poll() is not None:
                                result.update(failure='server_exited', category='infrastructure')
                            elif any(server_side_error(row, result.get('failure'))
                                     for row in result.get('proxy_requests', [])):
                                result.update(failure='server_http_error', category='infrastructure')
                            result.update(lsp_evidence(target))
                            result['effective_context'] = selected['context']
                            result['effective_output_tokens'] = runtime_config['output_tokens']
                            inference_oom = variant == '9b' and result.get('oom_evidence')
                            if inference_oom:
                                result.update(category='infrastructure', failure='server_oom')
                            if variant == '9b' and result.get('category') != 'infrastructure':
                                total, free = vram_capacity_and_free()
                                result['minimum_observed_headroom_mib'] = minimum_headroom(
                                    total, free, result.get('peak_vram_mib'))
                            baseline.write_json(target / 'result.json', result)
                            low_headroom = (variant == '9b' and result.get('minimum_observed_headroom_mib') is not None
                                            and result['minimum_observed_headroom_mib'] < 500)
                            if low_headroom:
                                result.update(category='infrastructure', failure='insufficient_vram_headroom')
                                baseline.write_json(target / 'result.json', result)
                            if (low_headroom or inference_oom) and selected['context'] > 8192:
                                pool.switches.append({'context': selected['context'],
                                                      'status': 'inference_oom' if inference_oom else 'insufficient_headroom',
                                                      'attempt': counter, 'oom_evidence': bool(inference_oom),
                                                      'minimum_observed_headroom_mib': result.get('minimum_observed_headroom_mib')})
                                baseline.write_json(unit_output / 'model-switches.json', pool.switches)
                                selected['context'] = next(value for value in CONTEXTS_9B
                                                           if value < selected['context'])
                                pool.close()
                                continue
                            if inference_oom:
                                pool.switches.append({'context': selected['context'], 'status': 'inference_oom',
                                                      'attempt': counter, 'oom_evidence': True})
                                baseline.write_json(unit_output / 'model-switches.json', pool.switches)
                                raise RuntimeError('9B OOM at smallest configured context')
                            if low_headroom:
                                raise RuntimeError('9B did not maintain 500 MiB observed headroom')
                            if variant == '9b' and result.get('category') != 'infrastructure' and result.get('minimum_observed_headroom_mib') is None:
                                raise RuntimeError('9B VRAM peak unavailable; headroom cannot be verified')
                            acceptable_grader_failure = (variant == 'control' and arm.get('cascade') and
                                                         result.get('failure') == 'grader_infrastructure' and
                                                         should_escalate(result))
                            if result.get('category') in {'infrastructure', 'harness'} and not acceptable_grader_failure:
                                raise RuntimeError(f'unit failed infrastructure/harness: {target}')
                            return result

                    switch_offset = len(pool.switches)
                    stop, samples = threading.Event(), []
                    sampler = threading.Thread(target=baseline.sample_vram, args=(stop, samples), daemon=True)
                    sampler.start()
                    try:
                        fallback = arm.get('cascade')
                        if fallback:
                            result = run_cascade(attempt, fallback)
                        else:
                            one = attempt('control')
                            result = {'attempts': [one], 'escalated': False,
                                      'first_pass': one['category'] == 'success',
                                      'final_pass': one['category'] == 'success',
                                      'total_seconds': one['total_seconds'], 'escalation_extra_seconds': 0}
                    finally:
                        stop.set()
                        sampler.join(timeout=10)
                    result['model_switches'] = pool.switches[switch_offset:]
                    result['resource_samples'] = samples
                    result['resources'] = baseline.resource_summary(samples)
                    baseline.write_json(unit_output / 'cascade.json', result)
                    rows = [json.loads(path.read_text(encoding='utf-8'))
                            for path in sorted(arm_output.glob('*/cascade.json'))]
                    baseline.write_json(arm_output / 'summary.json', summarize_cascades(rows))
                    print(json.dumps({'unit': unit, 'final_pass': result['final_pass'],
                                      'escalated': result['escalated']}), flush=True)
            finally:
                pool.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--stage', type=int, choices=[5])
    parser.add_argument('--arm')
    args = parser.parse_args(argv)
    if not (args.dry_run or args.stage or args.arm):
        parser.error('select --dry-run, --stage 5 or --arm')
    config = load_config(args.config)
    if args.arm and (args.arm not in config['arms'] or not config['arms'][args.arm].get('enabled', True)):
        parser.error('unknown or disabled arm')
    units = baseline.schedule(config)
    if args.arm:
        units = [unit for unit in units if unit['arm'] == args.arm]
    if args.dry_run:
        for index, unit in enumerate(units, 1):
            print(f"{index:03d} stage=5 arm={unit['arm']} task={unit['task']} rep={unit['repetition']}")
        for name, arm in config['arms'].items():
            if not arm.get('enabled', True):
                print(f"disabled arm={name}: {arm.get('disabled_reason', 'unspecified')}")
        print(f'Total: {len(units)}')
        return
    execute(config, units, args.config)


if __name__ == '__main__':
    main()
