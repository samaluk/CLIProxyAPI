#!/usr/bin/env python3
"""Install catalog sync for existing scoped profiles on macOS or Linux.

Requires Python 3.11+, private downstream keys and existing profile definitions.
Does not change the main Codex home or download/replace harness executables.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

import remote_sync
import refresh_scoped_catalogs as catalogs

FILES = ('remote_sync.py', 'refresh_scoped_catalogs.py', 'model_labels.py', 'codex_account_tiers.py')
LABEL = 'me.cpa.catalog-sync'


def install(root, endpoint, binaries, schedule=True):
    if sys.version_info < (3, 11) or sys.platform not in ('darwin', 'linux'):
        raise ValueError('Python 3.11+ on macOS or Linux/WSL required')
    endpoint = remote_sync.origin(endpoint)
    root = root.expanduser().resolve()
    if not any((root / s / 'keys/downstream.key').is_file() for s in ('personal', 'work')):
        raise ValueError('Install scoped profiles and private downstream keys first')
    for name, binary in binaries.items():
        if name not in ('codex', 'claude', 'opencode', 'pi') or not Path(binary).is_absolute() or not os.access(binary, os.X_OK):
            raise ValueError('Harness binaries must exist and be executable absolute paths')
    os.umask(0o077)
    runtime = root / 'sync-runtime'; runtime.mkdir(mode=0o700, exist_ok=True)
    state = root / 'sync-state'; state.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = state / 'install-backups' / stamp; backup.mkdir(parents=True, mode=0o700)
    source = Path(__file__).resolve().parent
    settings = root / 'gateway.json'
    config = catalogs.read(settings) if settings.exists() else {}
    config.update(endpoint=endpoint, trust_gateway_templates=True, binaries=binaries)
    targets = {runtime / name: (source / name).read_bytes() for name in FILES}
    targets[settings] = catalogs.encoded(config)
    targets[root / 'launch-harness.py'] = (source / 'launch_harness.py').read_bytes()
    for index, (path, raw) in enumerate(targets.items()):
        if path.is_symlink():
            raise ValueError('Refusing symlinked installation target')
        if path.exists():
            (backup / str(index)).write_bytes(path.read_bytes())
        catalogs.atomic_write(path, raw, 0o600)
    python = str(Path(sys.executable).resolve())
    command = [python, str(runtime / 'remote_sync.py'), '--profiles', str(root), '--apply']
    bin_dir = Path.home() / '.local/bin'; bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = '#!/bin/sh\nexec ' + shlex.join(command[:-1]) + ' "$@"\n'
    catalogs.atomic_write(bin_dir / 'cpa-catalog-sync', wrapper.encode(), 0o700)
    # Existing manual refresh entrypoint becomes the same remote reconciliation.
    refresh = bin_dir / 'cpa-catalog-refresh'
    if refresh.exists():
        (backup / 'cpa-catalog-refresh').write_bytes(refresh.read_bytes())
        catalogs.atomic_write(refresh, wrapper.encode(), 0o700)
    for scope in ('personal', 'work'):
        if not (root / scope / 'keys/downstream.key').is_file():
            continue
        scoped_bin = root / scope / 'bin'; scoped_bin.mkdir(parents=True, exist_ok=True)
        for harness in binaries:
            script = '#!/bin/sh\nexec ' + shlex.join([python, str(root / 'launch-harness.py'), scope, harness]) + ' "$@"\n'
            # Match the existing wrappers used by T3 as well as child processes.
            for path in (scoped_bin / harness, bin_dir / (harness + '-' + scope)):
                if path.exists() and not path.is_symlink():
                    (backup / (scope + '-' + path.name)).write_bytes(path.read_bytes())
                if path.is_symlink():
                    raise ValueError('Refusing symlinked launcher target')
                catalogs.atomic_write(path, script.encode(), 0o700)
    if schedule:
        if sys.platform == 'darwin':
            path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
            path.parent.mkdir(parents=True, exist_ok=True)
            body = {'Label': LABEL, 'ProgramArguments': command, 'StartInterval': 300,
                    'RunAtLoad': True, 'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin')},
                    'StandardOutPath': str(state / 'sync.log'), 'StandardErrorPath': str(state / 'sync-error.log')}
            subprocess.run(['launchctl', 'bootout', 'gui/' + str(os.getuid()), str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            catalogs.atomic_write(path, plistlib.dumps(body), 0o600)
            subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(path)], check=True)
        else:
            folder = Path.home() / '.config/systemd/user'; folder.mkdir(parents=True, exist_ok=True)
            # systemd uses its own quoting; JSON strings quote paths and escape
            # backslashes, while doubled percent signs disable specifiers.
            quote = lambda value: json.dumps(value).replace('%', '%%').replace('$', '$$')
            service = '[Unit]\nDescription=Synchronize scoped CPA model catalogs\n[Service]\nType=oneshot\nExecStart=' + ' '.join(map(quote, command)) + '\n'
            timer = '[Unit]\nDescription=Refresh CPA catalogs every five minutes\n[Timer]\nOnBootSec=30\nOnUnitActiveSec=300\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
            catalogs.atomic_write(folder / (LABEL + '.service'), service.encode(), 0o600)
            catalogs.atomic_write(folder / (LABEL + '.timer'), timer.encode(), 0o600)
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', LABEL + '.timer'], check=True)
    return {'profiles': str(root), 'endpoint': endpoint, 'scheduled': schedule, 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--binary', action='append', default=[], metavar='NAME=ABSOLUTE_PATH')
    parser.add_argument('--no-schedule', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.profiles, args.endpoint, dict(item.split('=', 1) for item in args.binary), not args.no_schedule), indent=2))
