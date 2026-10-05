import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import opencode_services as services


class OpenCodeServicesTests(unittest.TestCase):
    def test_waits_past_nonempty_builtin_snapshot_and_rejects_foreign_scope(self):
        expected = {'cpa-personal/personal/codex-oauth/gpt-6.1-sol'}
        snapshots = [
            {'data': [{'providerID': 'opencode', 'id': 'big-pickle'}]},
            {'data': [{'providerID': 'cpa-work', 'id': 'work/litellm/model'}]},
            {'data': [{'providerID': 'cpa-personal', 'id': 'personal/codex-oauth/gpt-6.1-sol'}]},
        ]
        with patch.object(services, 'request', side_effect=snapshots), patch.object(services.time, 'sleep'):
            self.assertEqual(services.settled_models('http://127.0.0.1:49374', 'secret', 'personal', expected, '/home'), 1)

    def test_incomplete_catalog_times_out_without_publishing_a_connection(self):
        with patch.object(services, 'request', return_value={'data': []}), \
                patch.object(services.time, 'monotonic', side_effect=[0, 16]):
            with self.assertRaises(ValueError):
                services.settled_models('http://127.0.0.1:49374', 'secret', 'work', {'cpa-work/m'}, '/home')

    def test_t3_patch_preserves_other_harnesses_and_saves_private_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'settings.json'
            settings = {'providerInstances': {
                'opencode_personal': {'driver': 'opencode', 'enabled': True, 'config': {
                    'binaryPath': str(root / 'personal/bin/opencode'), 'customModels': [{'id': 'saved'}]}},
                'codex_personal': {'driver': 'codex', 'config': {'model': 'retain'}},
            }, 'unrelated': ['retain']}
            before = json.dumps(settings).encode(); path.write_bytes(before)
            connections = {'personal': {'url': 'http://127.0.0.1:49374', 'password': 'private'}}
            self.assertTrue(services.connect_t3(path, root, connections))
            result = json.loads(path.read_text())
            self.assertEqual(result['providerInstances']['codex_personal'], settings['providerInstances']['codex_personal'])
            self.assertEqual(result['providerInstances']['opencode_personal']['config']['customModels'], [{'id': 'saved'}])
            self.assertEqual(result['unrelated'], ['retain'])
            backup = next((root / 'sync-state/t3-backups').iterdir())
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertFalse(services.connect_t3(path, root, connections))

    def test_wrong_wrapper_prevents_any_settings_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'settings.json'
            before = b'{"providerInstances":{"opencode_work":{"driver":"opencode","config":{"binaryPath":"opencode"}}}}'
            path.write_bytes(before)
            with self.assertRaises(ValueError):
                services.connect_t3(path, root, {'work': {'url': 'http://127.0.0.1:49375', 'password': 'private'}})
            self.assertEqual(path.read_bytes(), before)

    def test_failed_reload_keeps_revision_pending_so_retry_reloads_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'sync-state').mkdir()
            settings = {'providerInstances': {}}
            for scope, port in [('personal', 49374), ('work', 49375)]:
                profile = root / scope
                (profile / 'config/opencode').mkdir(parents=True)
                (profile / 'state/opencode').mkdir(parents=True)
                (profile / 'config/opencode/service.json').write_text(json.dumps({'port': port}))
                (profile / 'state/opencode/service.json').write_text(json.dumps({'url': f'http://127.0.0.1:{port}', 'password': 'private'}))
                (profile / 'config/opencode/opencode.json').write_text(json.dumps({'provider': {'cpa-' + scope: {'models': {'model': {}}}}}))
                settings['providerInstances']['opencode_' + scope] = {'driver': 'opencode', 'config': {'binaryPath': str(profile / 'bin/opencode')}}
            path = root / 'settings.json'; path.write_text(json.dumps(settings)); before = path.read_bytes()
            calls = []
            fail = True
            def command(binary, *args):
                scope = binary.parent.parent.name
                if args == ('--version',): return 'opencode v2.0.22'
                if args == ('service', 'status'): return f'http://127.0.0.1:{49374 if scope == "personal" else 49375}'
                if args == ('reload',):
                    calls.append(scope)
                    if scope == 'work' and fail: raise ValueError('reload failed')
                    return ''
                self.fail('Unexpected command')
            with patch.object(services, 'command', side_effect=command), patch.object(services, 'settled_models', return_value=1):
                with self.assertRaises(ValueError): services.reconcile(root, {}, path)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((root / 'sync-state/opencode-services.json').exists())
                fail = False
                services.reconcile(root, {}, path)
                self.assertEqual(calls, ['personal', 'work', 'personal', 'work'])
                services.reconcile(root, {}, path)
                self.assertEqual(calls, ['personal', 'work', 'personal', 'work'])
