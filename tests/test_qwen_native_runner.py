from benchmark.qwen_native_runner import native_coverage, native_units


def rows_for(harnesses, models, artifacts, tasks, *, failures=()):
    rows=[]
    for harness in harnesses:
        for model in models:
            artifact=artifacts[model]
            for task in tasks:
                failed=(harness,model,task) in failures
                unit={'stage':'triage','harness':harness,'model_id':model,'artifact_id':artifact,
                      'task':task,'seed':101,'unit_id':f'{harness}-{model}-{task}'}
                rows.append({'status':'finished','unit':unit,'result':{
                    'status':'model_failure' if failed else 'complete',
                    'full_completion':not failed,'seconds':1.0,'model_failure':failed}})
    return rows


def test_native_triage_ranks_all_harnesses_and_needs_both_models():
    cfg={'tasks':['python_fix','javascript_fix','authored_tests'],'harnesses':['a','b','c','d'],
         'best_harnesses':3}
    artifacts={'4B':'a4','9B':'a9'}
    rows=rows_for(cfg['harnesses'],['4B','9B'],artifacts,cfg['tasks'],
                  failures={('d','9B','authored_tests')})
    summary=native_coverage(rows,cfg)
    assert summary['all_native_harnesses_reported'] is True
    assert summary['finalists']==['a','b','c']
    assert summary['status']=='selected'


def test_native_triage_never_selects_zero_completion_harnesses():
    cfg={'tasks':['python_fix','javascript_fix','authored_tests'],'harnesses':['a','b','c'],
         'best_harnesses':3}
    rows=rows_for(cfg['harnesses'],['4B','9B'],{'4B':'a4','9B':'a9'},cfg['tasks'],
                  failures={(h,m,t) for h in cfg['harnesses'] for m in ('4B','9B') for t in cfg['tasks']})
    assert native_coverage(rows,cfg)['status']=='insufficient_native_coverage'


def test_native_deep_schedule_pins_seed_task_harness_artifact_axes():
    cfg={'triage_seeds':[101],'deep_seeds':[101,202],
         'tasks':['B1','B2'],
         'deep_tasks':4,
         'deep_task_ids':['python_fix','javascript_fix','authored_tests','mcp'],
         'context_tokens':16384,'output_tokens':8192}
    chosen={m:[{'artifact_id':m+'-q4','model_id':m,'engine':'llama.cpp'}] for m in ('4B','9B')}
    rows=native_units(cfg,chosen,'triage')
    assert len(rows)==2*11*2
    deep=native_units(cfg,chosen,'deep',harnesses=['opencode'],
                      best_artifacts={'4B':{'opencode':'4B-q4'},'9B':{'opencode':'9B-q4'}})
    assert len(deep)==2*1*4*2
    assert {x['seed'] for x in deep}=={101,202}
    assert len({x['unit_id'] for x in deep})==len(deep)


def test_native_deep_schedule_refuses_missing_or_duplicate_task_ids():
    cfg={'triage_seeds':[101],'deep_seeds':[101,202],
         'tasks':['python_fix','javascript_fix'],
         'deep_tasks':12,
         'deep_task_ids':['python_fix']*6,
         'context_tokens':16384,'output_tokens':8192}
    chosen={m:[{'artifact_id':m+'-q4','model_id':m,'engine':'llama.cpp'}]
            for m in ('4B','9B')}
    assert native_units(cfg,chosen,'deep',harnesses=['opencode'])==[]


def test_native_report_accounts_for_api_tool_and_context_coverage_axes():
    status={'harnesses':{'opencode':{'4B':{'score':1.0,'completion_count':3},
                                     '9B':{'score':2/3,'completion_count':2}}},
            'feature_tasks':{'mcp':'OpenCode native local MCP relay','continuation':'staged-session adapter pending'}}
    assert status['harnesses']['opencode']['4B']['completion_count']==3
    assert 'mcp' in status['feature_tasks'] and 'continuation' in status['feature_tasks']
