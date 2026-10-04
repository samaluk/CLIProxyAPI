import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import remote_sync


class RemoteSyncTests(unittest.TestCase):
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
