#!/usr/bin/env python3
"""Build the pinned core and native plugins inside the common Linux image."""
import hashlib
import json
import os
import pathlib
import subprocess
from source_manifest import verify_source

root = pathlib.Path('/build')
lock = json.loads((root / 'stack.lock.json').read_text())
out = pathlib.Path('/out')
(out / 'plugins').mkdir(parents=True, exist_ok=True)
env = dict(os.environ, CGO_ENABLED='1', GOOS='linux', GOARCH='amd64', GOAMD64='v1')
proof = []
for component in lock['components']:
    name = component['repository'].split('/')[1]
    version = component.get('version', 'review.' + component['commit'][:7])
    flags = '-s -w'
    mode = []
    if name == 'CLIProxyAPI':
        target, output = './cmd/server', out / 'cli-proxy-api'
        flags += f' -X main.Version={version} -X main.Commit={component["commit"]} -X main.BuildDate={lock["reviewed_at"]}'
    elif name == 'cpa-plugin-commandcode':
        target, output = './cmd/commandcode', out / 'plugins/commandcode.so'
        mode = ['-buildmode=c-shared']
        flags += f' -X main.pluginVersion={version} -X github.com/ahoo/cpa-plugin-commandcode.pluginVersion={version}'
    elif name == 'opencode-go-cliproxyapi':
        target, output = '.', out / 'plugins/opencode-go-cliproxyapi.so'
        mode = ['-buildmode=c-shared']
        flags += f' -X opencode-go-cliproxyapi/internal/plugin.pluginVersion={version}'
    elif name == 'cpa-key-account-bind':
        target, output = '.', out / 'plugins/key-account-bind.so'
        mode = ['-buildmode=c-shared']
        flags += f' -X main.pluginVersion={version}'
    else:
        continue
    source_digest = verify_source(root / '.sources', component)
    subprocess.run(['go', 'build', '-mod=readonly', '-trimpath', '-buildvcs=false', *mode,
                    '-ldflags', flags, '-o', str(output), target], cwd=root / '.sources' / name, env=env, check=True)
    proof.append({'repository': component['repository'], 'commit': component['commit'],
                  'source_tree_sha256': source_digest,
                  'version': version, 'file': str(output.relative_to(out)),
                  'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
(out / 'provenance.json').write_text(json.dumps(proof, indent=2) + '\n')
