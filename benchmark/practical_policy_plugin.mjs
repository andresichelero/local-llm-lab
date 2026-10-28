// Pinned OpenCode 1.19.4 hooks. This local module needs no npm dependencies.
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';

export const canonical = value => JSON.stringify(normalize(value));
function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,normalize(value[k])]));
  return value;
}
const digest = value => createHash('sha256').update(value).digest('hex');
const toolKey = (tool,args) => canonical([tool, tool==='bash'
  ? Object.fromEntries(Object.entries(args||{}).filter(([k])=>!['description','timeout'].includes(k))) : args]);

export class ProgressGuard {
  constructor(){ this.history=[]; this.reason=null; }
  before(tool,args,epoch) {
    const key=toolKey(tool,args);
    const recent=this.history.slice(-2);
    if(recent.length===2 && recent.every(x=>x.key===key && x.epoch===epoch) && recent[0].result===recent[1].result)
      throw new Error('LAB_POLICY_STOP:model_no_progress:identical_call');
    // Predict the start of a third period-2/3 block, across assistant turns.
    for(const period of [2,3]) {
      const h=this.history.slice(-period*2);
      if(h.length===period*2 && h.every(x=>x.epoch===epoch) && h.slice(0,period).every((x,i)=>x.key===h[i+period].key && x.result===h[i+period].result) && key===h[0].key)
        throw new Error('LAB_POLICY_STOP:model_no_progress:periodic_cycle');
    }
  }
  after(tool,args,result,epoch) {
    this.history.push({key:toolKey(tool,args),result:digest(String(result)),epoch});
    this.history=this.history.slice(-18);
  }
}

export function workspaceFingerprint(root) {
  const hashes=[];
  let bytes=0;
  function walk(dir) {
    for(const entry of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))) {
      if(entry.name.startsWith('.') || ['node_modules','__pycache__'].includes(entry.name)) continue;
      const file=path.join(dir,entry.name);
      if(entry.isSymbolicLink()) continue;
      if(entry.isDirectory()){walk(file);continue;}
      if(!entry.isFile() || hashes.length>=512) continue;
      const stat=fs.statSync(file);
      if(stat.size>1024*1024 || bytes+stat.size>8*1024*1024) continue;
      bytes+=stat.size;
      hashes.push([path.relative(root,file),digest(fs.readFileSync(file))]);
    }
  }
  walk(root);
  return digest(canonical(hashes));
}

export const LabPolicy = async ({directory}) => {
  const guards=new Map();
  const beforeEpochs=new Map();
  const policy=JSON.parse(fs.readFileSync('/opt/practical/policy.json','utf8'));
  const started=Date.now();
  const guard = session => { if(!guards.has(session)) guards.set(session,new ProgressGuard());return guards.get(session); };
  return {
    'tool.execute.before': async (input,output) => {
      const remaining=policy.wall_seconds*(policy.mode==='operational'?2:1)*1000-(Date.now()-started);
      if(remaining<=0) throw new Error('LAB_POLICY_STOP:budget_exhausted:wall');
      const epoch=workspaceFingerprint(directory);
      beforeEpochs.set(input.callID,epoch);
      guard(input.sessionID).before(input.tool,output.args,epoch);
      if(input.tool==='bash') output.args.timeout=Math.max(1,Math.min(Number(output.args.timeout)||60000,60000,remaining));
      if(['write','edit'].includes(input.tool) && output.args.filePath) {
        const target=path.resolve(directory,output.args.filePath);
        if(!target.startsWith(path.resolve(directory)+path.sep) || target.includes('/.opencode/'))
          throw new Error('LAB_POLICY_STOP:contract_error:protected_runtime_path');
      }
      process.stdout.write(JSON.stringify({_practical_driver:'policy_tool_start',call_id:input.callID,
        tool:input.tool,timeout_seconds:Math.min(input.tool==='bash'?60:10,remaining/1000)})+'\n');
    },
    'tool.execute.after': async (input,output) => {
      process.stdout.write(JSON.stringify({_practical_driver:'policy_tool_end',call_id:input.callID})+'\n');
      const epoch=workspaceFingerprint(directory);
      guard(input.sessionID).after(input.tool,input.args,output.output,epoch);
      const changed=beforeEpochs.get(input.callID)!==epoch;
      beforeEpochs.delete(input.callID);
      output.metadata={...(output.metadata||{}),lab_policy:{version:policy.version,workspace_fingerprint:epoch,changed}};
    },
  };
};

export default {id:'local-lab-policy', server:LabPolicy};
