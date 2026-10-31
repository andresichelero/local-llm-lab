import subprocess
from pathlib import Path

from benchmark import opencode_baseline as baseline


class Done:
    returncode = 0
    stdout = '{"passed": true, "status": "pass"}'
    stderr = ''


def config(tmp_path):
    return {'bwrap': 'bwrap', 'node': str(tmp_path / 'node' / 'bin' / 'node')}


def test_grader_reruns_once_after_a_timeout(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return Done

    monkeypatch.setattr(baseline.subprocess, 'run', run)
    result = baseline.sandbox_evaluate(config(tmp_path), 'tests_list', tmp_path, None, False, 30, True)
    assert result == {'passed': True, 'status': 'pass'}
    assert len(calls) == 2


def test_grader_reports_infrastructure_after_two_timeouts(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])

    monkeypatch.setattr(baseline.subprocess, 'run', run)
    result = baseline.sandbox_evaluate(config(tmp_path), 'tests_list', Path(tmp_path), None, False, 30, True)
    assert result['status'] == 'infrastructure'
    assert len(calls) == 2
