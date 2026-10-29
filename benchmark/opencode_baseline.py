"""Serial OpenCode baseline. Run only on the Linux lab host."""
from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from benchmark.harness_runner import summarize_usage

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'corpus'
CONFIG = ROOT / 'benchmark/configs/qwen-4b-opencode-baseline.json'
LAB = Path('/home/foxtrot/local-llm-benchmark')


def load_config():
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def schedule(config):
    return [{'stage': arm['stage'], 'arm': name, 'task': task, 'repetition': rep}
            for name, arm in config['arms'].items() for rep in range(1, arm['repetitions'] + 1)
            for task in config['tasks']]


def server_command(config, arm, port):
    sampling = config['sampling']['on' if arm['thinking'] else 'off']
    return [config['server'], '--model', config['models'][arm['model']]['path'],
            '--host', '127.0.0.1', '--port', str(port), '--alias', 'local-qwen',
            '--ctx-size', str(arm['context']), '--parallel', '1', '-ngl', '99',
            '--fit', 'off', '--flash-attn', 'on', '--cache-type-k', arm['kv_k'],
            '--cache-type-v', arm['kv_v'], '--jinja', '--reasoning',
            'on' if arm['thinking'] else 'off', '--chat-template-kwargs',
            json.dumps({'enable_thinking': arm['thinking']}), '--temp', str(sampling['temperature']),
            '--top-p', str(sampling.get('top_p', 0.95)), '--top-k', str(sampling.get('top_k', 20)),
            '--cache-prompt' if arm['cache_prompt'] else '--no-cache-prompt', '--no-webui']


def profile(config, arm, port):
    base = json.loads((ROOT / 'benchmark/configs/harnesses/opencode.json').read_text())
    base.update(autoupdate=False, model='local/local-qwen', subagent_depth=0)
    base['agent'] = {'build': {'mode': 'primary', 'steps': config['steps'], 'permission': {
        'task': {'*': 'deny'}, 'bash': {'*': 'allow'}, 'edit': {'*': 'allow'},
        'external_directory': {'*': 'deny'}, 'webfetch': 'deny',
        'websearch': 'deny'}}}
    provider = base['provider']['local']
    provider['options']['baseURL'] = f'http://127.0.0.1:{port}/v1'
    sampling = config['sampling']['on' if arm['thinking'] else 'off']
    options = {'temperature': sampling['temperature']}
    if arm['thinking']:
        options.update(topP=sampling['top_p'], topK=sampling['top_k'])
    provider['models'] = {'local-qwen': {'name': 'local-qwen',
        'limit': {'context': arm['context'], 'output': config['output_tokens']}, 'options': options}}
    return base


def ensure_manifest(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise RuntimeError('manifest changed; refusing to mix protocols')
    else:
        path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def classify_failure(code, output, server_alive):
    if not server_alive:
        return 'server_exited'
    if code == 0:
        return None
    lower = output.lower()
    if 'configuration is invalid' in lower:
        return 'harness_configuration_error'
    if re.search(r'(invalid|pars|malformed|truncat|unexpected).*tool|tool.{0,120}(invalid|pars|malformed|truncat|json|error)', lower):
        return 'model_protocol_error'
    if code and ('http 500' in lower or 'status code: 500' in lower):
        return 'server_http_error'
    return 'model_cli_failure' if code else None


def phase_failure(phase, server_log, server_alive):
    errors = [event for event in phase['events'] if event.get('type') == 'error']
    code = phase['code'] or (1 if errors else 0)
    evidence = phase['stderr'] + json.dumps(errors)
    if code:
        evidence += server_log[-16000:]
    return classify_failure(code, evidence, server_alive)


def retry_infrastructure(attempt):
    result = attempt()
    if result['category'] == 'infrastructure':
        result = attempt()
    return result


def run_phases(run, verify_phase1, followup, initial, continuation):
    first = run(initial, None)
    phases = [first]
    released = False
    has_error = any(event.get('type') == 'error' for event in first.get('events', []))
    if continuation and first['code'] == 0 and not has_error and first.get('session') and verify_phase1():
        released = True
        phases.append(run(followup(), first['session']))
    return {'phases': phases, 'released': released}


def prepare_workspace(config, task_id, workspace):
    task_dir = CORPUS / 'tasks' / task_id
    task = json.loads((task_dir / 'task.json').read_text())
    host = CORPUS / 'hosts' / task['host']
    if task_id not in config['tasks'] or task['id'] != task_id or host.parent != CORPUS / 'hosts':
        raise ValueError('invalid task or host')
    if any(p.is_symlink() for p in host.rglob('*')):
        raise ValueError('host symlink')
    shutil.copytree(host, workspace)
    patch = task_dir / 'bug.patch'
    if patch.stat().st_size:
        subprocess.run(['git', 'apply', '--whitespace=nowarn', str(patch)], cwd=workspace, check=True)
    phase = task['class'] == 'continuation'
    for name in (('verify_phase1.py', 'visible_phase1.py') if phase else ('verify.py', 'visible.py')):
        shutil.copy2(task_dir / name, workspace / name)
    if task['class'] in {'mcp', 'tool_recovery'}:
        shutil.copy2(CORPUS / 'stubs' / task_id / 'tool.py', workspace / 'tool.py')
    (workspace / 'TASK.md').write_text(task_prompt(task), encoding='utf-8')
    return task


def task_prompt(task):
    lines = [task['objective'], '', 'Relevant files: ' + ', '.join(task['relevant_files']),
             'Writable files: ' + ', '.join(task['writable_files']), *task['invariants']]
    if task['class'] in {'mcp', 'tool_recovery'}:
        lines.append('Run `python3 tool.py` to inspect the local tool output.')
    name = 'verify_phase1.py' if task['class'] == 'continuation' else 'verify.py'
    lines.append(f'Visible check: `python3 {name}`. Work in this directory.')
    return '\n'.join(lines) + '\n'


def release_followup(task_id, workspace):
    task_dir = CORPUS / 'tasks' / task_id
    data = json.loads((task_dir / 'followup.json').read_text())
    for name in ('verify.py', 'visible.py'):
        shutil.copy2(task_dir / name, workspace / name)
    text = data['objective'] + '\nVisible check: `python3 verify.py`.\n'
    (workspace / 'TASK.md').write_text(text, encoding='utf-8')
    return text


def parse_server_metrics(log):
    return {key: [int(x) for x in re.findall(r'\b' + key + r'\s*[=:]\s*(\d+)', log)]
            for key in ('prompt_n', 'cache_n')}


class Proxy:
    """Forward only to the local llama server and retain per-request timings."""
    def __init__(self, target):
        self.rows = []
        rows = self.rows

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                started = time.monotonic()
                conn = http.client.HTTPConnection('127.0.0.1', target, timeout=600)
                row = {'path': self.path, 'ttft_ms': None, 'timings': []}
                try:
                    data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    conn.request('POST', self.path, body=data,
                                 headers={'Content-Type': self.headers.get('Content-Type', 'application/json')})
                    response = conn.getresponse()
                    row['status'] = response.status
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while True:
                        part = response.readline()
                        if not part:
                            break
                        self.wfile.write(part)
                        self.wfile.flush()
                        try:
                            payload = json.loads(part.removeprefix(b'data:').strip())
                            if isinstance(payload, dict) and row['ttft_ms'] is None:
                                choices = payload.get('choices') or []
                                first = choices[0] if choices else {}
                                delta = first.get('delta') or first.get('message') or {}
                                if any(delta.get(key) for key in ('content', 'reasoning_content', 'tool_calls')):
                                    row['ttft_ms'] = (time.monotonic() - started) * 1000
                            if isinstance(payload, dict) and 'timings' in payload:
                                row['timings'].append(payload['timings'])
                        except (ValueError, UnicodeDecodeError):
                            pass
                except (OSError, http.client.HTTPException) as exc:
                    row['error'] = type(exc).__name__
                finally:
                    row['seconds'] = time.monotonic() - started
                    rows.append(row)
                    conn.close()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def sandbox_environment():
    return {'HOME': '/episode-home', 'XDG_CONFIG_HOME': '/episode-home/.config',
            'XDG_DATA_HOME': '/episode-home/.local/share', 'XDG_CACHE_HOME': '/episode-home/.cache',
            'XDG_RUNTIME_DIR': '/tmp', 'TMPDIR': '/tmp', 'PWD': '/workspace',
            'PATH': '/opt/node/bin:/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'OPENCODE_DISABLE_AUTOUPDATE': 'true', 'DO_NOT_TRACK': '1',
            'CORPUS_NODE': '/opt/node/bin/node'}


def bwrap_command(config, workspace, home, command):
    executable = Path(config['opencode']).resolve(strict=True)
    node = Path(config['node']).resolve(strict=True)
    return [config['bwrap'], '--die-with-parent', '--unshare-pid', '--ro-bind', '/usr', '/usr',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/opt', '--ro-bind', str(executable.parent), '/opt/opencode',
            '--ro-bind', str(node.parent.parent), '/opt/node', '--bind', str(workspace), '/workspace',
            '--bind', str(home), '/episode-home', '--chdir', '/workspace', '--', *command]


def verify_isolation(config, workspace, home, task_id):
    oracle = str(CORPUS / 'oracles' / task_id / 'oracle.py')
    script = ('test -r /workspace/TASK.md || exit 10; '
              'cat "$1" >/dev/null 2>&1 && exit 11; '
              'ls /mnt/d >/dev/null 2>&1 && exit 12; '
              'ls /home >/dev/null 2>&1 && exit 13; '
              'printf "workspace_readable oracle_denied mnt_d_denied home_denied\\n"')
    command = bwrap_command(config, workspace, home, ['/bin/sh', '-c', script, 'probe', oracle])
    proc = subprocess.run(command, env=sandbox_environment(), capture_output=True, text=True,
                          timeout=30, check=False)
    words = proc.stdout.split()
    return {'command': command, 'returncode': proc.returncode, 'stdout': proc.stdout,
            'stderr': proc.stderr, **{key: key in words for key in
            ('workspace_readable', 'oracle_denied', 'mnt_d_denied', 'home_denied')}}


def run_cli(config, workspace, home, prompt, session, timeout):
    args = ['/opt/opencode/' + Path(config['opencode']).resolve(strict=True).name,
            'run', '--format', 'json', '--pure', '--agent', 'build',
            '--model', 'local/local-qwen', '--dir', '/workspace']
    if session:
        args += ['--session', session]
    args.append(prompt)
    start = time.monotonic()
    command = bwrap_command(config, workspace, home, args)
    process = subprocess.Popen(command, cwd=workspace, env=sandbox_environment(), stdin=subprocess.DEVNULL,
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
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except ValueError:
            continue
    ids = {item['sessionID'] for item in events if item.get('sessionID')}
    return {'code': code, 'session': next(iter(ids)) if len(ids) == 1 else None,
            'events': events, 'stderr': stderr.decode(errors='replace'),
            'seconds': time.monotonic() - start}


def snapshot(workspace):
    return {p.relative_to(workspace).as_posix(): p.read_bytes()
            for p in workspace.rglob('*') if p.is_file() and not p.is_symlink()
            and not any(x in {'.git', '__pycache__'} for x in p.relative_to(workspace).parts)}


def workspace_diff(before, after):
    chunks = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name, b''), after.get(name, b'')
        if old == new:
            continue
        try:
            chunks.extend(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                                               fromfile='a/' + name, tofile='b/' + name))
        except UnicodeDecodeError:
            chunks.append(f'Binary file changed: {name}\n')
    return ''.join(chunks)


def check_visible(config, task_id, workspace, phase1=False, timeout=120):
    script = CORPUS / 'tasks' / task_id / ('verify_phase1.py' if phase1 else 'verify.py')
    env = {'PATH': str(Path(config['node']).parent) + ':/usr/bin:/bin', 'HOME': str(workspace.parent / 'home'),
           'PYTHONDONTWRITEBYTECODE': '1', 'CORPUS_NODE': config['node']}
    result = subprocess.run([sys.executable, str(script)], cwd=workspace, env=env,
                            capture_output=True, text=True, timeout=max(0.01, timeout), check=False)
    return {'passed': result.returncode == 0, 'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def grade(config, task_id, workspace, output, timeout=120):
    report = output / 'oracle-probe.json'
    env = {'PATH': str(Path(config['node']).parent) + ':/usr/bin:/bin', 'HOME': str(workspace.parent / 'home'),
           'PYTHONDONTWRITEBYTECODE': '1', 'CORPUS_NODE': config['node'],
           'PYTHONPATH': os.pathsep.join([str(workspace), str(CORPUS / 'support')]),
           'CORPUS_PROBE_REPORT': str(report)}
    oracle = CORPUS / 'oracles' / task_id / 'oracle.py'
    proc = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-p',
                           'corpus_probe', '-q', str(oracle)], cwd=workspace, env=env,
                          capture_output=True, text=True, timeout=max(0.01, timeout), check=False)
    (output / 'oracle-output.txt').write_text(proc.stdout + proc.stderr, encoding='utf-8')
    try:
        evidence = json.loads(report.read_text())
    except (OSError, ValueError):
        return {'passed': None, 'status': 'infrastructure'}
    if proc.returncode == 0 and evidence == {'assertions': 0, 'errors': 0}:
        return {'passed': True, 'status': 'pass'}
    if proc.returncode == 1 and evidence.get('assertions', 0) > 0 and evidence.get('errors') == 0:
        return {'passed': False, 'status': 'fail'}
    return {'passed': None, 'status': 'infrastructure'}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def sample_vram(stop, rows):
    while not stop.is_set():
        try:
            raw = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                                           '--format=csv,noheader,nounits'], text=True, timeout=5)
            rows.append(int(raw.splitlines()[0]))
        except (OSError, ValueError, subprocess.SubprocessError):
            rows.append(None)
        stop.wait(1)


def run_attempt(config, unit, output, server, port, log_path):
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    started = time.monotonic()
    deadline = started + config['wall_seconds']
    stop, samples = threading.Event(), []
    sampler = threading.Thread(target=sample_vram, args=(stop, samples), daemon=True)
    sampler.start()
    result = {'unit': unit, 'category': 'infrastructure', 'failure': 'unexpected_error'}
    try:
        task = prepare_workspace(config, unit['task'], workspace)
        before = snapshot(workspace)
        home = output / 'home'
        (home / '.config/opencode').mkdir(parents=True)
        (output / 'tmp').mkdir()
        cache = Path(config['provider_cache'])
        if cache.is_dir():
            shutil.copytree(cache, home / '.config/opencode/node_modules')
            for name in ('package.json', 'package-lock.json'):
                source = cache.parent / name
                if source.is_file():
                    shutil.copy2(source, home / '.config/opencode' / name)
        proof = verify_isolation(config, workspace, home, unit['task'])
        write_json(output / 'isolation-probe.json', proof)
        if proof['returncode'] or not all(proof[key] for key in
                                        ('workspace_readable', 'oracle_denied', 'mnt_d_denied', 'home_denied')):
            raise RuntimeError('bubblewrap isolation probe failed')
        offset = log_path.stat().st_size
        with Proxy(port) as proxy:
            port_proxy = proxy.server.server_address[1]
            write_json(home / '.config/opencode/opencode.json', profile(config, config['arms'][unit['arm']], port_proxy))
            def run(prompt, session):
                return run_cli(config, workspace, home, prompt, session,
                               deadline - time.monotonic() - 90)
            visible_phase = []
            def phase_check():
                checked = check_visible(config, unit['task'], workspace, phase1=True,
                                        timeout=min(60, deadline - time.monotonic() - 60))
                visible_phase.append(checked)
                return checked['passed']
            phases = run_phases(run, phase_check, lambda: release_followup(unit['task'], workspace),
                                (workspace / 'TASK.md').read_text(), task['class'] == 'continuation')
        events = [event for phase in phases['phases'] for event in phase['events']]
        (output / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        (output / 'workspace.diff').write_text(workspace_diff(before, snapshot(workspace)), encoding='utf-8')
        raw = log_path.read_bytes()[offset:].decode(errors='replace')
        (output / 'server-segment.log').write_text(raw, encoding='utf-8')
        visible = check_visible(config, unit['task'], workspace,
                                phase1=task['class'] == 'continuation' and not phases['released'],
                                timeout=min(30, deadline - time.monotonic() - 60))
        oracle = grade(config, unit['task'], workspace, output,
                       timeout=min(60, deadline - time.monotonic()))
        failures = [phase_failure(p, raw, server.poll() is None) for p in phases['phases']]
        failure = next((x for x in failures if x), None)
        if failure != 'model_protocol_error' and any(
            row.get('error') or row.get('status', 0) >= 500 for row in proxy.rows
        ):
            failure = 'server_http_error'
        if any(p['code'] == 124 for p in phases['phases']):
            failure = 'model_wall_timeout'
        if task['class'] == 'continuation' and not phases['released'] and failure is None:
            failure = 'harness_missing_session' if not phases['phases'][0]['session'] else 'model_phase1_incomplete'
        if phases['released'] and phases['phases'][1]['session'] != phases['phases'][0]['session']:
            failure = 'harness_session_mismatch'
        if failure is None and oracle['status'] == 'infrastructure':
            failure = 'grader_infrastructure'
        if failure is None and oracle['passed'] is False:
            failure = 'model_oracle_failed'
        if failure is None and not visible['passed']:
            failure = 'model_visible_failed'
        category = 'infrastructure' if failure in {'server_exited', 'server_http_error',
            'harness_configuration_error'} or oracle['status'] == 'infrastructure' else 'model'
        if failure in {'harness_missing_session', 'harness_session_mismatch'} and category != 'infrastructure':
            category = 'harness'
        if not failure and oracle['passed'] and visible['passed']:
            category = 'success'
        result = {'unit': unit, 'category': category, 'failure': failure,
                  'visible': visible, 'phase1_visible': visible_phase, 'oracle': oracle,
                  'continuation_released': phases['released'],
                  'phases': [{k: v for k, v in p.items() if k != 'events'} for p in phases['phases']],
                  'usage': summarize_usage('opencode', events), 'server_metrics': parse_server_metrics(raw),
                  'proxy_requests': proxy.rows, 'oom_evidence': bool(re.search(
                      r'out of memory|cudamalloc failed|failed to allocate cuda', raw, re.I))}
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        result.update(error=f'{type(exc).__name__}: {exc}')
    finally:
        stop.set()
        sampler.join(timeout=10)
        result['total_seconds'] = time.monotonic() - started
        result['vram_samples_mib'] = samples
        result['peak_vram_mib'] = max((x for x in samples if x is not None), default=None)
        write_json(output / 'result.json', result)
    return result


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class Server:
    def __init__(self, config, arm, output):
        self.config, self.arm, self.output = config, arm, output
        self.port = free_port()
        self.process = None

    def __enter__(self):
        self.output.mkdir(parents=True, exist_ok=True)
        self.path = self.output / 'server.log'
        self.log = self.path.open('ab', buffering=0)
        command = server_command(self.config, self.arm, self.port)
        write_json(self.output / 'server-command.json', command)
        env = {'PATH': '/usr/bin:/bin:/usr/lib/wsl/lib', 'HOME': str(self.output),
               'LD_LIBRARY_PATH': str(Path(self.config['server']).parent), 'CUDA_VISIBLE_DEVICES': '0'}
        try:
            self.process = subprocess.Popen(command, env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
        except OSError:
            self.log.close()
            raise
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('server exited during startup')
                try:
                    with urlopen(f'http://127.0.0.1:{self.port}/health', timeout=1) as response:
                        if response.status == 200:
                            return self
                except OSError:
                    pass
                time.sleep(1)
            raise RuntimeError('server health timeout')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.log.close()


def manifest(config):
    files = [CONFIG, Path(__file__), ROOT / 'benchmark/harness_runner.py',
             ROOT / 'benchmark/configs/harnesses/opencode.json', CORPUS / 'manifest.json',
             CORPUS / 'validate_corpus.py']
    files += [p for sub in ('hosts', 'tasks', 'oracles', 'stubs', 'support', 'prefixes')
              for p in (CORPUS / sub).rglob('*') if p.is_file() and not p.is_symlink()]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}
    frozen = json.loads((CORPUS / 'manifest.json').read_text())
    actual = {name.removeprefix('corpus/'): sha for name, sha in hashes.items()
              if name.startswith(tuple('corpus/' + item + '/' for item in
                                       ('hosts', 'tasks', 'oracles', 'stubs', 'support', 'prefixes')))}
    if actual != frozen:
        raise RuntimeError('corpus differs from its frozen manifest')
    expected = [(config['opencode'], config['opencode_sha256']), (config['server'], config['server_sha256'])]
    expected.extend((m['path'], m['sha256']) for m in config['models'].values())
    for path, sha in expected:
        if digest(path) != sha:
            raise RuntimeError(f'hash mismatch: {path}')
    cache = Path(config['provider_cache'])
    if not cache.is_dir():
        raise RuntimeError('OpenCode provider cache missing')
    cache_hashes = {p.relative_to(cache).as_posix():
                    ('link:' + os.readlink(p) + ':' + digest(p) if p.is_symlink() else digest(p))
                    for p in sorted(cache.rglob('*')) if p.is_file()}
    for name in ('package.json', 'package-lock.json'):
        source = cache.parent / name
        if source.is_file():
            cache_hashes['../' + name] = digest(source)
    version = subprocess.run([config['opencode'], '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if version != config['opencode_version']:
        raise RuntimeError('OpenCode version mismatch')
    return {'protocol_id': config['protocol_id'], 'config': config, 'files_sha256': hashes,
            'provider_cache_sha256': cache_hashes, 'node_sha256': digest(config['node']),
            'python_sha256': digest(sys.executable), 'bwrap_sha256': digest(config['bwrap']),
            'schedule': schedule(config), 'server_lifecycle': 'one process per arm; not restarted between episodes',
            'isolation': 'bubblewrap filesystem and PID namespace; external network is not blocked'}


def execute(config, selected, smoke=False):
    output = Path(config['output'])
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ensure_manifest(output / 'manifest.json', manifest(config))
        running = subprocess.run(['pgrep', '-x', 'llama-server'], capture_output=True, text=True, check=False)
        if running.returncode != 1:
            raise RuntimeError('another llama-server is running or process inspection failed')
        for arm_name in dict.fromkeys(u['arm'] for u in selected):
            units = [u for u in selected if u['arm'] == arm_name]
            arm_dir = output / ('smoke' if smoke else 'units') / arm_name
            arm_dir.mkdir(parents=True, exist_ok=True)
            # A restart occurs only on a new invocation or after server failure.
            epoch = len(list(arm_dir.glob('server-*')))
            server = None

            def start_server():
                nonlocal epoch
                for startup in range(2):
                    epoch += 1
                    directory = arm_dir / f'server-{epoch:03d}'
                    candidate = Server(config, config['arms'][arm_name], directory)
                    try:
                        return candidate.__enter__()
                    except (OSError, RuntimeError) as exc:
                        directory.mkdir(parents=True, exist_ok=True)
                        log = directory / 'server.log'
                        raw = log.read_text(errors='replace') if log.exists() else ''
                        write_json(directory / 'startup-error.json', {'error': str(exc), 'attempt': startup + 1,
                            'oom_evidence': bool(re.search(r'out of memory|cudamalloc failed|failed to allocate cuda', raw, re.I))})
                raise RuntimeError(f'server startup failed twice: {arm_name}')

            try:
                server = start_server()
                for unit in units:
                    unit_dir = arm_dir / f"{unit['task']}-r{unit['repetition']}"
                    unit_dir.mkdir(exist_ok=True)
                    existing = sorted(unit_dir.glob('attempt-*/result.json'))
                    if existing and json.loads(existing[-1].read_text())['category'] != 'infrastructure':
                        continue
                    index = len(existing)
                    def attempt():
                        nonlocal index
                        index += 1
                        return run_attempt(config, unit, unit_dir / f'attempt-{index:02d}',
                                           server.process, server.port, server.path)
                    if index >= 2:
                        raise RuntimeError(f'infrastructure retries exhausted: {unit}')
                    result = attempt()
                    if result['category'] == 'infrastructure' and index < 2:
                        if server.process.poll() is not None:
                            server.__exit__(None, None, None)
                            server = start_server()
                        result = attempt()
                    print(json.dumps({'unit': unit, 'category': result['category'], 'failure': result['failure']}), flush=True)
                    if result['category'] == 'infrastructure':
                        raise RuntimeError(f'infrastructure retry exhausted: {unit}')
            finally:
                if server is not None:
                    server.__exit__(None, None, None)


def main(argv=None):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--stage', type=int, choices=(1, 2, 3))
    parser.add_argument('--arm')
    parser.add_argument('--task', help='select a task for smoke only')
    args = parser.parse_args(argv)
    config = load_config()
    if not (args.dry_run or args.smoke or args.stage or args.arm):
        parser.error('select --dry-run, --smoke, --stage or --arm')
    if args.arm and args.arm not in config['arms']:
        parser.error('unknown arm')
    if args.task and (not args.smoke or args.task not in config['tasks']):
        parser.error('--task must name a corpus task and requires --smoke')
    units = schedule(config)
    if args.stage:
        units = [u for u in units if u['stage'] == args.stage]
    if args.arm:
        units = [u for u in units if u['arm'] == args.arm]
    if args.smoke:
        if args.arm and args.arm != 'B0':
            parser.error('smoke uses B0')
        task = args.task or 'py_query'
        units = [u for u in units if u['arm'] == 'B0' and u['task'] == task and u['repetition'] == 1]
    if not units:
        parser.error('selection is empty')
    if args.dry_run:
        for index, unit in enumerate(units, 1):
            print(f"{index:03d} stage={unit['stage']} arm={unit['arm']} task={unit['task']} rep={unit['repetition']}")
        print(f'Total: {len(units)}')
        return
    execute(config, units, args.smoke)


if __name__ == '__main__':
    main()
