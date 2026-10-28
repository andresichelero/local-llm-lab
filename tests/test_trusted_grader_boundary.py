"""Exercise the real sandbox boundary, not just collector parsers."""
import pytest

from benchmark import practical_runtime_v2 as runtime, practical_tasks_v2 as tasks


@pytest.mark.parametrize('task',[t for t,s in tasks.TASK_SPECS.items() if s['language']!='mcp'])
@pytest.mark.parametrize('variant',[0,1])
def test_reference_through_data_only_boundary(tmp_path,task,variant):
    workspace=tmp_path/'input'
    tasks.seed_task(task,workspace)
    for phase in range(1,tasks.TASK_SPECS[task]['phases']+1):
        for name,value in tasks.reference_files(task,variant,phase).items():
            target=workspace/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(value)
        verdict=runtime._grader_result(task,phase,workspace,lab=runtime.LAB)
        assert verdict['passed'],verdict


def test_independent_m1_through_data_only_boundary(tmp_path):
    workspace=tmp_path/'input'
    contract=tasks.M1_INDEPENDENT_CONTRACT
    tasks.seed_task('M1',workspace,task_contract_id=contract)
    for name,value in tasks.reference_files('M1',task_contract_id=contract).items():
        target=workspace/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(value)
    verdict=runtime._grader_result('M1',1,workspace,lab=runtime.LAB,task_contract_id=contract)
    assert verdict['passed'],verdict


def test_malformed_node_candidate_import_is_a_model_failure(tmp_path):
    workspace=tmp_path/'input'
    tasks.seed_task('M1',workspace,task_contract_id=tasks.M1_INDEPENDENT_CONTRACT)
    target=workspace/'src/config/merge.js'
    target.write_text('function mergeConfig( {\nmodule.exports = {mergeConfig};\n')
    verdict=runtime._grader_result('M1',1,workspace,lab=runtime.LAB,
                                  task_contract_id=tasks.M1_INDEPENDENT_CONTRACT)
    assert verdict['passed'] is False,verdict
    assert verdict['candidate_failure_observed'] is True,verdict
    assert verdict['contract_invalid'] is False and verdict['infrastructure'] is False


@pytest.mark.parametrize('payload',[
    "raise SystemExit(0)\n",
    "import os\nos._exit(0)\n",
    "import os,sys,json\nfd=int(sys.argv[sys.argv.index('--rpc-fd')+1])\n"
    "os.write(fd,(json.dumps({'event':'stop','check':'Acceptance.test_must_fail','stop':'pass'})+'\\n'+json.dumps({'event':'end'})+'\\n').encode())\nos._exit(0)\n",
])
def test_candidate_never_approves_a_false_trusted_assertion(monkeypatch,tmp_path,payload):
    workspace=tmp_path/'input'
    workspace.mkdir()
    (workspace/'victim.py').write_text(payload+'\ndef target(): return 1\n')
    monkeypatch.setattr(tasks,'checks_source',lambda *a,**k:
        'from unittest import TestCase\nfrom victim import target\n'
        'class Acceptance(TestCase):\n def test_must_fail(self):\n  target()\n  self.assertFalse(True)\n')
    result=runtime._grader_result('B1',1,workspace,lab=runtime.LAB)
    assert result['passed'] is False,result


def test_dynamic_file_import_cannot_execute_candidate_in_judge(monkeypatch,tmp_path):
    workspace=tmp_path/'input'
    workspace.mkdir()
    (workspace/'victim.py').write_text('import unittest\nunittest.TestCase.assertFalse=lambda *a,**k: None\n')
    monkeypatch.setattr(tasks,'checks_source',lambda *a,**k:
        'import importlib.util\nfrom unittest import TestCase\n'
        's=importlib.util.spec_from_file_location("victim","/workspace/victim.py")\n'
        's.loader.exec_module(importlib.util.module_from_spec(s))\n'
        'class Acceptance(TestCase):\n def test_must_fail(self): self.assertFalse(True)\n')
    result=runtime._grader_result('B1',1,workspace,lab=runtime.LAB)
    assert not result['passed'],result


def test_candidate_file_cannot_shadow_judges_standard_library(tmp_path):
    workspace=tmp_path/'input'
    tasks.seed_task('B1',workspace)
    for name,value in tasks.reference_files('B1').items():
        target=workspace/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(value)
    (workspace/'csv.py').write_text('raise SystemExit(0)\n')
    result=runtime._grader_result('B1',1,workspace,lab=runtime.LAB)
    assert result['passed'],result


@pytest.mark.parametrize('payload', [
    "process.exit(0);",
    "console.log('TAP version 13\\nok 1 - must fail\\n1..1\\n# tests 1\\n# pass 1'); process.exit(0);",
    "require('fs').writeFileSync('.forged.json', JSON.stringify({passed:true})); process.exit(0);",
])
def test_node_candidate_cannot_forge_trusted_tap(monkeypatch, tmp_path, payload):
    workspace = tmp_path / 'input'
    workspace.mkdir()
    (workspace / 'victim.js').write_text(payload + '\nmodule.exports={target:()=>1};')
    monkeypatch.setattr(tasks, 'checks_source', lambda *a, **k:
        "const {test}=require('node:test'); const a=require('node:assert/strict');\n"
        "const {target}=require(require('node:path').join(process.cwd(),'victim.js'));\n"
        "test('must fail',()=>{target(); a.equal(true,false);});\n")
    result = runtime._grader_result('B2', 1, workspace, lab=runtime.LAB)
    assert result['passed'] is False, result
