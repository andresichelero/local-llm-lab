import json
import subprocess
from pathlib import Path


def test_preexecution_guard_blocks_identical_and_periodic_loops_but_allows_new_state():
    node = '/home/foxtrot/local-llm-benchmark/runtimes/node-v22.23.3-linux-x64/bin/node'
    module = (Path(__file__).parents[1] / 'benchmark/practical_policy_plugin.mjs').as_uri()
    script = '''
      const {ProgressGuard}=await import(process.argv[1]);
      const g=new ProgressGuard();
      for(let i=0;i<2;i++){g.before('read',{filePath:'x'},'epoch1');g.after('read',{filePath:'x'},'same','epoch1');}
      let stopped=false;try{g.before('read',{filePath:'x'},'epoch1');}catch(e){stopped=e.message.includes('model_no_progress');}
      if(!stopped) throw new Error('third identical call was admitted');
      g.before('read',{filePath:'x'},'epoch2');
      const cycle=new ProgressGuard();
      let periodic=false;
      try{for(let i=0;i<12;i++){const t=i%2?'grep':'read';cycle.before(t,{path:t},'epoch');cycle.after(t,{path:t},t,'epoch');}}catch(e){periodic=e.message.includes('model_no_progress');}
      if(!periodic) throw new Error('periodic cycle admitted');
      console.log(JSON.stringify({passed:true}));
    '''
    result = subprocess.run([node, '--input-type=module', '-e', script, module], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['passed']
