#!/usr/bin/env python3
"""Build the locked core while preserving the deployed gateway and plugins."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from source_manifest import verify_source

root = Path('/build')
lock = json.loads((root / 'stack.lock.json').read_text())
component = next(item for item in lock['components'] if item['repository'] == 'samaluk/CLIProxyAPI')
digest = verify_source(root / '.sources', component)
out = Path('/out')
out.mkdir(parents=True, exist_ok=True)
binary = out / 'cli-proxy-api'
environment = dict(os.environ, CGO_ENABLED='1', GOOS='linux', GOARCH='amd64', GOAMD64='v1')
flags = (f'-s -w -X main.Version={component["version"]} '
         f'-X main.Commit={component["commit"]} -X main.BuildDate={lock["reviewed_at"]}')
subprocess.run(['go', 'build', '-mod=readonly', '-trimpath', '-buildvcs=false',
                '-ldflags', flags, '-o', str(binary), './cmd/server'],
               cwd=root / '.sources/CLIProxyAPI', env=environment, check=True)
proof = json.loads((root / 'base-provenance.json').read_text())
entry = {'repository': component['repository'], 'commit': component['commit'],
         'source_tree_sha256': digest, 'version': component['version'],
         'file': 'cli-proxy-api', 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
assert sum(item['repository'] == component['repository'] for item in proof) == 1
proof = [entry if item['repository'] == component['repository'] else item for item in proof]
(out / 'provenance.json').write_text(json.dumps(proof, indent=2) + '\n')
