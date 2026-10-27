#!/usr/bin/env python3
"""Build only the locked dogfood Go plugin, retaining all base-image binaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from source_manifest import verify_source

root = Path('/build')
lock = json.loads((root / 'stack.lock.json').read_text())
component = next(c for c in lock['components'] if c['repository'] == 'samaluk/opencode-go-cliproxyapi')
source = root / '.sources/opencode-go-cliproxyapi'
digest = verify_source(root / '.sources', component)
out = Path('/out')
(out / 'plugins').mkdir(parents=True, exist_ok=True)
binary = out / 'plugins/opencode-go-cliproxyapi.so'
environment = dict(os.environ, CGO_ENABLED='1', GOOS='linux', GOARCH='amd64', GOAMD64='v1')
flags = '-s -w -X opencode-go-cliproxyapi/internal/plugin.pluginVersion=' + component['version']
subprocess.run(['go', 'build', '-mod=readonly', '-tags', 'debug', '-trimpath', '-buildvcs=false',
    '-buildmode=c-shared', '-ldflags', flags, '-o', str(binary), '.'], cwd=source, env=environment, check=True)
proof = json.loads((root / 'base-provenance.json').read_text())
entry = {'repository':component['repository'], 'commit':component['commit'], 'source_tree_sha256':digest,
    'version':component['version'], 'file':'plugins/opencode-go-cliproxyapi.so',
    'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(), 'build_tags':['debug']}
assert sum(p['repository'] == component['repository'] for p in proof) == 1
proof = [entry if p['repository'] == component['repository'] else p for p in proof]
(out / 'provenance.json').write_text(json.dumps(proof, indent=2) + '\n')
