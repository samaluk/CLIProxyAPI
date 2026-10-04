#!/usr/bin/env python3
"""Install pinned reviewed plugins serially through CPA's management installer.

Requires an exact published registry/stack pair. Keeps source identity, settings,
account bindings and main Codex intact. Private backups are never restored over
live credentials or session state. No changes without --execute.
"""
from pathlib import Path
import argparse, copy, datetime, hashlib, importlib.util, json, os, time, tomllib, urllib.request
ROOT=Path(os.environ.get('CPA_STATE_DIR', Path.home()/'.local/state/cpa-stack'))
CORE=Path.home()/'Library/Application Support/com.cpa.gui/cpa-core'
URL='https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/plugins.json'
SOURCE='source-'+hashlib.sha256(URL.encode()).hexdigest()[:12]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def without_store(cfg):
 cfg=copy.deepcopy(cfg)
 for p in cfg.get('plugins',{}).get('configs',{}).values():
  if isinstance(p,dict):p.pop('store',None)
 return cfg
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--registry',type=Path,required=True);parser.add_argument('--stack',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
 registry=json.loads(args.registry.read_text());stack=json.loads(args.stack.read_text());targets={p['id']:p for p in stack['plugins']}
 if not args.execute:print(json.dumps({'install':[{'id':p['id'],'version':p['version']} for p in registry['plugins']],'source':URL}));return
 os.umask(0o077)
 private=ROOT/'private/reviewed-deployments'/('plugins-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S'));private.mkdir(parents=True,mode=0o700)
 spec=importlib.util.spec_from_file_location('deploy',Path(__file__).resolve().parent/'deploy_reviewed_stack.py');deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
 secret=tomllib.loads((CORE.parent/'config.toml').read_text())['management-secret-key'];opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),deploy.NoRedirect())
 def api(path,method='GET',body=None):
  req=urllib.request.Request('http://127.0.0.1:8317/v0/management/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'},method=method)
  with opener.open(req,timeout=55) as r:return json.load(r)
 def registered(pid,version):
  deadline=time.monotonic()+25
  while time.monotonic()<deadline:
   item=next(p for p in api('plugins')['plugins'] if p['id']==pid)
   if item.get('registered') and item.get('effective_enabled') and item.get('metadata',{}).get('version')==version:return item
   time.sleep(.25)
  raise RuntimeError('Plugin did not register: '+pid)
 with urllib.request.urlopen(URL,timeout=30) as response:published=response.read()
 assert published==args.registry.read_bytes(),'Public registry is stale; no plugin changed. Keep the source URL.'
 before=api('config');configs={p['id']:api('plugins/'+p['id']+'/config') for p in registry['plugins']};protected=[Path.home()/'.codex/config.toml',CORE/'cli-proxy-api',Path.home()/'Library/Application Support/Agent Profiles/launch-harness.py',Path.home()/'.t3/userdata/settings.json'];hashes={p:sha(p) for p in protected}
 state_path=Path(configs['key-account-bind']['account-isolation']['state-file']);state=json.loads(state_path.read_text());(private/'binding-state-before.json').write_text(json.dumps(state));(private/'config-before.yaml').write_bytes((CORE/'config.yaml').read_bytes());(private/'plugin-configs-before.json').write_text(json.dumps(configs))
 health=object.__new__(deploy.Deployment);health.management=secret;health.keys=[(deploy.PROFILES/s/'keys/downstream.key').read_text().strip() for s in ('personal','work')];health.opener=opener;baseline=health.health();rows=[]
 for entry in registry['plugins']:
  pid=entry['id'];version=entry['version'];old=configs[pid]['store']['version'];assert configs[pid]['store']['source-id']==SOURCE and configs[pid]['enabled'] is True
  assert version==targets[pid]['version'];assert old in [v['version'] for v in entry['versions']]
  deploy.check_active_requests(deploy.inventory())
  print('Installing '+pid+' '+version,flush=True)
  attempted=False
  try:
   attempted=True;result=api('plugin-store/'+pid+'/install?source='+SOURCE,'POST',{'version':version,'upgrade_only':version!=old});assert result.get('version')==version and not result.get('restart_required'),'Unexpected install result'
   active=registered(pid,version);assert sha(Path(active['path']))==targets[pid]['library_sha256'],'Loaded library checksum differs'
   after=api('plugins/'+pid+'/config');assert {k:v for k,v in configs[pid].items() if k!='store'}=={k:v for k,v in after.items() if k!='store'},'Plugin settings changed';assert after['store']['source-id']==SOURCE
   assert without_store(before)==without_store(api('config')),'Non-store effective configuration changed'
   current=health.health();assert all(current['models'].get(route)==fields for route,fields in baseline['models'].items()),'Catalog lost a route/capability'
   assert all(sha(p)==h for p,h in hashes.items()),'Protected configuration changed'
   state_after=json.loads(state_path.read_text());assert all(state_after.get('sessions',{}).get(k)==v for k,v in state.get('sessions',{}).items()),'Existing binding records changed'
  except BaseException:
   if attempted:
    api('plugin-store/'+pid+'/install?source='+SOURCE,'POST',{'version':old});registered(pid,old)
   raise
  rows.append({'id':pid,'previousVersion':old,'version':version,'sourceId':SOURCE,'registered':True,'sha256':targets[pid]['library_sha256'],'path':active['path'],'settingsPreserved':True,'existingBindingsPreserved':True,'knownCapabilitiesPreserved':True})
  args.report.write_text(json.dumps({'completedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plugins':rows,'routeCount':len(current['models']),'mainCodexPreserved':True,'bindingCountBefore':len(state.get('sessions',{})),'bindingCountAfter':len(state_after.get('sessions',{})),'backup':str(private),'method':'management plugin-store installer; no GUI click-through claim'},indent=2)+'\n')
 print('All reviewed plugins installed and verified.',flush=True)
if __name__=='__main__':main()
