#!/usr/bin/env python3
"""Install an opt-in Personal-only Handy relay without changing the NAS policy.

Uses stock Caddy, a scoped catalog file and a persistent application session ID.
The existing compatibility relay and live harness processes remain untouched.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

import install_remote_sync as installer
import remote_sync

LABEL = 'me.cpa.handy-personal'


def configuration(root, endpoint, key, session, port):
    endpoint = remote_sync.origin(endpoint)
    if not endpoint.startswith('https://') or not 1024 <= port <= 65535:
        raise ValueError('Handy requires an HTTPS gateway and an unprivileged local port')
    if len(key) < 16 or any(c in key for c in '\r\n'):
        raise ValueError('Invalid scoped key')
    uuid.UUID(session)
    quote = json.dumps
    return '\n'.join([
        '{', '    admin off', '    auto_https off', '}',
        'http://127.0.0.1:' + str(port) + ' {', '    bind 127.0.0.1',
        '    @personal header Authorization ' + quote('Bearer ' + key),
        '    handle @personal {', '        handle /v1/models {',
        '            root * ' + quote(str(root / 'personal/catalogs')),
        '            rewrite * /handy-models.json', '            file_server', '        }',
        '        handle /v1/chat/completions {',
        '            reverse_proxy ' + endpoint + ' {',
        '                header_up Host ' + urlsplit(endpoint).netloc,
        '                header_up Authorization ' + quote('Bearer ' + key),
        '                header_up Session-Id ' + session,
        '                header_up -Thread-Id', '                header_up -Thread_id',
        '                header_up -Session_id', '                header_up -X-Codex-Turn-Metadata',
        '                header_up -X-Codex-Parent-Thread-Id',
        '                header_up -X-Openai-Subagent', '                flush_interval -1',
        '            }', '        }', '        handle {', '            respond "Unknown Handy endpoint" 404', '        }',
        '    }', '    handle {', '        respond "Personal key required" 401', '    }', '}', ''])


def install(root, caddy, port=8318, replace=False):
    if sys.platform != 'darwin':
        raise ValueError('This relay installer currently supports macOS only')
    root = root.expanduser().absolute()
    if not caddy.is_absolute() or not os.access(caddy, os.X_OK):
        raise ValueError('Use an installed absolute Caddy executable')
    settings = json.loads((root / 'gateway.json').read_text())
    installed_sync = root / 'sync-runtime/remote_sync.py'
    if not installed_sync.is_file() or installed_sync.read_bytes() != Path(remote_sync.__file__).read_bytes():
        raise ValueError('Reinstall current catalog helpers before installing the Handy relay')
    key = (root / 'personal/keys/downstream.key').read_text().strip()
    session_path = root / 'personal/handy/session.json'
    session = json.loads(session_path.read_text())['session'] if session_path.exists() else str(uuid.uuid4())
    raw = configuration(root, settings['endpoint'], key, session, port).encode()
    # Validate syntax without placing credentials in command arguments or output.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'Caddyfile'; path.write_bytes(raw); path.chmod(0o600)
        result = subprocess.run([str(caddy), 'validate', '--config', str(path), '--adapter', 'caddyfile'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise ValueError('Handy Caddy configuration failed validation')
    domain = 'gui/' + str(os.getuid())
    loaded = installer.run(['launchctl', 'print', domain + '/' + LABEL], False)
    if loaded and not replace:
        raise ValueError('Handy relay already installed; update it during an idle window')
    config_path = root / 'personal/handy/Caddyfile'
    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    if loaded:
        previous = plistlib.loads(plist.read_bytes())
        if previous.get('ProgramArguments') != [str(caddy), 'run', '--config', str(config_path), '--adapter', 'caddyfile']:
            raise ValueError('Existing Handy relay is not owned by this installer')
    else:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
    catalog = root / 'personal/catalogs/handy-models.json'
    snapshot = remote_sync.fetch(settings['endpoint'], key, 'personal')
    models = {'object': 'list', 'data': [{'id': m['slug'], 'object': 'model', 'owned_by': 'cpa-personal'}
                                       for m in sorted(snapshot['models'], key=lambda m: m['slug'])]}
    targets = {config_path: (raw, 0o600), session_path: (remote_sync.catalogs.encoded({'session': session}), 0o600),
               catalog: (remote_sync.catalogs.encoded(models), 0o600),
               plist: (plistlib.dumps({'Label': LABEL, 'RunAtLoad': True, 'KeepAlive': True,
                       'ProgramArguments': [str(caddy), 'run', '--config', str(config_path), '--adapter', 'caddyfile'],
                       'StandardOutPath': str(root / 'sync-state/handy-relay.log'),
                       'StandardErrorPath': str(root / 'sync-state/handy-relay-error.log')}), 0o600)}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    def activate():
        if loaded:
            installer.run(['launchctl', 'kickstart', '-k', domain + '/' + LABEL])
        else:
            installer.run(['launchctl', 'bootstrap', domain, str(plist)])
    def recover():
        if loaded:
            installer.run(['launchctl', 'kickstart', '-k', domain + '/' + LABEL], False)
        else:
            installer.run(['launchctl', 'bootout', domain + '/' + LABEL], False)
    installer.write_transaction(targets, root / 'sync-state/install-backups' / ('handy-' + stamp),
                                activate=activate, recover=recover)
    return {'endpoint': 'http://127.0.0.1:' + str(port) + '/v1', 'scope': 'personal', 'models': len(models['data'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--caddy', type=Path, default=Path('/opt/homebrew/bin/caddy'))
    parser.add_argument('--port', type=int, default=8318)
    parser.add_argument('--replace', action='store_true', help='Replace this owned relay during an idle Handy window')
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(install(args.profiles, args.caddy, args.port, args.replace)))
