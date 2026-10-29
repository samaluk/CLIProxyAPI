import copy,unittest
import refresh_scoped_catalogs as refresh

ID='gpt-6.1-sol';ROUTE='personal/codex-oauth/'+ID
NATIVE={'models':[{'slug':ID,'visibility':'list','model_messages':{'instructions_template':'exact trusted native prompt'},'include_skills_usage_instructions':True}]}

class NativeDiscoveryTests(unittest.TestCase):
 def test_new_live_model_is_admitted_without_a_native_template(self):
  live={ROUTE:{'slug':ROUTE,'canonical_model_id':ID,'context_window':272000}}
  document,pending=refresh.codex_update({'models':[]},live,'personal')
  self.assertEqual(pending,[])
  self.assertEqual(document['models'][0]['slug'],ROUTE)
  self.assertNotIn('base_instructions',document['models'][0])
  self.assertNotIn('model_messages',document['models'][0])
 def test_existing_and_remote_prompt_fields_are_removed_from_metadata(self):
  document={'models':[{'slug':ROUTE,'base_instructions':'custom prompt','model_messages':NATIVE['models'][0]['model_messages']}]}
  original=copy.deepcopy(document)
  out,pending=refresh.codex_update(document,{ROUTE:{'slug':ROUTE,'base_instructions':'remote prompt'}},'personal')
  self.assertEqual(document,original);self.assertEqual(pending,[])
  self.assertNotIn('base_instructions',out['models'][0]);self.assertNotIn('model_messages',out['models'][0])
 def test_new_native_model_missing_from_proxy_is_reported_not_invented(self):
  catalogs={'personal':[{'slug':'personal/codex-oauth/gpt-6-sol','canonical_model_id':'gpt-6-sol'}]}
  self.assertEqual(refresh.registration_candidates(NATIVE,catalogs,[]),[ID])
  self.assertEqual(refresh.registration_candidates(NATIVE,catalogs,[ROUTE]),[])
  catalogs['personal'].append({'slug':ROUTE,'canonical_model_id':ID})
  self.assertEqual(refresh.registration_candidates(NATIVE,catalogs,[]),[])
 def test_hidden_native_models_are_not_proposed(self):
  native=copy.deepcopy(NATIVE);native['models'][0]['visibility']='hide'
  self.assertEqual(refresh.registration_candidates(native,{},[]),[])

if __name__=='__main__':unittest.main()
