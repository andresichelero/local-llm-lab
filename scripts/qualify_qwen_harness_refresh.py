"""Offline CLI/dependency checks for refreshed installs; no model/API benchmark."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location(
    'refresh_qwen', Path(__file__).with_name('refresh_qwen_harnesses.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

COMMANDS = {'pi':'pi','opencode':'opencode','codex':'codex','claude-code':'claude',
            'trueforge':'trueforge','deepseek-harness':'dsh','qwen-code':'qwen',
            'mistral-vibe':'vibe','aider':'aider','openhands':'openhands','headroom':'headroom'}


def audit_summary(audit):
    vulnerabilities = audit.get('vulnerabilities') or {}
    direct = []
    for package, finding in sorted(vulnerabilities.items()):
        if not finding.get('isDirect'):
            continue
        via = []
        for item in finding.get('via', []):
            if isinstance(item, str):
                via.append(item)
            else:
                via.append({key: item[key] for key in ('name', 'title', 'url', 'range', 'severity') if key in item})
        direct.append({
            'package': package,
            'severity': finding.get('severity'),
            'range': finding.get('range'),
            'fix_available': finding.get('fixAvailable'),
            'via': via,
        })
    return {
        'counts': audit.get('metadata', {}).get('vulnerabilities', {}),
        'vulnerable_packages': len(vulnerabilities),
        'direct': direct,
    }


def add_hermes_tools_to_path(env, data_home):
    tools_root = Path(data_home) / 'tools'
    tool_bins = sorted(
        str(path / 'bin')
        for path in tools_root.iterdir()
        if path.is_dir() and (path / 'bin').is_dir()
    ) if tools_root.is_dir() else []
    if tool_bins:
        env['PATH'] = os.pathsep.join([*tool_bins, env.get('PATH', '')])
    return env


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state=json.loads((r.REPORT/'installation.json').read_text())
    if state['status']=='installing':
        raise RuntimeError('wait for the entire refresh before qualifying harnesses')
    discovery=json.loads((r.REPORT/'discovery.json').read_text())
    resolved={item['id']:item for item in discovery['harnesses']+discovery['plugins']}
    node=Path(state['runtime']['node']['root'])
    result={'scope':'installation and offline CLI checks only; model/tool parity pending',
            'inference':False,'items':{},'runtimes':{},'native':{},'security_reviews':{}}
    environment=r.clean_env(r.BASE/'homes/qualification',node)
    for name,argv in [('node',[node/'bin/node','--version']),('npm',[node/'bin/npm','--version'])]:
        result['runtimes'][name]=subprocess.check_output(argv,env=environment,text=True).strip()
    for minor,python in state['runtime']['python'].items():
        result['runtimes']['python-'+minor]=subprocess.check_output([python,'--version'],env=environment,text=True).strip()
    result['runtimes']['llama.cpp']={'latest_stable':'v0.7.0',
        'tag_commit':'620d2225cc436ab0b001e3200e590e3b286ef9ab',
        'installed_source_commit':subprocess.check_output(['git','-C',r.LAB/'tools/llama.cpp-v0.7.0-620d2225c',
            'rev-parse','HEAD'],env=environment,text=True).strip(),
        'binary_sha256':digest(r.LAB/'tools/llama-bin/llama-server'),
        'status':'already-current-stable; preserved, not rebuilt'}
    for name,item in state['items'].items():
        data={'installation':item['status'],'version':item.get('version'),'source':item.get('source')}
        result['items'][name]=data
        if item['status'] not in {'installed','staged'}:
            data['status']='blocked_at_installation'
            data['error']=item.get('error')
            continue
        prefix=Path(item['root'])
        env=r.clean_env(r.BASE/'homes'/name,node)
        env['PATH']=str(r.BASE/'native/usr/bin')+':'+env['PATH']
        env['LD_LIBRARY_PATH']=str(r.BASE/'native/usr/lib/x86_64-linux-gnu')
        try:
            if item['kind']=='npm':
                package=prefix/'node_modules'/resolved[name]['package']/'package.json'
                installed=json.loads(package.read_text())
                data['package_version']=installed['version']
                data['package_lock_sha256']=digest(prefix/'package-lock.json')
                if name=='headroom-opencode':
                    event=r.run(name+'-import',['unshare','--user','--map-root-user','--net',
                        node/'bin/node','--input-type=module','-e',
                        "import('headroom-opencode').then(m=>console.log(Object.keys(m).sort().join(',')))"],
                        env=env,cwd=prefix,timeout=45,check=False)
                    data.update(status='plugin-import-ok' if event['returncode']==0 else 'plugin-import-blocked',check=event)
                    continue
                executable=prefix/'node_modules/.bin'/COMMANDS[name]
            elif item['kind']=='pypi':
                executable=prefix/'bin'/COMMANDS[name]
                data['python']=item['python']
                data['dependency_freeze_log']=str(max((r.REPORT/'logs').glob(name+'-freeze-*.log')))
            elif name=='hermes':
                executable=r.BASE/'homes/hermes/.local/bin/hermes'
                hermes_home=Path(item['home'])/'hermes-data'
                env['HERMES_HOME']=str(hermes_home)
                add_hermes_tools_to_path(env, hermes_home)
                data['installed_commit']=subprocess.check_output(['git','-C',prefix,'rev-parse','HEAD'],env=env,text=True).strip()
            else:
                data['installed_commit']=subprocess.check_output(['git','-C',prefix,'rev-parse','HEAD'],env=env,text=True).strip()
                package=json.loads((prefix/'package.json').read_text())
                data['package_version']=package['version']
                event=r.run(name+'-syntax',[node/'bin/node','--check',prefix/'index.js'],env=env,timeout=30,check=False)
                data.update(status='plugin-source-staged' if event['returncode']==0 else 'plugin-syntax-blocked',check=event)
                continue
            if not executable.exists():
                raise FileNotFoundError(f'expected CLI is missing: {executable}')
            data['executable']=str(executable)
            data['executable_sha256']=digest(executable.resolve())
            event=r.run(name+'-version',['unshare','--user','--map-root-user','--net',executable,'--version'],
                env=env,timeout=45,check=False)
            data['version_output']=Path(event['log']).read_text(errors='replace')[-2500:]
            help_event=r.run(name+'-help',['unshare','--user','--map-root-user','--net',executable,'--help'],
                env=env,timeout=45,check=False)
            data['help_output']=Path(help_event['log']).read_text(errors='replace')[-2500:]
            data['help_check']=help_event
            if event['returncode'] == 0 and help_event['returncode'] == 0:
                status='cli-version-ok'
            elif event['returncode'] == 0:
                status='cli-help-needs-review'
            else:
                status='cli-needs-review'
            data.update(status=status,check=event)
        except Exception as exc:
            data.update(status='qualification-blocked',error=f'{type(exc).__name__}: {exc}')
        r.atomic(r.REPORT/'qualification.json',result)
    for path in (r.REPORT/'logs').glob('*-audit-*.log'):
        name=path.name.split('-audit-',1)[0]
        try:
            audit=json.loads(path.read_text())
            result['security_reviews'][name]=audit_summary(audit)
            result['security_reviews'][name].update(error=audit.get('error'),log=str(path))
        except ValueError:
            result['security_reviews'][name]={'error':'audit did not return parseable JSON','log':str(path)}
    for name,relative in [('bubblewrap','bwrap'),('socat','socat')]:
        env=r.clean_env(r.BASE/'homes/native-qualification',node)
        env['LD_LIBRARY_PATH']=str(r.BASE/'native/usr/lib/x86_64-linux-gnu')
        executable=r.BASE/'native/usr/bin'/relative
        event=r.run('native-'+name+'-version',['unshare','--user','--map-root-user','--net',executable,
            '--version' if name=='bubblewrap' else '-V'],env=env,timeout=30,check=False)
        result['native'][name]=event
    result['pending']=['common local Qwen endpoint and wire-protocol parity',
        'sandbox, tool, limits and workload parity before a harness quality ranking',
        'security review of audit findings; no force-fixes applied']
    r.atomic(r.REPORT/'qualification.json',result)
    print(json.dumps({'runtimes':result['runtimes'],'items':{k:v.get('status') for k,v in result['items'].items()},
        'security_reviews':result['security_reviews'],'pending':result['pending']},indent=2))


if __name__=='__main__':
    main()
