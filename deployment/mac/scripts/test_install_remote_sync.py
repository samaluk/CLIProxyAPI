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
