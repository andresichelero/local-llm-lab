#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import json
import statistics
import sys
from pathlib import Path

root = Path(sys.argv[1])
source = root / "results/raw/tier0.jsonl"
target = root / "results/reports/tier0-summary.md"
rows = []
if source.exists():
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
if not rows:
    target.write_text("# Tier 0 summary\n\nNo completed benchmark records yet.\n", encoding="utf-8")
    print(target)
    raise SystemExit(0)
def stats(key):
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return "not available"
    return f"median {statistics.median(values):.3f}, mean {statistics.mean(values):.3f}, min {min(values):.3f}, max {max(values):.3f}"
text = [
    "# Tier 0 summary",
    "",
    f"Successful measured runs: {len(rows)}",
    f"Model: {rows[0].get('model')} ({rows[0].get('quant')})",
    f"Runtime: {rows[0].get('runtime')}",
    f"TTFT ms: {stats('ttft_ms')}",
    f"Generation tokens/s: {stats('generation_tps')}",
    f"Wall seconds: {stats('wall_time_s')}",
    "",
    "These results measure throughput and latency only; they do not establish model quality.",
    "",
]
target.write_text("\n".join(text), encoding="utf-8")
print(target)
PY
