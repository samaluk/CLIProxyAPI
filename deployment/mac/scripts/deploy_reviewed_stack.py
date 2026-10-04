#!/usr/bin/env python3
"""Install a verified reviewed app/core pair. No mutation without --execute.

Coordinate an idle restart window before execution. The active request-file
check is a best-effort guard, not proof that every client is idle. This swaps
only the app, core executable and core provenance; it never restores auth,
session state or configuration. Backups and startup logs remain private.
"""
from pathlib import Path
import argparse
import ctypes
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import time
import tomllib
import urllib.parse
import urllib.request
import uuid

LAB = Path(os.environ.get('CPA_STATE_DIR', str(Path.home()/'.local/state/cpa-stack')))
DATA = Path.home() / 'Library/Application Support/com.cpa.gui'
CORE = DATA / 'cpa-core'
APP = Path('/Applications/EasyCLIProxyAPI.app')
PROFILES = Path.home() / 'Library/Application Support/Agent Profiles'
APP_SOURCE = Path(os.environ.get('CPA_APP_SOURCE', '/Applications/EasyCLIProxyAPI.app'))
APP_SHA = None
APP_HEAD = None
STATE_ROOT = LAB / 'private/reviewed-deployments'
MANIFEST_URL = 'https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/core.json'
CORE_BINARY = CORE / 'cli-proxy-api'
GUI_CONFIG = DATA / 'config.toml'
CORE_FILES = ('cpa-gui-meta.json', 'reviewed-core.json')
CAP_FIELDS = ('canonical_model_id', 'context_window', 'max_context_window', 'max_tokens',
              'max_output_tokens', 'input_modalities', 'supported_input_modalities',
              'output_modalities', 'supported_reasoning_levels', 'default_reasoning_level')


def gui_config_semantics(config):
    """An omitted new false default is equivalent to the GUI writing it out."""
    result = dict(config)
    result.setdefault('auth-dir-user-selected', False)
    return result


def reviewed_release_tag(tag):
    """Allow the legacy SHA tag and unique dated builds without URL syntax."""
    return isinstance(tag, str) and re.fullmatch(
        r'v[0-9]+\.[0-9]+\.[0-9]+-review\.[0-9a-f]+(?:\.[0-9]{8}(?:\.[0-9]+)?)?', tag
    ) is not None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True)


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_copy(source, target):
    temporary = target.with_name('.' + target.name + '.stage-' + uuid.uuid4().hex)
    try:
        shutil.copy2(source, temporary)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def app_binary(path):
    return path / 'Contents/MacOS/cpa-gui'


def verify_app(path, expected):
    require(path.is_dir() and not path.is_symlink(), 'App bundle is absent or symlinked')
    require(sha(app_binary(path)) == expected, 'App executable checksum mismatch')
    run('codesign', '--verify', '--deep', '--strict', str(path))


def tree_digest(path):
    """Verify copied app contents, including relative symlink targets."""
    digest = hashlib.sha256()
    for item in sorted(path.rglob('*')):
        relative = str(item.relative_to(path))
        if item.is_symlink():
            value = ['symlink', relative, os.readlink(item)]
        elif item.is_file():
            value = ['file', relative, sha(item), item.stat().st_mode & 0o777]
        else:
            value = ['directory', relative, item.stat().st_mode & 0o777]
        digest.update(json.dumps(value, separators=(',', ':')).encode() + b'\n')
    return digest.hexdigest()


def exchange_directories(left, right):
    """Atomic macOS exchange: neither live path disappears if rename fails."""
    require(left.is_dir() and right.is_dir(), 'Both app directories must exist before exchange')
    require(left.stat().st_dev == right.stat().st_dev, 'App exchange must use one filesystem')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # RENAME_SWAP is defined as 0x00000002 in the local macOS SDK's stdio.h.
    if rename(os.fsencode(left), os.fsencode(right), 0x2) != 0:
        raise OSError(ctypes.get_errno(), 'Atomic app directory exchange failed')


def inventory():
    wanted = {str(app_binary(APP)), str(CORE_BINARY)}
    found = {}
    for line in run('ps', '-axo', 'pid=,comm=').stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1] in wanted:
            pid = int(parts[0])
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], capture_output=True, text=True)
            if result.returncode == 1 or not result.stdout.strip():
                continue  # Process exited between the two read-only snapshots.
            require(result.returncode == 0, 'Could not identify exact process start time')
            started = result.stdout.strip()
            found[pid] = {'path': parts[1], 'started': started}
    return found


def check_active_requests(processes):
    for pid in processes:
        result = subprocess.run(['lsof', '-p', str(pid), '-Fn'], capture_output=True, text=True)
        require(result.returncode == 0, 'Could not inspect exact process open files')
        require('/request-log-parts-request-body-' not in result.stdout,
                'An active request body is open; no process stopped')


def port_open():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', 8317)) == 0


def listener_pids():
    result = subprocess.run(['lsof', '-nP', '-iTCP:8317', '-sTCP:LISTEN', '-t'], capture_output=True, text=True)
    require(result.returncode in (0, 1), 'Could not inspect the proxy listener')
    return {int(pid) for pid in result.stdout.split()}


def stop_exact(expected, on_signal=None):
    current = inventory()
    require(current == expected, 'App/core PID identity changed before stop')
    check_active_requests(current)
    # Signal only the identities just checked. GUI exit can also stop the core.
    for pid, identity in current.items():
        present = inventory()
        if pid not in present:
            continue
        require(present[pid] == identity, 'A process identity changed during stop')
        if on_signal:
            on_signal()
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    # Core cleanup can take thirty seconds after SIGTERM. Allow that cleanup
    # to finish before recovery, while retaining the no-force-kill boundary.
    deadline = time.monotonic() + 60
    while inventory() and time.monotonic() < deadline:
        time.sleep(.2)
    require(not inventory(), 'App/core did not stop gracefully; no forced kill attempted')
    require(not port_open(), 'Unexpected proxy listener remains after stop')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Deployment:
    def __init__(self, args):
        self.args = args
        self.state = STATE_ROOT / ('update-guards-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
        self.state.mkdir(mode=0o700)
        self.backup = self.state / 'previous'
        self.backup.mkdir(mode=0o700)
        self.app_stage_root = None
        self.staged_app = None
        self.staged_core = None
        self.stopped = False
        self.stop_attempted = False
        self.exchanged = False
        self.core_replaced = False
        self.child = None
        self.report = {'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       'state': str(self.state), 'deployed': False, 'method': 'guarded shell bootstrap; no GUI click-through claim'}

    def record(self, phase):
        self.report['phase'] = phase
        (self.state / 'deployment.json').write_text(json.dumps(self.report, indent=2) + '\n')
        print(phase, flush=True)

    def request(self, path, key):
        request = urllib.request.Request('http://127.0.0.1:8317' + path, headers={'Authorization': 'Bearer ' + key})
        with self.opener.open(request, timeout=4) as response:
            return json.load(response)

    def health(self):
        models = {}
        for key in self.keys:
            response = self.request('/v1/models?client_version=pi', key)
            require(isinstance(response.get('models'), list), 'Rich catalog envelope is missing')
            for model in response['models']:
                values = {}
                for field in CAP_FIELDS:
                    value = model.get(field)
                    if value is None:
                        continue
                    if field == 'supported_reasoning_levels':
                        value = sorted(set(item['effort'] for item in value))
                    elif field.endswith('modalities'):
                        value = sorted(set(value))
                    values[field] = value
                route = model['slug']
                require(route not in models or models[route] == values, 'Scoped catalogs disagree about one route')
                models[route] = values
        plugins = self.request('/v0/management/plugins', self.management)
        registered = {plugin['id']: {'enabled': plugin.get('effective_enabled'), 'version': plugin.get('metadata', {}).get('version')}
                      for plugin in plugins['plugins'] if plugin.get('registered')}
        require(models, 'Catalog baseline is empty')
        return {'models': models, 'plugins': registered}

    def differences(self, after):
        changes = []
        for route, fields in self.before['models'].items():
            if route not in after['models']:
                changes.append({'route': route, 'field': 'missing'})
            else:
                for name, value in fields.items():
                    if after['models'][route].get(name) != value:
                        changes.append({'route': route, 'field': name})
        for name, value in self.before['plugins'].items():
            if after['plugins'].get(name) != value:
                changes.append({'plugin': name, 'field': 'registration/version'})
        return changes

    def protected_ok(self):
        require(all(path.is_file() and sha(path) == expected for path, expected in self.protected.items()),
                'Protected configuration changed; do not overwrite a concurrent edit')
        require(gui_config_semantics(tomllib.loads(GUI_CONFIG.read_text())) == gui_config_semantics(self.gui_config), 'GUI configuration changed semantically')

    def prepare(self):
        require(hasattr(ctypes.CDLL(None), 'renamex_np'), 'Atomic app exchange is unavailable')
        require(not APP.is_symlink() and not CORE_BINARY.is_symlink(), 'Live app/core path is symlinked')
        self.manifest = json.loads(self.args.core_manifest.read_text())
        m = self.manifest
        require(set(m) == {'schema_version', 'revision', 'repository', 'tag', 'commit', 'assets'}, 'Unexpected core manifest schema')
        require(m['schema_version'] == 1 and type(m['revision']) is int and m['revision'] > 0, 'Positive manifest revision required')
        require(m['repository'] == 'samaluk/CLIProxyAPI' and re.fullmatch('[0-9a-f]{40}', m['commit']), 'Unexpected reviewed repository or commit')
        require(reviewed_release_tag(m['tag']), 'Unexpected reviewed release tag')
        assets = [asset for asset in m['assets'] if asset.get('os') == 'darwin' and asset.get('arch') == 'arm64']
        require(len(assets) == 1, 'Exactly one macOS ARM64 asset is required')
        self.asset = assets[0]
        asset = self.asset
        expected_url = f"https://github.com/{m['repository']}/releases/download/{m['tag']}/cli-proxy-api_darwin_arm64.tar.gz"
        require(asset['url'] == expected_url and re.fullmatch('[0-9a-f]{64}', asset['sha256']), 'Manifest asset is not pinned to the reviewed release')
        require(type(asset['size']) is int and 0 < asset['size'] <= 512 * 1024 * 1024, 'Invalid archive size')
        require(self.args.core_archive.stat().st_size == asset['size'] and sha(self.args.core_archive) == asset['sha256'], 'Core archive checksum or size mismatch')
        require(re.fullmatch('[0-9a-f]{64}', self.args.core_binary_sha256), 'Expected core binary SHA256 is invalid')
        self.candidate = self.state / 'core-candidate'
        with tarfile.open(self.args.core_archive) as archive:
            members = archive.getmembers()
            require(len(members) == 1 and members[0].isfile() and members[0].name == 'cli-proxy-api', 'Archive must contain only the root executable')
            require(0 < members[0].size <= 512 * 1024 * 1024, 'Invalid core executable size')
            with archive.extractfile(members[0]) as source, self.candidate.open('xb') as target:
                shutil.copyfileobj(source, target)
        self.candidate.chmod(0o755)
        require(sha(self.candidate) == self.args.core_binary_sha256, 'Core executable checksum mismatch')
        run('codesign', '--verify', '--strict', str(self.candidate))
        banner = run(str(self.candidate), '-h').stdout.splitlines()[0]
        require(m['tag'][1:] in banner and m['commit'] in banner, 'Core build identity does not match manifest')
        verify_app(APP_SOURCE, APP_SHA)
        self.old_app_sha = sha(app_binary(APP))
        verify_app(APP, self.old_app_sha)
        self.old_app_tree = tree_digest(APP)
        self.old_core_sha = sha(CORE_BINARY)
        self.old_provenance = json.loads((CORE / 'reviewed-core.json').read_text())
        self.old_metadata_hashes = {name: sha(CORE / name) if (CORE / name).exists() else None for name in CORE_FILES}
        require(self.old_provenance.get('binarySha256') == self.old_core_sha, 'Installed core provenance checksum mismatch')
        require(type(self.old_provenance.get('revision')) is int and self.old_provenance['revision'] > 0, 'Seed and verify the current core revision before this deployment')
        require(m['revision'] > self.old_provenance['revision'], 'New core revision must be strictly newer than the installed revision')
        self.gui_config = tomllib.loads(GUI_CONFIG.read_text())
        require(self.gui_config.get('port', 8317) == 8317, 'This helper requires the existing 8317 listener')
        require(self.gui_config.get('reviewed-core-manifest-url') == self.args.manifest_url, 'GUI reviewed channel differs from the deployment channel')
        channel = urllib.parse.urlsplit(self.args.manifest_url)
        require(channel.scheme == 'https' and channel.hostname and not channel.username and not channel.password and not channel.query and not channel.fragment,
                'Reviewed channel must remain a plain HTTPS URL')
        self.management = self.gui_config['management-secret-key']
        self.keys = [(PROFILES / scope / 'keys/downstream.key').read_text().strip() for scope in ('personal', 'work')]
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.before = self.health()
        require({'commandcode', 'opencode-go-cliproxyapi', 'key-account-bind'} <= self.before['plugins'].keys(), 'Required plugin baseline is missing')
        if self.args.expected_route_count is not None:
            require(len(self.before['models']) == self.args.expected_route_count, 'Live route count differs from the expected baseline')
        (self.state / 'baseline.json').write_text(json.dumps(self.before, indent=2) + '\n')
        main_config = Path.home() / '.codex/config.toml'
        protected = [main_config, PROFILES / 'launch-harness.py', Path.home() / '.t3/userdata/settings.json', CORE / 'config.yaml']
        main = tomllib.loads(main_config.read_text())
        if main.get('model_catalog_json'):
            catalog = Path(main['model_catalog_json']).expanduser()
            protected.append(catalog if catalog.is_absolute() else main_config.parent / catalog)
        protected.extend(self.args.protect)
        self.protected = {path: sha(path) for path in protected}
        self.original_pids = inventory()
        require(any(item['path'] == str(app_binary(APP)) for item in self.original_pids.values()), 'Expected running Easy app is absent')
        core_pids = {pid for pid, item in self.original_pids.items() if item['path'] == str(CORE_BINARY)}
        require(len(core_pids) == 1 and listener_pids() == core_pids, 'Proxy listener is not the exact expected core process')
        # All copying happens before the restart. The app stage is on the live
        # app filesystem; the core stage/atomic copies use its own filesystem.
        run('ditto', str(APP), str(self.backup / 'EasyCLIProxyAPI.app'))
        require(tree_digest(self.backup / 'EasyCLIProxyAPI.app') == self.old_app_tree, 'Whole-app backup differs')
        verify_app(self.backup / 'EasyCLIProxyAPI.app', self.old_app_sha)
        shutil.copy2(CORE_BINARY, self.backup / 'core-binary')
        require(sha(self.backup / 'core-binary') == self.old_core_sha, 'Core backup differs')
        for name in CORE_FILES:
            if (CORE / name).exists():
                shutil.copy2(CORE / name, self.backup / name)
        for index, path in enumerate([*self.protected, GUI_CONFIG]):
            shutil.copy2(path, self.backup / f'protected-{index:02d}')
        self.app_stage_root = Path('/Applications') / ('.cpa-update-guards-' + uuid.uuid4().hex)
        self.app_stage_root.mkdir(mode=0o700)
        self.staged_app = self.app_stage_root / 'EasyCLIProxyAPI.app'
        run('ditto', str(APP_SOURCE), str(self.staged_app))
        verify_app(self.staged_app, APP_SHA)
        require(tree_digest(self.staged_app) == tree_digest(APP_SOURCE), 'Staged app differs from its source')
        require(self.staged_app.stat().st_dev == APP.stat().st_dev, 'Staged app is on a different filesystem')
        self.staged_core = CORE / ('.cli-proxy-api.update-guards-' + uuid.uuid4().hex)
        shutil.copy2(self.candidate, self.staged_core)
        require(sha(self.staged_core) == self.args.core_binary_sha256, 'Core stage differs from candidate')
        with self.staged_core.open('rb') as stream:
            os.fsync(stream.fileno())
        fsync_dir(CORE)
        self.report.update({'appHead': APP_HEAD, 'appBuildProfile': 'release optimized', 'appSha256': APP_SHA,
                            'oldAppSha256': self.old_app_sha, 'coreCommit': m['commit'], 'coreVersion': m['tag'][1:],
                            'coreSha256': self.args.core_binary_sha256, 'oldCoreSha256': self.old_core_sha,
                            'revision': m['revision'], 'oldRevision': self.old_provenance['revision'],
                            'appSwapBackup': str(self.staged_app), 'backup': str(self.backup),
                            'routesBefore': len(self.before['models'])})
        self.record('prepared and verified; live components unchanged')

    def start_core(self):
        require(not inventory() and not port_open(), 'A process appeared before core startup')
        environment = os.environ.copy()
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
            environment.pop(name, None)
        with (self.state / 'core-startup.log').open('ab') as log:
            self.child = subprocess.Popen([str(CORE_BINARY), '-config', str(CORE / 'config.yaml')], cwd=CORE,
                                          env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                          start_new_session=True)
        return self.wait_health(require_gui=False)

    def wait_health(self, require_gui):
        deadline = time.monotonic() + 45
        consecutive = 0
        differences = []
        while time.monotonic() < deadline:
            require(self.child is not None and self.child.poll() is None, 'Core child exited during startup')
            try:
                current = inventory()
                require(self.child.pid in current, 'Started core identity is missing')
                require(listener_pids() == {self.child.pid}, 'Proxy listener changed ownership')
                if require_gui:
                    require(any(value['path'] == str(app_binary(APP)) for value in current.values()), 'GUI has not launched')
                after = self.health()
                differences = self.differences(after)
                self.protected_ok()
                if not differences:
                    consecutive += 1
                    if consecutive >= 3:
                        return after
                else:
                    consecutive = 0
            except Exception:
                consecutive = 0
            time.sleep(.25)
        (self.state / 'health-differences.json').write_text(json.dumps(differences, indent=2) + '\n')
        raise RuntimeError('Core/GUI did not reach a stable preserved catalog and configuration')

    def write_provenance(self):
        now = int(time.time())
        metadata = {'version': self.manifest['tag'][1:], 'assetName': self.asset['url'].rsplit('/', 1)[1], 'installedAtUnix': now}
        provenance = {'manifestUrl': self.args.manifest_url, 'repository': self.manifest['repository'],
                      'tag': self.manifest['tag'], 'commit': self.manifest['commit'], 'archiveSha256': self.asset['sha256'],
                      'binarySha256': self.args.core_binary_sha256, 'installedAtUnix': now,
                      'backupDir': str(self.backup), 'revision': self.manifest['revision']}
        for name, value in [('cpa-gui-meta.json', metadata), ('reviewed-core.json', provenance)]:
            source = self.state / name
            source.write_text(json.dumps(value, indent=2) + '\n')
            atomic_copy(source, CORE / name)

    def exchange_app(self):
        exchange_directories(self.staged_app, APP)
        # Record the successful atomic exchange before fallible durability work.
        self.exchanged = not self.exchanged
        fsync_dir(APP.parent)
        fsync_dir(self.staged_app.parent)

    def rollback(self):
        current = inventory()
        if current:
            stop_exact(current)
        require(not port_open(), 'Unknown listener prevents safe rollback')
        recovery_errors = []
        try:
            if self.exchanged:
                verify_app(self.staged_app, self.old_app_sha)
                self.exchange_app()
            verify_app(APP, self.old_app_sha)
        except BaseException as error:
            recovery_errors.append(error)
        # Attempt every component even if a previous rename succeeded and its
        # subsequent fsync failed. Never abandon core recovery after app recovery.
        if self.core_replaced:
            try:
                atomic_copy(self.backup / 'core-binary', CORE_BINARY)
            except BaseException as error:
                recovery_errors.append(error)
            for name in CORE_FILES:
                try:
                    if (self.backup / name).exists():
                        atomic_copy(self.backup / name, CORE / name)
                    else:
                        (CORE / name).unlink(missing_ok=True)
                except BaseException as error:
                    recovery_errors.append(error)
        if recovery_errors:
            raise RuntimeError('Component recovery encountered an error; both restorations were attempted and backups retained') from recovery_errors[0]
        require(sha(CORE_BINARY) == self.old_core_sha, 'Previous core restoration failed')
        # Never restore configuration or rotated OAuth/session state. If another
        # writer changed protected settings, retain backups for a manual merge.
        self.protected_ok()
        self.start_core()
        run('open', '-a', str(APP))
        self.wait_health(require_gui=True)
        self.report['rolledBack'] = True
        self.record('previous app and core restored and healthy')

    def execute(self):
        try:
            self.prepare()
            self.protected_ok()
            require(sha(CORE_BINARY) == self.old_core_sha and tree_digest(APP) == self.old_app_tree,
                    'Live binary/app changed during staging')
            require(all((sha(CORE / name) if (CORE / name).exists() else None) == value for name, value in self.old_metadata_hashes.items()),
                    'Core provenance changed during staging')
            require(not self.differences(self.health()), 'Baseline changed during staging')
            # Staging is read-only with respect to the running stack. Wait for
            # an idle window only after that work, immediately before the
            # final identity/activity check in stop_exact.
            idle_deadline = time.monotonic() + 120
            while True:
                require(inventory() == self.original_pids, 'Process identity changed during idle wait')
                try:
                    check_active_requests(self.original_pids)
                    break
                except RuntimeError as idle_error:
                    if str(idle_error) != 'An active request body is open; no process stopped':
                        raise
                    require(time.monotonic() < idle_deadline, 'No idle window observed; live components unchanged')
                    time.sleep(1)
            self.protected_ok()
            def mark_stop():
                self.stop_attempted = True
            stop_exact(self.original_pids, on_signal=mark_stop)
            self.stopped = True
            self.record('original app and core stopped gracefully')
            self.protected_ok()
            self.exchange_app()
            self.record('app atomically exchanged; previous app retained')
            verify_app(APP, APP_SHA)
            # Mark restoration necessary before replacement, including a rare
            # successful rename followed by an fsync failure.
            self.core_replaced = True
            os.replace(self.staged_core, CORE_BINARY)
            fsync_dir(CORE)
            self.start_core()
            self.write_provenance()
            run('open', '-a', str(APP))
            after = self.wait_health(require_gui=True)
            verify_app(APP, APP_SHA)
            require(sha(CORE_BINARY) == self.args.core_binary_sha256, 'Active core changed after GUI adoption')
            require(json.loads((CORE / 'reviewed-core.json').read_text()).get('revision') == self.manifest['revision'], 'Installed revision changed')
            self.protected_ok()
            self.report.update({'deployed': True, 'routesAfter': len(after['models']), 'plugins': after['plugins'],
                                'knownCapabilitiesPreserved': True, 'protectedConfigurationPreserved': True,
                                'mainCodexPreserved': True, 'guiConfigSemanticallyPreserved': True,
                                'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()})
            self.record('deployment complete and verified')
        except BaseException as error:
            self.report['failureType'] = type(error).__name__
            self.record('deployment failed; recovery assessed')
            if self.stop_attempted:
                try:
                    self.rollback()
                except BaseException as recovery_error:
                    self.report['rollbackFailureType'] = type(recovery_error).__name__
                    self.record('automatic recovery incomplete; private backups retained')
                    raise RuntimeError('Deployment and automatic recovery failed; inspect the private state directory') from recovery_error
            raise


def main():
    global APP_SOURCE, APP_SHA, APP_HEAD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-manifest', type=Path, required=True)
    parser.add_argument('--core-archive', type=Path, required=True)
    parser.add_argument('--core-binary-sha256', required=True)
    parser.add_argument('--manifest-url', default=MANIFEST_URL)
    parser.add_argument('--expected-route-count', type=int)
    parser.add_argument('--protect', type=Path, action='append', default=[])
    parser.add_argument('--execute', action='store_true', help='Perform the already-authorized coordinated restart and deployment')
    parser.add_argument('--app-source', type=Path, default=APP_SOURCE)
    parser.add_argument('--app-head', required=True)
    parser.add_argument('--app-binary-sha256', required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.app_head), 'Invalid app source commit')
    require(re.fullmatch('[0-9a-f]{64}', args.app_binary_sha256), 'Invalid app binary checksum')
    APP_SOURCE, APP_HEAD, APP_SHA = args.app_source, args.app_head, args.app_binary_sha256
    if not args.execute:
        print(json.dumps({'mode': 'plan only; no files changed', 'app': str(APP_SOURCE), 'appSha256': APP_SHA,
                          'coreManifest': str(args.core_manifest), 'coreArchive': str(args.core_archive),
                          'coreBinarySha256': args.core_binary_sha256, 'note': 'Run in a coordinated idle restart window; open-file checks are best effort.'}, indent=2))
        return
    os.umask(0o077)
    STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE_ROOT / 'deploy-update-guards.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Deployment(args).execute()


if __name__ == '__main__':
    main()
