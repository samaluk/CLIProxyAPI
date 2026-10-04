#!/usr/bin/env python3
"""Export exact public source commits for an offline container build context."""
import sys
import argparse
import json
import pathlib
import subprocess
import tarfile
import tempfile
import shutil
from source_manifest import tree_digest

if sys.version_info < (3, 12):
    raise SystemExit('Source preparation requires Python 3.12+ on the build host; the NAS does not need Python')

ROOT = pathlib.Path(__file__).resolve().parent
RUNTIME = {'CLIProxyAPI', 'cpa-plugin-commandcode', 'opencode-go-cliproxyapi', 'cpa-key-account-bind'}


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-repos', type=pathlib.Path, help='Optional clean checkout cache; exact lock commits are still required')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'stack.lock.json').read_text())
    destination = ROOT / '.sources'
    if destination.exists():
        raise SystemExit('.sources already exists; inspect it, then move it aside before preparing a different lock')
    with tempfile.TemporaryDirectory(dir=ROOT, prefix='.prepare-') as temp:
        staged = pathlib.Path(temp) / 'sources'
        staged.mkdir()
        manifest = {}
        for component in lock['components']:
            name = component['repository'].split('/')[1]
            if name not in RUNTIME:
                continue
            commit = component['commit']
            if args.local_repos:
                repo = args.local_repos / name
                if run('git', 'status', '--porcelain', cwd=repo):
                    raise SystemExit(f'{name}: source cache has uncommitted changes')
            else:
                repo = pathlib.Path(temp) / name
                subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
                subprocess.run(['git', '-C', str(repo), 'fetch', '--quiet', '--depth=1',
                                'https://github.com/' + component['repository'] + '.git', commit], check=True)
            if run('git', 'rev-parse', commit + '^{commit}', cwd=repo) != commit:
                raise SystemExit(f'{name}: commit verification failed')
            archive = pathlib.Path(temp) / (name + '.tar')
            subprocess.run(['git', 'archive', '--format=tar', '--output', str(archive), commit], cwd=repo, check=True)
            target = staged / name
            target.mkdir()
            with tarfile.open(archive) as tar:
                # Git archives may contain symlinks. Reject any entry that escapes
                # its source directory; extraction_filter is available in Python 3.12+.
                tar.extractall(target, filter='data')
            manifest[name] = {'repository': component['repository'], 'commit': commit,
                              'tree_sha256': tree_digest(target)}
            print(name + ' ' + commit)
        (staged / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        shutil.move(staged, destination)


if __name__ == '__main__':
    main()
