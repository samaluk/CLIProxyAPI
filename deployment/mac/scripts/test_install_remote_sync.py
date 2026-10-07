import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import install_remote_sync as installer
import launch_harness


class InstallTests(unittest.TestCase):
    def test_native_symlink_is_resolved_before_public_wrapper_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);native=home/'.local/share/claude/versions/native';native.parent.mkdir(parents=True)
            native.write_text('native executable')
            entry=home/'.config/cpa/bin/claude';entry.parent.mkdir(parents=True);entry.symlink_to(native)
            with patch.object(Path,'home',return_value=home):
                result=installer.native_entrypoints({'claude':str(entry)},True)
                self.assertEqual(result,{'claude':str(native.resolve())})
                entry.unlink();entry.write_text('wrapper')
                with self.assertRaises(ValueError):installer.native_entrypoints({'claude':str(entry)},True)
            self.assertEqual(native.read_text(),'native executable')

    def test_proxy_only_install_has_no_prompt_and_preserves_work_inheritance(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder).resolve();root=self.fixture(home)
            path=root/'personal/codex/config.toml';path.parent.mkdir(parents=True)
            path.write_text('model="personal/codex-oauth/fixture"\n[model_providers.cpa-personal]\nbase_url="https://old.invalid/v1"\nrequires_openai_auth=false\n')
            path=root/'personal/catalogs/codex-catalog.json';path.parent.mkdir(parents=True)
            path.write_text('{"models":[{"slug":"personal/codex-oauth/fixture"}]}')
            with patch.object(Path,'home',return_value=home):
                installer.install(root,'https://nas.example',{'codex':sys.executable},False,proxy_only=True)
                installer.install(root,'https://nas.example',{},False)
            settings=json.loads((root/'gateway.json').read_text())
            self.assertFalse(settings['pi_selector'])
            self.assertTrue(settings['authoritative_catalog'])
            self.assertEqual(settings['entrypoint_mode'],'personal_default')
            wrapper=(home/'.config/cpa/bin/codex').read_text()
            self.assertIn('${AGENT_PROFILE:-personal}',wrapper)
            self.assertNotIn('select-pi',wrapper)
            self.assertEqual(json.loads((home/'.codex/auth.json').read_text()),{'OPENAI_API_KEY':'fixture-downstream-key'})
            import tomllib
            config=tomllib.loads((root/'personal/codex/config.toml').read_text())
            self.assertTrue(config['model_providers']['cpa-personal']['requires_openai_auth'])
            self.assertEqual(config['agents']['max_depth'],2)

    def test_pi_selector_cannot_be_its_own_native_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            entry = home/'.local/bin/pi'; entry.parent.mkdir(parents=True)
            entry.write_text('#!/bin/sh\nexit 0\n'); entry.chmod(0o700)
            with patch.object(Path, 'home', return_value=home):
                with self.assertRaisesRegex(ValueError, 'native Pi binary'):
                    installer.install(root, 'https://nas.example', {'pi': str(entry)}, False, True)
            self.assertFalse((root/'gateway.json').exists())

    def test_proxy_pi_catalog_sync_does_not_require_t3_instances(self):
        import remote_sync
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            profile = root / 'personal/pi'; profile.mkdir()
            (profile/'settings.json').write_text('{"packages":[]}')
            (profile/'models.json').write_text('{"providers":{"cliproxyapi":{"models":[]}}}')
            (profile/'cliproxyapi-models.json').write_text('{"models":[]}')
            with patch.object(Path, 'home', return_value=home):
                installer.install(root, 'https://nas.example', {'pi':sys.executable}, False, proxy_only=True)
                installer.install(root, 'https://nas.example', {}, False)
            settings = json.loads((root/'gateway.json').read_text())
            self.assertFalse(settings.get('t3_pi_profiles', False))
            self.assertFalse((home/'.t3/userdata/settings.json').exists())
            snapshot = {'models':[{'slug':'personal/codex-oauth/fixture'}]}
            changes, _ = remote_sync.prepare_profile(root, 'personal', snapshot, 'https://nas.example',
                False, settings['binaries'], settings.get('pi_native_catalog') is True, True)
            native = json.loads(changes[profile/'models.json']['after'])
            self.assertEqual([m['id'] for m in native['providers']['cliproxyapi']['models']],
                             ['personal/codex-oauth/fixture'])

    def test_pi_selector_survives_reinstallation(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            with patch.object(Path, 'home', return_value=home):
                installer.install(root, 'https://nas.example', {'pi': sys.executable}, False, True)
                installer.install(root, 'https://nas.example', {}, False)
            self.assertTrue(json.loads((root/'gateway.json').read_text())['pi_selector'])
            self.assertIn('select-pi.py', (home/'.local/bin/pi').read_text())

    def test_pi_connection_cannot_inherit_the_other_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(Path(folder).resolve())
            (root/'gateway.json').write_text(json.dumps({'endpoint':'https://nas.example','binaries':{'pi':sys.executable}}))
            with patch.object(launch_harness,'ROOT',root), patch.object(sys,'argv',['launch','personal','pi']), patch.dict(os.environ,{'CLIPROXYAPI_BASE_URL':'https://wrong.example','CLIPROXYAPI_API_KEY':'wrong-key','CLIPROXYAPI_PROVIDER_ID':'wrong-provider'}), patch.object(os,'execve') as execute:
                launch_harness.main()
            env = execute.call_args.args[2]
            self.assertEqual(env['CLIPROXYAPI_BASE_URL'], 'https://nas.example')
            self.assertEqual(env['CLIPROXYAPI_API_KEY'], 'fixture-downstream-key')
            self.assertEqual(env['PI_CODING_AGENT_DIR'], str(root/'personal/pi'))
            self.assertNotIn('CLIPROXYAPI_PROVIDER_ID', env)
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
            self.assertNotIn('ANTHROPIC_BASE_URL', env)

    def test_t3_pi_install_preserves_customizations_and_guards_concurrent_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            settings_path = home / '.t3/userdata/settings.json'
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(json.dumps({'providerInstances': {'pi': {'driver':'pi','enabled':True},
                'pi_work': {'driver':'pi','displayName':'my work','enabled':False,
                            'config':{'binaryPath':str(root/'work/bin/pi'),'launchArgs':'--no-skills'}}},
                'other': 'unchanged'}))
            for scope in ('personal', 'work'):
                profile = root/scope
                (profile/'keys').mkdir(parents=True, exist_ok=True)
                (profile/'keys/downstream.key').write_text('fixture-key')
                (profile/'pi').mkdir()
                (profile/'pi/models.json').write_text('{"providers":{"cliproxyapi":{}}}')
                (profile/'pi/cliproxyapi-models.json').write_text(json.dumps({'models':[{'id':scope+'/saved'}]}))
                (profile/'pi/settings.json').write_text(json.dumps({'defaultModel':scope+'/saved',
                    'packages':['npm:@router-for-me/pi-cliproxyapi-provider@1.4.20','my-other-extension']}))
            def snapshot(endpoint, key, scope): return {'models':[{'slug':scope+'/saved'}]}
            def mapper(profile, live, binary): return ([{'id':next(iter(live))}], 'fixture', [])
            with patch.object(Path,'home',return_value=home), patch.object(installer.remote_sync,'fetch',side_effect=snapshot), patch.object(installer.catalogs,'stock_pi_map',side_effect=mapper):
                targets = installer.t3_pi_targets(root,'https://nas.example',{'pi':sys.executable})
            updated = json.loads(targets[settings_path][0])
            self.assertFalse(updated['providerInstances']['pi']['enabled'])
            self.assertTrue(updated['providerInstances']['pi_personal']['enabled'])
            self.assertEqual(updated['providerInstances']['pi_work']['displayName'], 'my work')
            self.assertFalse(updated['providerInstances']['pi_work']['enabled'])
            self.assertEqual(updated['other'], 'unchanged')
            config = json.loads(targets[root/'work/pi/settings.json'][0])
            self.assertEqual(config['packages'], ['my-other-extension'])
            self.assertEqual(config['defaultModel'], 'work/saved')
            settings_path.write_text('{"concurrent":"edit"}')
            with self.assertRaisesRegex(ValueError, 'ownership check'):
                installer.write_transaction(targets, root/'conflicting-install')
            self.assertEqual(json.loads(settings_path.read_text()), {'concurrent':'edit'})

    def fixture(self, home):
        root = home / 'profiles'
        path = root / 'personal/keys/downstream.key'
        path.parent.mkdir(parents=True)
        path.write_text('fixture-downstream-key')
        return root

    def test_reinstall_preserves_other_binaries_and_empty_options(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            with patch.object(Path, 'home', return_value=home):
                installer.install(root, 'https://nas.example', {'codex': sys.executable, 'pi': sys.executable}, False)
                installer.install(root, 'https://nas.example', {'codex': sys.executable}, False)
                installer.install(root, 'https://nas.example', {}, False)
            self.assertEqual(set(json.loads((root/'gateway.json').read_text())['binaries']), {'codex','pi'})

    def test_failed_write_restores_every_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve(); root = self.fixture(home)
            old=root/'gateway.json';old.write_text('{"endpoint":"https://old.example"}')
            launcher=root/'launch-harness.py';launcher.write_text('old launcher')
            real=home/'refresh';real.write_text('old refresh')
            link=home/'.local/bin/cpa-catalog-refresh';link.parent.mkdir(parents=True);link.symlink_to(real)
            count=0; atomic=installer.catalogs.atomic_write
            def fail_once(*args):
                nonlocal count
                count+=1
                if count==7:raise OSError('injected disk error')
                return atomic(*args)
            with patch.object(Path,'home',return_value=home), patch.object(installer.catalogs,'atomic_write',side_effect=fail_once):
                with self.assertRaises(OSError):installer.install(root,'https://new.example',{'codex':sys.executable},False)
            self.assertEqual(json.loads(old.read_text())['endpoint'],'https://old.example')
            self.assertEqual(launcher.read_text(),'old launcher')
            self.assertTrue(link.is_symlink())
            self.assertFalse((root/'sync-runtime/remote_sync.py').exists())

    def test_v2_retirement_only_matches_our_unchanged_v1_loader(self):
        legacy = b"import { preservePromptIdentity } from './identity.mjs';\nexport default async function PromptIdentity() {\n  return {\n    'experimental.chat.system.transform': async ({ model }, output) => preservePromptIdentity(model, output.system),\n  };\n}\n"
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder).resolve();root=self.fixture(home)
            module=home/'opencode-prompt-identity/plugin.mjs';module.parent.mkdir();module.write_bytes(legacy)
            identity=module.parent/'identity.mjs';identity.write_bytes(b'known helper')
            paths=[home/'.config/opencode/plugins/cpa-prompt-identity.js',*[root/scope/'config/opencode/plugins/cpa-prompt-identity.js' for scope in ('personal','work')]]
            for path in paths:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(f'export {{ default }} from "{module.as_uri()}";\n')
            binary=home/'opencode';binary.write_text('fixture');binary.chmod(0o700)
            with patch.object(Path,'home',return_value=home),patch.object(installer.shutil,'which',return_value=str(binary)),patch.dict(installer.LEGACY_PROMPT_FILES,{'plugin.mjs':hashlib.sha256(legacy).hexdigest(),'identity.mjs':hashlib.sha256(b'known helper').hexdigest()},clear=True):
                self.assertEqual(set(installer.legacy_prompt_targets(root,str(binary),2)),set(paths))
                self.assertEqual(installer.legacy_prompt_targets(root,str(binary),1),{})
                targets=installer.legacy_prompt_targets(root,str(binary),2)
                paths[0].write_text('// concurrent user edit\n'+paths[0].read_text())
                with self.assertRaisesRegex(ValueError,'ownership check'):
                    installer.write_transaction(targets,home/'race-backup')
                self.assertTrue(all(path.exists() for path in paths))
                paths[0].write_bytes(targets[paths[0]][2])

                paths[0].write_text('// user customization\n'+paths[0].read_text())
                self.assertEqual(set(installer.legacy_prompt_targets(root,str(binary),2)),set(paths[1:]))
                identity.write_bytes(b'user changed helper')
                self.assertEqual(installer.legacy_prompt_targets(root,str(binary),2),{})
                identity.write_bytes(b'known helper')
                paths[0].write_bytes(b'\xff')
                self.assertEqual(set(installer.legacy_prompt_targets(root,str(binary),2)),set(paths[1:]))
                module.write_bytes(legacy+b'// changed\n')
                self.assertEqual(installer.legacy_prompt_targets(root,str(binary),2),{})

    def test_retired_plugin_is_archived_and_restored_on_activation_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();p=root/'plugin.js';p.write_bytes(b'owned loader');p.chmod(0o640)
            installer.write_transaction({p:(None,0o600)},root/'backup')
            self.assertFalse(p.exists());self.assertEqual((root/'backup/0').read_bytes(),b'owned loader')
            p.write_bytes(b'owned loader');p.chmod(0o640)
            def fail():raise RuntimeError('fixture activation failure')
            with self.assertRaises(RuntimeError):installer.write_transaction({p:(None,0o600)},root/'backup2',fail)
            self.assertEqual(p.read_bytes(),b'owned loader');self.assertEqual(p.stat().st_mode&0o777,0o640)

    def test_scheduler_failure_restores_files_and_invokes_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();p=root/'existing';p.write_bytes(b'old');recovered=[]
            def activate():raise RuntimeError('scheduler failure')
            with self.assertRaises(RuntimeError):
                installer.write_transaction({p:(b'new',0o600)},root/'backup',activate,lambda:recovered.append(True))
            self.assertEqual(p.read_bytes(),b'old');self.assertEqual(recovered,[True])

    def test_claude_unknown_limits_do_not_inherit_previous_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.fixture(Path(folder).resolve())
            (root/'gateway.json').write_text(json.dumps({'endpoint':'https://nas.example','binaries':{'claude':sys.executable}}))
            p=root/'personal/catalogs/codex-catalog.json';p.parent.mkdir(parents=True);p.write_text('{"models":[]}')
            with patch.object(launch_harness,'ROOT',root), patch.object(sys,'argv',['launch','personal','claude']), patch.dict(os.environ,{'CLAUDE_CODE_MAX_CONTEXT_TOKENS':'999999','CLAUDE_CODE_MAX_OUTPUT_TOKENS':'77777'}), patch.object(os,'execve') as execute:
                launch_harness.main()
            env=execute.call_args.args[2]
            self.assertNotIn('CLAUDE_CODE_MAX_CONTEXT_TOKENS',env)
            self.assertNotIn('CLAUDE_CODE_MAX_OUTPUT_TOKENS',env)
