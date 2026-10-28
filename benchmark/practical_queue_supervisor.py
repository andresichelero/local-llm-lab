"""Wait for GPU capacity and resume an existing queue without replaying results."""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAB = Path('/home/foxtrot/local-llm-benchmark')


def action_for(manifest: dict[str, Any], records: list[dict[str, Any]],
               free_mib: int, floor_mib: int) -> str:
    state = manifest.get('status')
    if state == 'complete':
        return 'complete'
    if state == 'blocked':
        blocked = [r for r in records if r.get('status') == 'blocked']
        if (not blocked or any(r.get('failure') != 'infrastructure'
                               or 'GPU capacity gate failed' not in str(r.get('error', ''))
                               for r in blocked)):
            return 'needs_attention'
    elif state not in {'planned', 'running', 'interrupted'}:
        return 'needs_attention'
    return 'resume' if free_mib >= floor_mib else 'waiting_for_vram'


def active_campaign(pid_path: Path) -> bool:
    try:
        pid = int(pid_path.read_text().strip())
        parts = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return b'benchmark.practical_queue' in parts
    except (OSError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=LAB / 'results/practical-selection-7bplus-v1')
    parser.add_argument('--catalogue', type=Path, default=ROOT / 'benchmark/configs/practical-7bplus-v1.json')
    parser.add_argument('--poll-seconds', type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 60:
        parser.error('poll interval must be 1-60 seconds')
    output = args.output
    # Do not create an implicit campaign. It must already have a frozen manifest.
    manifest_path = output / 'manifest.json'
    if not manifest_path.is_file():
        parser.error('an existing campaign manifest is required')
    lock = (output / 'supervisor.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 3
    while True:
        manifest = json.loads(manifest_path.read_text())
        records_path = output / 'records.json'
        records = json.loads(records_path.read_text()) if records_path.exists() else []
        floor = manifest['immutable']['gpu_free_floor_mib']
        if active_campaign(output / 'campaign.pid'):
            action, free = 'running', None
        else:
            result = subprocess.run(['/usr/lib/wsl/lib/nvidia-smi', '--query-gpu=memory.free',
                                     '--format=csv,noheader,nounits'], capture_output=True,
                                    text=True, timeout=15, check=True)
            free = int(result.stdout.strip().splitlines()[0])
            action = action_for(manifest, records, free, floor)
        status = {'status': action, 'gpu_free_mib': free, 'required_mib': floor,
                  'completed_episodes': sum(r.get('status') == 'complete' for r in records),
                  'updated_at_utc': datetime.now(timezone.utc).isoformat()}
        temporary = output / 'supervisor-state.tmp'
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(output / 'supervisor-state.json')
        if action in {'complete', 'needs_attention'}:
            print(json.dumps(status), flush=True)
            return 0 if action == 'complete' else 2
        if action == 'resume':
            command = [str(LAB / 'envs/lab-validation/bin/python'), '-m',
                       'benchmark.practical_queue', '--catalogue', str(args.catalogue),
                       '--output', str(output), '--execute', '--retry-blocked',
                       '--gpu-free-floor-mib', str(floor)]
            with (output / 'campaign-console.log').open('ab', buffering=0) as log:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True, close_fds=True)
            (output / 'campaign.pid').write_text(str(process.pid) + '\n')
            print(json.dumps({**status, 'campaign_pid': process.pid}), flush=True)
        time.sleep(args.poll_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
