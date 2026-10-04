import copy,json,pathlib,tempfile,unittest
from unittest.mock import patch
import refresh_scoped_catalogs as refresh

ROUTE='work/litellm/gpt-5.6-luna-pro'
FRESH={'slug':ROUTE,'canonical_model_id':'native-luna','context_window':1050000,'max_tokens':128000,'input_modalities':['text','image'],'supported_input_modalities':['text','image'],'output_modalities':['text'],'supported_reasoning_levels':[{'effort':x,'description':x} for x in ('none','low','medium','high','xhigh','max')],'default_reasoning_level':'medium'}

class TransformTests(unittest.TestCase):
 def test_credentials_can_only_reach_local_origin_without_redirect(self):
  self.assertEqual(refresh.validate_origin('http://127.0.0.1:8317/'),'http://127.0.0.1:8317')
  for url in ('http://127.0.0.1:8317@evil.example','https://evil.example','http://localhost:8317/path','http://localhost:8317?x=1','http://user@localhost:8317'):
   with self.assertRaises(ValueError):refresh.validate_origin(url)
  self.assertIsNone(refresh.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example'))
 def test_ingress_discards_auth_and_instruction_prose(self):
  raw={**FRESH,'base_instructions':'PRIVATE PROMPT','model_messages':{'instructions_template':'PRIVATE'},'apiKey':'SECRET','description':'REMOTE PROSE'}
  out=refresh.safe_model(raw)
  self.assertNotIn('PRIVATE',json.dumps(out));self.assertNotIn('SECRET',json.dumps(out));self.assertNotIn('REMOTE',json.dumps(out))
 def test_codex_preserves_prompts_and_temporarily_absent_routes(self):
  base={'other':'setting','models':[{'slug':ROUTE,'base_instructions':'user prompt','model_messages':{'native':'bytes'},'display_name':'user label','custom':'keep','context_window':42},{'slug':'personal/codex-oauth/gpt-6-astra'},{'slug':next(iter(refresh.RETIRED))}]}
  original=copy.deepcopy(base);out,pending=refresh.codex_update(base,{ROUTE:FRESH},'work')
  self.assertEqual(base,original);self.assertEqual(out['other'],'setting');self.assertEqual(len(out['models']),2)
  model=out['models'][0];self.assertEqual(model['base_instructions'],'user prompt');self.assertEqual(model['model_messages'],{'native':'bytes'});self.assertEqual(model['custom'],'keep');self.assertEqual(model['display_name'],'user label');self.assertEqual(model['context_window'],1050000);self.assertEqual(pending,[])
 def test_new_codex_requires_exact_canonical_template(self):
  out,pending=refresh.codex_update({'models':[]},{ROUTE:FRESH},'work',{'models':[{'slug':'native-luna-extra','base_instructions':'wrong'}]})
  self.assertEqual(out['models'],[]);self.assertEqual(pending,[ROUTE])
  out,pending=refresh.codex_update({'models':[]},{ROUTE:FRESH},'work',{'models':[{'slug':'native-luna','base_instructions':'trusted'}]})
  self.assertEqual(out['models'][0]['base_instructions'],'trusted');self.assertEqual(out['models'][0]['slug'],ROUTE);self.assertFalse(pending)
 def test_opencode_preserves_provider_user_options_aliases_and_valid_effort(self):
  original={'model':'cpa-work/'+ROUTE,'user':True,'provider':{'cpa-work':{'options':{'apiKey':'private'},'models':{ROUTE:{'name':'my label','options':{'reasoningEffort':'high','temperature':.2},'variants':{'max':{'custom':1},'ultra':{'reasoningEffort':'ultra'}},'headers':{'custom':'value'}},'legacy-alias':{'name':'saved thread alias'}}}}}
  out=refresh.opencode_update(original,{ROUTE:FRESH},'work');provider=out['provider']['cpa-work'];model=provider['models'][ROUTE]
  self.assertEqual(out['model'],original['model']);self.assertEqual(provider['options'],original['provider']['cpa-work']['options']);self.assertIn('legacy-alias',provider['models']);self.assertEqual(model['name'],'my label');self.assertEqual(model['options'],{'reasoningEffort':'high','temperature':.2});self.assertEqual(model['variants']['max'],{'custom':1,'reasoningEffort':'max'});self.assertTrue(model['variants']['ultra']['disabled']);self.assertEqual(model['limit'],{'context':1050000,'output':128000})
 def test_opencode_never_invents_missing_output_or_file_to_pdf(self):
  out=refresh.opencode_update({'provider':{'cpa-work':{'models':{}}}},{ROUTE:{'slug':ROUTE,'context_window':100,'supported_input_modalities':['text','file']}},'work')
  m=out['provider']['cpa-work']['models'][ROUTE];self.assertNotIn('limit',m);self.assertEqual(m['modalities']['input'],['text'])
 def test_removed_effort_default_changes_only_when_unsupported(self):
  base={'provider':{'cpa-work':{'models':{ROUTE:{'options':{'reasoningEffort':'ultra','user':1}}}}}}
  m=refresh.opencode_update(base,{ROUTE:FRESH},'work')['provider']['cpa-work']['models'][ROUTE];self.assertEqual(m['options'],{'reasoningEffort':'medium','user':1})
 def test_pi_keeps_combined_cache_costs_and_missing_astra(self):
  document={'models':[{'id':ROUTE,'cost':{'input':7},'name':'my name','stale':True},{'id':'personal/codex-oauth/gpt-6-astra','contextWindow':42},{'id':next(iter(refresh.RETIRED))}],'fastModelIds':[ROUTE,next(iter(refresh.RETIRED))],'fetchedAt':123,'inferenceBaseUrl':'url'}
  mapped=[{'id':ROUTE,'name':'remote','cost':{'input':0},'reasoning':True,'contextWindow':1050000,'maxTokens':128000,'input':['text','image'],'thinkingLevelMap':{'off':'none','max':'max','ultra':None}}]
  out=refresh.pi_update(document,mapped,{ROUTE:FRESH});self.assertEqual(len(out['models']),2);m=out['models'][0];self.assertEqual(m['cost'],{'input':7});self.assertEqual(m['name'],'my name');self.assertNotIn('stale',m);self.assertIsNone(m['thinkingLevelMap']['ultra']);self.assertEqual(out['fetchedAt'],123)
 def test_pi_does_not_overwrite_evidence_with_mapper_fallback(self):
  original={'models':[{'id':ROUTE,'maxTokens':64000,'contextWindow':250000,'input':['text','image'],'thinkingLevelMap':{'max':'max'}}]}
  mapped=[{'id':ROUTE,'maxTokens':16384,'contextWindow':128000,'input':['text'],'reasoning':False}]
  model=refresh.pi_update(original,mapped,{ROUTE:{'slug':ROUTE}})['models'][0]
  self.assertEqual(model['maxTokens'],64000);self.assertEqual(model['contextWindow'],250000);self.assertEqual(model['input'],['text','image']);self.assertEqual(model['thinkingLevelMap'],{'max':'max'})
 def test_reconciliation_is_idempotent(self):
  codex={'models':[{'slug':ROUTE,'base_instructions':'same'}]};first,_=refresh.codex_update(codex,{ROUTE:FRESH},'work');second,_=refresh.codex_update(first,{ROUTE:FRESH},'work');self.assertEqual(first,second)
  opencode={'provider':{'cpa-work':{'models':{}}}};first=refresh.opencode_update(opencode,{ROUTE:FRESH},'work');self.assertEqual(first,refresh.opencode_update(first,{ROUTE:FRESH},'work'))

class TransactionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name).resolve();self.profiles=self.root/'profiles';self.path=self.profiles/'work/catalogs/codex-catalog.json';self.path.parent.mkdir(parents=True);self.path.write_bytes(b'old');self.path.chmod(0o640);self.changes={self.path:{'before':b'old','after':b'new'}}
 def tearDown(self):self.tmp.cleanup()
 def test_backup_apply_and_mode_preserved(self):
  backup=refresh.apply_changes(self.changes,self.profiles,self.root/'private');self.assertEqual(self.path.read_bytes(),b'new');self.assertEqual((backup/'0').read_bytes(),b'old');self.assertEqual(backup.stat().st_mode&0o777,0o700);self.assertEqual(self.path.stat().st_mode&0o777,0o640)
 def test_concurrent_edit_rejected_before_write(self):
  self.path.write_bytes(b'user edit')
  with self.assertRaises(ValueError):refresh.apply_changes(self.changes,self.profiles,self.root/'private')
  self.assertEqual(self.path.read_bytes(),b'user edit')
 def test_main_codex_and_symlink_targets_rejected(self):
  with self.assertRaises(ValueError):refresh.apply_changes(self.changes,self.profiles,self.root/'private',[self.path])
  self.path.unlink();target=self.root/'main';target.write_bytes(b'old');self.path.symlink_to(target)
  with self.assertRaises(ValueError):refresh.apply_changes(self.changes,self.profiles,self.root/'private')
  self.assertEqual(target.read_bytes(),b'old')
 def test_failure_after_first_write_restores_previous_bytes(self):
  second=self.profiles/'work/pi/cliproxyapi-models.json';second.parent.mkdir(parents=True);second.write_bytes(b'old2');self.changes[second]={'before':b'old2','after':b'new2'}
  real=refresh.atomic_write
  def fail(path,raw,mode):
   if raw==b'new2':raise OSError('fixture failure')
   real(path,raw,mode)
  with patch.object(refresh,'atomic_write',side_effect=fail):
   with self.assertRaises(OSError):refresh.apply_changes(self.changes,self.profiles,self.root/'private')
  self.assertEqual(self.path.read_bytes(),b'old');self.assertEqual(second.read_bytes(),b'old2')

if __name__=='__main__':unittest.main()
