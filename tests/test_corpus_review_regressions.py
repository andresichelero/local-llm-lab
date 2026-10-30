"""Concrete partial solutions must be rejected by the private oracles."""

import os
import shutil

import pytest

from test_corpus_validate import load_validator


@pytest.mark.parametrize(('task', 'old', 'new'), [
    ('py_route', 'url_args[name] = wildcard_filter(url_args[name])',
     'url_args[name] = int(url_args[name])'),
    ('recover_cookieformat', "return bool(data.startswith(tob('!')) and tob('?') in data)",
     "return data.startswith(b'!')"),
    ('cont_forms', "return s.encode('latin1').decode(encoding or self.input_encoding)",
     "return s.encode('latin1').decode('utf8')"),
])
def test_partial_implementation_is_rejected(tmp_path, task, old, new):
    validator = load_validator()
    workspace = tmp_path / 'workspace'
    shutil.copytree(validator.ROOT / 'hosts' / 'bottle-0.13.2', workspace)
    source = workspace / 'bottle.py'
    original = source.read_text(encoding='utf-8')
    assert original.count(old) == 1
    source.write_text(original.replace(old, new, 1), encoding='utf-8')
    support = str(validator.ROOT / 'support')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', CORPUS_SUPPORT=support,
               PYTHONPATH=str(workspace) + os.pathsep + support)
    assert validator.run_oracle(validator.ROOT / 'oracles' / task / 'oracle.py', workspace, env, task) == 1


@pytest.mark.parametrize(('task', 'suite'), [
    ('tests_escape', "assert bottle.html_escape(\"&'\") == '&amp;&#039;'"),
    ('tests_list', "assert bottle.makelist(('a', 'b')) == ['a', 'b']\n    assert bottle.makelist(0) == []"),
    ('tests_compare', "assert not bottle._lscmp('abc', 'abd')\n    assert not bottle._lscmp('abc', 'abcd')"),
])
def test_partial_authored_suite_is_rejected(tmp_path, task, suite):
    validator = load_validator()
    workspace = tmp_path / 'workspace'
    shutil.copytree(validator.ROOT / 'hosts' / 'bottle-0.13.2', workspace)
    (workspace / 'test' / f'test_{task}.py').write_text(
        f'import bottle\n\ndef test_partial():\n    {suite}\n', encoding='utf-8')
    support = str(validator.ROOT / 'support')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', CORPUS_SUPPORT=support,
               PYTHONPATH=str(workspace) + os.pathsep + support)
    assert validator.run_oracle(validator.ROOT / 'oracles' / task / 'oracle.py', workspace, env, task) == 1
