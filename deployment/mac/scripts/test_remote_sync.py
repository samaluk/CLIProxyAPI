import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import remote_sync


class DiagnosticsTests(unittest.TestCase):
    def tearDown(self): remote_sync.FAILURE_CONTEXT.clear()

    def test_failed_fetch_records_exact_static_cause_and_frame_without_touching_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();state=root/'sync-state';state.mkdir();status=state/'status.json';status.write_text('last success')
            remote_sync.phase('fetch-catalog', root=root, scope='work')
            def fail(): raise ValueError('Gateway catalog unavailable: HTTP 503')
            with patch.object(remote_sync,'main',side_effect=lambda: (remote_sync.phase('fetch-catalog',root=root,scope='work'),fail())), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(remote_sync.run(),1)
            receipt_path=next((state/'diagnostics').glob('*-failure.json'));receipt=json.loads(receipt_path.read_text())
            self.assertEqual(receipt['message'],'Gateway catalog unavailable: HTTP 503')
            self.assertEqual(receipt['stage'],'fetch-catalog');self.assertEqual(receipt['scope'],'work')
            self.assertEqual(receipt['traceback'][-1]['function'],'fail')
            self.assertGreater(receipt['traceback'][-1]['line'],0)
            self.assertEqual(receipt_path.stat().st_mode & 0o777,0o600)
            self.assertEqual(status.read_text(),'last success')

    def test_unknown_exception_text_and_diagnostic_write_errors_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); remote_sync.phase('prepare-profile',root=root,scope='personal')
            try: raise ValueError('private credential/provider body')
            except ValueError as error: path=remote_sync.failure_receipt(error)
            self.assertNotIn('private credential/provider body',path.read_text())
            def fail(): remote_sync.phase('fetch-catalog',root=root);raise ValueError('sensitive')
            with patch.object(remote_sync,'main',side_effect=fail),patch.object(remote_sync,'failure_receipt',side_effect=OSError('disk full')),contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(remote_sync.run(),1)
            self.assertNotIn('sensitive',stderr.getvalue())
            self.assertIn('ValueError',stderr.getvalue())


class NativePiTests(unittest.TestCase):
    def test_generated_pi_override_follows_authenticated_label_but_custom_name_stays(self):
        route='work/litellm/gpt-5.6-luna'
        document={'providers':{'cliproxyapi':{'modelOverrides':{route:{'name':'W/LL · 5.6 Luna','maxTokens':100}}}}}
        cache={'models':[{'id':route,'name':'W/LL · 6 Luna · via 5.6 Luna'}]}
        result=remote_sync.catalogs.pi_native_update(document,cache,'work','https://nas.example')
        self.assertEqual(result['providers']['cliproxyapi']['modelOverrides'][route],{'maxTokens':100})
        self.assertEqual(document['providers']['cliproxyapi']['modelOverrides'][route]['name'],'W/LL · 5.6 Luna')
        document['providers']['cliproxyapi']['modelOverrides'][route]['name']='My custom name'
        result=remote_sync.catalogs.pi_native_update(document,cache,'work','https://nas.example')
        self.assertEqual(result['providers']['cliproxyapi']['modelOverrides'][route]['name'],'My custom name')

    def test_generated_pi_override_does_not_mask_later_backend_changes(self):
        route='work/litellm/gpt-5.6-luna'
        previous='W/LL · 6 Luna · via 5.6 Luna'
        document={'providers':{'cliproxyapi':{'models':[{'id':route,'name':previous}],
                  'modelOverrides':{route:{'name':previous,'maxTokens':100}}}}}
        for name in ('W/LL · 6.1 Sol · via 5.6 Luna','W/LL · 6 Luna · via 5.6 Luna'):
            cache={'models':[{'id':route,'name':name}]}
            document=remote_sync.catalogs.pi_native_update(document,cache,'work','https://nas.example')
            provider=document['providers']['cliproxyapi']
            self.assertEqual(provider['models'][0]['name'],name)
            self.assertEqual(provider['modelOverrides'][route],{'maxTokens':100})

    def test_catalog_only_registers_scope_and_retains_saved_ids_and_overrides(self):
        document = {'providers': {'cliproxyapi': {'modelOverrides': {'personal/saved': {'name': 'mine'}}}}}
        models = [{'id': 'personal/saved', 'name': 'saved', 'reasoning': True, 'thinkingLevelMap': {'high':'high'}, 'contextWindow': 4000},
                  {'id': 'work/litellm/x'}, {'id': 'commandcode/ambiguous'}]
        result = remote_sync.catalogs.pi_native_update(document, {'models':models}, 'personal', 'https://nas.example')
        provider = result['providers']['cliproxyapi']
        self.assertEqual([m['id'] for m in provider['models']], ['personal/saved'])
        self.assertEqual(provider['models'][0]['thinkingLevelMap'], {'high':'high'})
        self.assertEqual(provider['modelOverrides'], document['providers']['cliproxyapi']['modelOverrides'])
        self.assertEqual(provider['apiKey'], '${CPA_API_KEY}')
        self.assertEqual(provider['api'], 'openai-responses')
        with self.assertRaises(ValueError):
            remote_sync.catalogs.pi_native_update(document, {'models':[]}, 'work', 'https://nas.example')


class RemoteSyncTests(unittest.TestCase):
    def test_handy_export_contains_only_scoped_ids_and_no_prompt_material(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'personal/catalogs/handy-models.json';path.parent.mkdir(parents=True)
            path.write_text('{}')
            snapshot={'models':[{'slug':'personal/codex-oauth/gpt-6-luna','base_instructions':'private prompt'}]}
            changes,_=remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',False)
            exported=json.loads(changes[path]['after'])
            self.assertEqual(exported['data'],[{'id':'personal/codex-oauth/gpt-6-luna','object':'model','owned_by':'cpa-personal'}])
            self.assertNotIn('private prompt',changes[path]['after'].decode())
            snapshot['models'].append({'slug':'work/foreign'})
            with self.assertRaises(ValueError):remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',False)

    def test_t3_claude_refresh_is_scoped_guarded_and_preserves_custom_options(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'settings.json'
            route='work/litellm/opus'
            instance={'driver':'claudeAgent','config':{'binaryPath':str(root/'work/bin/claude'),'customModels':[{'slug':route,'name':'old','capabilities':{'custom':'preserve'}}]}}
            original={'providerInstances':{'claude_work':instance,'unrelated':{'keep':True}}}
            path.write_text(json.dumps(original))
            snapshots={'work':{'scope':'work','models':[{'slug':route,'canonical_model_id':'gpt-6-luna'},{'slug':'work/litellm/new'}]}}
            result=json.loads(remote_sync.t3_claude_targets(root,snapshots,path)[path]['after'])
            models=result['providerInstances']['claude_work']['config']['customModels']
            self.assertEqual(models[0]['capabilities'],{'custom':'preserve'})
            self.assertEqual(models[0]['name'],'W/LL · 6 Luna · via Opus')
            self.assertEqual(models[1]['slug'],'work/litellm/new')
            self.assertEqual(result['providerInstances']['unrelated'],{'keep':True})
            snapshots['work']['models'][0]['slug']='personal/foreign'
            with self.assertRaises(ValueError):remote_sync.t3_claude_targets(root,snapshots,path)
            snapshots['work']['models']=[];instance['config']['binaryPath']='/unmanaged/claude';path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):remote_sync.t3_claude_targets(root,snapshots,path)

    def test_litellm_label_uses_backend_identity_without_rewriting_route_or_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'work/catalogs/codex-catalog.json';path.parent.mkdir(parents=True)
            route='work/litellm/gpt-5.6-luna'
            path.write_text(json.dumps({'models':[{'slug':route,'base_instructions':'saved native prompt'}]}))
            snapshot={'models':[{'slug':route,'canonical_model_id':'gpt-6-luna'}]}
            changes,_=remote_sync.prepare_profile(root,'work',snapshot,'https://nas.example',False)
            model=json.loads(changes[path]['after'])['models'][0]
            self.assertEqual(model['slug'],route)
            self.assertEqual(model['display_name'],'W/LL · 6 Luna · via 5.6 Luna')
            self.assertEqual(model['base_instructions'],'saved native prompt')
            self.assertEqual(remote_sync.model_label('work/litellm/qwen3-coder','qwen/qwen3-coder'),'W/LL · Qwen 3 Coder')

    def test_origins_reject_plaintext_remote_and_credential_redirect_inputs(self):
        self.assertEqual(remote_sync.origin('https://nas.example/'), 'https://nas.example')
        self.assertEqual(remote_sync.origin('http://127.0.0.1:8317'), 'http://127.0.0.1:8317')
        for value in ('http://nas.example', 'https://key@nas.example', 'https://nas.example/path', 'https://nas.example?key=x'):
            with self.assertRaises(ValueError): remote_sync.origin(value)

    def test_endpoint_update_preserves_provider_identity_and_native_default(self):
        before = 'model_provider = "openai"\n[model_providers.cpa-gui]\nname = "Old threads"\nbase_url = "http://127.0.0.1:8317/v1"\nwire_api = "responses"\n[projects.foo]\ntrust_level = "trusted"\n'
        after = remote_sync.codex_endpoint(before, 'https://nas.example')
        self.assertEqual(after, before.replace('http://127.0.0.1:8317/v1', 'https://nas.example/v1'))
        self.assertEqual(remote_sync.codex_endpoint(after, 'https://nas.example'), after)

    def test_reconciliation_preserves_saved_prompts_and_missing_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'work/catalogs/codex-catalog.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'models':[{'slug':'work/litellm/m','base_instructions':'trusted','context_window':1000,'default_reasoning_level':'high'},{'slug':'work/litellm/old','base_instructions':'saved'}]}))
            snapshot = {'models':[{'slug':'work/litellm/m','context_window':2000,'supported_reasoning_levels':[],'default_reasoning_level':None,'base_instructions':'untrusted'}]}
            changes, pending = remote_sync.prepare_profile(root,'work',snapshot,'https://nas.example',False)
            updated=json.loads(changes[path]['after'])
            self.assertEqual(updated['models'][0]['base_instructions'],'trusted')
            self.assertEqual(updated['models'][0]['context_window'],2000)
            self.assertNotIn('default_reasoning_level',updated['models'][0])
            self.assertEqual(updated['models'][1]['slug'],'work/litellm/old')
            self.assertEqual(json.loads(path.read_text())['models'][0]['context_window'],1000)
            self.assertEqual(pending,[])

    def test_new_prompt_template_requires_explicit_gateway_trust(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'personal/catalogs/codex-catalog.json';path.parent.mkdir(parents=True);path.write_text('{"models":[]}')
            snapshot={'models':[{'slug':'personal/codex-oauth/new','canonical_model_id':'native','context_window':2000}], 'templates':[{'slug':'native','base_instructions':'operator trusted native template'}]}
            changes,pending=remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',False)
            self.assertEqual(pending,['personal/codex-oauth/new'])
            changes,pending=remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',True)
            self.assertEqual(pending,[])
            self.assertEqual(json.loads(changes[path]['after'])['models'][0]['base_instructions'],'operator trusted native template')

    def test_endpoint_files_apply_in_same_validated_transaction(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();path=root/'personal/codex/config.toml';path.parent.mkdir(parents=True)
            before='[model_providers.cpa-personal]\nbase_url="http://127.0.0.1:8317/v1"\n';path.write_text(before)
            changes,_=remote_sync.prepare_profile(root,'personal',{'models':[{'slug':'personal/test/model'}]},'https://nas.example',False)
            with self.assertRaises(ValueError):remote_sync.catalogs.validate_targets(changes,root)
            remote_sync.catalogs.apply_changes(changes,root,root/'backups',extra_paths={path})
            self.assertIn('https://nas.example/v1',path.read_text())

    def test_account_false_capabilities_replace_saved_true_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();p=root/'personal/catalogs/codex-catalog.json';p.parent.mkdir(parents=True)
            fields=('supports_parallel_tool_calls','supports_image_detail_original','support_verbosity')
            model=dict(slug='personal/codex-oauth/example',base_instructions='trusted',**{x:True for x in fields})
            p.write_text(json.dumps({'models':[model]}))
            snapshot={'models':[dict(slug=model['slug'],**{x:False for x in fields})]}
            changes,_=remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',False)
            updated=json.loads(changes[p]['after'])['models'][0]
            self.assertTrue(all(updated[x] is False for x in fields))

    def test_installed_opencode2_selects_enabled_only_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'personal/config/opencode/opencode.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'provider':{'cpa-personal':{'models':{}}}}))
            route='personal/commandcode/deepseek-v4.1-flash'
            snapshot={'models':[{'slug':route,'supported_reasoning_levels':[{'effort':'high'}]}]}
            with patch.object(remote_sync.catalogs,'opencode_major_version',return_value=2) as version:
                changes,_=remote_sync.prepare_profile(root,'personal',snapshot,'https://nas.example',False,{'opencode':'/stock/opencode'})
            version.assert_called_once_with('/stock/opencode')
            variants=json.loads(changes[path]['after'])['provider']['cpa-personal']['models'][route]['variants']
            self.assertEqual(variants,{'high':{'reasoningEffort':'high'}})
