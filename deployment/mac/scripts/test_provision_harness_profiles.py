import json
from pathlib import Path
import tempfile
import unittest

import provision_harness_profiles as provisioning


class ProvisioningTests(unittest.TestCase):
    def test_adds_missing_harnesses_without_copying_credentials_or_changing_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);key=root/'personal/keys/downstream.key';key.parent.mkdir(parents=True);key.write_text('private-fixture-key')
            config=root/'personal/codex/config.toml';config.parent.mkdir(parents=True);config.write_text('model="personal/verified/default"\n')
            targets=provisioning.targets(root,'https://nas.example',{'codex':'/codex','claude':'/claude','opencode':'/opencode','pi':'/pi'})
            self.assertNotIn(config,targets)
            self.assertTrue(all('/personal/' in str(p) for p in targets))
            self.assertTrue(all('private-fixture-key' not in value[0].decode() for value in targets.values()))
            pi=json.loads(targets[root/'personal/pi/settings.json'][0]);self.assertEqual(pi['defaultModel'],'personal/verified/default')
            opencode=json.loads(targets[root/'personal/config/opencode/opencode.json'][0])
            self.assertEqual(opencode['provider']['cpa-personal']['options']['apiKey'],'{env:CPA_API_KEY}')
            self.assertEqual(config.read_text(),'model="personal/verified/default"\n')


if __name__ == '__main__':unittest.main()
