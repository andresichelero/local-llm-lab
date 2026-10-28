"""Trusted sandbox driver: retain the OpenCode session, export snapshots and test results."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path


def snapshot(phase):
    root = Path('/workspace')
    path = root / f'.snapshot{phase}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(root.rglob('*')):
            relative = source.relative_to(root)
            if (source.is_file() and not source.is_symlink()
                    and not any(p in {'.git', '__pycache__'} for p in relative.parts)
                    and source.name not in {'.snapshot1.zip', '.snapshot2.zip', '.practical.json'}):
                archive.write(source, str(relative))


def authored_tests():
    sys.path.insert(0, '/workspace')
    sys.path.insert(0, '/workspace/src')
    stream = io.StringIO()
    try:
        suite = unittest.defaultTestLoader.discover('/workspace/tests')
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
        return {'passed': result.wasSuccessful(), 'count': result.testsRun,
                'output': stream.getvalue()[-12000:]}
    except Exception as exc:
        return {'passed': False, 'count': 0, 'output': str(exc)}


def main():
    config = json.loads(Path('/opt/practical/driver.json').read_text())
    started = time.monotonic()
    events, phases, session = [], [], None
    for index, prompt in enumerate(config['prompts'], 1):
        args = ['/opt/opencode', 'run', '--format', 'json', '--pure', '--agent', 'build',
                '--model', config['model'], '--dir', '/workspace']
        if index > 1:
            if not session:
                break
            args += ['--session', session]
        args += [prompt]
        remaining = max(1, config.get('seconds', 290) - (time.monotonic() - started))
        if len(config['prompts']) > 1 and index == 1:
            remaining = min(remaining, 145)
        phase_start = time.monotonic()
        try:
            proc = subprocess.run(args, capture_output=True, timeout=remaining)
            raw, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            raw, stderr, code = exc.stdout or b'', exc.stderr or b'', 124
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(stderr[-16000:])
        phase_events = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
                phase_events.append(event)
                session = event.get('sessionID') or session
            except (ValueError, AttributeError):
                pass
        events.extend(phase_events)
        # Run authored tests in a separate process so imports cannot contaminate
        # continuation or the driver. The same outer wall deadline applies.
        test_info = {'passed': None, 'count': 0}
        if Path('/workspace/tests').is_dir():
            try:
                test = subprocess.run(['/usr/bin/python3', '-B', '/opt/practical/driver.py', '--tests'],
                                      capture_output=True, timeout=10)
                test_info = json.loads(test.stdout)
            except (subprocess.TimeoutExpired, ValueError):
                test_info = {'passed': False, 'count': 0, 'output': 'test timeout or invalid output'}
        state = Path('/scratch/practical-mcp-state.json')
        if state.is_file():
            (Path('/workspace') / '.mcp-state.json').write_bytes(state.read_bytes())
        snapshot(index)
        phases.append({'phase': index, 'exit_code': code, 'seconds': time.monotonic() - phase_start,
                       'session_id': session, 'authored_tests': test_info,
                       'final_text': '\n'.join(str(e.get('part', {}).get('text', ''))
                                               for e in phase_events if e.get('type') == 'text')})
        Path('/workspace/.practical.json').write_text(json.dumps({'phases': phases}))
        if code != 0:
            break
    return 0


if __name__ == '__main__':
    if '--tests' in sys.argv:
        print(json.dumps(authored_tests()))
    else:
        os.chdir('/workspace')
        raise SystemExit(main())
