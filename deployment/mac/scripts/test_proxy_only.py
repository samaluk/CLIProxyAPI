import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import launch_harness
import proxy_only
import remote_sync


class PolicyTests(unittest.TestCase):
    def test_default_homes_clear_upstream_auth_and_keep_cursor_only_in_personal(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); root = home/'profiles'; profile = root/'personal'
            files = {
                'keys/downstream.key': 'fixture-gateway',
                'codex/config.toml': 'model = "personal/codex-oauth/gpt-6-astra"\n',
                'catalogs/codex-catalog.json': json.dumps({'models':[{'slug':'personal/codex-oauth/gpt-6-astra'}]}),
                'pi/settings.json': json.dumps({'defaultProvider':'cliproxyapi','defaultModel':'personal/codex-oauth/gpt-6-astra',
                                               'enabledModels':['cliproxyapi/personal/**','cursor/**'],'extensions':['/cursor-sdk/index.js']}),
                'pi/models.json': json.dumps({'providers':{'cliproxyapi':{'models':[{'id':'personal/codex-oauth/gpt-6-astra'}]}}}),
            }
            for name, raw in files.items():
                path=profile/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_text(raw)
            path=home/'.codex/auth.json';path.parent.mkdir();path.write_text('{"tokens":{"access_token":"direct"}}')
            path=home/'.pi/agent/auth.json';path.parent.mkdir(parents=True);path.write_text('{"openai-codex":{"type":"oauth"},"cursor":{"type":"api_key","key":"cursor-fixture"}}')
            settings={'endpoint':'https://nas.example','binaries':{'codex':'/codex','pi':'/pi'},'pi_cursor_personal':True}
            targets=proxy_only.default_home_targets(root,settings,home=home)
            self.assertEqual(json.loads(targets[home/'.codex/auth.json'][0]),{'OPENAI_API_KEY':'fixture-gateway'})
            self.assertEqual(list(json.loads(targets[home/'.pi/agent/auth.json'][0])),['cursor'])
            models=json.loads(targets[home/'.pi/agent/models.json'][0])
            self.assertEqual(list(models['providers']),['cliproxyapi'])
            self.assertEqual(models['providers']['cliproxyapi']['apiKey'],'fixture-gateway')
            self.assertEqual(json.loads(targets[home/'.pi/agent/settings.json'][0])['extensions'],['/cursor-sdk/index.js'])
            self.assertIn('tokens',json.loads((home/'.codex/auth.json').read_text()))

    def test_native_codex_cutover_preserves_history_settings_and_only_uses_gateway_auth(self):
        raw = ('model = "gpt-6-astra"\nnotify = ["my-notification"]\n'
               '[agents]\nmax_threads = 4\ndefault_subagent_model = "gpt-6-sol"\n'
               '[projects."/my/project"]\ntrust_level = "trusted"\n'
               '[model_providers.old]\nbase_url = "https://old.invalid"\n')
        updated = proxy_only.provider_config(raw, 'personal', 'https://nas.example',
                                            'fixture-gateway-key', Path('/managed/catalog.json'),
                                            'personal/codex-oauth/gpt-6-astra')
        document = tomllib.loads(updated.decode())
        self.assertEqual(document['model_provider'], 'cpa-personal')
        self.assertEqual(document['forced_login_method'], 'api')
        self.assertEqual(document['cli_auth_credentials_store'], 'file')
        self.assertEqual(document['notify'], ['my-notification'])
        self.assertEqual(document['agents']['max_threads'], 4)
        self.assertEqual(document['agents']['default_subagent_model'], document['model'])
        self.assertEqual(list(document['model_providers']), ['cpa-personal'])
        self.assertTrue(document['model_providers']['cpa-personal']['requires_openai_auth'])
        self.assertNotIn('experimental_bearer_token', document['model_providers']['cpa-personal'])
        self.assertEqual(proxy_only.provider_config(updated.decode(), 'personal', 'https://nas.example',
                         'fixture-gateway-key', Path('/managed/catalog.json'), document['model']), updated)

    def test_authoritative_refresh_removes_missing_and_hidden_models_across_client_schemas(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            keep, removed, hidden = ('work/litellm/' + x for x in ('keep', 'removed', 'hidden'))
            files = {
                'catalogs/codex-catalog.json': {'models': [{'slug': x, 'base_instructions': 'trusted'} for x in (keep, removed, hidden)]},
                'config/opencode/opencode.json': {'provider': {'cpa-work': {'models': {x: {} for x in (keep, removed, hidden)}}, 'native': {} }},
                'pi/cliproxyapi-models.json': {'models': [{'id': x} for x in (keep, removed, hidden)]},
                'pi/models.json': {'providers': {'cliproxyapi': {}}},
            }
            for name, value in files.items():
                path = root / 'work' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            snapshot = {'models': [{'slug': keep}, {'slug': hidden, 'visibility': 'hide'}]}
            with patch.object(remote_sync.catalogs, 'opencode_major_version', return_value=2):
                changes, _ = remote_sync.prepare_profile(root, 'work', snapshot, 'https://nas.example', False,
                                                        pi_native=True, authoritative=True)
            codex = json.loads(changes[root/'work/catalogs/codex-catalog.json']['after'])
            self.assertEqual([m['slug'] for m in codex['models']], [keep])
            self.assertEqual(codex['models'][0]['base_instructions'], 'trusted')
            opencode = json.loads(changes[root/'work/config/opencode/opencode.json']['after'])
            self.assertEqual(list(opencode['provider']), ['cpa-work'])
            self.assertEqual(list(opencode['provider']['cpa-work']['models']), [keep])
            pi = json.loads(changes[root/'work/pi/models.json']['after'])
            self.assertEqual([m['id'] for m in pi['providers']['cliproxyapi']['models']], [keep])
            self.assertEqual(len(json.loads((root/'work/catalogs/codex-catalog.json').read_text())['models']), 3)

    def test_native_usage_preserves_personal_logins_and_keeps_inference_on_gateway(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); root = home/'profiles'
            native = b'{"tokens":{"access_token":"native-fixture","refresh_token":"refresh-fixture"}}'
            for scope in ('personal','work'):
                profile = root/scope
                for relative in ('keys','codex','catalogs'): (profile/relative).mkdir(parents=True)
                (profile/'keys/downstream.key').write_text('gateway-'+scope)
                (profile/'codex/auth.json').write_bytes(native)
                (profile/'codex/config.toml').write_text('model="'+scope+'/fixture"\nforced_login_method="api"\n[model_providers.cpa-'+scope+']\nbase_url="https://nas.example/v1"\nrequires_openai_auth=true\n')
                (profile/'catalogs/codex-catalog.json').write_text(json.dumps({'models':[{'slug':scope+'/fixture'}]}))
            (home/'.codex').mkdir(); (home/'.codex/auth.json').write_bytes(native)
            (home/'.codex/config.toml').write_text('forced_login_method="api"\nnotify=["keep"]\n')
            settings = {'endpoint':'https://nas.example','binaries':{'codex':'/native/codex'},'codex_native_usage':True}
            with patch.object(Path,'home',return_value=home):
                scoped = proxy_only.scoped_auth_targets(root,settings)
            self.assertNotIn(root/'personal/codex/auth.json',scoped)
            self.assertEqual(json.loads(scoped[root/'work/codex/auth.json'][0]),{'OPENAI_API_KEY':'gateway-work'})
            prepared = {p:{'after':target[0]} for p,target in scoped.items()}
            default = proxy_only.default_home_targets(root,settings,prepared,home)
            self.assertNotIn(home/'.codex/auth.json',default)
            for path,data in [(root/'personal/codex/config.toml',scoped[root/'personal/codex/config.toml'][0]),
                              (home/'.codex/config.toml',default[home/'.codex/config.toml'][0])]:
                config=tomllib.loads(data.decode())
                self.assertNotIn('forced_login_method',config)
                provider=config['model_providers']['cpa-personal']
                self.assertEqual(provider['base_url'],'https://nas.example/v1')
                self.assertEqual(provider['experimental_bearer_token'],'gateway-personal')
                self.assertTrue(provider['requires_openai_auth'])
            self.assertEqual((home/'.codex/auth.json').read_bytes(),native)
            self.assertEqual((root/'personal/codex/auth.json').read_bytes(),native)

    def test_native_usage_login_exception_is_personal_codex_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for scope in ('personal','work'):
                key=root/scope/'keys/downstream.key';key.parent.mkdir(parents=True);key.write_text('fixture-'+scope)
            (root/'gateway.json').write_text(json.dumps({'endpoint':'https://nas.example','proxy_only':True,
                'codex_native_usage':True,'binaries':{'codex':'/native/codex','pi':'/native/pi'}}))
            for scope,harness in [('personal','codex'),('work','codex'),('personal','pi')]:
                with patch.object(launch_harness,'ROOT',root), patch('sys.argv',['launch',scope,harness,'login']), \
                     patch.object(os,'execve') as execute:
                    if (scope,harness)==('personal','codex'):
                        launch_harness.main()
                        self.assertEqual(execute.call_args.args[2]['CPA_API_KEY'],'fixture-personal')
                    else:
                        with self.assertRaises(SystemExit):launch_harness.main()
                        execute.assert_not_called()

    def test_claude_menu_removes_saved_models_but_retains_live_custom_options(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root/'settings.json'
            keep, removed = 'work/litellm/keep', 'work/litellm/removed'
            path.write_text(json.dumps({'providerInstances': {'claude_work': {'driver': 'claudeAgent',
                'config': {'binaryPath': str(root/'work/bin/claude'), 'customModels': [
                    {'slug': keep, 'capabilities': {'custom': True}}, removed]}}}}))
            targets = remote_sync.t3_claude_targets(root, {'work': {'scope': 'work', 'models': [{'slug': keep}]}}, path, True)
            models = json.loads(targets[path.resolve()]['after'])['providerInstances']['claude_work']['config']['customModels']
            self.assertEqual([m['slug'] for m in models], [keep])
            self.assertEqual(models[0]['capabilities'], {'custom': True})

    def test_proxy_launch_strips_provider_credentials_and_limits_cursor_to_personal_pi(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = {'endpoint': 'https://nas.example', 'proxy_only': True, 'pi_cursor_personal': True,
                        'binaries': {'pi': '/native/pi', 'codex': '/native/codex'}}
            (root/'gateway.json').write_text(json.dumps(settings))
            for scope in ('personal', 'work'):
                key = root/scope/'keys/downstream.key'; key.parent.mkdir(parents=True)
                key.write_text('fixture-' + scope)
            inputs = {'OPENROUTER_API_KEY': 'direct', 'OPENCODE_API_KEY': 'direct', 'OPENAI_API_KEY': 'direct',
                      'CURSOR_API_KEY': 'exception', 'GITHUB_TOKEN': 'tool-credential'}
            for scope, harness in (('personal','pi'), ('work','pi'), ('personal','codex')):
                with patch.object(launch_harness, 'ROOT', root), patch('sys.argv', ['launch', scope, harness]), \
                     patch.dict(os.environ, inputs, clear=True), patch.object(os, 'execve') as execute:
                    launch_harness.main()
                env = execute.call_args.args[2]
                self.assertEqual(env['CPA_API_KEY'], 'fixture-' + scope)
                self.assertNotIn('OPENROUTER_API_KEY', env)
                self.assertNotIn('OPENCODE_API_KEY', env)
                self.assertNotIn('OPENAI_API_KEY', env)
                self.assertEqual('CURSOR_API_KEY' in env, scope == 'personal' and harness == 'pi')
                self.assertEqual(env['GITHUB_TOKEN'], 'tool-credential')

    def test_proxy_profile_rejects_native_login(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); key = root/'personal/keys/downstream.key'; key.parent.mkdir(parents=True)
            key.write_text('fixture')
            (root/'gateway.json').write_text(json.dumps({'endpoint':'https://nas.example','proxy_only':True}))
            with patch.object(launch_harness,'ROOT',root), patch('sys.argv',['launch','personal','codex','login']), \
                 patch.object(os,'execve') as execute, self.assertRaises(SystemExit):
                launch_harness.main()
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
