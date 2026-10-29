"""Worker-facing packet, assembled only from explicit public inputs."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

BLOCK_REASONS = ('insufficient_context', 'conflicting_requirements', 'cannot_safely_edit')


@dataclass(frozen=True)
class WorkerPackage:
    contract_version: str
    task_id: str
    base_revision: str
    input_hashes: dict[str, str]
    objective: str
    invariants: list[str]
    writable_files: list[str]
    readonly_context: dict[str, str]
    prefix_id: str | None
    verification_profile: str
    budgets: dict[str, int]
    block_reasons: list[str]
    markdown: str

    def to_dict(self):
        metadata = asdict(self)
        del metadata['markdown']
        return metadata


@dataclass(frozen=True)
class WorkerResult:
    kind: Literal['patch', 'blocked']
    output: str
    reason: str | None = None

    def __post_init__(self):
        if self.kind == 'patch' and self.reason is None:
            return
        if self.kind == 'blocked' and self.reason in BLOCK_REASONS:
            return
        raise ValueError('invalid worker result or block reason')

    def to_dict(self):
        return asdict(self)


# JSON Schema is deliberately closed: unknown fields must not silently enter prompts.
PACKAGE_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object', 'additionalProperties': False,
    'required': [name for name in WorkerPackage.__dataclass_fields__ if name != 'markdown'],
    'properties': {
        **{name: {'type': 'string'} for name in ('contract_version', 'task_id', 'base_revision', 'objective', 'verification_profile')},
        **{name: {'type': 'array', 'items': {'type': 'string'}} for name in ('invariants', 'writable_files', 'block_reasons')},
        **{name: {'type': 'object', 'additionalProperties': {'type': 'string'}} for name in ('input_hashes', 'readonly_context')},
        'prefix_id': {'type': ['string', 'null']},
        'budgets': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
    },
}
RESULT_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'oneOf': [
        {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'output', 'reason'], 'properties': {'kind': {'const': 'patch'}, 'output': {'type': 'string'}, 'reason': {'type': 'null'}}},
        {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'output', 'reason'], 'properties': {'kind': {'const': 'blocked'}, 'output': {'type': 'string'}, 'reason': {'enum': list(BLOCK_REASONS)}}},
    ],
}


def build_package(corpus_root: Path, task_id: str, workspace: Path, base_revision: str, *,
                  readonly_context: dict[str, str] | None = None, prefix: bytes | None = None,
                  followup: bool = False, budgets: dict[str, int] | None = None) -> WorkerPackage:
    if followup:
        raise ValueError('follow-up must be released by the accepting runner')
    return _build_package(corpus_root, task_id, workspace, base_revision,
                          readonly_context=readonly_context, prefix=prefix, budgets=budgets)


def _build_package(corpus_root: Path, task_id: str, workspace: Path, base_revision: str, *,
                   readonly_context: dict[str, str] | None = None, prefix: bytes | None = None,
                   followup: bool = False, budgets: dict[str, int] | None = None) -> WorkerPackage:
    if not task_id or not all(c.isalnum() or c in '_-' for c in task_id):
        raise ValueError('invalid task id')
    folder = corpus_root / 'tasks' / task_id
    task = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
    if task['id'] != task_id:
        raise ValueError('task id mismatch')
    if followup:
        if task['class'] != 'continuation':
            raise ValueError('follow-up requires accepted first delivery')
        follow = json.loads((folder / 'followup.json').read_text(encoding='utf-8'))
        task['objective'] = follow['objective']
    writable = task['writable_files']
    from benchmark.guarded_edit import _resolve_workspace_path
    hashes = {}
    for name in writable:
        target = _resolve_workspace_path(Path(name), workspace)
        hashes[name] = hashlib.sha256(target.read_bytes() if target.exists() else b'').hexdigest()
    visible_name = 'visible_phase1.py' if task['class'] == 'continuation' and not followup else 'visible.py'
    context = {'visible_test': (folder / visible_name).read_text(encoding='utf-8')}
    if 'stub' in task:
        expected_stub = f'corpus/stubs/{task_id}/tool.py'
        if task['stub'] != expected_stub:
            raise ValueError('unexpected tool stub path')
        stub = _resolve_workspace_path(Path('stubs') / task_id / 'tool.py', corpus_root)
        result = subprocess.run([sys.executable, '-B', str(stub)], check=True, text=True,
                                capture_output=True, timeout=5)
        json.loads(result.stdout)
        context['tool_output'] = result.stdout
    if readonly_context:
        permitted = set(task['relevant_files']) | set(writable)
        for name, snippet in readonly_context.items():
            if name not in permitted or not snippet or name in {'visible_test'}:
                raise ValueError('context must be a selected relevant workspace file')
            path = _resolve_workspace_path(Path(name), workspace)
            if (not path.is_file() or 'oracles' in path.parts
                    or path.name.endswith('.patch')
                    or snippet not in path.read_text(encoding='utf-8')):
                raise ValueError('context must be an exact workspace snippet')
            context[name] = snippet
    if prefix is not None:
        allowed_prefix = _resolve_workspace_path(Path('prefixes') / (task['host'] + '.txt'), corpus_root)
        if prefix != allowed_prefix.read_bytes():
            raise ValueError('prefix differs from the frozen host prefix')
    prefix_id = hashlib.sha256(prefix).hexdigest() if prefix is not None else None
    reasons = list(BLOCK_REASONS)
    # The W16 default reserves 2,048 tokens for generation within a 16,384 window.
    limits = {'input_tokens': 14336, 'max_tokens': 2048, 'wall_seconds': 300, 'repairs': 1}
    if budgets:
        limits.update(budgets)
    if (limits['wall_seconds'] <= 0 or limits['wall_seconds'] > 300
            or limits['repairs'] not in (0, 1)
            or limits['input_tokens'] <= 0 or limits['max_tokens'] <= 0):
        raise ValueError('invalid budgets')
    body = ('# Task\n' + task['objective'] + '\n\n# Invariants\n' + '\n'.join('- ' + x for x in task['invariants'])
            + '\n\n# Writable files\n' + '\n'.join('- ' + x for x in writable)
            + '\n\n# Visible context\n' + '\n'.join('## ' + k + '\n' + v for k, v in context.items())
            + '\n\n# Response format\n'
            + 'Repeat blocks with these exact LF-terminated lines and no fences or prose:\n'
            + 'FILE: relative/path\n<<<<<<< SEARCH\n<exact existing text>\n'
            + '=======\n<replacement text>\n>>>>>>> REPLACE\n'
            + 'For a new file use an empty search. Or output exactly BLOCKED: '
            + '<reason> using one of: ' + ', '.join(reasons) + '.\n')
    return WorkerPackage('1', task_id, base_revision, hashes, task['objective'], task['invariants'], writable,
                         context, prefix_id, 'phase1' if task['class'] == 'continuation' and not followup else 'final',
                         limits, reasons, body)
