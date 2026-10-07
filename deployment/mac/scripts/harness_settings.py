"""Review and project a small, explicit shared policy into native config files.

No provider credentials, prompts, commands or permission grants are accepted.
Unsupported settings remain visible in the report instead of being invented.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.parse
import urllib.request

import refresh_scoped_catalogs as catalogs


def validate(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'harnesses'} or value['schema'] != 1:
        raise ValueError('Unknown shared harness settings schema')
    harnesses = value['harnesses']
    if not isinstance(harnesses, dict) or set(harnesses) != {'codex', 'claude', 'opencode', 'pi'}:
        raise ValueError('Unknown harness settings family')
    codex = harnesses['codex']
    if not isinstance(codex, dict) or set(codex) != {'model_reasoning_effort', 'agents'}:
        raise ValueError('Unknown Codex shared settings')
    if codex['model_reasoning_effort'] not in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Invalid Codex reasoning effort')
    agents_value = codex['agents']
    canonical = 'max_concurrent_threads_per_session'
    if not isinstance(agents_value, dict) or set(agents_value) not in (
            {canonical, 'max_depth'}, {'max_threads', 'max_depth'}):
        raise ValueError('Unknown Codex agent settings')
    capacity = agents_value.get(canonical, agents_value.get('max_threads'))
    if capacity is not None and (type(capacity) is not int or not 1 <= capacity <= 64):
        raise ValueError('Invalid native subagent capacity')
    if type(agents_value['max_depth']) is not int or not 1 <= agents_value['max_depth'] <= 8:
        raise ValueError('Invalid Codex subagent depth')
    claude = harnesses['claude']
    if not isinstance(claude, dict) or set(claude) != {'effortLevel', 'autoCompactEnabled'}:
        raise ValueError('Unknown Claude shared settings')
    if claude['effortLevel'] not in ('low', 'medium', 'high', 'max') or type(claude['autoCompactEnabled']) is not bool:
        raise ValueError('Invalid Claude shared setting')
    opencode = harnesses['opencode']
    if not isinstance(opencode, dict) or set(opencode) != {'autoupdate', 'share', 'permission'}:
        raise ValueError('Unknown OpenCode shared settings')
    if type(opencode['autoupdate']) is not bool or opencode['share'] not in ('disabled', 'manual') or opencode['permission'] != 'ask':
        raise ValueError('Invalid OpenCode shared setting')
    pi = harnesses['pi']
    if not isinstance(pi, dict) or set(pi) != {'defaultThinkingLevel', 'hideThinkingBlock', 'compaction'}:
        raise ValueError('Unknown Pi shared settings')
    if pi['defaultThinkingLevel'] not in ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max') or type(pi['hideThinkingBlock']) is not bool:
        raise ValueError('Invalid Pi shared setting')
    if not isinstance(pi['compaction'], dict) or set(pi['compaction']) != {'enabled'} or type(pi['compaction']['enabled']) is not bool:
        raise ValueError('Invalid Pi compaction setting')
    value = copy.deepcopy(value)
    value['harnesses']['codex']['agents'].pop('max_threads', None)
    value['harnesses']['codex']['agents'][canonical] = capacity
    return value


def load(root, settings):
    path = root / 'shared-settings.json'
    cached = validate(json.loads(path.read_text()))
    address = settings.get('shared_settings_url')
    if not address:
        return cached, 'local', None
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Shared settings require an explicit HTTPS data URL')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), catalogs.NoRedirect())
    try:
        with opener.open(address, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Shared settings exceed size limit')
        value = validate(json.loads(raw))
    except Exception:
        # A failed policy fetch cannot replace the last validated policy, and
        # must not stop a successful model exclusion from propagating.
        return cached, 'cached; remote policy unavailable or invalid', None
    after = catalogs.encoded(value)
    return value, 'remote', {'before': path.read_bytes(), 'after': after} if path.read_bytes() != after else None


def agents(raw, values):
    values = dict(values)
    canonical = 'max_concurrent_threads_per_session'
    if 'max_threads' in values:
        values.setdefault(canonical, values.pop('max_threads'))
    pattern = r'(?ms)(^\[agents\]\s*\n)(.*?)(?=^\[|\Z)'
    def update(match):
        body = match[2]
        if canonical in values or re.search(r'(?m)^[ \t]*' + canonical + r'\s*=', body):
            body = re.sub(r'(?m)^[ \t]*max_threads\s*=.*\n?', '', body)
        else:
            body = re.sub(r'(?m)^([ \t]*)max_threads(\s*=)', r'\1' + canonical + r'\2', body)
        for name, value in values.items():
            line = name + ' = ' + json.dumps(value)
            body, count = re.subn(r'(?m)^[ \t]*' + name + r'\s*=.*$', lambda _: line, body)
            if not count:
                body = body.rstrip() + '\n' + line + '\n'
        return match[1] + body
    raw, count = re.subn(pattern, update, raw)
    if not count:
        raw = raw.rstrip() + '\n\n[agents]\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in values.items())
    tomllib.loads(raw)
    return raw


def project(root, policy, prepared):
    """Project each harness's own baseline across that harness's profiles."""
    changes = {}
    defaults = policy['harnesses']
    def read(path):
        return prepared[path]['after'] if path in prepared else path.read_bytes()
    def emit(path, after):
        before = prepared[path]['before'] if path in prepared else path.read_bytes()
        if after != before:
            changes[path] = {'before': before, 'after': after}
    for scope in ('personal', 'work'):
        profile = root / scope
        path = profile / 'codex/config.toml'
        if path.exists():
            raw = read(path).decode()
            effort = defaults['codex']['model_reasoning_effort']
            raw, count = re.subn(r'(?m)^model_reasoning_effort\s*=.*$', lambda _: 'model_reasoning_effort = ' + json.dumps(effort), raw)
            if not count:
                raw = 'model_reasoning_effort = ' + json.dumps(effort) + '\n' + raw
            values = {k: v for k, v in defaults['codex']['agents'].items() if v is not None}
            emit(path, agents(raw, values).encode())
        for harness, relative in (('claude', 'claude/settings.json'), ('pi', 'pi/settings.json'),
                                  ('opencode', 'config/opencode/opencode.json')):
            path = profile / relative
            if path.exists():
                value = json.loads(read(path))
                for key, expected in defaults[harness].items():
                    if isinstance(expected, dict):
                        value.setdefault(key, {}).update(expected)
                    else:
                        value[key] = expected
                emit(path, catalogs.encoded(value))
    return changes


def report(root, policy, machine=None):
    import socket
    machine = machine or socket.gethostname()
    groups = {name: [] for name in ('codex', 'claude', 'opencode', 'pi')}
    for scope in ('personal', 'work'):
        profile = root / scope
        entries = (('codex', profile/'codex/config.toml'), ('claude', profile/'claude/settings.json'),
                   ('opencode', profile/'config/opencode/opencode.json'), ('pi', profile/'pi/settings.json'))
        for harness, path in entries:
            if not path.exists():
                continue
            value = tomllib.loads(path.read_text()) if harness == 'codex' else json.loads(path.read_text())
            configured = {}
            for key in policy['harnesses'][harness]:
                if isinstance(policy['harnesses'][harness][key], dict):
                    configured[key] = {k: value.get(key, {}).get(k) for k in policy['harnesses'][harness][key]}
                else:
                    configured[key] = value.get(key)
            differences = []
            for key, expected in policy['harnesses'][harness].items():
                if key == 'agents':
                    differences.extend('agents.' + k for k, v in expected.items()
                                       if v is not None and configured[key].get(k) != v)
                elif configured[key] != expected:
                    differences.append(key)
            groups[harness].append({'machine': machine, 'profile': scope, 'path': str(path),
                                    'configured': configured, 'drift': differences})
    return {'policy': policy, 'byHarness': groups,
            'note': 'Compare one harness across machines and profiles. Account/model bindings and local paths are expected differences. These are configured values; project or session overrides may change effective behavior.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--ssh', action='append', default=[], metavar='HOST', help='Compare the same harness on another managed machine')
    parser.add_argument('--compare', action='append', default=[], type=Path, metavar='REPORT', help='Merge an exported machine report')
    args = parser.parse_args()
    root = args.profiles.expanduser().resolve()
    policy = validate(json.loads((root/'shared-settings.json').read_text()))
    result = report(root, policy)
    failures = []
    def merge(value):
        if not isinstance(value, dict) or not isinstance(value.get('byHarness'), dict):
            raise ValueError('Invalid harness comparison report')
        for harness, rows in result['byHarness'].items():
            incoming = value['byHarness'].get(harness, [])
            if not isinstance(incoming, list):
                raise ValueError('Invalid harness comparison rows')
            rows.extend(incoming)
    for path in args.compare:
        merge(json.loads(path.read_text()))
    for host in args.ssh:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', host):
            raise ValueError('Invalid SSH comparison host')
        try:
            process = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                                      '"$HOME/.local/bin/cpa-harness-settings"'],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
            if process.returncode or len(process.stdout) > 1024 * 1024:
                raise ValueError('Remote comparison unavailable')
            merge(json.loads(process.stdout))
        except Exception:
            failures.append({'host':host,'status':'unavailable or invalid report'})
    result['unavailableMachines'] = failures
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
