"""Deterministic, model-neutral selection of read-only procedural guidance."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'agent-manual'


def selected_skills(task: str):
    from benchmark.practical_tasks_v2 import ALL_TASKS
    if task not in ALL_TASKS:
        raise ValueError('unknown manual task')
    if task == 'D2':
        return ('code-and-tests', 'mcp-transactions', 'verify-and-finish')
    return (('mcp-transactions' if task in {'C2', 'M2', 'H2'} else 'code-and-tests'),
            'recover-and-checkpoint', 'verify-and-finish')


def manual_evidence(task: str, *, with_skills=True):
    files = [ROOT / 'CORE.md', *(ROOT / 'skills' / name / 'SKILL.md' for name in (selected_skills(task) if with_skills else ()))]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def task_instructions(task: str, *, with_skills=True):
    pieces = [(ROOT / 'CORE.md').read_text(encoding='utf-8')]
    pieces.extend((ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8') for name in (selected_skills(task) if with_skills else ()))
    return '\n\n'.join(pieces)
