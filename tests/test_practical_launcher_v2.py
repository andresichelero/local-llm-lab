"""The launcher updates new campaigns but never mutates frozen resumed runtimes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name == 'nt', reason='WSL bash entrypoint')
ROOT = Path(__file__).resolve().parents[1]


def _manifest_with_immutable(immutable):
    from benchmark import practical_campaign_v2 as campaign

    return {'immutable': immutable, 'immutable_sha256': campaign._hash_value(immutable)}


@pytest.mark.parametrize('resume', ['new', 'planned', 'frozen'])
@pytest.mark.parametrize('mode', ['execute', 'validate-only', 'regrade-run'])
def test_launcher_updates_only_before_new_campaign(tmp_path, resume, mode):
    root = tmp_path / 'checkout'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    launcher = scripts / 'run-practical-selection-v2.sh'
    shutil.copyfile(ROOT / 'scripts/run-practical-selection-v2.sh', launcher)
    (scripts / '00_update_runtime.sh').write_text('echo update >> "$TRACE"\n')
    lab = tmp_path / 'lab'
    python = lab / 'envs/lab-validation/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$TRACE"\n')
    python.chmod(0o755)
    output = tmp_path / 'campaign with spaces'
    output.mkdir()
    if resume != 'new':
        (output / 'manifest.json').write_text(
            '{"runtime_versions":{"python":"fixture"}}' if resume == 'frozen'
            else '{"runtime_versions":null,"status":"planned"}')
    trace = tmp_path / 'trace'
    mode_args = ['--execute'] if mode == 'execute' else (
        ['--validate-only'] if mode == 'validate-only' else ['--regrade-run'])
    result = subprocess.run(['bash', str(launcher), '--output', str(output), *mode_args],
                            env={**os.environ, 'BENCH_STORAGE_ROOT': str(lab), 'TRACE': str(trace)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = trace.read_text().splitlines()
    assert ('update' in lines) == (resume != 'frozen' and mode == 'execute')
    assert str(output) in lines
    assert all(argument in lines for argument in mode_args)
    assert ('--execute' in lines) == (mode == 'execute')
    assert 'benchmark.practical_campaign_v2' in lines


@pytest.mark.skipif(os.environ.get('RUN_PRACTICAL_INTEGRATION') != '1',
                    reason='actual pinned WSL CLI integration')
@pytest.mark.parametrize('mode', ['--validate-only', '--regrade-run'])
def test_launcher_dispatches_actual_non_inference_cli_modes(tmp_path, mode):
    output = tmp_path / 'output'
    output.mkdir()
    if mode == '--validate-only':
        immutable = {'runtime_expectations': {
                'opencode': '1.19.4',
                'llama_revision': '620d2225cc436ab0b001e3200e590e3b286ef9ab',
            }}
        (output / 'manifest.json').write_text(json.dumps(_manifest_with_immutable(immutable)))
    result = subprocess.run(['bash', str(ROOT / 'scripts/run-practical-selection-v2.sh'),
                             mode, '--output', str(output)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    if mode == '--validate-only':
        validation = json.loads(result.stdout)
        assert validation['runtime_versions']['opencode_expected_version'] == '1.19.4'
        assert validation['runtime_versions']['llama_runtime_revision'] == (
            '620d2225cc436ab0b001e3200e590e3b286ef9ab')


def test_validate_only_selects_frozen_runtime_contract_from_output_manifest(tmp_path, monkeypatch, capsys):
    from benchmark import practical_campaign_v2 as campaign
    from benchmark import practical_runtime_v2 as runtime
    from benchmark import practical_tasks_v2 as tasks

    contract = {'opencode': '1.19.4',
                'llama_revision': '620d2225cc436ab0b001e3200e590e3b286ef9ab'}
    output = tmp_path / 'existing-campaign'
    output.mkdir()
    (output / 'manifest.json').write_text(json.dumps(_manifest_with_immutable({
        'runtime_expectations': contract,
    })))
    monkeypatch.setattr(runtime, '_ACTIVE_RUNTIME_CONTRACT', runtime._ACTIVE_RUNTIME_CONTRACT)
    configured = []
    configure = runtime.configure_runtime_contract

    def record_configuration(value):
        configured.append(dict(value))
        configure(value)

    monkeypatch.setattr(runtime, 'configure_runtime_contract', record_configuration)
    monkeypatch.setattr(runtime, 'validate_environment', lambda *, lab: {
        'passed': True,
        'runtime_versions': {
            'opencode_expected_version': runtime.current_runtime_contract(lab)['opencode'],
            'llama_runtime_revision': runtime.current_runtime_contract(lab)['llama_revision'],
        },
    })
    monkeypatch.setattr(campaign, '_load_runtime_and_tasks', lambda: (runtime, tasks))

    result = campaign.main(['--validate-only', '--output', str(output)])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert configured == [contract]
    assert payload['runtime_versions']['opencode_expected_version'] == '1.19.4'


def test_validate_only_rejects_invalid_frozen_runtime_contract(tmp_path, monkeypatch, capsys):
    from benchmark import practical_campaign_v2 as campaign
    from benchmark import practical_runtime_v2 as runtime
    from benchmark import practical_tasks_v2 as tasks

    output = tmp_path / 'existing-campaign'
    output.mkdir()
    immutable = {'runtime_expectations': {
            'opencode': 'not-a-version', 'llama_revision': 'invalid',
        }}
    (output / 'manifest.json').write_text(json.dumps(_manifest_with_immutable(immutable)))
    def unexpected_validation(**kwargs):
        raise AssertionError('invalid frozen runtime contract reached environment validation')

    monkeypatch.setattr(runtime, 'validate_environment', unexpected_validation)
    monkeypatch.setattr(campaign, '_load_runtime_and_tasks', lambda: (runtime, tasks))

    result = campaign.main(['--validate-only', '--output', str(output)])

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload['passed'] is False
    assert payload['failure'] == 'runtime_contract_invalid'
    assert 'invalid runtime contract' in payload['reason']


@pytest.mark.parametrize('damage', ['missing_hash', 'changed_contract'])
def test_validate_only_rejects_missing_or_stale_immutable_hash(tmp_path, monkeypatch, capsys, damage):
    from benchmark import practical_campaign_v2 as campaign
    from benchmark import practical_runtime_v2 as runtime
    from benchmark import practical_tasks_v2 as tasks

    output = tmp_path / 'existing-campaign'
    output.mkdir()
    immutable = {'runtime_expectations': {
        'opencode': '1.19.4', 'llama_revision': '620d2225cc436ab0b001e3200e590e3b286ef9ab',
    }}
    manifest = _manifest_with_immutable(immutable)
    if damage == 'missing_hash':
        del manifest['immutable_sha256']
    else:
        manifest['immutable']['runtime_expectations']['opencode'] = '1.19.5'
    (output / 'manifest.json').write_text(json.dumps(manifest))
    configured = []
    validated = []
    monkeypatch.setattr(runtime, 'configure_runtime_contract', configured.append)
    monkeypatch.setattr(runtime, 'validate_environment', lambda **kwargs: validated.append(kwargs))
    monkeypatch.setattr(campaign, '_load_runtime_and_tasks', lambda: (runtime, tasks))

    result = campaign.main(['--validate-only', '--output', str(output)])

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload['passed'] is False
    assert payload['failure'] == 'runtime_contract_invalid'
    assert 'immutable_sha256' in payload['reason']
    assert configured == []
    assert validated == []
