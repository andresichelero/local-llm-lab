"""Versioned agent budgets. Host-owned counters never trust a model's progress claim."""
from __future__ import annotations

import json
import hashlib
import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Mapping

VERSION = 'limits-skills-v2'
# Read-back support: historical evidence carries the previous budget contract
# unchanged.  Old ledgers are only readable, never rebuilt into new runs.
LEGACY_VERSION = 'limits-skills-v1'
SUPPORTED_VERSIONS = (VERSION, LEGACY_VERSION)


class PolicyLimit(RuntimeError):
    def __init__(self, category: str):
        self.category = category
        super().__init__('budget_exhausted:' + category)


@dataclass(frozen=True)
class BudgetPolicy:
    main: int
    wall_seconds: float
    title: int = 1
    compaction: int = 2
    metadata: int = 10
    mode: str = 'benchmark'
    version: str = VERSION

    def __post_init__(self):
        if self.mode not in {'benchmark', 'operational'} or self.version not in SUPPORTED_VERSIONS:
            raise ValueError('unsupported budget policy')
        for field in ('main', 'title', 'compaction', 'metadata'):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= 10000:
                raise ValueError('invalid budget: ' + field)
        if not math.isfinite(self.wall_seconds) or not 0 < self.wall_seconds <= 3600:
            raise ValueError('invalid wall budget')

    @classmethod
    def for_task(cls, spec: Mapping, *, mode='benchmark'):
        main = spec['max_requests']
        base = spec.get('base_max_requests', main)
        return cls(main=main, wall_seconds=spec['seconds'],
                   compaction=2 if base <= 30 else 3 if base <= 45 else 4, mode=mode)

    @property
    def multiplier(self):
        return 2 if self.mode == 'operational' else 1

    @property
    def max_model_requests(self):
        return self.main * self.multiplier + self.title + self.compaction * self.multiplier

    def as_dict(self):
        return asdict(self)


class BudgetLedger:
    def __init__(self, policy: BudgetPolicy, *, clock=time.monotonic,
                 progress_probe: Callable[[], str | None] | None = None):
        self.policy, self.clock, self.progress_probe = policy, clock, progress_probe
        self.started = clock()
        self.used = dict.fromkeys(('main', 'title', 'compaction', 'metadata'), 0)
        self.attempted = dict(self.used)
        self.extensions = 0
        self.limit_reason = None
        self._lock = threading.RLock()
        self._last_progress = progress_probe() if progress_probe else None

    def _extend(self):
        if self.policy.mode != 'operational' or self.extensions >= 2 or not self.progress_probe:
            return False
        proof = self.progress_probe()
        if proof is None or proof == self._last_progress:
            return False
        self._last_progress = proof
        self.extensions += 1
        return True

    def ceiling(self, kind):
        if kind == 'main':
            return min(self.policy.main * self.policy.multiplier,
                       self.policy.main + math.ceil(self.policy.main / 2) * self.extensions)
        if kind == 'compaction':
            return self.policy.compaction * self.policy.multiplier
        return getattr(self.policy, kind)

    def remaining_seconds(self):
        with self._lock:
            limit = min(self.policy.wall_seconds * self.policy.multiplier,
                        self.policy.wall_seconds * (1 + self.extensions / 2))
            remaining = limit - (self.clock() - self.started)
            if remaining <= 0 and self._extend():
                return self.remaining_seconds()
            return max(0.0, remaining)

    def admit(self, kind):
        with self._lock:
            if kind not in self.used:
                raise ValueError('unclassified model request')
            self.attempted[kind] += 1
            if self.remaining_seconds() <= 0:
                self.limit_reason = 'wall'
                raise PolicyLimit('wall')
            if self.used[kind] >= self.ceiling(kind):
                if kind != 'main' or not self._extend():
                    self.limit_reason = kind
                    raise PolicyLimit(kind)
            self.used[kind] += 1

    def snapshot(self):
        with self._lock:
            return {'version': self.policy.version, 'mode': self.policy.mode, 'used': dict(self.used),
                    'attempted': dict(self.attempted), 'extensions': self.extensions,
                    'ceilings': {kind: self.ceiling(kind) for kind in self.used},
                    'limit_reason': self.limit_reason,
                    'elapsed_seconds': round(self.clock() - self.started, 3)}


def classify_request(request):
    """Match pinned system prefixes, never arbitrary strings in user/tool content."""
    for message in request.get('messages', []):
        if not isinstance(message, dict) or message.get('role') != 'system':
            continue
        value = message.get('content', '')
        if isinstance(value, list):
            value = '\n'.join(str(p.get('text', '')) for p in value if isinstance(p, dict))
        value = str(value).strip().lower()
        if value.startswith('you are a title generator.'):
            return 'title'
        if value.startswith('you are a context summarization agent.'):
            return 'compaction'
        if value.startswith('you are opencode,'):
            return 'main'
    return 'unknown'


def validate_history(messages):
    pending, answered, seen_calls = set(), set(), set()
    for message in messages:
        if not isinstance(message, dict):
            return 'invalid_message'
        role = message.get('role')
        if role == 'tool':
            ident = message.get('tool_call_id')
            if not ident or ident not in pending or ident in answered:
                return 'orphan_tool_result'
            if message.get('content') is None:
                return 'missing_tool_result_content'
            answered.add(ident)
            continue
        if role in {'assistant', 'user'}:
            if pending - answered:
                return 'missing_tool_result'
            pending, answered = set(), set()
            for call in message.get('tool_calls') or []:
                ident = call.get('id')
                if not ident or ident in seen_calls:
                    return 'invalid_tool_call_id'
                pending.add(ident)
                seen_calls.add(ident)
    return 'missing_tool_result' if pending - answered else None


def usage_from_bytes(raw):
    """Missing usage remains None, including truncated streams."""
    usages = []
    try:
        value = json.loads(raw)
        if isinstance(value, dict) and isinstance(value.get('usage'), dict):
            usages.append(value['usage'])
    except (ValueError, TypeError, UnicodeDecodeError):
        for line in raw.decode('utf-8', errors='replace').splitlines():
            if line.startswith('data: '):
                try:
                    item = json.loads(line[6:])
                    if isinstance(item.get('usage'), dict):
                        usages.append(item['usage'])
                except (ValueError, AttributeError):
                    continue
    return usages[-1] if usages else None


def progress_from_events(raw):
    """Read runtime tool metadata, never free-text model assertions of progress."""
    proofs = set()
    for line in raw.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
            if event.get('type') != 'tool_use':
                continue
            state = event.get('part', {}).get('state') or {}
            if state.get('status') != 'completed':
                continue
            policy = (state.get('metadata') or {}).get('lab_policy') or {}
            if policy.get('changed') is True and policy.get('workspace_fingerprint'):
                proofs.add('file:' + policy['workspace_fingerprint'])
            tool = str(event.get('part', {}).get('tool', ''))
            if tool.startswith(('lab_', 'lab.')):
                output = state.get('output')
                if isinstance(output, str):
                    output = json.loads(output)
                if not isinstance(output, dict) or output.get('isError') or output.get('error'):
                    continue
                value = output.get('structuredContent', output)
                if 'data' not in value:
                    content = output.get('content', [])
                    value = json.loads(content[0]['text']) if content else {}
                data = value.get('data')
                if not isinstance(data, dict):
                    continue
                # Only real MCP responses count. Repeated pages/receipts do not
                # create new progress, and arbitrary text/bad calls never count.
                if ('next_cursor' in data and isinstance(data.get('items'), list)
                        or type(data.get('version')) is int and not data.get('idempotent_replay')):
                    proofs.add('mcp:' + tool + ':' + json.dumps(data, sort_keys=True))
        except (ValueError, AttributeError, TypeError, KeyError, IndexError):
            continue
    return hashlib.sha256(json.dumps(sorted(proofs)).encode()).hexdigest() if proofs else None
