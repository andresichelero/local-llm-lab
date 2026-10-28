"""Run the existing isolated task suite with an independently frozen model queue."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_runtime_v2 as runtime
from benchmark import practical_tasks_v2 as tasks

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOGUE = ROOT / 'benchmark/configs/practical-7bplus-v1.json'


def load_catalogue(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    protocol = value.get('protocol_id', '')
    if protocol in {'practical-agent-selection-v2-r3',
                    'practical-agent-selection-v2-tool-review-v1',
                    'practical-agent-selection-7bplus-v1'}:
        raise ValueError('a new queue must not reuse a historical protocol id')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{3,100}', protocol):
        raise ValueError('invalid queue protocol id')
    models = value.get('models')
    if not isinstance(models, dict) or not models:
        raise ValueError('queue needs an explicit nonempty model catalogue')
    for name, contract in models.items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name):
            raise ValueError('invalid model identity')
        if (not isinstance(contract, dict)
                or not all(isinstance(contract.get(k), str) and contract[k]
                           for k in ('alias', 'path', 'revision', 'sha256'))
                or not re.fullmatch(r'[0-9a-f]{64}', contract['sha256'])):
            raise ValueError(f'invalid model contract: {name}')
        runtime.resolve_server(contract, runtime.LAB)
    return value


class QueueRuntime:
    """Supply the same catalogue to admission and execution, freezing both bundles."""

    def __init__(self, models: Mapping[str, Mapping[str, Any]], catalogue: Path):
        self.models = models
        self.__file__ = runtime.__file__
        self.PROVENANCE_SOURCE_PATHS = (Path(__file__), catalogue,
                                        ROOT / 'scripts/run-practical-7bplus.sh')

    def __getattr__(self, name: str) -> Any:
        return getattr(runtime, name)

    def probe_profile(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return runtime.probe_profile(*args, **kwargs, models=self.models)

    def validate_environment(self, *, lab: Path = runtime.LAB) -> dict[str, Any]:
        result = runtime.validate_environment(lab=lab)
        if result.get('passed') is not True:
            return result
        from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

        try:
            bundles = {}
            for contract in self.models.values():
                server, revision = runtime.resolve_server(contract, lab)
                if str(server) in bundles:
                    continue
                _assert_server_bundle(server, server.parent)
                checked = subprocess.run([str(server), '--version'], capture_output=True, text=True,
                                         timeout=20, check=True,
                                         env={**os.environ, 'LD_LIBRARY_PATH': str(server.parent)})
                version = require_runtime_revision(checked.stdout, checked.stderr, revision)
                server_hash = runtime._sha256(server)
                if contract.get('runtime') and server_hash != contract['runtime']['sha256']:
                    raise ValueError('custom runtime hash mismatch')
                libraries = {p.name: runtime._sha256(p) for p in sorted(server.parent.glob('*.so*'))
                             if p.is_file() and not p.is_symlink()}
                bundles[str(server)] = {'version': version, 'sha256': server_hash,
                                        'libraries': libraries}
            result['runtime_versions']['queue_bundles'] = bundles
            return result
        except Exception as exc:
            return {'passed': False, 'status': 'infrastructure', 'failure': 'infrastructure',
                    'reason': f'{type(exc).__name__}: {exc}', 'runtime_versions': {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalogue', type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument('--output', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--validate-only', action='store_true')
    parser.add_argument('--retry-blocked', action='store_true')
    parser.add_argument('--gpu-free-floor-mib', type=int, default=7000)
    args = parser.parse_args(argv)
    config = load_catalogue(args.catalogue)
    output = args.output or Path(config.get('output', runtime.LAB / 'results' / config['protocol_id']))
    # These globals are scoped to this command's process. Historical defaults on disk stay intact.
    campaign.PROTOCOL = runtime.PROTOCOL = config['protocol_id']
    prior_path = output / 'manifest.json'
    prior = json.loads(prior_path.read_text()) if prior_path.is_file() else {}
    pinned = prior.get('runtime_versions')
    if pinned:
        runtime.configure_runtime_contract({'opencode': pinned['opencode_expected_version'],
                                             'llama_revision': pinned['llama_runtime_revision']})
    elif args.execute:
        from benchmark.practical_repair import daily_contract
        runtime.configure_runtime_contract(daily_contract(runtime.LAB))
    adapter = QueueRuntime(config['models'], args.catalogue)
    if args.validate_only:
        result = adapter.validate_environment()
        print(json.dumps(result, indent=2))
        return 0 if result.get('passed') else 2
    if not args.execute:
        manifest = campaign.build_manifest(config['models'], tasks_module=tasks, runtime_module=adapter,
                                           gpu_free_floor_mib=args.gpu_free_floor_mib)
        campaign._load_or_create_manifest(output, manifest)
        print(json.dumps({'status': 'planned', 'output': str(output), 'models': list(config['models'])}))
        return 0
    manifest = campaign.run_campaign(output, models=config['models'], tasks_module=tasks,
                                     runtime=adapter, retry_blocked=args.retry_blocked,
                                     gpu_free_floor_mib=args.gpu_free_floor_mib)
    print(json.dumps({'status': manifest['status'], 'output': str(output),
                      'records': manifest.get('record_count', 0)}))
    return 0 if manifest['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
