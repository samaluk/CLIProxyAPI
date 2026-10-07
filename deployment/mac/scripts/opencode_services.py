"""Connect existing scoped T3 instances to settled, stock OpenCode 2 services."""
import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

import refresh_scoped_catalogs as catalogs


def command(binary, *args):
    result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        # CLI output may contain a password or a provider response.
        raise ValueError('Scoped OpenCode service command failed')
    return result.stdout.strip()


def request(url, password, path, method='GET'):
    auth = base64.b64encode(('opencode:' + password).encode()).decode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), catalogs.NoRedirect())
    with opener.open(urllib.request.Request(url + path, headers={'Authorization': 'Basic ' + auth},
                                          method=method), timeout=20) as response:
        return json.load(response)


def settled_models(url, password, scope, expected, directory):
    """The first nonempty snapshot can contain only built-ins, before policies load."""
    path = '/api/model?' + urllib.parse.urlencode({'location[directory]': str(directory)})
    deadline = time.monotonic() + 15
    while True:
        models = request(url, password, path)['data']
        actual = {f"{m['providerID']}/{m['id']}" for m in models}
        if expected <= actual and actual and all(m.startswith('cpa-' + scope + '/') for m in actual):
            return len(actual)
        if time.monotonic() >= deadline:
            raise ValueError('Scoped OpenCode catalog did not settle')
        time.sleep(.2)


def connect_t3(path, root, connections):
    """Change only existing instances already assigned to these scoped wrappers."""
    before = path.read_bytes()
    settings = json.loads(before)
    changed = False
    for scope, connection in connections.items():
        instance = settings.get('providerInstances', {}).get('opencode_' + scope)
        wrapper = str(root / scope / 'bin/opencode')
        if not instance or instance.get('driver') != 'opencode' or instance.get('config', {}).get('binaryPath') != wrapper:
            raise ValueError('T3 scoped OpenCode instance does not match installed profile')
        config = instance['config']
        for name, value in [('serverUrl', connection['url']), ('serverPassword', connection['password'])]:
            if config.get(name) != value:
                config[name] = value
                changed = True
    if changed:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root / 'sync-state/t3-backups' / (stamp + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        catalogs.atomic_write(backup, before, 0o600)
        # Detect an edit made while we prepared the patch instead of overwriting it.
        if path.read_bytes() != before:
            raise ValueError('T3 settings changed during reconciliation')
        catalogs.atomic_write(path, catalogs.encoded(settings), 0o600)
    return changed


def reconcile(root, changed_files, t3_path=None):
    connections, receipts = {}, []
    state_path = root / 'sync-state/opencode-services.json'
    previous = catalogs.read(state_path) if state_path.exists() else {}
    revisions = {}
    for scope, port in [('personal', 49374), ('work', 49375)]:
        profile = root / scope
        binary = profile / 'bin/opencode'
        if catalogs.opencode_major_version(str(binary)) != 2:
            raise ValueError('The T3 service connection requires stock OpenCode 2')
        config_path = profile / 'config/opencode/service.json'
        config = catalogs.read(config_path) if config_path.exists() else {}
        # Defaults are loopback and port 49374. Preserve the existing password.
        if config.get('hostname', '127.0.0.1') != '127.0.0.1':
            raise ValueError('Scoped OpenCode service must listen on loopback')
        url = command(binary, 'service', 'status')
        if config.get('port', 49374) != port:
            if url != 'stopped':
                raise ValueError('Configure the scoped OpenCode port before connecting an active service')
            command(binary, 'service', 'set', 'port', str(port))
        if url == 'stopped':
            command(binary, 'service', 'start')
            url = command(binary, 'service', 'status')
        if url != f'http://127.0.0.1:{port}':
            raise ValueError('Scoped OpenCode service has an unexpected address')
        registry = catalogs.read(profile / 'state/opencode/service.json')
        password = registry['password']
        if registry.get('url') != url or not password:
            raise ValueError('Scoped OpenCode service registry does not match')
        definition_path = profile / 'config/opencode/opencode.json'
        revision = hashlib.sha256(definition_path.read_bytes()).hexdigest()
        if previous.get(scope) != revision or definition_path in changed_files:
            # Stock reload retains running sessions at their next step boundary.
            command(binary, 'reload')
        definition = catalogs.read(definition_path)
        expected = {f'{p}/{m}' for p, value in definition['provider'].items() for m in value.get('models', {})}
        count = settled_models(url, password, scope, expected, Path.home())
        connections[scope] = {'url': url, 'password': password}
        revisions[scope] = revision
        receipts.append({'scope': scope, 'url': url, 'models': count})
    changed = connect_t3(t3_path or Path.home() / '.t3/userdata/settings.json', root, connections)
    catalogs.atomic_write(state_path, catalogs.encoded(revisions), 0o600)
    return {'services': receipts, 't3SettingsChanged': changed}
