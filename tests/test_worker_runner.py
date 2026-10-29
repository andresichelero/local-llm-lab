import hashlib
import json
from pathlib import Path

from benchmark.worker_contract import build_package
from benchmark.worker_runner import VisibleResult, WorkerRunner


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []
        self.counts = []

    def count_tokens(self, messages, timeout=None):
        self.counts.append(messages)
        return 10

    def generate(self, messages, max_tokens, timeout, cache_prompt):
        self.messages.append(messages)
        assert cache_prompt
        return next(self.responses)


def patch(old, new):
    return f'FILE: bottle.py\n<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n'


def package(tmp_path, prefix=None):
    (tmp_path / 'bottle.py').write_text('x = 1\n')
    root = Path(__file__).resolve().parents[1] / 'corpus'
    return build_package(root, 'py_range', tmp_path, 'rev', prefix=prefix)


def test_runner_repair_never_receives_private_diagnostic(tmp_path):
    p = package(tmp_path)
    client = FakeClient([patch('x = 1', 'x = 2'), patch('x = 2', 'x = 3')])
    visible = iter([VisibleResult(False, 'visible assertion: expected 3'), VisibleResult(True, '')])
    calls = []
    def oracle():
        calls.append('private secret oracle')
        return False
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    result = runner.run(p, lambda: next(visible), oracle)
    assert result.state == 'accepted' and result.oracle_passed is False
    assert calls == ['private secret oracle']
    assert 'visible assertion' in str(client.messages[1])
    assert 'private secret oracle' not in str(client.messages)
    assert runner.finalize(result.state) == runner.finalize(result.state)
    states = [json.loads(line)['state'] for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    assert states == ['prepared', 'generating', 'candidate', 'verifying', 'generating', 'candidate', 'verifying', 'accepted']


def test_runner_stable_prefix_and_token_count(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'corpus'
    prefix = (root / 'prefixes' / 'bottle-0.13.2.txt').read_bytes()
    p = package(tmp_path, prefix)
    client = FakeClient(['BLOCKED: insufficient_context'])
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: True, mode='WL', prefix=prefix)
    assert result.state == 'blocked' and result.input_tokens == 10
    assert hashlib.sha256(client.messages[0][0]['content'].encode()).hexdigest() == p.prefix_id
    assert client.counts[0] == client.messages[0]


def test_runner_invalid_output_and_timeout(tmp_path):
    p = package(tmp_path)
    client = FakeClient(['```bad```'])
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    assert runner.run(p, lambda: VisibleResult(True, ''), lambda: True).reason == 'malformed_output'
    class TimeoutClient(FakeClient):
        def generate(self, *args):
            raise TimeoutError()
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', TimeoutClient([]))
    assert runner.run(p, lambda: VisibleResult(True, ''), lambda: True).state == 'infrastructure_error'


def test_runner_no_repair_without_new_visible_diagnostic(tmp_path):
    p = package(tmp_path)
    client = FakeClient([patch('x = 1', 'x = 2')])
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    result = runner.run(p, lambda: VisibleResult(False, ''), lambda: True)
    assert result.state == 'rejected' and len(client.messages) == 1


def test_llama_token_count_uses_template_then_tokenize():
    from benchmark.worker_runner import LlamaClient
    client = LlamaClient('http://invalid')
    calls = []
    def fake_post(path, payload, timeout=None):
        calls.append((path, payload))
        return {'prompt': 'rendered'} if path == '/apply-template' else {'tokens': [1, 2, 3]}
    client._post = fake_post
    assert client.count_tokens([{'role': 'user', 'content': 'hi'}]) == 3
    assert [call[0] for call in calls] == ['/apply-template', '/tokenize']
    assert calls[1][1]['content'] == 'rendered'
    assert calls[1][1]['add_special'] is True and calls[1][1]['parse_special'] is True



def test_followup_is_released_only_after_accepted_first_delivery(tmp_path):
    import pytest
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('x = 1\n')
    p = build_package(root, 'cont_quote', tmp_path, 'rev')
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    with pytest.raises(ValueError):
        runner.followup_package(root, p)
    oracle_calls = []
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: oracle_calls.append(True))
    assert result.state == 'accepted' and result.oracle_passed is None and oracle_calls == []
    followup = runner.followup_package(root, p)
    assert followup.verification_profile == 'final' and followup.objective != p.objective


def test_same_prefix_is_identical_between_tasks(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('x = 1\n')
    prefix = (root / 'prefixes' / 'bottle-0.13.2.txt').read_bytes()
    first = build_package(root, 'py_range', tmp_path, 'rev', prefix=prefix)
    second = build_package(root, 'py_query', tmp_path, 'rev', prefix=prefix)
    seen = []
    for p in (first, second):
        client = FakeClient(['BLOCKED: insufficient_context'])
        WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client).run(
            p, lambda: VisibleResult(True, ''), lambda: True, mode='WL', prefix=prefix)
        seen.append(client.messages[0][0]['content'].encode())
    assert seen[0] == seen[1] == prefix and first.prefix_id == second.prefix_id


def test_wall_budget_interrupts_blocked_visible_verifier(tmp_path):
    import time
    from dataclasses import replace
    p = package(tmp_path)
    p = replace(p, budgets={**p.budgets, 'wall_seconds': 1})
    client = FakeClient([patch('x = 1', 'x = 2')])
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    started = time.monotonic()
    result = runner.run(p, lambda: time.sleep(5), lambda: True)
    assert result.state == 'infrastructure_error' and result.reason == 'TimeoutError'
    assert time.monotonic() - started < 3


def test_private_oracle_requires_boolean_result(tmp_path):
    p = package(tmp_path)
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: 2)
    assert result.state == 'infrastructure_error' and result.oracle_passed is None


def test_runner_classifies_unavailable_syntax_validator_as_infrastructure(tmp_path, monkeypatch):
    from benchmark.guarded_edit import BatchResult, EditStatus
    p = package(tmp_path)
    output = patch('x = 1', 'x = 2')
    client = FakeClient([output])
    monkeypatch.setattr('benchmark.worker_runner.apply_edit_batch',
                        lambda *a, **kw: BatchResult(False, EditStatus.VALIDATOR_UNAVAILABLE, output))
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client)
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    assert result.state == 'infrastructure_error' and result.reason == 'validator_unavailable'


def test_rendered_input_budget_rejects_before_generation(tmp_path):
    from dataclasses import replace
    p = package(tmp_path)
    p = replace(p, budgets={**p.budgets, 'input_tokens': 9})
    client = FakeClient([])
    result = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client).run(
        p, lambda: VisibleResult(True, ''), lambda: True)
    assert result.state == 'rejected' and result.reason == 'input_budget' and not client.messages


def test_terminal_persistence_interrupted_after_append(tmp_path, monkeypatch):
    import time
    from dataclasses import replace
    p = package(tmp_path)
    p = replace(p, budgets={**p.budgets, 'wall_seconds': 1})
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    record = runner._record
    def slow_record(state, **fields):
        record(state, **fields)
        if state == 'accepted':
            time.sleep(2)
    monkeypatch.setattr(runner, '_record', slow_record)
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    entries = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    terminal = [e for e in entries if e['state'] in {'accepted', 'rejected', 'blocked', 'infrastructure_error'}]
    assert len(terminal) == 1
    assert terminal[0]['state'] == result.state
    assert terminal[0]['oracle_passed'] == result.oracle_passed


def test_private_oracle_swallows_timeout_without_acceptance(tmp_path):
    import time
    from dataclasses import replace
    p = package(tmp_path)
    p = replace(p, budgets={**p.budgets, 'wall_seconds': 1})
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    captured = []
    def private_oracle():
        try:
            time.sleep(2)
            return True
        except Exception as error:  # noqa: BLE001 - reproduce the private wrapper swallowing timeout
            captured.append(type(error).__name__)
            return False
    result = runner.run(p, lambda: VisibleResult(True, ''), private_oracle)
    entries = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    assert captured == ['TimeoutError']
    assert result.state == 'infrastructure_error' and result.reason == 'TimeoutError'
    assert result.oracle_passed is None
    assert all(e['state'] != 'accepted' for e in entries)


def test_repair_prompt_excludes_private_oracle_fragments_and_stderr(tmp_path, capsys):
    import sys
    root = Path(__file__).resolve().parents[1] / 'corpus'
    lines = (root / 'oracles' / 'py_range' / 'oracle.py').read_text().splitlines()
    fragments = [line.strip() for line in lines if len(line.strip()) >= 35]
    assert fragments
    p = package(tmp_path)
    client = FakeClient([patch('x = 1', 'x = 2'), patch('x = 2', 'x = 3')])
    visible = iter([VisibleResult(False, 'visible assertion: expected 3'), VisibleResult(True, '')])
    def oracle():
        print(fragments[0], file=sys.stderr)
        return False
    result = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', client).run(p, lambda: next(visible), oracle)
    assert result.oracle_passed is False
    assert fragments[0] in capsys.readouterr().err
    prompt = '\n'.join(message['content'] for messages in client.messages for message in messages)
    assert all(fragment not in prompt for fragment in fragments)


def test_terminal_write_failure_has_no_unsafe_retry(tmp_path, monkeypatch):
    import pytest

    from benchmark.worker_runner import JournalPersistenceError
    p = package(tmp_path)
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    record = runner._record
    def failed_write(state, **fields):
        if state == 'accepted':
            raise OSError('write failed')
        record(state, **fields)
    monkeypatch.setattr(runner, '_record', failed_write)
    with pytest.raises(JournalPersistenceError):
        runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    entries = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    assert not any(e['state'] in {'accepted', 'rejected', 'blocked', 'infrastructure_error'} for e in entries)
    with pytest.raises(JournalPersistenceError):
        runner.finalize('infrastructure_error')


def test_terminal_completed_before_io_error_is_recovered_without_second_terminal(tmp_path, monkeypatch):
    p = package(tmp_path)
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([patch('x = 1', 'x = 2')]))
    record = runner._record
    def failed_after_write(state, **fields):
        record(state, **fields)
        if state == 'accepted':
            raise OSError('close failed after append')
    monkeypatch.setattr(runner, '_record', failed_after_write)
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    entries = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    terminal = [e for e in entries if e['state'] in {'accepted', 'rejected', 'blocked', 'infrastructure_error'}]
    assert len(terminal) == 1 and terminal[0]['state'] == result.state == 'accepted'
    assert runner.finalize('infrastructure_error') == result


def test_timeout_after_prepared_is_terminal_infrastructure_error(tmp_path, monkeypatch):
    import time
    from dataclasses import replace
    p = package(tmp_path)
    p = replace(p, budgets={**p.budgets, 'wall_seconds': 1})
    runner = WorkerRunner(tmp_path, tmp_path / 'journal.jsonl', FakeClient([]))
    record = runner._record
    def delayed_prepared(state, **fields):
        record(state, **fields)
        if state == 'prepared':
            time.sleep(2)
    monkeypatch.setattr(runner, '_record', delayed_prepared)
    result = runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    entries = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    assert result.state == 'infrastructure_error' and result.reason == 'TimeoutError'
    assert [e['state'] for e in entries] == ['prepared', 'infrastructure_error']


def test_incomplete_terminal_line_is_not_accepted_or_retried(tmp_path, monkeypatch):
    import pytest

    from benchmark.worker_runner import JournalPersistenceError
    p = package(tmp_path)
    journal = tmp_path / 'journal.jsonl'
    runner = WorkerRunner(tmp_path, journal, FakeClient([patch('x = 1', 'x = 2')]))
    record = runner._record
    def partial_terminal(state, **fields):
        if state == 'accepted':
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'attempt_id': runner.attempt_id, 'state': state, **fields}))
            raise OSError('missing line ending')
        record(state, **fields)
    monkeypatch.setattr(runner, '_record', partial_terminal)
    with pytest.raises(JournalPersistenceError):
        runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    assert not journal.read_bytes().endswith(b'\n')
    with pytest.raises(JournalPersistenceError):
        runner.finalize('infrastructure_error')


def test_journal_with_non_object_record_stops_without_terminal(tmp_path):
    import pytest

    from benchmark.worker_runner import JournalPersistenceError
    p = package(tmp_path)
    journal = tmp_path / 'journal.jsonl'
    journal.write_text('[]\n')
    runner = WorkerRunner(tmp_path, journal, FakeClient([patch('x = 1', 'x = 2')]))
    with pytest.raises(JournalPersistenceError):
        runner.run(p, lambda: VisibleResult(True, ''), lambda: True)
    assert not any('"state": "accepted"' in line for line in journal.read_text().splitlines())
