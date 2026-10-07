#!/usr/bin/env python3
"""Install catalog sync for existing scoped profiles on macOS or Linux.

Requires Python 3.11+, private downstream keys and existing profile definitions.
Does not change the main Codex home or download/replace harness executables.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse

import remote_sync
import refresh_scoped_catalogs as catalogs

FILES = ('remote_sync.py', 'refresh_scoped_catalogs.py', 'model_labels.py', 'codex_account_tiers.py', 'opencode_services.py', 'proxy_only.py', 'harness_settings.py')
LABEL = 'me.cpa.catalog-sync'


def python_runtime():
    """Keep stable package-manager entrypoints instead of resolving Cellar paths."""
    preferred = ['/opt/homebrew/bin/python3', '/usr/local/bin/python3'] if sys.platform == 'darwin' else ['/usr/bin/python3', '/usr/local/bin/python3']
    for candidate in [*preferred, shutil.which('python3'), sys.executable]:
        if not candidate or not Path(candidate).is_absolute() or not os.access(candidate, os.X_OK):
            continue
        check = subprocess.run([candidate, '-c', 'import sys; sys.exit(sys.version_info < (3, 11))'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode == 0:
            return candidate
    raise ValueError('No stable Python 3.11+ interpreter is available')


def native_entrypoints(binaries, proxy_only):
    """Resolve native symlinks before replacing their public command path."""
    result = dict(binaries)
    if proxy_only:
        for name, binary in result.items():
            path = Path(binary)
            entry = Path.home() / '.config/cpa/bin' / name
            if path == entry:
                if not path.is_symlink() or path.resolve() == entry:
                    raise ValueError('Native executable overlaps a managed entrypoint; supply its real installation path')
                result[name] = str(path.resolve())
    return result


def write_transaction(targets, backup, activate=None, recover=None):
    """Archive preflight contents and roll back failures. None retires a file.

    A target may include expected prior bytes to guard an earlier ownership check.
    """
    saved = {}
    for path, target in targets.items():
        raw, mode = target[:2]
        if any(p.is_symlink() for p in path.parents):
            raise ValueError('Refusing symlinked installation directory')
        if path.exists() and not path.is_file():
            raise ValueError('Installation target must be a file')
        saved[path] = {'link': str(path.readlink()) if path.is_symlink() else None,
                       'raw': path.read_bytes() if path.exists() else None,
                       'mode': path.stat().st_mode & 0o777 if path.exists() else None}
        if len(target) == 3 and saved[path]['raw'] != target[2]:
            raise ValueError('Installation target changed after ownership check')
    backup.mkdir(parents=True, mode=0o700)
    manifest = []
    for index, (path, old) in enumerate(saved.items()):
        if old['raw'] is not None:
            (backup / str(index)).write_bytes(old['raw'])
        manifest.append({'path': str(path), 'backup': str(index) if old['raw'] is not None else None,
                         'symlink': old['link'], 'mode': old['mode']})
    (backup / 'manifest.json').write_bytes(catalogs.encoded(manifest))
    written = []
    try:
        for path, target in targets.items():
            raw, mode = target[:2]
            old = saved[path]
            if (path.read_bytes() if path.exists() else None) != old['raw']:
                raise ValueError('Installation target changed after preflight')
            path.parent.mkdir(parents=True, exist_ok=True)
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                catalogs.atomic_write(path, raw, mode)
            written.append(path)
        if activate:
            activate()
    except BaseException:
        for path in reversed(written):
            if (path.read_bytes() if path.exists() else None) != targets[path][0]:
                continue  # Preserve a concurrent edit; the manifest retains recovery data.
            old = saved[path]
            if old['link'] is not None:
                path.unlink(); path.symlink_to(old['link'])
            elif old['raw'] is None:
                path.unlink()
            else:
                catalogs.atomic_write(path, old['raw'], old['mode'])
        if recover:
            recover()
        raise


def run(command, required=True):
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if required and result.returncode:
        raise RuntimeError('Catalog scheduler command failed')
    return result.returncode == 0


def retire_native_claude_keychain(backup):
    """Archive the native login privately before removing its active record.

    No token refresh or upstream revocation occurs. Secret subprocess output
    never reaches logs, and a concurrent credential refresh prevents deletion.
    """
    if sys.platform != 'darwin':
        return 'not applicable'
    service = 'Claude Code-credentials'
    lookup = ['security', 'find-generic-password', '-s', service]
    metadata = subprocess.run(lookup, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
    if metadata.returncode == 44:
        return 'no native record'
    if metadata.returncode:
        raise ValueError('Native Claude keychain metadata is unavailable')
    secret = subprocess.run([*lookup, '-w'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    if secret.returncode or not secret.stdout.strip():
        raise ValueError('Native Claude login could not be backed up; record retained')
    folder = backup / 'native-claude-keychain'
    folder.mkdir(mode=0o700)
    catalogs.atomic_write(folder / 'credentials.private', secret.stdout, 0o600)
    catalogs.atomic_write(folder / 'attributes.private', metadata.stdout, 0o600)
    latest = subprocess.run([*lookup, '-w'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    if latest.returncode or latest.stdout != secret.stdout:
        raise ValueError('Native Claude login changed during backup; record retained')
    result = subprocess.run(['security', 'delete-generic-password', '-s', service],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if result.returncode:
        raise ValueError('Native Claude keychain record could not be retired; backup retained')
    return 'privately archived and retired'


def scheduler(command, state, targets):
    """Return activation/recovery operations; read state before any mutation."""
    if sys.platform == 'darwin':
        path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
        domain = 'gui/' + str(os.getuid())
        was_loaded = run(['launchctl', 'print', domain + '/' + LABEL], False)
        body = {'Label': LABEL, 'ProgramArguments': command, 'StartInterval': 300, 'RunAtLoad': True,
                'StandardOutPath': str(state / 'sync.log'), 'StandardErrorPath': str(state / 'sync-error.log')}
        targets[path] = (plistlib.dumps(body), 0o600)
        def activate():
            run(['launchctl', 'bootout', domain + '/' + LABEL], False)
            run(['launchctl', 'bootstrap', domain, str(path)])
        def recover():
            run(['launchctl', 'bootout', domain + '/' + LABEL], False)
            if was_loaded:
                run(['launchctl', 'bootstrap', domain, str(path)], False)
    else:
        folder = Path.home() / '.config/systemd/user'
        quote = lambda value: json.dumps(value).replace('%', '%%').replace('$', '$$')
        service = '[Unit]\nDescription=Synchronize scoped CPA model catalogs\n[Service]\nType=oneshot\nExecStart=' + ' '.join(map(quote, command)) + '\n'
        timer = '[Unit]\nDescription=Refresh CPA catalogs every five minutes\n[Timer]\nOnBootSec=30\nOnUnitActiveSec=300\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
        targets[folder / (LABEL + '.service')] = (service.encode(), 0o600)
        targets[folder / (LABEL + '.timer')] = (timer.encode(), 0o600)
        was_enabled = run(['systemctl', '--user', 'is-enabled', LABEL + '.timer'], False)
        was_active = run(['systemctl', '--user', 'is-active', LABEL + '.timer'], False)
        def activate():
            run(['systemctl', '--user', 'daemon-reload'])
            run(['systemctl', '--user', 'enable', '--now', LABEL + '.timer'])
        def recover():
            run(['systemctl', '--user', 'daemon-reload'], False)
            run(['systemctl', '--user', 'enable' if was_enabled else 'disable', LABEL + '.timer'], False)
            run(['systemctl', '--user', 'start' if was_active else 'stop', LABEL + '.timer'], False)
    return activate, recover


# Ownership fingerprints of the complete old workaround. Edited files are retained.
LEGACY_PROMPT_FILES = {
    'plugin.mjs': 'd0ed066ba376774845ed9ec25730b6984bf4482d5965bc851f9c1cedb84e3c37',
    'identity.mjs': 'd488b2b6caa51d98cdf9b0e6cc70d456d3bd075a68429d7f4a2753c19e70eefa',
    'vendor/codex.txt': 'c30bca40693a47965e25ceac3f02d3709712af7abeab1278bba53a9efcffa928',
    'vendor/gpt.txt': '83a66a46a5febbc21454161d5f053638b22d25d95e09d77b8f6da33debc848ad',
}


def legacy_prompt_targets(root, binary, major_version):
    """Archive only known unchanged loaders when their harness runs OpenCode 2.

    V2's stock OpenAI prompt selection no longer mistakes codex-oauth routes for
    Codex models. Porting the obsolete prefix substitution would add no benefit.
    """
    if major_version != 2:
        return {}
    paths = [root / scope / 'config/opencode/plugins/cpa-prompt-identity.js'
             for scope in ('personal', 'work')]
    global_binary = shutil.which('opencode')
    if global_binary and Path(global_binary).resolve() == Path(binary).resolve():
        paths.append(Path.home() / '.config/opencode/plugins/cpa-prompt-identity.js')
    targets = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        loader = path.read_bytes()
        try:
            text = loader.decode('utf-8')
        except UnicodeDecodeError:
            continue
        match = re.fullmatch(r'export \{ default \} from "(file://[^"\n]+)";\n?', text)
        if not match:
            continue
        parsed = urllib.parse.urlsplit(match[1])
        if parsed.netloc or parsed.query or parsed.fragment:
            continue
        module = Path(urllib.parse.unquote(parsed.path))
        if module.name != 'plugin.mjs' or module.parent.name != 'opencode-prompt-identity':
            continue
        if all((module.parent / name).is_file() and
               hashlib.sha256((module.parent / name).read_bytes()).hexdigest() == digest
               for name, digest in LEGACY_PROMPT_FILES.items()):
            targets[path] = (None, 0o600, loader)
    return targets


def t3_pi_targets(root, endpoint, binaries, settings_path=None):
    """Plan two stock Pi instances and retire only the combined CPA discovery.

    Configs and T3 settings join the installer's guarded, backed-up transaction.
    Existing scoped instance overrides and unrelated packages are preserved.
    """
    settings_path = settings_path or Path.home() / '.t3/userdata/settings.json'
    before = settings_path.read_bytes()
    settings = json.loads(before)
    instances = settings.setdefault('providerInstances', {})
    targets = {}
    for scope in ('personal', 'work'):
        profile = root / scope
        snapshot = remote_sync.fetch(endpoint, (profile / 'keys/downstream.key').read_text().strip(), scope)
        live = {m['slug']: catalogs.safe_model(m) for m in snapshot['models']}
        mapped = catalogs.pi_model_map(live)
        cache = catalogs.pi_update(catalogs.read(profile / 'pi/cliproxyapi-models.json'), mapped, live)
        path = profile / 'pi/models.json'
        raw = path.read_bytes()
        native = catalogs.pi_native_update(json.loads(raw), cache, scope, endpoint)
        targets[path] = (catalogs.encoded(native), 0o600, raw)
        path = profile / 'pi/settings.json'
        raw = path.read_bytes()
        config = json.loads(raw)
        config['packages'] = [item for item in config.get('packages', []) if not (
            isinstance(item, str) and re.fullmatch(r'npm:@router-for-me/pi-cliproxyapi-provider(?:@[0-9.]+)?', item))]
        targets[path] = (catalogs.encoded(config), 0o600, raw)
        wrapper = str(profile / 'bin/pi')
        identifier = 'pi_' + scope
        if identifier in instances:
            instance = instances[identifier]
            if instance.get('driver') != 'pi' or instance.get('config', {}).get('binaryPath') != wrapper:
                raise ValueError('Existing T3 Pi instance is not managed by this profile')
        else:
            instances[identifier] = {'driver': 'pi', 'displayName': 'Pi ' + ('P' if scope == 'personal' else 'W'),
                                     'enabled': True, 'config': {'binaryPath': wrapper}}
    legacy = instances.get('pi')
    if legacy and legacy.get('driver') == 'pi' and legacy.get('config', {}).get('binaryPath', 'pi') in (
            'pi', '', str(Path.home() / '.local/bin/pi')):
        legacy['enabled'] = False
        legacy['displayName'] = 'Pi · Legacy home (unmigrated)'
    targets[settings_path] = (catalogs.encoded(settings), 0o600, before)
    return targets

def install(root, endpoint, binaries, schedule=True, pi_selector=False, t3_opencode_services=False, t3_pi_profiles=False, proxy_only=False, cursor_pi_personal=False, shared_settings_url=None):
    if sys.version_info < (3, 11) or sys.platform not in ('darwin', 'linux'):
        raise ValueError('Python 3.11+ on macOS or Linux/WSL required')
    endpoint = remote_sync.origin(endpoint)
    root = root.expanduser().resolve()
    scopes = [s for s in ('personal', 'work') if (root / s / 'keys/downstream.key').is_file()]
    if not scopes:
        raise ValueError('Install scoped profiles and private downstream keys first')
    settings = root / 'gateway.json'
    config = catalogs.read(settings) if settings.exists() else {}
    pi_selector = pi_selector or config.get('pi_selector', False)
    t3_opencode_services = t3_opencode_services or config.get('t3_opencode_services', False)
    t3_pi_profiles = t3_pi_profiles or config.get('t3_pi_profiles', False)
    proxy_only = proxy_only or config.get('proxy_only', False)
    cursor_pi_personal = cursor_pi_personal or config.get('pi_cursor_personal', False)
    binaries = dict(config.get('binaries', {}), **binaries)
    binaries = native_entrypoints(binaries, proxy_only)
    if not binaries:
        raise ValueError('Supply at least one --binary on first installation')
    for name, binary in binaries.items():
        if name not in ('codex', 'claude', 'opencode', 'pi') or not Path(binary).is_absolute() or not os.access(binary, os.X_OK):
            raise ValueError('Harness binaries must exist and be executable absolute paths')
    os.umask(0o077)
    runtime = root / 'sync-runtime'
    state = root / 'sync-state'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = state / 'install-backups' / stamp
    source = Path(__file__).resolve().parent
    config.update(endpoint=endpoint, trust_gateway_templates=True, binaries=binaries,
                  runtime_path=config.get('runtime_path', os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')))
    if proxy_only:
        config.update(proxy_only=True, authoritative_catalog=True, manage_default_homes=True,
                      default_proxy_scope=config.get('default_proxy_scope', 'personal'),
                      pi_cursor_personal=cursor_pi_personal, entrypoint_mode='personal_default', pi_selector=False,
                      shared_settings=True)
        if 'pi' in binaries:
            config['pi_native_catalog'] = True
        pi_selector = False
    if shared_settings_url is not None:
        config['shared_settings_url'] = shared_settings_url
    if pi_selector:
        if 'pi' not in binaries:
            raise ValueError('The Pi selector requires an installed Pi binary')
        if Path(binaries['pi']).resolve() == (Path.home() / '.local/bin/pi').resolve():
            raise ValueError('Use the native Pi binary, not the profile selector')
        config['pi_selector'] = True
    if t3_opencode_services:
        if 'opencode' not in binaries:
            raise ValueError('The T3 service connection requires an installed OpenCode binary')
        if scopes != ['personal', 'work']:
            raise ValueError('The T3 service connection requires both scoped profiles')
        config['t3_opencode_services'] = True
    if t3_pi_profiles:
        if 'pi' not in binaries or scopes != ['personal', 'work']:
            raise ValueError('T3 Pi profiles require both scoped accounts and a native Pi binary')
        config.update(t3_pi_profiles=True, pi_native_catalog=True)
    retired = legacy_prompt_targets(root, binaries['opencode'],
                                   catalogs.opencode_major_version(binaries['opencode'])) if 'opencode' in binaries else {}
    targets = t3_pi_targets(root, endpoint, binaries) if t3_pi_profiles else {}
    targets.update(retired)
    if proxy_only:
        import proxy_only as policy
        import harness_settings
        targets.update(policy.shell_targets(config))
        for scope in scopes:
            if 'pi' not in binaries:
                continue
            path = root / scope / 'pi/settings.json'
            value = json.loads(targets[path][0] if path in targets else path.read_bytes())
            if scope == 'work':
                for field in ('packages', 'extensions'):
                    value[field] = [item for item in value.get(field, []) if 'pi-cursor-sdk' not in str(item)]
                value['enabledModels'] = [item for item in value.get('enabledModels', [])
                                          if item.startswith('cliproxyapi/work/')]
            targets[path] = (catalogs.encoded(value), 0o600)
        if cursor_pi_personal:
            if 'pi' not in binaries:
                raise ValueError('Personal Cursor requires an installed Pi binary')
            extension = Path.home() / '.pi/agent/npm/node_modules/pi-cursor-sdk/dist/index.js'
            if not extension.is_file():
                raise ValueError('Install the existing Cursor SDK extension before enabling the Personal Pi exception')
            path = root / 'personal/pi/settings.json'
            value = json.loads(targets[path][0] if path in targets else path.read_bytes())
            value.setdefault('extensions', [])
            if str(extension) not in value['extensions']:
                value['extensions'].append(str(extension))
            value['enabledModels'] = list(dict.fromkeys([*value.get('enabledModels', []), 'cursor/**']))
            targets[path] = (catalogs.encoded(value), 0o600)
        targets.update(policy.scoped_auth_targets(root, config))
        shared_path = root / 'shared-settings.json'
        shared = harness_settings.validate(catalogs.read(shared_path) if shared_path.exists() else
                     catalogs.read(source.parent.parent / 'client-settings.json'))
        if not shared_path.exists():
            targets[shared_path] = (catalogs.encoded(shared), 0o600)
        prepared = {path: {'before': path.read_bytes() if path.exists() else b'', 'after': value[0]}
                    for path, value in targets.items() if value[0] is not None}
        projected = harness_settings.project(root, shared, prepared)
        targets.update({path: (value['after'], 0o600) for path, value in projected.items()})
        prepared = {path: {'after': value[0]} for path, value in targets.items() if value[0] is not None}
        targets.update(policy.default_home_targets(root, config, prepared))
    targets.update({runtime / name: ((source / name).read_bytes(), 0o600) for name in FILES})
    targets[settings] = (catalogs.encoded(config), 0o600)
    targets[root / 'launch-harness.py'] = ((source / 'launch_harness.py').read_bytes(), 0o600)
    python = python_runtime()
    command = [python, str(runtime / 'remote_sync.py'), '--profiles', str(root), '--apply']
    bin_dir = Path.home() / '.local/bin'
    if proxy_only:
        for harness in binaries:
            command_line = shlex.join([python, str(root / 'launch-harness.py')])
            entry = ('#!/bin/sh\nscope="${AGENT_PROFILE:-personal}"\n'
                     'case "$scope" in personal|work) ;; *) echo "Invalid inherited proxy account" >&2; exit 1 ;; esac\n'
                     'exec ' + command_line + ' "$scope" ' + shlex.quote(harness) + ' "$@"\n')
            targets[Path.home() / '.config/cpa/bin' / harness] = (entry.encode(), 0o700)
    if pi_selector and not proxy_only:
        targets[root / 'select-pi.py'] = ((source / 'select_pi.py').read_bytes(), 0o600)
        entry = '#!/bin/sh\nexec ' + shlex.join([python, str(root / 'select-pi.py')]) + ' "$@"\n'
        targets[bin_dir / 'pi'] = (entry.encode(), 0o700)
    wrapper = '#!/bin/sh\nexec ' + shlex.join(command[:-1]) + ' "$@"\n'
    targets[bin_dir / 'cpa-catalog-sync'] = (wrapper.encode(), 0o700)
    report_command = [python, str(runtime / 'harness_settings.py'), '--profiles', str(root)]
    targets[bin_dir / 'cpa-harness-settings'] = (('#!/bin/sh\nexec ' + shlex.join(report_command) + ' "$@"\n').encode(), 0o700)
    if (bin_dir / 'cpa-catalog-refresh').exists():
        targets[bin_dir / 'cpa-catalog-refresh'] = (wrapper.encode(), 0o700)
    for scope in scopes:
        for harness in binaries:
            script = '#!/bin/sh\nexec ' + shlex.join([python, str(root / 'launch-harness.py'), scope, harness]) + ' "$@"\n'
            for path in (root / scope / 'bin' / harness, bin_dir / (harness + '-' + scope)):
                targets[path] = (script.encode(), 0o700)
    activate, recover = scheduler(command, state, targets) if schedule else (None, None)
    write_transaction(targets, backup, activate, recover)
    keychain = retire_native_claude_keychain(backup) if proxy_only and 'claude' in binaries else 'unchanged'
    return {'profiles': str(root), 'endpoint': endpoint, 'scheduled': schedule, 'backup': str(backup),
            'retiredLegacyPromptLoaders': len(retired), 'nativeClaudeKeychain': keychain}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--binary', action='append', default=[], metavar='NAME=ABSOLUTE_PATH')
    parser.add_argument('--no-schedule', action='store_true')
    parser.add_argument('--pi-selector', action='store_true', help='Install an explicit personal/work chooser as ~/.local/bin/pi')
    parser.add_argument('--t3-opencode-services', action='store_true', help='Connect existing T3 Personal/Work instances to stock OpenCode 2 services')
    parser.add_argument('--t3-pi-profiles', action='store_true', help='Connect Personal/Work T3 instances to scoped native Pi catalogs')
    parser.add_argument('--proxy-only', action='store_true', help='Make proxy discovery authoritative and install scoped entrypoints for all harnesses')
    parser.add_argument('--cursor-pi-personal', action='store_true', help='Preserve the existing native Cursor SDK only in Personal Pi')
    parser.add_argument('--shared-settings-url', help='HTTPS URL of the reviewed shared settings JSON, containing no credentials')
    args = parser.parse_args()
    print(json.dumps(install(args.profiles, args.endpoint, dict(item.split('=', 1) for item in args.binary), not args.no_schedule, args.pi_selector, args.t3_opencode_services, args.t3_pi_profiles, args.proxy_only, args.cursor_pi_personal, args.shared_settings_url), indent=2))
