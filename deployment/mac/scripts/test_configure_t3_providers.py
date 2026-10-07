import json
from pathlib import Path
import tempfile
import unittest

import configure_t3_providers as configure


class T3ProviderTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)/'profiles'; root.mkdir()
        for scope in ('personal', 'work'):
            profile = root/scope
            (profile/'keys').mkdir(parents=True)
            (profile/'keys/downstream.key').write_text('fixture')
            (profile/'bin').mkdir()
            for name in ('codex', 'claude', 'opencode', 'pi'):
                binary = profile/'bin'/name; binary.write_text('#!/bin/sh\n'); binary.chmod(0o700)
        (root/'gateway.json').write_text(json.dumps({'proxy_only':True, 'binaries':{
            name:'/native/'+name for name in ('codex', 'claude', 'opencode', 'pi')}}))
        settings = Path(folder)/'settings.json'
        settings.write_text(json.dumps({'providerInstances':{'claudeAgent':{'driver':'claudeAgent',
            'enabled':False,'config':{'binaryPath':'claude','launchArgs':'keep'}}},'other':'keep'}))
        return root, settings

    def test_registers_scopes_preserves_native_auth_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root, settings = self.fixture(folder)
            document = json.loads(settings.read_text())
            document['providerInstances']['antigravity_work'] = {'driver':'antigravity',
                'config':{'apiKey':'native-fixture','authMethod':'agent-platform','gcpProject':'keep',
                          'binaryPath':'/installed/by/t3'}}
            settings.write_text(json.dumps(document))
            planned = configure.targets(root, settings, Path('/native/cursor'), True)
            result = json.loads(planned[settings][0])
            self.assertEqual(result['other'], 'keep')
            self.assertNotIn('pi', result['providers'])
            self.assertEqual(result['providerInstances']['claudeAgent']['config']['launchArgs'], 'keep')
            for scope in ('personal', 'work'):
                for name in ('codex', 'claude', 'opencode', 'pi'):
                    instance = result['providerInstances'][name+'_'+scope]
                    self.assertTrue(instance['enabled'])
                    self.assertEqual(instance['config']['binaryPath'],str(root/scope/'bin'/name))
            work = result['providerInstances']['antigravity_work']['config']
            self.assertEqual(work['apiKey'],'native-fixture')
            self.assertEqual(work['gcpProject'],'keep')
            self.assertEqual(work['binaryPath'],'/installed/by/t3')
            self.assertEqual(result['providerInstances']['antigravity']['config']['binaryPath'],'')
            for path, target in planned.items(): path.write_bytes(target[0])
            self.assertEqual(configure.targets(root, settings, Path('/native/cursor'), True), {})

    def test_rejects_unowned_wrapper_or_home_without_writing(self):
        for field, value in [('binaryPath','/foreign/codex'),('homePath','/history/to/preserve')]:
            with tempfile.TemporaryDirectory() as folder:
                root, settings = self.fixture(folder)
                document = json.loads(settings.read_text())
                config = {'binaryPath':str(root/'personal/bin/codex'), 'homePath':str(root/'personal/codex')}
                config[field] = value
                document['providerInstances']['codex_personal'] = {'driver':'codex','config':config}
                before = json.dumps(document).encode(); settings.write_bytes(before)
                with self.assertRaises(ValueError): configure.targets(root,settings)
                self.assertEqual(settings.read_bytes(),before)
