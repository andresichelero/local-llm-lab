"""Serial F3 prefix-cache campaign. Dry runs are strictly offline."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from benchmark import opencode_baseline as baseline
from benchmark import practical_worker_guard as guard
from benchmark.worker_contract import build_package
from benchmark.worker_runner import LlamaClient, VisibleResult, WorkerRunner

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'corpus'
CONFIG = ROOT / 'benchmark/configs/qwen-4b-prefix-cache.json'
ARMS = ('P-W16', 'P-WL-cold', 'P-WL-warm')


def estimate_tokens(text):
    return math.ceil(len(text) / 3.5)


def schedule(tasks):
    return [{'arm': arm, 'host': task['host'], 'task': task['id'], 'repetition': rep}
            for arm in ARMS for task in sorted(tasks, key=lambda t: (t['host'], t['id']))
            for rep in range(1, 4)]


def tasks_with_prefix():
    result = []
    for path in sorted((CORPUS / 'tasks').glob('*/task.json')):
        task = json.loads(path.read_text(encoding='utf-8'))
        if (CORPUS / 'prefixes' / (task['host'] + '.txt')).is_file():
            result.append(task)
    return result


def select_context(task, workspace, max_chars=12000):
    """One contiguous window per relevant file, ranked by public objective words."""
    terms = set(re.findall(r'[a-zA-Z_][a-zA-Z_0-9]{3,}', task['objective'].lower()))
    selected = {}
    names = sorted(task['relevant_files'])
    allowance = max(1, max_chars // max(len(names), 1))
    for name in names:
        path = workspace / name
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding='utf-8')
        if not text:
            continue
        if len(text) <= allowance:
            selected[name] = text
            continue
        lines = text.splitlines(keepends=True)
        offsets = []
        position = 0
        for line in lines:
            score = len(terms.intersection(re.findall(r'[a-zA-Z_][a-zA-Z_0-9]{3,}', line.lower())))
            offsets.append((score, position))
            position += len(line)
        _, offset = max(offsets, key=lambda item: (item[0], -item[1]))
        start = max(0, min(len(text) - allowance, offset - allowance // 2))
        selected[name] = text[start:start + allowance]
    return selected


def fit_prefix(prefix, packets, counter, budget):
    """Deterministic fitting line boundary, shared by all packets of a host."""
    lines = prefix.decode('utf-8').splitlines(keepends=True)
    ends = [0]
    for line in lines:
        ends.append(ends[-1] + len(line.encode('utf-8')))
    if not packets:
        raise ValueError('empty packet set')
    if any(counter(b'', packet) > budget for packet in packets):
        raise ValueError('packet does not fit without prefix')
    low, high = 0, len(ends) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if all(counter(prefix[:ends[mid]], packet) <= budget for packet in packets):
            low = mid
        else:
            high = mid - 1
    return prefix[:ends[low]]


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return [center - radius, center + radius]


def summarize(rows):
    arms = {}
    for arm in ARMS:
        valid = [r for r in rows if r['arm'] == arm and r['category'] in ('model', 'success')]
        wins = sum(r['success'] for r in valid)
        medians = {}
        for key in ('ttft_ms', 'prompt_n', 'cache_n', 'cache_fraction', 'generated_tokens',
                    'decode_tok_s', 'total_seconds', 'peak_vram_mib', 'repairs'):
            values = [r[key] for r in valid if isinstance(r.get(key), (int, float))]
            medians[key] = statistics.median(values) if values else None
        arms[arm] = {'n': len(valid), 'successes': wins,
                     'wilson_95': wilson(wins, len(valid)),
                     'median': medians,
                     'infrastructure': sum(r['arm'] == arm and r['category'] == 'infrastructure' for r in rows)}
    pairs = {}
    for left, right in [('P-W16', 'P-WL-cold'), ('P-W16', 'P-WL-warm'), ('P-WL-cold', 'P-WL-warm')]:
        maps = [{(r['task'], r['repetition']): r for r in rows
                 if r['arm'] == arm and r['category'] in ('model', 'success')} for arm in (left, right)]
        keys = sorted(maps[0].keys() & maps[1].keys())
        pairs[left + '__' + right] = {
            'n': len(keys), 'both_success': sum(maps[0][k]['success'] and maps[1][k]['success'] for k in keys),
            'left_only': sum(maps[0][k]['success'] and not maps[1][k]['success'] for k in keys),
            'right_only': sum(not maps[0][k]['success'] and maps[1][k]['success'] for k in keys),
            'both_fail': sum(not maps[0][k]['success'] and not maps[1][k]['success'] for k in keys),
            'units': [{'task': k[0], 'repetition': k[1], 'left': maps[0][k]['success'],
                       'right': maps[1][k]['success'],
                       'left_seconds': maps[0][k].get('total_seconds'),
                       'right_seconds': maps[1][k].get('total_seconds')} for k in keys]}
    return {'arms': arms, 'pairs': pairs}


def run_lifecycle(units, server_factory, warm, run):
    """Cold starts per unit; other arms keep one server per host."""
    index = 0
    for arm in ARMS:
        arm_units = [u for u in units if u['arm'] == arm]
        for host in sorted({u['host'] for u in arm_units}):
            group = [u for u in arm_units if u['host'] == host]
            if arm == 'P-WL-cold':
                for unit in group:
                    index += 1
                    with server_factory(arm, host, index) as server:
                        run(server, unit)
            else:
                index += 1
                with server_factory(arm, host, index) as server:
                    if arm == 'P-WL-warm':
                        warm(server, host)
                    for unit in group:
                        run(server, unit)


def ensure_no_server():
    proc = subprocess.run(['pgrep', '-x', 'llama-server'], capture_output=True, text=True, check=False)
    if proc.returncode != 1:
        raise RuntimeError('llama-server already active or process inspection failed')


def messages_for(prefix, markdown):
    messages = []
    if prefix is not None:
        messages.append({'role': 'system', 'content': prefix.decode('utf-8')})
    return messages + [{'role': 'user', 'content': markdown}]


class MeasuredClient(LlamaClient):
    """Collect TTFT and server timing fields from streamed completion events."""
    def __init__(self, base_url):
        super().__init__(base_url)
        self.rows = []

    def generate(self, messages, max_tokens, timeout, cache_prompt):
        import urllib.request
        payload = {'messages': messages, 'max_tokens': max_tokens, 'temperature': 0, 'seed': 42,
                   'cache_prompt': cache_prompt, 'chat_template_kwargs': {'enable_thinking': False},
                   'stream': True, 'stream_options': {'include_usage': True}}
        request = urllib.request.Request(self.base_url + '/v1/chat/completions',
                                         data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        started = time.monotonic()
        row = {'ttft_ms': None, 'timings': None, 'usage': None}
        pieces = []
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for line in response:
                    if not line.startswith(b'data:'):
                        continue
                    data = line[5:].strip()
                    if data == b'[DONE]':
                        break
                    event = json.loads(data)
                    choices = event.get('choices') or []
                    delta = choices[0].get('delta', {}) if choices else {}
                    content = delta.get('content') or ''
                    if content and row['ttft_ms'] is None:
                        row['ttft_ms'] = (time.monotonic() - started) * 1000
                    pieces.append(content)
                    if event.get('timings'):
                        row['timings'] = event['timings']
                    if event.get('usage'):
                        row['usage'] = event['usage']
        finally:
            row['seconds'] = time.monotonic() - started
            self.rows.append(row)
        return ''.join(pieces)


def metric_summary(rows):
    timings = [r.get('timings') or {} for r in rows]
    def total(key):
        values = [t.get(key) for t in timings]
        return sum(values) if values and all(isinstance(v, (int, float)) for v in values) else None
    prompt, cache = total('prompt_n'), total('cache_n')
    generated = total('predicted_n')
    rates = [t['predicted_per_second'] for t in timings if isinstance(t.get('predicted_per_second'), (int, float))]
    return {'ttft_ms': next((r['ttft_ms'] for r in rows if r['ttft_ms'] is not None), None),
            'prompt_n': prompt, 'cache_n': cache,
            'cache_fraction': cache / (prompt + cache) if prompt is not None and cache is not None and prompt + cache else None,
            'generated_tokens': generated, 'decode_tok_s': statistics.median(rates) if rates else None,
            'requests': rows}


def make_package(task, workspace, arm, prefix=None, runner=None):
    context = select_context(task, workspace)
    budget = {'input_tokens': (16384 if arm == 'P-W16' else 65536) - 2048,
              'max_tokens': 2048, 'wall_seconds': 300, 'repairs': 1}
    kwargs = {'readonly_context': context, 'budgets': budget}
    if runner:
        package = runner.followup_package(CORPUS, runner.package, **kwargs)
    else:
        package = build_package(CORPUS, task['id'], workspace, task['host'], **kwargs)
    if prefix is not None:
        package = dataclasses.replace(package, prefix_id=hashlib.sha256(prefix).hexdigest())
    return package


def dry_plan(config, tasks):
    packets = {}
    with tempfile.TemporaryDirectory(prefix='prefix-plan-') as tmp:
        for task in tasks:
            workspace = Path(tmp) / task['id']
            baseline.prepare_workspace(config, task['id'], workspace)
            for arm in ARMS:
                package = make_package(task, workspace, arm)
                packets[(task['id'], arm)] = package.markdown
        selected = {}
        for host in sorted({task['host'] for task in tasks}):
            original = (CORPUS / 'prefixes' / (host + '.txt')).read_bytes()
            host_packets = [packets[(task['id'], 'P-WL-cold')] for task in tasks if task['host'] == host]
            def count(prefix, packet):
                return estimate_tokens(prefix.decode('utf-8')) + estimate_tokens(packet) + 32
            selected[host] = fit_prefix(original, host_packets, count,
                                        65536 - 2048 - config['repair_reserve_tokens'])
        for unit in schedule(tasks):
            prefix = (CORPUS / 'prefixes' / (unit['host'] + '.txt')).read_text(encoding='utf-8')
            chosen = selected[unit['host']].decode('utf-8')
            package = packets[(unit['task'], unit['arm'])]
            print(json.dumps({**unit, 'package_estimated_tokens': estimate_tokens(package),
                              'prefix_estimated_tokens': estimate_tokens(chosen) if unit['arm'] != 'P-W16' else 0,
                              'original_prefix_estimated_tokens': estimate_tokens(prefix),
                              'prefix_reduced_estimate': len(chosen) < len(prefix) if unit['arm'] != 'P-W16' else False,
                              'estimate': 'characters/3.5; runtime uses exact tokenizer'}, ensure_ascii=False))


def classify_result(result, visible, oracle, server_alive=True):
    if not server_alive:
        failure = 'server_exited'
    elif result.state == 'infrastructure_error' or oracle.get('status') == 'infrastructure':
        failure = 'grader_infrastructure' if oracle.get('status') == 'infrastructure' else 'server_http_error'
    elif result.state != 'accepted':
        failure = result.reason or result.state
    else:
        failure = None
    return failure, baseline.classify(failure, oracle, visible)


def verification_worker(request):
    """Run the existing verifier in a separate, fail-closed restricted process."""
    output = Path(request['output']).resolve(strict=True)
    workspace = (output / 'workspace').resolve(strict=True)
    config, task = request['config'], request['task']
    if task not in config['tasks'] or workspace.parent != output:
        raise ValueError('invalid verification request')
    guard.disable_process_inspection()
    guard.restrict_candidate_process(
        workspace=output,
        helper_paths=[CORPUS / 'tasks' / task, CORPUS / 'oracles' / task,
                      CORPUS / 'support', Path(sys.prefix)],
        node_root=Path(config['node']).resolve().parent.parent)
    if request['kind'] == 'visible':
        return baseline.check_visible(config, task, workspace, phase1=request['phase1'])
    if request['kind'] == 'oracle':
        return baseline.grade(config, task, workspace, output)
    raise ValueError('invalid verification kind')


def isolated_verify(config, task, output, kind, phase1=False):
    request = {'config': config, 'task': task, 'output': str(output.resolve()),
               'kind': kind, 'phase1': phase1}
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(output / 'home'),
           'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    proc = subprocess.run([sys.executable, '-m', 'benchmark.prefix_cache_campaign', '--verify-worker'],
                          input=json.dumps(request), text=True, capture_output=True, cwd=ROOT,
                          env=env, timeout=125, check=False)
    if proc.returncode:
        raise RuntimeError('isolated verifier failed: ' + proc.stderr[-1000:])
    return json.loads(proc.stdout)


def run_episode(config, task, unit, server, prefix, output):
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    (output / 'home').mkdir()
    baseline.prepare_workspace(config, task['id'], workspace)
    client = MeasuredClient(f'http://127.0.0.1:{server.port}')
    package = make_package(task, workspace, unit['arm'], prefix)
    runner = WorkerRunner(workspace, output / 'journal.jsonl', client)
    runner.package = package
    visible = {'passed': False}
    oracle = {'passed': None, 'status': 'not_run'}
    verification_failed = False
    stop, resources = threading.Event(), []
    sampler = threading.Thread(target=baseline.sample_vram, args=(stop, resources), daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        def check(phase1=False):
            nonlocal verification_failed
            try:
                value = isolated_verify(config, task['id'], output, 'visible', phase1)
            except Exception:
                verification_failed = True
                raise
            visible.update(value)
            return VisibleResult(value['passed'], (value['stdout'] + '\n' + value['stderr'])[-8000:])

        def grade():
            nonlocal verification_failed
            try:
                value = isolated_verify(config, task['id'], output, 'oracle')
            except Exception:
                verification_failed = True
                oracle['status'] = 'infrastructure'
                raise
            oracle.update(value)
            if value['passed'] is None:
                raise RuntimeError('grader infrastructure')
            return value['passed']

        result = runner.run(package, lambda: check(package.verification_profile == 'phase1'), grade,
                            mode='W16' if prefix is None else 'WL', prefix=prefix)
        phases = [dataclasses.asdict(result)]
        if package.verification_profile == 'phase1' and result.state == 'accepted':
            baseline.release_followup(task['id'], workspace)
            follow = make_package(task, workspace, unit['arm'], prefix, runner)
            first_events = [json.loads(line) for line in
                            (output / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
            if any(e['state'] == 'generating' and e.get('turn', 0) > 0 for e in first_events):
                follow = dataclasses.replace(follow, budgets={**follow.budgets, 'repairs': 0})
            next_runner = WorkerRunner(workspace, output / 'journal.jsonl', client)
            result = next_runner.run(follow, check, grade, mode='W16' if prefix is None else 'WL', prefix=prefix)
            phases.append(dataclasses.asdict(result))
        # A rejected final delivery is graded for the final metric, never fed back to the model.
        if (result.state != 'infrastructure_error' and oracle['status'] == 'not_run'
                and not (package.verification_profile == 'phase1' and len(phases) == 1)):
            try:
                grade()
            except Exception as exc:  # noqa: BLE001 - record grader infrastructure failures
                oracle['error_type'] = type(exc).__name__
        if verification_failed:
            oracle['status'] = 'infrastructure'
        failure, category = classify_result(result, visible, oracle, server.process.poll() is None)
        journal = [json.loads(line) for line in (output / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
        generations = sum(e['state'] == 'generating' for e in journal)
        repairs = sum(e['state'] == 'generating' and e.get('turn', 0) > 0 for e in journal)
        row = {**unit, 'success': category == 'success', 'category': category, 'failure': failure,
               'state': result.state, 'phases': phases, 'visible': visible, 'oracle': oracle,
               'repairs': repairs, 'generations': generations, 'total_seconds': time.monotonic() - started,
               'prefix_sha256': hashlib.sha256(prefix).hexdigest() if prefix is not None else None,
               **metric_summary(client.rows)}
    finally:
        stop.set()
        sampler.join(timeout=3)
    row['peak_vram_mib'] = baseline.resource_summary(resources)['vram_mib']['max']
    baseline.write_json(output / 'result.json', row)
    return row


def campaign(config, tasks):
    ensure_no_server()
    output = Path(config['output'])
    output.mkdir(parents=True, exist_ok=False)
    # Freeze the actual corpus and code identities before any future inference.
    frozen = json.loads((CORPUS / 'manifest.json').read_text(encoding='utf-8'))
    actual = {str(path.relative_to(CORPUS)).replace(os.sep, '/'): baseline.digest(path)
              for directory in ('hosts', 'tasks', 'oracles', 'stubs', 'support', 'prefixes')
              for path in (CORPUS / directory).rglob('*') if path.is_file() and not path.is_symlink()
              and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    if actual != frozen:
        raise RuntimeError('corpus differs from frozen manifest')
    for path, expected in [(config['server'], config['server_sha256']),
                           (config['models']['q4']['path'], config['models']['q4']['sha256'])]:
        if baseline.digest(path) != expected:
            raise RuntimeError('binary hash mismatch: ' + path)
    code_files = [Path(__file__), CONFIG, ROOT / 'benchmark/worker_runner.py',
                  ROOT / 'benchmark/worker_contract.py', ROOT / 'benchmark/guarded_edit.py',
                  ROOT / 'benchmark/opencode_baseline.py']
    baseline.write_json(output / 'manifest.json', {'config': config, 'corpus': actual,
                                                    'code': {str(p.relative_to(ROOT)): baseline.digest(p)
                                                             for p in code_files},
                                                    'schedule': schedule(tasks)})
    task_by_id = {task['id']: task for task in tasks}
    packets = {}
    with tempfile.TemporaryDirectory(prefix='prefix-packets-') as tmp:
        for task in tasks:
            workspace = Path(tmp) / task['id']
            baseline.prepare_workspace(config, task['id'], workspace)
            packets[task['id']] = make_package(task, workspace, 'P-WL-cold').markdown
    prefixes, rows = {}, []

    def start_server(arm, host, index):
        return baseline.Server(config, config['arms'][arm], output / 'servers' / f'{index:03d}-{arm}-{host}')

    def select_prefix(server, host):
        if host not in prefixes:
            client = LlamaClient(f'http://127.0.0.1:{server.port}')
            original = (CORPUS / 'prefixes' / (host + '.txt')).read_bytes()
            host_packets = [packets[t['id']] for t in tasks if t['host'] == host]
            # 4K reserve for changed follow-up, repair output and diagnostic.
            limit = 65536 - 2048 - config['repair_reserve_tokens']
            def count(prefix, packet):
                return client.count_tokens(messages_for(prefix, packet), timeout=120)
            chosen = fit_prefix(original, host_packets, count, limit)
            prefixes[host] = chosen
            baseline.write_json(output / f'prefix-{host}.json', {
                'original_bytes': len(original), 'selected_bytes': len(chosen),
                'original_sha256': hashlib.sha256(original).hexdigest(),
                'selected_sha256': hashlib.sha256(chosen).hexdigest(),
                'input_limit_before_repair_reserve': limit,
                'rule': 'binary search initial whole lines, exact template token count, all initial host packets'})
        return prefixes[host]

    def warm(server, host):
        prefix = select_prefix(server, host)
        client = MeasuredClient(f'http://127.0.0.1:{server.port}')
        client.generate(messages_for(prefix, 'Cache warmup. Reply OK.'), 1, 300, True)
        baseline.write_json(server.output / 'warmup.json', {'host': host, 'requests': client.rows})

    def run(server, unit):
        task = task_by_id[unit['task']]
        prefix = None if unit['arm'] == 'P-W16' else select_prefix(server, unit['host'])
        unit_dir = output / 'units' / unit['arm'] / f"{unit['task']}-r{unit['repetition']}"
        row = run_episode(config, task, unit, server, prefix, unit_dir)
        rows.append(row)
        baseline.write_json(output / 'summary.json', summarize(rows))
        print(json.dumps({'unit': unit, 'category': row['category'], 'failure': row['failure']}), flush=True)
        if row['category'] == 'infrastructure':
            raise RuntimeError('infrastructure failure; campaign stopped and results preserved')

    run_lifecycle(schedule(tasks), start_server, warm, run)
    baseline.write_json(output / 'summary.json', summarize(rows))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.verify_worker:
        print(json.dumps(verification_worker(json.load(sys.stdin))))
        return
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    tasks = tasks_with_prefix()
    if sorted(config['tasks']) != sorted(task['id'] for task in tasks):
        raise RuntimeError('configured task list differs from corpus')
    if args.dry_run:
        dry_plan(config, tasks)
    else:
        campaign(config, tasks)


if __name__ == '__main__':
    main()
