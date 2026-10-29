import hashlib
import json
from pathlib import Path

from benchmark.worker_contract import build_package


def test_package_excludes_private_and_reference(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'corpus'
    workspace = tmp_path
    (workspace / 'bottle.py').write_text('def hello():\n    pass\n')
    package = build_package(root, 'py_range', workspace, 'revision')
    rendered = json.dumps(package.to_dict()) + package.markdown
    for private in (root / 'oracles').rglob('*.py'):
        assert private.read_text(encoding='utf-8') not in rendered
    for patch in (root / 'tasks').rglob('reference.patch'):
        content = patch.read_text(encoding='utf-8')
        if content:
            assert content not in rendered
    assert package.input_hashes['bottle.py'] == hashlib.sha256((workspace / 'bottle.py').read_bytes()).hexdigest()


def test_continuation_followup_requires_accepted_delivery(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('pass\n')
    import pytest
    with pytest.raises(ValueError):
        build_package(root, 'cont_quote', tmp_path, 'rev', followup=True)


def test_context_rejects_untrusted_private_content(tmp_path):
    import pytest
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('x = 1\n')
    secret = (root / 'oracles' / 'py_range' / 'oracle.py').read_text()
    with pytest.raises(ValueError):
        build_package(root, 'py_range', tmp_path, 'rev', readonly_context={'bottle.py': secret})
    package = build_package(root, 'py_range', tmp_path, 'rev', readonly_context={'bottle.py': 'x = 1\n'})
    assert 'x = 1' in package.markdown


def test_package_includes_deterministic_tool_evidence(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('pass\n')
    package = build_package(root, 'mcp_header', tmp_path, 'rev')
    assert 'underscores map to hyphens' in package.markdown
    assert 'header_contract' in package.readonly_context['tool_output']


def test_metadata_and_blocked_result_have_closed_typed_contract(tmp_path):
    import pytest

    from benchmark.worker_contract import PACKAGE_SCHEMA, WorkerResult
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('pass\n')
    package = build_package(root, 'py_range', tmp_path, 'rev')
    assert 'markdown' not in package.to_dict() and 'markdown' not in PACKAGE_SCHEMA['properties']
    assert WorkerResult('blocked', 'BLOCKED: insufficient_context', 'insufficient_context').reason == 'insufficient_context'
    with pytest.raises(ValueError):
        WorkerResult('blocked', 'BLOCKED: unknown', 'unknown')
    with pytest.raises(ValueError):
        WorkerResult('patch', 'x', 'insufficient_context')


def test_all_corpus_packages_exclude_private_files():
    root = Path(__file__).resolve().parents[1] / 'corpus'
    private = [p.read_text(encoding='utf-8') for p in (root / 'oracles').rglob('*.py')]
    private += [p.read_text(encoding='utf-8') for p in (root / 'tasks').rglob('reference.patch')]
    for task_file in (root / 'tasks').glob('*/task.json'):
        task = json.loads(task_file.read_text(encoding='utf-8'))
        package = build_package(root, task['id'], root / 'hosts' / task['host'], 'rev')
        rendered = json.dumps(package.to_dict()) + package.markdown
        assert all(not content or content not in rendered for content in private), task['id']


def test_public_builder_cannot_self_assert_continuation_acceptance(tmp_path):
    import pytest
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('pass\n')
    with pytest.raises((ValueError, TypeError)):
        build_package(root, 'cont_quote', tmp_path, 'rev', followup=True, first_delivery_accepted=True)


def test_reject_prefix_that_is_not_frozen_host_prefix(tmp_path):
    import pytest
    root = Path(__file__).resolve().parents[1] / 'corpus'
    (tmp_path / 'bottle.py').write_text('pass\n')
    secret = (root / 'oracles' / 'py_range' / 'oracle.py').read_bytes()
    with pytest.raises(ValueError, match='prefix'):
        build_package(root, 'py_range', tmp_path, 'rev', prefix=secret)


def test_packages_exclude_nontrivial_private_oracle_lines():
    root = Path(__file__).resolve().parents[1] / 'corpus'
    checked = 0
    for task_file in (root / 'tasks').glob('*/task.json'):
        task = json.loads(task_file.read_text(encoding='utf-8'))
        package = build_package(root, task['id'], root / 'hosts' / task['host'], 'rev')
        rendered = package.markdown + json.dumps(package.to_dict(), ensure_ascii=False)
        # Some identical assertions are deliberately public in the visible test.
        public_lines = {line.strip() for line in package.readonly_context['visible_test'].splitlines()}
        for private in (root / 'oracles' / task['id']).rglob('*'):
            if private.is_file() and private.suffix == '.py':
                for line in private.read_text(encoding='utf-8').splitlines():
                    fragment = line.strip()
                    if (len(fragment) >= 35 and fragment not in public_lines
                            and not fragment.startswith(('#', 'import ', 'from '))):
                        checked += 1
                        assert fragment not in rendered, (task['id'], fragment)
    assert checked > 0
