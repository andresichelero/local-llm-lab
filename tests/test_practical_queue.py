"""Controls for catalogue isolation and per-model inference runtimes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_queue as queue
from benchmark import practical_runtime_v2 as runtime


def test_catalogue_does_not_reintroduce_removed_models(tmp_path):
    path = tmp_path / 'queue.json'
    path.write_text(json.dumps({'protocol_id': 'practical-7bplus-test', 'models': {
        'bonsai-2-27b': {'alias': 'bonsai', 'path': '/models/27.gguf',
                         'sha256': 'a' * 64, 'revision': 'fixture'},
    }}))
    config = queue.load_catalogue(path)
    assert list(config['models']) == ['bonsai-2-27b']
    path.write_text(json.dumps({**config, 'protocol_id': 'practical-agent-selection-v2-r3'}))
    with pytest.raises(ValueError, match='historical'):
        queue.load_catalogue(path)


def test_catalogue_rejects_historical_7bplus_id_and_accepts_new_protocol(tmp_path):
    path = tmp_path / 'queue.json'
    models = {'bonsai-2-27b': {'alias': 'bonsai', 'path': '/models/27.gguf',
                               'sha256': 'a' * 64, 'revision': 'fixture'}}
    historical = {'protocol_id': 'practical-agent-selection-7bplus-v1', 'models': models}
    path.write_text(json.dumps(historical))
    with pytest.raises(ValueError, match='historical'):
        queue.load_catalogue(path)

    current = {**historical, 'protocol_id': 'practical-agent-selection-7bplus-tool-review-v2'}
    path.write_text(json.dumps(current))
    assert queue.load_catalogue(path)['protocol_id'] == current['protocol_id']

    default = queue.load_catalogue(queue.DEFAULT_CATALOGUE)
    assert default['protocol_id'] == current['protocol_id']
    assert default['output'].endswith('practical-selection-7bplus-tool-review-v2')


def test_runtime_identity_is_frozen_in_model_manifest():
    first = {'m': {'alias': 'm', 'path': 'm.gguf', 'sha256': 'a' * 64,
                   'runtime': {'server': '/prism/llama-server', 'version_prefix': '73bfe6c',
                               'sha256': 'b' * 64}, 'quantization': 'PTQ1_0'}}
    one = campaign._model_artifacts(first)
    first['m']['runtime'] = {**first['m']['runtime'], 'sha256': 'c' * 64}
    two = campaign._model_artifacts(first)
    assert one != two
    assert one['m']['quantization'] == 'PTQ1_0'


def test_custom_runtime_resolves_without_changing_default(tmp_path):
    server, revision = runtime.resolve_server({}, tmp_path)
    assert server == tmp_path / 'tools/llama-bin/llama-server'
    contract = {'runtime': {'server': '/prism/llama-server', 'version_prefix': '73bfe6c',
                            'sha256': 'b' * 64}}
    server, revision = runtime.resolve_server(contract, tmp_path)
    assert str(server) == '/prism/llama-server'
    assert revision == '73bfe6c'
    with pytest.raises(ValueError, match='runtime'):
        runtime.resolve_server({'runtime': {'server': '/unknown'}}, tmp_path)


def test_probe_receives_exact_queue_catalogue(monkeypatch, tmp_path):
    models = {'bonsai-2-27b': {'alias': 'fixture'}}
    seen = {}

    def probe(*args, **kwargs):
        seen.update(kwargs)
        return {'passed': True}

    monkeypatch.setattr(runtime, 'probe_profile', probe)
    adapter = queue.QueueRuntime(models, tmp_path / 'catalogue.json')
    adapter.probe_profile('bonsai-2-27b', {'id': 'baseline'}, lab=tmp_path)
    assert seen['models'] is models


def test_new_protocol_is_used_for_every_schedule(monkeypatch):
    monkeypatch.setattr(campaign, 'PROTOCOL', 'new-queue-protocol')
    baseline = campaign.baseline_schedule(('a', 'b'))
    tuning = campaign.tuning_schedule(('a', 'b'), campaign.profile_catalog(
        context_32k_cache_prompt=False)['cache_on'], stage='cache_on')
    holdout = campaign.holdout_schedule(('a', 'b'), {
        'a': campaign.BASELINE_PROFILE, 'b': campaign.BASELINE_PROFILE})
    assert {r['protocol'] for r in baseline + tuning + holdout} == {'new-queue-protocol'}


@pytest.mark.parametrize('frozen', [True, False])
def test_launcher_keeps_custom_output_runtime_frozen(tmp_path, frozen):
    root = tmp_path / 'repo'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    shutil.copyfile(Path(queue.__file__).parents[1] / 'scripts/run-practical-7bplus.sh',
                    scripts / 'run-practical-7bplus.sh')
    marker = tmp_path / 'updated'
    (scripts / '00_update_runtime.sh').write_text('touch "$UPDATE_TEST_MARKER"\n')
    lab = tmp_path / 'lab'
    binary = lab / 'envs/lab-validation/bin/python'
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    output = tmp_path / 'custom-output'
    output.mkdir()
    (output / 'manifest.json').write_text(json.dumps({'runtime_versions': {'fixture': '1'} if frozen else None}))
    subprocess.run(['bash', str(scripts / 'run-practical-7bplus.sh'), '--execute',
                    '--output', str(output)], check=True,
                   env={**os.environ, 'BENCH_STORAGE_ROOT': str(lab), 'UPDATE_TEST_MARKER': str(marker)})
    assert marker.exists() is not frozen
