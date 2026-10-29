"""Offline-testable worker orchestration; client and verifiers are injected."""
from __future__ import annotations

import hashlib
import json
import signal
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from benchmark.guarded_edit import EditStatus, apply_edit_batch
from benchmark.worker_contract import WorkerPackage, _build_package


class LlamaClient:
    """Minimal llama-server JSON client. No request occurs until a method is called."""
    def __init__(self, base_url: str, timeout: float = 300):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def _post(self, path, data, timeout=None):
        request = urllib.request.Request(self.base_url + path, data=json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            return json.load(response)

    def count_tokens(self, messages, timeout=None):
        started = time.monotonic()
        rendered = self._post('/apply-template', {'messages': messages, 'chat_template_kwargs': {'enable_thinking': False}}, timeout)['prompt']
        remaining = None if timeout is None else timeout - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            raise TimeoutError('wall budget exceeded')
        return len(self._post('/tokenize', {'content': rendered, 'add_special': True,
                                            'parse_special': True}, remaining)['tokens'])

    def generate(self, messages, max_tokens, timeout, cache_prompt):
        result = self._post('/v1/chat/completions', {'messages': messages, 'max_tokens': max_tokens,
                            'temperature': 0, 'seed': 42, 'cache_prompt': cache_prompt,
                            'chat_template_kwargs': {'enable_thinking': False}}, timeout)
        return result['choices'][0]['message']['content']


@dataclass(frozen=True)
class VisibleResult:
    passed: bool
    diagnostic: str


@dataclass(frozen=True)
class RunResult:
    attempt_id: str
    state: str
    input_tokens: int
    oracle_passed: bool | None = None
    reason: str = ''


class WorkerRunner:
    def __init__(self, workspace: Path, journal: Path, client):
        self.workspace, self.journal, self.client = workspace, journal, client
        self.attempt_id = uuid.uuid4().hex
        self.state = None
        self.result = None
        self.input_tokens = 0
        self.task_id = None
        self._visible_accepted = False

    def _record(self, state, **fields):
        self.state = state
        with self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'attempt_id': self.attempt_id, 'state': state, **fields}, ensure_ascii=False) + '\n')

    def finalize(self, state, oracle_passed=None, reason=''):
        if self.result is None:
            if state not in {'accepted', 'rejected', 'blocked', 'infrastructure_error'}:
                raise ValueError('invalid terminal state')
            if state == 'accepted' and not self._visible_accepted:
                raise ValueError('acceptance requires successful visible verification')
            self._record(state, reason=reason, oracle_passed=oracle_passed)
            self.result = RunResult(self.attempt_id, state, self.input_tokens, oracle_passed, reason)
        return self.result

    def followup_package(self, corpus_root, package, **kwargs):
        if (self.result is None or self.result.state != 'accepted'
                or self.task_id != package.task_id or package.verification_profile != 'phase1'):
            raise ValueError('follow-up requires this runner to accept the first delivery')
        return _build_package(corpus_root, package.task_id, self.workspace, package.base_revision,
                              followup=True, **kwargs)

    def run(self, package: WorkerPackage, visible, private_oracle, *, mode='W16', prefix=None):
        # POSIX main-thread timer also interrupts blocking injected verifiers.
        # Refuse to steal an existing process timer from another owner.
        try:
            previous_handler = signal.getsignal(signal.SIGALRM)
            if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
                raise RuntimeError('process timer already in use')
            def expired(_signum, _frame):
                raise TimeoutError('wall budget exceeded')
            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, package.budgets['wall_seconds'])
        except (AttributeError, ValueError, RuntimeError) as err:
            self._record('prepared', task_id=package.task_id, mode=mode)
            return self.finalize('infrastructure_error', reason=type(err).__name__)
        try:
            return self._run(package, visible, private_oracle, mode=mode, prefix=prefix)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _run(self, package: WorkerPackage, visible, private_oracle, *, mode='W16', prefix=None):
        if self.state is not None:
            raise RuntimeError('runner is single-use')
        self.task_id = package.task_id
        self._record('prepared', task_id=package.task_id, mode=mode)
        started = time.monotonic()
        try:
            if mode not in ('W16', 'WL'):
                raise ValueError('invalid mode')
            messages = []
            if mode == 'WL':
                if prefix is None or hashlib.sha256(prefix).hexdigest() != package.prefix_id:
                    raise ValueError('prefix hash mismatch')
                messages.append({'role': 'system', 'content': prefix.decode('utf-8')})
            messages.append({'role': 'user', 'content': package.markdown})
            hashes = dict(package.input_hashes)
            empty_sha = hashlib.sha256(b'').hexdigest()
            authored = tuple(name for name in package.writable_files
                             if hashes.get(name) == empty_sha
                             and not (self.workspace / name).exists())
            for turn in range(package.budgets['repairs'] + 1):
                remaining = package.budgets['wall_seconds'] - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError('wall budget exceeded')
                count = self.client.count_tokens(messages, remaining)
                self.input_tokens = count
                if count > package.budgets['input_tokens']:
                    return self.finalize('rejected', reason='input_budget')
                remaining = package.budgets['wall_seconds'] - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError('wall budget exceeded')
                self._record('generating', turn=turn, input_tokens=count)
                output = self.client.generate(messages, package.budgets['max_tokens'], remaining, True)
                self._record('candidate', turn=turn, output=output)
                if time.monotonic() - started > package.budgets['wall_seconds']:
                    raise TimeoutError('wall budget exceeded')
                if output.startswith('BLOCKED: '):
                    reason = output.removeprefix('BLOCKED: ').removesuffix('\n')
                    if reason in package.block_reasons:
                        return self.finalize('blocked', reason=reason)
                edit = apply_edit_batch(self.workspace, output, hashes, package.writable_files,
                                        authored_tests=authored)
                if not edit.success:
                    state = 'infrastructure_error' if edit.status == EditStatus.VALIDATOR_UNAVAILABLE else 'rejected'
                    return self.finalize(state, reason=edit.status.value)
                hashes.update({item.path: item.after_sha256 for item in edit.files})
                self._record('verifying', turn=turn, receipts=[vars(item) for item in edit.files])
                check = visible()
                if time.monotonic() - started > package.budgets['wall_seconds']:
                    raise TimeoutError('wall budget exceeded')
                if check.passed:
                    score = None if package.verification_profile == 'phase1' else private_oracle()
                    if score is not None and not isinstance(score, bool):
                        raise TypeError('private oracle must return a boolean')
                    if score is None and package.verification_profile != 'phase1':
                        raise TypeError('private oracle must return a boolean')
                    self._visible_accepted = True
                    return self.finalize('accepted', oracle_passed=score)
                diagnostic = check.diagnostic.strip()
                if turn >= package.budgets['repairs'] or not diagnostic or diagnostic in package.markdown:
                    return self.finalize('rejected', reason='no_new_visible_diagnostic')
                messages.extend([{'role': 'assistant', 'content': output},
                                 {'role': 'user', 'content': 'Visible verification failed:\n' + diagnostic}])
            return self.finalize('rejected', reason='repair_exhausted')
        except Exception as err:  # noqa: BLE001 - isolate injected infrastructure failures
            return self.finalize('infrastructure_error', reason=type(err).__name__)
