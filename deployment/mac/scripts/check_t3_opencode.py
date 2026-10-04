#!/usr/bin/env python3
"""Probe T3's OpenCode v2 authenticated catalog contract through scoped launchers.
Starts only a temporary local server; creates no conversation or model request.
"""
import base64, json, os, re, secrets, signal, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

ROOT = Path.home() / 'Library/Application Support/Agent Profiles'

def check(scope):
    password = secrets.token_urlsafe(32)
    env = dict(os.environ, OPENCODE_PASSWORD=password)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(ROOT / scope / 'bin/opencode'), 'serve', '--hostname=127.0.0.1', '--port=0'],
                                   env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            url = None
            while time.monotonic() < deadline:
                log.seek(0); output = log.read().decode(errors='replace')
                match = re.search(r'server listening on\s+(https?://[^\s]+)', output, re.I)
                if match:
                    url = match[1]; break
                if process.poll() is not None: break
                time.sleep(.1)
            if not url:
                return {'scope': scope, 'ok': False, 'reason': 'Server did not report readiness'}
            auth = base64.b64encode(('opencode:' + password).encode()).decode()
            def get(path):
                return json.load(urlopen(Request(url + path, headers={'Authorization': 'Basic ' + auth}), timeout=30))
            try:
                info = get('/api/info')
                # Same local default directory as the spawned server.
                models = get('/api/model?' + urlencode({'location[directory]': str(Path.home())}))['data']
                settle_deadline = time.monotonic() + 20
                while (not models or any(m['providerID'] != f'cpa-{scope}' for m in models)) and time.monotonic() < settle_deadline:
                    time.sleep(.5)
                    models = get('/api/model?' + urlencode({'location[directory]': str(Path.home())}))['data']
            except HTTPError as error:
                return {'scope': scope, 'ok': False, 'httpStatus': error.code,
                        'reason': 'T3 server password rejected' if error.code == 401 else 'API request failed'}
            config = json.loads((ROOT / scope / 'config/opencode/opencode.json').read_text())
            expected = {f'{provider}/{model}' for provider, value in config['provider'].items() for model in value.get('models', {})}
            actual = {f"{m['providerID']}/{m['id']}" for m in models}
            missing = sorted(expected - actual)
            foreign = sorted(x for x in actual if not x.startswith(f'cpa-{scope}/'))
            return {'scope': scope, 'ok': bool(actual) and not missing and not foreign,
                    'version': info['version'], 'expectedModels': len(expected), 'catalogModels': len(actual),
                    'missingCount': len(missing), 'missingSample': missing[:3], 'foreignScopeModels': foreign}
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()

if __name__ == '__main__':
    results = [check(scope) for scope in ('personal', 'work')]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r['ok'] for r in results) else 1)
