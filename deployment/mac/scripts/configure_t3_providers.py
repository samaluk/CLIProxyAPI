#!/usr/bin/env python3
"""Register installed scoped harnesses and the native exceptions in local T3."""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import sys

import install_remote_sync as installer
import refresh_scoped_catalogs as catalogs


def targets(root, settings_path, cursor_binary=None, t3_antigravity=False, work_native=None):
    before = settings_path.read_bytes() if settings_path.exists() else None
    document = json.loads(before) if before is not None else {}
    instances = document.setdefault('providerInstances', {})
    gateway_path = root/'gateway.json'
    gateway_before = gateway_path.read_bytes()
    gateway = json.loads(gateway_before)
    if gateway.get('proxy_only') is not True:
        raise ValueError('Configure proxy-only harness profiles first')
    for harness, driver, name in [('codex', 'codex', 'Codex'), ('claude', 'claudeAgent', 'Claude'),
                                  ('opencode', 'opencode', 'OpenCode'), ('pi', 'pi', 'Pi')]:
        if harness not in gateway['binaries']:
            raise ValueError('Install all four compatible harnesses before registering T3')
        for scope in ('personal', 'work'):
            profile = root/scope
            binary = profile/'bin'/harness
            if not (profile/'keys/downstream.key').is_file() or not os.access(binary, os.X_OK):
                raise ValueError('Both scoped harness wrappers and downstream keys must exist')
            identifier = harness+'_'+scope
            if identifier not in instances:
                config = {'binaryPath':str(binary), 'customModels':[]} if harness != 'pi' else {'binaryPath':str(binary)}
                if harness in ('codex', 'claude'):
                    config['homePath'] = str(profile/harness)
                instances[identifier] = {'driver':driver, 'displayName':name+' '+scope.title(),
                                         'enabled':True, 'config':config}
            else:
                instance = instances[identifier]
                config = instance.get('config', {})
                if instance.get('driver') != driver or config.get('binaryPath') != str(binary):
                    raise ValueError('Existing T3 instance is not owned by the scoped profile')
                if harness in ('codex', 'claude') and config.get('homePath') != str(profile/harness):
                    raise ValueError('Existing T3 HOME differs; preserve its history and resolve it separately')
                instance['enabled'] = True
            legacy = instances.get(driver)
            if legacy and legacy.get('driver') == driver and legacy.get('config', {}).get('binaryPath', harness) in (
                    harness, '', str(Path.home()/'.config/cpa/bin'/harness)):
                legacy['enabled'] = False
                legacy.setdefault('displayName', name+' Legacy home')
            if driver != 'pi':
                document.setdefault('providers', {}).setdefault(driver, {})['enabled'] = False
    if document.get('providers', {}).get('pi') == {'enabled':False}:
        document['providers'].pop('pi')
    if cursor_binary is not None:
        instance = instances.setdefault('cursor', {'driver':'cursor', 'displayName':'Cursor', 'config':{}})
        if instance.get('driver') != 'cursor':
            raise ValueError('Existing Cursor identifier belongs to another driver')
        instance['enabled'] = True
        instance.setdefault('config', {})['binaryPath'] = str(cursor_binary)
    if t3_antigravity:
        for identifier, label, auth in [('antigravity', 'AGY Personal', {'authMethod':'oauth-personal'}),
                                        ('antigravity_work', 'AGY Work', {'authMethod':'agent-platform',
                                         'gcpProject':'buk-cli', 'gcpLocation':'global'})]:
            instance = instances.setdefault(identifier, {'driver':'antigravity', 'displayName':label,
                                                        'config':copy.deepcopy(auth)})
            if instance.get('driver') != 'antigravity':
                raise ValueError('Existing Antigravity identifier belongs to another driver')
            instance['enabled'] = True
            config = instance.setdefault('config', {})
            config.setdefault('binaryPath', '')
            if identifier == 'antigravity_work' and work_native is not None:
                if config.get('apiKey') and config['apiKey'] != work_native['apiKey']:
                    raise ValueError('Preserve the existing native Work key instead of replacing it')
                config.update(work_native)
    gateway.update(t3_claude_profiles=True, t3_pi_profiles=True, pi_native_catalog=True,
                   t3_opencode_services=True)
    planned = {}
    for path, previous, value in [(settings_path, before, document), (gateway_path, gateway_before, gateway)]:
        after = catalogs.encoded(value)
        if after != previous:
            planned[path] = (after, 0o600, previous)
    return planned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--settings', type=Path, default=Path.home()/'.t3/userdata/settings.json')
    parser.add_argument('--cursor-binary', type=Path)
    parser.add_argument('--t3-antigravity', action='store_true', help='Enable T3-managed native Antigravity instances')
    parser.add_argument('--work-native-config-stdin', action='store_true',
                        help='Seed only the native Work Agent Platform API configuration from private stdin')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.profiles.expanduser().resolve()
    for binary in (args.cursor_binary,):
        if binary is not None and (not binary.is_absolute() or not os.access(binary, os.X_OK)):
            raise ValueError('Native exception binary must be an installed executable absolute path')
    work_native = None
    if args.work_native_config_stdin:
        if not args.t3_antigravity:
            raise ValueError('Native Work configuration requires T3 Antigravity registration')
        work_native = json.load(sys.stdin)
        if (not isinstance(work_native, dict) or set(work_native) != {'authMethod','apiKey','gcpProject','gcpLocation'}
                or work_native['authMethod'] != 'agent-platform'
                or not all(isinstance(v, str) for v in work_native.values()) or not work_native['apiKey']):
            raise ValueError('Expected the native Work Agent Platform API configuration, never OAuth tokens')
    planned = targets(root, args.settings.expanduser().resolve(), args.cursor_binary,
                      args.t3_antigravity, work_native)
    if args.apply and planned:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        installer.write_transaction(planned, root/'sync-state/t3-provider-backups'/stamp)
    print(json.dumps({'applied':args.apply, 'changedFiles':[str(p) for p in planned]}, indent=2))


if __name__ == '__main__':
    main()
