"""Acquire only the authorized Bonsai assets and write the next queue catalogue."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = Path('/home/foxtrot/local-llm-benchmark')
TAG = 'prism-b10787-73bfe6c'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(url: str, target: Path, expected: str) -> None:
    if target.exists():
        if digest(target) != expected:
            raise RuntimeError(f'Existing asset has different content: {target}')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.partial')
    print(json.dumps({'downloading': url, 'destination': str(target)}), flush=True)
    urllib.request.urlretrieve(url, partial)
    if digest(partial) != expected:
        raise RuntimeError(f'Download hash mismatch: {target}')
    partial.replace(target)


def main() -> None:
    from benchmark.practical_selection import contracts

    release = json.load(urllib.request.urlopen(
        f'https://api.github.com/repos/PrismML-Eng/llama.cpp/releases/tags/{TAG}', timeout=30))
    asset = next(a for a in release['assets']
                 if a['name'] == f'llama-{TAG}-bin-linux-cuda-13.3-x64.tar.gz')
    bundle = LAB / 'tools' / TAG
    archive = LAB / 'downloads' / asset['name']
    fetch(asset['browser_download_url'], archive, asset['digest'].removeprefix('sha256:'))
    if not bundle.exists():
        stage = bundle.with_name(bundle.name + '.staging')
        stage.mkdir(exist_ok=False)
        with tarfile.open(archive) as tar:
            tar.extractall(stage, filter='data')
        stage.rename(bundle)
    servers = [p for p in bundle.rglob('llama-server') if p.is_file()]
    if len(servers) != 1:
        raise RuntimeError('Ambiguous Prism server location')
    server = servers[0]
    # Use the complete release directory: its shared libraries are part of the runtime.
    runtime = {'server': str(server), 'version_prefix': '73bfe6c',
               'sha256': digest(server)}
    repo = 'prism-ml/Ternary-Bonsai-2-9B-gguf'
    info = json.load(urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}?blobs=true', timeout=30))
    name = 'Ternary-Bonsai-2-9B-PQ2_0.gguf'
    entry = next(x for x in info['siblings'] if x['rfilename'] == name)
    target = Path('/mnt/c/Users/Andre/LocalLLMLabModels') / name
    if not target.exists() and shutil.disk_usage('/mnt/c').free < entry['size'] + 8 * 1024**3:
        raise RuntimeError('Insufficient C: space for the model and working reserve')
    fetch(f'https://huggingface.co/{repo}/resolve/{info["sha"]}/{name}', target, entry['lfs']['sha256'])
    old = contracts()
    model27 = Path('/mnt/c/Users/Andre/Ternary-Bonsai-2-27B-PTQ1_0.gguf')
    if not model27.is_file():
        raise RuntimeError('Existing Bonsai 27B file is missing')
    print('Hashing existing Bonsai 27B; no second copy or download.', flush=True)
    models = {
        'bonsai-2-27b': {'alias': 'Ternary-Bonsai-2-27B-PTQ1_0', 'path': str(model27),
                         'sha256': digest(model27), 'revision': 'existing-personal-artifact-20261020',
                         'quantization': 'PTQ1_0', 'runtime': runtime},
        'bonsai-2-9b': {'alias': 'Ternary-Bonsai-2-9B-PQ2_0', 'path': str(target),
                        'sha256': entry['lfs']['sha256'], 'revision': info['sha'],
                        'quantization': 'PQ2_0', 'runtime': runtime},
        **{k: old[k] for k in ('ornith-1.0-9b', 'qwen3.5-9b', 'gemma-4-12b')},
    }
    config = {'protocol_id': 'practical-agent-selection-7bplus-v1', 'models': models,
              'qwen38_research': {'official_7b_to_12b_found': False,
                                  'community_distill': 'empero-ai/Qwen3.8-9B-Distill',
                                  'decision': 'Not an official Qwen3.8 release; keep Qwen3.5-9B as control'},
              'runtime_archive_sha256': asset['digest'],
              'output': str(LAB / 'results/practical-selection-7bplus-v1')}
    path = ROOT / 'benchmark/configs/practical-7bplus-v1.json'
    data = json.dumps(config, indent=2) + '\n'
    if path.exists() and path.read_text() != data:
        raise RuntimeError('Existing frozen catalogue differs; refusing overwrite')
    path.write_text(data)
    env = {**os.environ, 'LD_LIBRARY_PATH': str(server.parent)}
    import subprocess
    check = subprocess.run([str(server), '--version'], env=env, capture_output=True, text=True, check=True)
    print(check.stdout + check.stderr, flush=True)
    print(json.dumps({'catalogue': str(path), 'models': list(models), 'runtime': runtime}), flush=True)


if __name__ == '__main__':
    main()
