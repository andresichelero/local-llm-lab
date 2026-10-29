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


class JournalPersistenceError(RuntimeError):
    """The journal write is ambiguous or failed; do not retry this attempt."""


class WorkerRunner:
    def __init__(self, workspace: Path, journal: Path, client):
        self.workspace, self.journal, self.client = workspace, journal, client
        self.attempt_id = uuid.uuid4().hex
        self.state = None
        self.result = None
        self.input_tokens = 0
        self.task_id = None
        self._visible_accepted = False
        self._deadline = None
        self._expired = False
        self._timer_owned = False
        self._journal_failed = False

    def _record(self, state, **fields):
        if self._journal_failed:
            raise JournalPersistenceError('journal persistence previously failed')
        try:
            with self.journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'attempt_id': self.attempt_id, 'state': state, **fields}, ensure_ascii=False) + '\n')
        except OSError as err:
            self._journal_failed = True
            raise JournalPersistenceError('journal append failed; attempt cannot be retried') from err
        self.state = state

    def _persisted_terminal(self):
        terminals = {'accepted', 'rejected', 'blocked', 'infrastructure_error'}
        try:
            if not self.journal.exists():
                return None
            with self.journal.open(encoding='utf-8') as stream:
                events = []
                for line in stream:
                    if not line.endswith('\n'):
                        raise ValueError('incomplete JSONL record')
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise TypeError('journal record must be an object')
                    events.append(event)
        except (OSError, ValueError, TypeError) as err:
            self._journal_failed = True
            raise JournalPersistenceError('journal cannot be read unambiguously') from err
        matches = [event for event in events
                   if event.get('attempt_id') == self.attempt_id and event.get('state') in terminals]
        if len(matches) > 1:
            self._journal_failed = True
            raise JournalPersistenceError('multiple terminal records already exist')
        if not matches:
            return None
        event = matches[0]
        return RunResult(self.attempt_id, event['state'], self.input_tokens,
                         event.get('oracle_passed'), event.get('reason', ''))

    def _check_deadline(self):
        if self._expired or (self._deadline is not None and time.monotonic() >= self._deadline):
            self._expired = True
            raise TimeoutError('wall budget exceeded')

    def finalize(self, state, oracle_passed=None, reason=''):
        if self.result is not None:
            return self.result
        previous_mask = None
        try:
            if self._timer_owned:
                previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                signal.setitimer(signal.ITIMER_REAL, 0)
                if signal.sigtimedwait({signal.SIGALRM}, 0) is not None:
                    self._expired = True
            existing = self._persisted_terminal()
            if existing is not None:
                self.state = existing.state
                self.result = existing
                return existing
            if self._journal_failed:
                raise JournalPersistenceError('journal persistence previously failed')
            if self._expired or (self._deadline is not None and time.monotonic() >= self._deadline):
                state, oracle_passed, reason = 'infrastructure_error', None, 'TimeoutError'
            if state not in {'accepted', 'rejected', 'blocked', 'infrastructure_error'}:
                raise ValueError('invalid terminal state')
            if state == 'accepted' and not self._visible_accepted:
                raise ValueError('acceptance requires successful visible verification')
            try:
                self._record(state, reason=reason, oracle_passed=oracle_passed)
            except Exception as err:
                existing = self._persisted_terminal()
                if existing is not None:
                    self.state = existing.state
                    self.result = existing
                    return existing
                self._journal_failed = True
                raise JournalPersistenceError('terminal append failed; no retry is safe') from err
            self.result = RunResult(self.attempt_id, state, self.input_tokens, oracle_passed, reason)
            return self.result
        finally:
            if previous_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

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
                self._expired = True
                raise TimeoutError('wall budget exceeded')
            signal.signal(signal.SIGALRM, expired)
            self._deadline = time.monotonic() + package.budgets['wall_seconds']
            self._timer_owned = True
            signal.setitimer(signal.ITIMER_REAL, package.budgets['wall_seconds'])
        except (AttributeError, ValueError, RuntimeError) as err:
            self._record('prepared', task_id=package.task_id, mode=mode)
            return self.finalize('infrastructure_error', reason=type(err).__name__)
        try:
            return self._run(package, visible, private_oracle, mode=mode, prefix=prefix)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            self._timer_owned = False
            signal.signal(signal.SIGALRM, previous_handler)

    def _run(self, package: WorkerPackage, visible, private_oracle, *, mode='W16', prefix=None):
        if self.state is not None:
            raise RuntimeError('runner is single-use')
        self.task_id = package.task_id
        started = time.monotonic()
        try:
            self._record('prepared', task_id=package.task_id, mode=mode)
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
                    if package.budgets.get('repair_rejected_edits', False):
                        self._record('edit_rejected', turn=turn, status=edit.status.value)
                    state = 'infrastructure_error' if edit.status == EditStatus.VALIDATOR_UNAVAILABLE else 'rejected'
                    if (state == 'rejected' and package.budgets.get('repair_rejected_edits', False)
                            and turn < package.budgets['repairs']):
                        messages.extend([{'role': 'assistant', 'content': output},
                                         {'role': 'user', 'content': f'Edit rejected ({edit.status.value}): '
                                          f'{edit.error_message}. Copy each SEARCH block exactly from the '
                                          'current file text shown above and resend the complete edit.'}])
                        continue
                    return self.finalize(state, reason=edit.status.value)
                hashes.update({item.path: item.after_sha256 for item in edit.files})
                self._record('verifying', turn=turn, receipts=[vars(item) for item in edit.files])
                check = visible()
                if time.monotonic() - started > package.budgets['wall_seconds']:
                    raise TimeoutError('wall budget exceeded')
                if check.passed:
                    score = None if package.verification_profile == 'phase1' else private_oracle()
                    self._check_deadline()
                    if score is not None and not isinstance(score, bool):
                        raise TypeError('private oracle must return a boolean')
                    if score is None and package.verification_profile != 'phase1':
                        raise TypeError('private oracle must return a boolean')
                    self._visible_accepted = True
                    return self.finalize('accepted', oracle_passed=score)
                diagnostic = check.diagnostic.strip()
                if turn >= package.budgets['repairs'] or not diagnostic or diagnostic in package.markdown:
                    return self.finalize('rejected', reason='no_new_visible_diagnostic')
                if package.budgets.get('repair_rejected_edits', False):
                    self._record('visible_repair', turn=turn)
                messages.extend([{'role': 'assistant', 'content': output},
                                 {'role': 'user', 'content': 'Visible verification failed:\n' + diagnostic}])
            return self.finalize('rejected', reason='repair_exhausted')
        except JournalPersistenceError:
            raise
        except Exception as err:  # noqa: BLE001 - isolate injected infrastructure failures
            return self.finalize('infrastructure_error', reason=type(err).__name__)
