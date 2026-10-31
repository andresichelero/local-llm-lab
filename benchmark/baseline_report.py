"""Offline summary of OpenCode baseline results; never runs an episode."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

INFRA = {'server_exited', 'server_http_error', 'harness_configuration_error',
         'grader_infrastructure'}


def wilson(successes, n):
    if not n:
        return None, None
    z = 1.959963984540054
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def mcnemar_exact(wins, losses):
    n = wins + losses
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)


def read_results(directories):
    """Use first non-infrastructure attempt, separately per input directory and unit."""
    selected = []
    for root in map(Path, directories):
        if not root.is_dir():
            raise ValueError(f'not a directory: {root}')
        # units excludes smoke, and attempt ordering is encoded in its path.
        groups = defaultdict(list)
        for path in sorted((root / 'units').glob('*/*/attempt-*/result.json')):
            groups[path.parent.parent].append(path)
        for paths in groups.values():
            for path in paths:
                row = json.loads(path.read_text(encoding='utf-8'))
                if row.get('failure') not in INFRA:
                    row['_source'] = str(root.resolve())
                    selected.append(row)
                    break
    return selected


def _numbers(values):
    return [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)]


def _med(values):
    numbers = _numbers(values)
    return median(numbers) if numbers else None


def _sum_if_complete(values):
    values = list(values)
    if not values:
        return 0
    nums = _numbers(values)
    return sum(nums) if len(nums) == len(values) else None


def _success(row):
    # v5 misclassified some model failures as infrastructure; failure is authoritative.
    return row.get('failure') is None and row.get('category') == 'success'


def _timings(row):
    # Streaming may repeat timings; one final timing object per request.
    return [request['timings'][-1] for request in row.get('proxy_requests', [])
            if request.get('timings')]


def _metric(row, key):
    return _med([entry.get(key) for entry in _timings(row)])


def _timing_sum(row, key):
    timings = _timings(row)
    if not timings or len(timings) != len(row.get('proxy_requests', [])):
        return None
    return _sum_if_complete([item.get(key) for item in timings])


def _usage_token(row, key):
    usage = row.get('usage') or {}
    if usage.get('model_calls') == 0:
        return None
    return usage.get(key)


def _taxonomy(row):
    value = row.get('taxonomy') or {}
    if not isinstance(value, dict):
        return []
    return [x for x in [value.get('primary'), *(value.get('secondary') or [])] if x]


def summarize(rows, control=None, control_dir=None):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['_source'], row['unit']['arm'])].append(row)
    arms, tasks, comparisons = [], [], []
    for (source, arm), data in sorted(grouped.items()):
        successes = sum(_success(r) for r in data)
        lo, hi = wilson(successes, len(data))
        failed = [r for r in data if not _success(r)]
        tags = Counter(tag for row in failed for tag in _taxonomy(row))
        arms.append({'source': source, 'arm': arm, 'n': len(data), 'successes': successes,
                     'success_rate': successes / len(data), 'wilson_low': lo, 'wilson_high': hi,
                     'seconds_mean': mean(_numbers([r.get('total_seconds') for r in data]))
                         if _numbers([r.get('total_seconds') for r in data]) else None,
                     'seconds_median': _med([r.get('total_seconds') for r in data]),
                     'ttft_ms_median': _med([_med([x.get('ttft_ms') for x in r.get('proxy_requests', [])]) for r in data]),
                     'prefill_tok_s_median': _med([_metric(r, 'prompt_per_second') for r in data]),
                     'decode_tok_s_median': _med([_metric(r, 'predicted_per_second') for r in data]),
                     'peak_vram_mib_median': _med([r.get('peak_vram_mib') for r in data]),
                     'processed_tokens_total': _sum_if_complete([_timing_sum(r, 'prompt_n') for r in data]),
                     'cache_tokens_total': _sum_if_complete([_timing_sum(r, 'cache_n') for r in data]),
                     'wasted_prompt_tokens': _sum_if_complete([_usage_token(r, 'prompt_tokens') for r in failed]),
                     'wasted_completion_tokens': _sum_if_complete([_usage_token(r, 'completion_tokens') for r in failed]),
                     'wasted_seconds': _sum_if_complete([r.get('total_seconds') for r in failed]),
                     'taxonomy': json.dumps(dict(sorted(tags.items())), ensure_ascii=False)})
        by_task = defaultdict(list)
        for row in data:
            by_task[row['unit']['task']].append(row)
        for task, subset in sorted(by_task.items()):
            passed = sum(_success(r) for r in subset)
            tasks.append({'source': source, 'arm': arm, 'task': task, 'n': len(subset),
                          'successes': passed, 'outcomes': ''.join('1' if _success(r) else '0'
                              for r in sorted(subset, key=lambda x: x['unit']['repetition'])),
                          'stability': ('insufficient' if len(subset) < 2 else
                                        'mixed' if 0 < passed < len(subset) else 'consistent')})
    for source in sorted({r['_source'] for r in rows}):
        names = {arm for src, arm in grouped if src == source}
        reference_source = str(Path(control_dir).resolve()) if control_dir else source
        reference_names = {arm for src, arm in grouped if src == reference_source}
        baseline = control or ('C4-q4' if 'C4-q4' in reference_names else 'B0')
        if baseline not in reference_names:
            continue
        reference = {(r['unit']['task'], r['unit']['repetition']): _success(r)
                     for r in grouped[(reference_source, baseline)]}
        for arm in sorted(names):
            if source == reference_source and arm == baseline:
                continue
            pairs = [(_success(r), reference[key]) for r in grouped[(source, arm)]
                     if (key := (r['unit']['task'], r['unit']['repetition'])) in reference]
            wins = sum(a and not b for a, b in pairs)
            losses = sum(b and not a for a, b in pairs)
            comparisons.append({'source': source, 'arm': arm, 'control': baseline, 'control_source': reference_source,
                                'pairs': len(pairs),
                                'wins': wins, 'losses': losses, 'ties': len(pairs) - wins - losses,
                                'mcnemar_p': mcnemar_exact(wins, losses) if pairs else None})
    task_matrix = defaultdict(dict)
    for row in tasks:
        task_matrix[(row['source'], row['task'])][row['arm']] = {
            'n': row['n'], 'successes': row['successes']}
    task_comparisons = [{'source': source, 'task': task,
                         'arms': json.dumps(arm_data, ensure_ascii=False, sort_keys=True)}
                        for (source, task), arm_data in sorted(task_matrix.items())]
    return {'arms': arms, 'tasks': tasks, 'task_comparisons': task_comparisons,
            'comparisons': comparisons}


def write_report(tables, markdown, csv_path):
    sections = [('arms', 'By arm'), ('tasks', 'By task and arm'),
                ('task_comparisons', 'Arm comparisons by task and directory'),
                ('comparisons', 'Paired comparisons: exact McNemar test')]
    lines = ['# OpenCode baseline report', '',
             ('First attempt per unit, excluding explicit infrastructure failures; '
             'units without an eligible attempt are excluded. Directories are analyzed separately.'),
             ('Pairs use identical tasks and repetitions; an unpaired repetition is excluded. '
             'Token rates and TTFT are medians of per-episode medians; '
             'empty fields indicate unavailable data.'), '']
    for name, title in sections:
        lines.extend([f'## {title}', ''])
        entries = tables[name]
        if not entries:
            lines.extend(['No data.', ''])
            continue
        columns = list(entries[0])
        lines.extend(['| ' + ' | '.join(columns) + ' |',
                      '| ' + ' | '.join('---' for _ in columns) + ' |'])
        for row in entries:
            lines.append('| ' + ' | '.join(_format(row.get(col)) for col in columns) + ' |')
        lines.append('')
    Path(markdown).write_text('\n'.join(lines), encoding='utf-8')
    all_rows = [(name, row) for name, _ in sections for row in tables[name]]
    columns = list(dict.fromkeys(key for _, row in all_rows for key in row))
    with Path(csv_path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['section', *columns])
        writer.writeheader()
        for section, row in all_rows:
            writer.writerow({'section': section, **row})


def _format(value):
    if value is None:
        return ''
    if isinstance(value, float):
        return f'{value:.4f}'
    return str(value).replace('|', r'\|').replace('\n', ' ')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+')
    parser.add_argument('--markdown', required=True)
    parser.add_argument('--csv', required=True)
    parser.add_argument('--control', help='control arm; default C4-q4 when available, otherwise B0')
    parser.add_argument('--control-dir', help='directory containing the control arm for all inputs')
    args = parser.parse_args(argv)
    directories = list(args.directories)
    if args.control_dir and Path(args.control_dir).resolve() not in [Path(p).resolve() for p in directories]:
        directories.append(args.control_dir)
    write_report(summarize(read_results(directories), args.control, args.control_dir), args.markdown, args.csv)


if __name__ == '__main__':
    main()
