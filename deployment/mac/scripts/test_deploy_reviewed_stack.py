"""Isolated deployment-boundary fixtures. Never use the live app/core paths."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest import mock

FILE = Path(__file__).with_name('deploy_reviewed_stack.py')
SPEC = importlib.util.spec_from_file_location('deployment', FILE)
deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deployment)


class DeploymentBoundaryTests(unittest.TestCase):
    def test_new_false_auth_directory_default_is_semantically_unchanged(self):
        original = {'auth-dir': 'fixture-auth'}
        self.assertEqual(deployment.gui_config_semantics(original),
                         deployment.gui_config_semantics({**original, 'auth-dir-user-selected': False}))
        self.assertNotEqual(deployment.gui_config_semantics(original),
                            deployment.gui_config_semantics({**original, 'auth-dir-user-selected': True}))
        self.assertNotEqual(deployment.gui_config_semantics(original),
                            deployment.gui_config_semantics({'auth-dir': 'different-auth'}))

    def test_graceful_shutdown_allows_core_cleanup_beyond_twenty_seconds(self):
        clock = {'now': 0.0}
        processes = {123: {'path': 'fixture-core', 'started': 'fixture-time'}}
        def inventory():
            return processes if clock['now'] < 30 else {}
        def sleep(seconds):
            clock['now'] += seconds
        with mock.patch.object(deployment, 'inventory', side_effect=inventory), \
             mock.patch.object(deployment, 'check_active_requests'), \
             mock.patch.object(deployment, 'port_open', return_value=False), \
             mock.patch.object(deployment.time, 'monotonic', side_effect=lambda: clock['now']), \
             mock.patch.object(deployment.time, 'sleep', side_effect=sleep), \
             mock.patch.object(deployment.os, 'kill') as kill:
            deployment.stop_exact(processes)
        kill.assert_called_once_with(123, deployment.signal.SIGTERM)
        self.assertGreaterEqual(clock['now'], 30)

    def test_reviewed_release_tags_allow_unique_dated_builds(self):
        for tag in ('v8.0.2-review.e37070a', 'v8.0.3-review.88e9798.20260928',
                    'v8.0.3-review.88e9798.20260928.2'):
            self.assertTrue(deployment.reviewed_release_tag(tag), tag)
        for tag in (None, 'v8.0.3', 'v8.0.3-review.88e9798/asset',
                    'v8.0.3-review.88e9798?x=1', 'v8.0.3-review.88e9798.2026092',
                    'v8.0.3-review.88e9798.20260928\n'):
            self.assertFalse(deployment.reviewed_release_tag(tag), tag)

    def test_successful_swap_is_tracked_before_durability_failure_and_can_swap_back(self):
        with tempfile.TemporaryDirectory(dir=FILE.parent, prefix='app-exchange-fixture-') as temp:
            root = Path(temp)
            live, stage = root / 'live.app', root / 'stage.app'
            live.mkdir()
            stage.mkdir()
            (live / 'sentinel').write_text('old')
            (stage / 'sentinel').write_text('new')
            task = object.__new__(deployment.Deployment)
            task.staged_app, task.exchanged = stage, False
            with mock.patch.object(deployment, 'APP', live), mock.patch.object(deployment, 'fsync_dir', side_effect=OSError('fixture fsync failure')):
                with self.assertRaises(OSError):
                    task.exchange_app()
                self.assertTrue(task.exchanged)
                self.assertEqual((live / 'sentinel').read_text(), 'new')
                self.assertEqual((stage / 'sentinel').read_text(), 'old')
                with self.assertRaises(OSError):
                    task.exchange_app()
                self.assertFalse(task.exchanged)
                self.assertEqual((live / 'sentinel').read_text(), 'old')

    def test_failed_rename_preserves_original_live_app_and_tracking(self):
        with tempfile.TemporaryDirectory(dir=FILE.parent, prefix='app-failure-fixture-') as temp:
            root = Path(temp)
            live, stage = root / 'live.app', root / 'stage.app'
            live.mkdir()
            stage.mkdir()
            (live / 'sentinel').write_text('old')
            (stage / 'sentinel').write_text('new')
            task = object.__new__(deployment.Deployment)
            task.staged_app, task.exchanged = stage, False
            with mock.patch.object(deployment, 'APP', live), mock.patch.object(deployment, 'exchange_directories', side_effect=OSError('fixture rename failure')):
                with self.assertRaises(OSError):
                    task.exchange_app()
            self.assertFalse(task.exchanged)
            self.assertEqual((live / 'sentinel').read_text(), 'old')

    def test_active_request_rejection_does_not_signal_or_mark_stop(self):
        processes = {123: {'path': 'fixture-core', 'started': 'fixture-time'}}
        mark_stop = mock.Mock()
        with mock.patch.object(deployment, 'inventory', return_value=processes), \
             mock.patch.object(deployment, 'check_active_requests', side_effect=RuntimeError('fixture active request')), \
             mock.patch.object(deployment.os, 'kill') as kill:
            with self.assertRaises(RuntimeError):
                deployment.stop_exact(processes, on_signal=mark_stop)
        mark_stop.assert_not_called()
        kill.assert_not_called()

    def test_preflight_rejection_does_not_enter_rollback(self):
        task = object.__new__(deployment.Deployment)
        task.prepare = mock.Mock()
        task.protected_ok = mock.Mock()
        task.old_core_sha, task.old_app_tree = 'old', 'tree'
        task.old_metadata_hashes = {}
        task.original_pids = {}
        task.differences = mock.Mock(return_value=[])
        task.health = mock.Mock(return_value={})
        task.stop_attempted = False
        task.report = {}
        task.record = mock.Mock()
        task.rollback = mock.Mock()
        with mock.patch.object(deployment, 'sha', return_value='old'), \
             mock.patch.object(deployment, 'tree_digest', return_value='tree'), \
             mock.patch.object(deployment, 'stop_exact', side_effect=RuntimeError('fixture preflight rejection')):
            with self.assertRaises(RuntimeError):
                task.execute()
        task.rollback.assert_not_called()
        self.assertFalse(task.stop_attempted)

    def test_app_recovery_durability_failure_does_not_abandon_core_restore(self):
        with tempfile.TemporaryDirectory(dir=FILE.parent, prefix='both-components-fixture-') as temp:
            root = Path(temp)
            core, backup = root / 'core', root / 'backup'
            core.mkdir()
            backup.mkdir()
            binary = core / 'cli-proxy-api'
            binary.write_bytes(b'new-core')
            (backup / 'core-binary').write_bytes(b'old-core')
            (backup / 'reviewed-core.json').write_text('old-provenance')
            task = object.__new__(deployment.Deployment)
            task.backup, task.exchanged, task.core_replaced = backup, True, True
            task.staged_app, task.old_app_sha = root / 'old.app', 'fixture'
            task.start_core = mock.Mock()
            def app_restored_then_fsync_failed():
                task.exchanged = False
                raise OSError('fixture app fsync failure')
            task.exchange_app = app_restored_then_fsync_failed
            with mock.patch.object(deployment, 'CORE', core), \
                 mock.patch.object(deployment, 'CORE_BINARY', binary), \
                 mock.patch.object(deployment, 'inventory', return_value={}), \
                 mock.patch.object(deployment, 'port_open', return_value=False), \
                 mock.patch.object(deployment, 'verify_app'):
                with self.assertRaisesRegex(RuntimeError, 'both restorations were attempted'):
                    task.rollback()
            self.assertEqual(binary.read_bytes(), b'old-core')
            self.assertEqual((core / 'reviewed-core.json').read_text(), 'old-provenance')
            task.start_core.assert_not_called()


if __name__ == '__main__':
    unittest.main()
