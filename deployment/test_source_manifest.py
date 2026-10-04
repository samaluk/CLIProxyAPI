import json
import pathlib
import tempfile
import unittest
from source_manifest import tree_digest, verify_source


class SourceManifestTests(unittest.TestCase):
    def test_stale_lock_and_modified_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = pathlib.Path(directory)
            source = sources / 'repo'
            source.mkdir()
            (source / 'main.go').write_text('fixture')
            component = {'repository': 'owner/repo', 'commit': 'old'}
            digest = tree_digest(source)
            (sources / 'manifest.json').write_text(json.dumps({'repo': {**component, 'tree_sha256': digest}}))
            self.assertEqual(verify_source(sources, component), digest)
            with self.assertRaisesRegex(ValueError, 'current lock'):
                verify_source(sources, {**component, 'commit': 'new'})
            (source / 'main.go').write_text('modified')
            with self.assertRaisesRegex(ValueError, 'content changed'):
                verify_source(sources, component)

    def test_modes_and_symlink_targets_affect_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            script = root / 'script'
            script.write_text('fixture')
            first = tree_digest(root)
            script.chmod(0o755)
            self.assertNotEqual(first, tree_digest(root))
            link = root / 'link'
            link.symlink_to('script')
            second = tree_digest(root)
            link.unlink()
            link.symlink_to('other')
            self.assertNotEqual(second, tree_digest(root))
