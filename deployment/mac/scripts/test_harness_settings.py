import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import harness_settings


POLICY = {'schema':1,'harnesses':{
    'codex':{'model_reasoning_effort':'medium','agents':{'max_threads':4,'max_depth':2}},
    'claude':{'effortLevel':'medium','autoCompactEnabled':False},
    'opencode':{'autoupdate':False,'share':'disabled','permission':'ask'},
    'pi':{'defaultThinkingLevel':'high','hideThinkingBlock':True,'compaction':{'enabled':False}},
}}


class SettingsTests(unittest.TestCase):
    def test_policy_cannot_inject_commands_credentials_or_permissions(self):
        self.assertEqual(harness_settings.validate(copy.deepcopy(POLICY)), POLICY)
        for name in ('command', 'api_key', 'permissions'):
            value=copy.deepcopy(POLICY);value[name]='untrusted'
            with self.assertRaises(ValueError):harness_settings.validate(value)
        for capacity in (True,0,65,'4'):
            value=copy.deepcopy(POLICY);value['harnesses']['codex']['agents']['max_threads']=capacity
            with self.assertRaises(ValueError):harness_settings.validate(value)

    def test_unavailable_policy_retains_last_validated_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'shared-settings.json';path.write_text(json.dumps(POLICY))
            with patch.object(harness_settings.urllib.request,'build_opener') as build:
                build.return_value.open.side_effect=OSError('untrusted private response')
                value,state,change=harness_settings.load(root,{'shared_settings_url':'https://example.invalid/settings.json'})
            self.assertEqual(value,POLICY);self.assertIsNone(change)
            self.assertNotIn('untrusted private response',state)
            self.assertEqual(json.loads(path.read_text()),POLICY)

    def test_harness_baselines_preserve_roles_and_distinct_harness_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'personal'
            files={
                'codex/config.toml':'model="personal/test/model"\n[agents]\ndefault_subagent_model="personal/test/child"\n',
                'claude/settings.json':json.dumps({'hooks':{'preserve':True}}),
                'pi/settings.json':json.dumps({'extensions':['preserve']}),
                'config/opencode/opencode.json':json.dumps({'provider':{'cpa-personal':{'models':{
                    'personal/known':{'variants':{'medium':{}}},'personal/unsupported':{'variants':{'low':{}}}}}}}),
            }
            for name,raw in files.items():
                path=profile/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(raw)
            changes=harness_settings.project(root,POLICY,{})
            codex=tomllib.loads(changes[profile/'codex/config.toml']['after'].decode())
            self.assertEqual(codex['agents']['max_threads'],4)
            self.assertEqual(codex['agents']['max_depth'],2)
            self.assertEqual(codex['agents']['default_subagent_model'],'personal/test/child')
            claude=json.loads(changes[profile/'claude/settings.json']['after'])
            self.assertEqual(claude['effortLevel'],'medium');self.assertEqual(claude['hooks'],{'preserve':True})
            pi=json.loads(changes[profile/'pi/settings.json']['after'])
            self.assertEqual(pi['defaultThinkingLevel'],'high');self.assertEqual(pi['extensions'],['preserve'])
            models=json.loads(changes[profile/'config/opencode/opencode.json']['after'])['provider']['cpa-personal']['models']
            self.assertNotIn('options',models['personal/known'])
            self.assertNotIn('options',models['personal/unsupported'])
            for path,change in changes.items():path.write_bytes(change['after'])
            self.assertEqual(harness_settings.project(root,POLICY,{}),{})
            report=harness_settings.report(root,POLICY,machine='fixture-host')
            self.assertEqual(report['byHarness']['codex'][0]['machine'],'fixture-host')
            self.assertEqual(report['byHarness']['codex'][0]['profile'],'personal')
            self.assertEqual(report['byHarness']['codex'][0]['drift'],[])


if __name__ == '__main__':unittest.main()
