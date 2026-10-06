import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launch_harness


class ClaudeCapabilitiesTests(unittest.TestCase):
    def test_scoped_snapshot_supplies_limits_without_a_codex_prompt_template(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'work'
            for relative in ('keys','catalogs'):(profile/relative).mkdir(parents=True)
            (root/'sync-state').mkdir()
            (root/'gateway.json').write_text(json.dumps({'endpoint':'https://nas.example','binaries':{'claude':'/stock/claude'}}))
            (profile/'keys/downstream.key').write_text('fixture')
            (profile/'catalogs/codex-catalog.json').write_text('{"models":[]}')
            route='work/litellm/new'
            (root/'sync-state/work.json').write_text(json.dumps({'scope':'work','models':[{'slug':route,'context_window':922000,'max_tokens':128000}]}))
            with patch.object(launch_harness,'ROOT',root),patch.object(launch_harness.sys,'argv',['launcher','work','claude','--model',route]),patch.object(launch_harness.os,'execve') as execute:
                launch_harness.main()
            env=execute.call_args.args[2]
            self.assertEqual(env['CLAUDE_CODE_MAX_CONTEXT_TOKENS'],'922000')
            self.assertEqual(env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'],'128000')
            self.assertEqual(env['CPA_API_KEY'],'fixture')


if __name__ == '__main__':unittest.main()
