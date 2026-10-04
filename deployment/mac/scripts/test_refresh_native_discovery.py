import copy,unittest
import refresh_scoped_catalogs as refresh

ID='gpt-6.1-sol';ROUTE='personal/codex-oauth/'+ID
NATIVE={'models':[{'slug':ID,'visibility':'list','model_messages':{'instructions_template':'exact trusted native prompt'},'include_skills_usage_instructions':True}]}

class NativeDiscoveryTests(unittest.TestCase):
 def test_new_live_model_uses_exact_local_native_template(self):
  trusted={'models':[{'slug':'gpt-6-sol','base_instructions':'wrong generation'}]}
  templates,added=refresh.template_catalog_from_native(trusted,NATIVE)
  live={ROUTE:{'slug':ROUTE,'canonical_model_id':ID,'context_window':272000}}
  document,pending=refresh.codex_update({'models':[]},live,'personal',templates)
  self.assertEqual(added,[ID]);self.assertEqual(pending,[])
  self.assertEqual(document['models'][0]['base_instructions'],'exact trusted native prompt')
  self.assertEqual(document['models'][0]['model_messages'],NATIVE['models'][0]['model_messages'])
  self.assertEqual(trusted['models'][0]['base_instructions'],'wrong generation')
 def test_existing_templates_are_never_replaced_and_promptless_models_stay_pending(self):
  trusted={'models':[{'slug':ID,'base_instructions':'reviewed custom prompt'}]};original=copy.deepcopy(trusted)
  templates,added=refresh.template_catalog_from_native(trusted,NATIVE)
  self.assertEqual(templates,original);self.assertEqual(added,[])
  templates,added=refresh.template_catalog_from_native({'models':[]},{'models':[{'slug':ID}]})
  self.assertEqual(templates['models'],[]);self.assertEqual(added,[])
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
