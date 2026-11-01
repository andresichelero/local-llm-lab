#!/usr/bin/env python3
"""Measure decode speed of the recommended R-q4 server on fixed prompts.

Each arm is a set of extra server flags. Arms run in ABBA order, one server load
per arm and block, and every request records speed, draft acceptance and GPU
telemetry from the busy samples. Results go to requests.jsonl in --out.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark import nvml_session

BASE = Path('/home/foxtrot/local-llm-benchmark')
SERVER = BASE / 'tools/llama-bin-master-792fcf4e7/llama-server'
MODEL = BASE / 'models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf'
CONTEXT_SOURCE = ROOT / 'corpus/hosts/bottle-0.13.2/bottle.py'
CONTEXT_CHARS = 95000
PORT = 8099
CLOCK_MEMORY = 2
POWER_CAP = 4
BUSY_PCT = 90
ARMS = {'base': [], 'draft-q4': ['-ctkd', 'q4_0', '-ctvd', 'q4_0']}
SHORT = 'Write a Python function that parses an ISO 8601 duration into seconds. Include error handling and a short test.'
LONG_TASK = 'Refactor the routing code above so that dynamic route filters live in their own class. Show the new class.'
MEMORY_LINE = re.compile(r'llama_kv_cache: size|compute buffer size')


def server_command(arm, verbose=False):
    return [str(SERVER), '--model', str(MODEL), '--host', '127.0.0.1', '--port', str(PORT), '--alias', 'local-qwen',
            '--ctx-size', '65536', '--parallel', '1', '-ngl', '99', '--fit', 'off', '--flash-attn', 'on',
            '--cache-type-k', 'q4_0', '--cache-type-v', 'q4_0', '--jinja', '--reasoning', 'off',
            '--chat-template-kwargs', '{"enable_thinking": false}', '--temp', '0.2', '--top-p', '0.95',
            '--top-k', '20', '--no-webui', '--spec-type', 'draft-mtp', '--spec-draft-n-max', '2',
            '--ctx-checkpoints', '64', '--checkpoint-min-step', '1024', '--cache-ram', '2048'] + ARMS[arm] + (
                ['--log-verbosity', '4'] if verbose else [])


def call(path, payload=None, timeout=600):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(f'http://127.0.0.1:{PORT}{path}', data, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def wait_ready(process):
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError(f'server exited with {process.returncode}')
        try:
            if call('/health', timeout=2).get('status') == 'ok':
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError('server not ready')


def busy_summary(samples, limit_w):
    """Summarize the samples with the GPU busy; fall back to all of them on very short requests."""
    busy = [row for row in samples if (row['gpu_util_pct'] or 0) >= BUSY_PCT] or samples
    if not busy:
        return {'power_limit_w': limit_w}
    return {'power_limit_w': limit_w, 'samples': len(busy),
            'clock_mhz': statistics.median(row['gpu_clock_mhz'] for row in busy),
            'memory_clock_mhz': statistics.median(row['memory_clock_mhz'] for row in busy),
            'power_w': round(statistics.median(row['power_w'] for row in busy), 1),
            'temp_c': max(row['temperature_c'] for row in busy),
            'power_cap_share': round(sum(row['reasons'] & POWER_CAP > 0 for row in busy) / len(busy), 3),
            'peak_mib': max(row['vram_used_mib'] for row in samples)}


def telemetry():
    """Start sampling and return a function that stops it and gives the summary."""
    library, device = nvml_session._open()
    samples, done = [], threading.Event()
    limit, reasons, memory = ctypes.c_uint(), ctypes.c_ulonglong(), ctypes.c_uint()
    library.nvmlDeviceGetEnforcedPowerLimit(device, ctypes.byref(limit))

    def sample():
        while not done.wait(0.5):
            library.nvmlDeviceGetCurrentClocksThrottleReasons(device, ctypes.byref(reasons))
            library.nvmlDeviceGetClockInfo(device, CLOCK_MEMORY, ctypes.byref(memory))
            samples.append({**nvml_session.metrics(), 'reasons': reasons.value, 'memory_clock_mhz': memory.value})

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()

    def stop():
        done.set()
        thread.join()
        return busy_summary(samples, limit.value / 1000)
    return stop


def generate(prompt, predict):
    start = time.time()
    body = call('/v1/chat/completions', {'model': 'local-qwen', 'messages': [{'role': 'user', 'content': prompt}],
                                         'max_tokens': predict, 'seed': 1234, 'cache_prompt': False})
    timings = body.get('timings', {})
    text = body['choices'][0]['message'].get('content') or ''
    return {'wall_s': round(time.time() - start, 2), 'prompt_n': timings.get('prompt_n'),
            'predicted_n': timings.get('predicted_n'), 'tok_s': timings.get('predicted_per_second'),
            'prompt_tok_s': timings.get('prompt_per_second'), 'draft_n': timings.get('draft_n'),
            'draft_accepted': timings.get('draft_n_accepted'),
            'output_sha': hashlib.sha256(text.encode()).hexdigest()[:12]}


def run_arm(arm, block, out, prompts, repeats, verbose=False):
    log = out / f'{arm}-b{block}.log'
    idle = nvml_session.memory_mib()[2]
    with log.open('wb') as sink:
        process = subprocess.Popen(server_command(arm, verbose), stdout=sink, stderr=subprocess.STDOUT)
    try:
        wait_ready(process)
        row = {'arm': arm, 'block': block, 'idle_mib': idle, 'loaded_mib': nvml_session.memory_mib()[2]}
        print(row, flush=True)
        for line in log.read_text(errors='replace').splitlines():
            if MEMORY_LINE.search(line):
                print(line[:150], flush=True)
        for kind, prompt, predict in prompts:
            for repeat in range(repeats):
                stop = telemetry()
                result = generate(prompt, predict)
                result.update(row, kind=kind, repeat=repeat, **stop())
                with (out / 'requests.jsonl').open('a') as sink:
                    sink.write(json.dumps(result) + '\n')
    finally:
        process.terminate()
        process.wait(timeout=60)
        time.sleep(3)


def summarize(rows):
    """Return one line per arm and prompt kind; warm-up requests do not count."""
    groups = {}
    for row in rows:
        if row['kind'] != 'warmup':
            groups.setdefault((row['kind'], row['arm'], row['power_limit_w'], row['memory_clock_mhz']), []).append(row)
    lines = []
    for (kind, arm, limit, memory), part in sorted(groups.items(), key=str):
        accepted = sum(row['draft_accepted'] or 0 for row in part)
        drafted = sum(row['draft_n'] or 0 for row in part)
        speeds = [row['tok_s'] for row in part]
        lines.append(f'{kind} {arm} limit={limit:.0f}W memory={memory:.0f}MHz n={len(part)} '
                     f'tok/s median {statistics.median(speeds):.1f} range {min(speeds):.1f}-{max(speeds):.1f} '
                     f'acceptance {accepted / max(drafted, 1):.3f} '
                     f'clock {statistics.median(row["clock_mhz"] for row in part):.0f}MHz '
                     f'power {statistics.median(row["power_w"] for row in part):.1f}W '
                     f'peak {max(row["peak_mib"] for row in part)}MiB '
                     f'outputs {len({row["output_sha"] for row in part})}')
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--arms', default='base,draft-q4')
    parser.add_argument('--blocks', type=int, default=4)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--verbose-log', action='store_true', help='print buffer sizes; may slow decode, so not for speed runs')
    parser.add_argument('--summary', action='store_true', help='only print the summary of --out')
    args = parser.parse_args()
    requests = args.out / 'requests.jsonl'
    if not args.summary:
        args.out.mkdir(parents=True, exist_ok=True)
        context = CONTEXT_SOURCE.read_text(encoding='utf-8')[:CONTEXT_CHARS]
        prompts = [('warmup', SHORT, 64), ('short', SHORT, 400), ('long', f'{context}\n\n{LONG_TASK}', 400)]
        arms = args.arms.split(',')
        for block in range(args.blocks):
            for arm in arms if block % 2 == 0 else arms[::-1]:
                run_arm(arm, block, args.out, prompts, args.repeats, args.verbose_log)
    print('\n'.join(summarize(json.loads(line) for line in requests.read_text().splitlines())))


if __name__ == '__main__':
    main()
