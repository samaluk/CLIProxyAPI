#!/usr/bin/env python3
"""Reconcile managed client catalogs from one explicitly configured TLS gateway.

The server owns discovery. Clients retain prompts, routing IDs, user options and
missing saved models. No upstream OAuth credentials are needed on a client.
"""
import argparse
import ast
import copy
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import traceback
import urllib.error
import urllib.parse
import urllib.request

import refresh_scoped_catalogs as catalogs
from model_labels import model_label


FAILURE_CONTEXT = {}


def phase(name, **context):
    FAILURE_CONTEXT.update(stage=name, stageStartedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), **context)


def failure_receipt(error):
    """Record stack locations and reviewed application messages, never locals.

    Unknown exception text, HTTP bodies and chained exception text are omitted.
    Literal ValueError messages in the installed helpers are safe static prose.
    """
    root = FAILURE_CONTEXT.get('root')
    if root is None:
        return None
    folder = root / 'sync-state/diagnostics'
    if folder.is_symlink() or any(p.is_symlink() for p in folder.parents):
        return None
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_messages = set()
    for name in ('remote_sync.py', 'refresh_scoped_catalogs.py', 'opencode_services.py'):
        tree = ast.parse((Path(__file__).parent / name).read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                    node.func.id == 'ValueError' and node.args and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                safe_messages.add(node.args[0].value)
    message = str(error)
    safe = type(error) is ValueError and (message in safe_messages or
                re.fullmatch(r'Gateway catalog unavailable: HTTP [0-9]{3}', message))
    stamp = datetime.datetime.now(datetime.timezone.utc)
    frames = [{'file': frame.f_code.co_filename, 'line': line, 'function': frame.f_code.co_name}
              for frame, line in traceback.walk_tb(error.__traceback__)]
    receipt = {'failedAt': stamp.isoformat(), 'stage': FAILURE_CONTEXT.get('stage'),
               'stageStartedAt': FAILURE_CONTEXT.get('stageStartedAt'),
               'scope': FAILURE_CONTEXT.get('scope'), 'exception': type(error).__name__,
               'message': message if safe else 'Exception text omitted; inspect stack locations',
               'traceback': frames}
    path = folder / (stamp.strftime('%Y%m%dT%H%M%S%fZ') + '-failure.json')
    catalogs.atomic_write(path, catalogs.encoded(receipt), 0o600)
    return path


def run():
    FAILURE_CONTEXT.clear()
    try:
        main()
        return 0
    except Exception as error:
        try:
            receipt = failure_receipt(error)
        except Exception:
            receipt = None  # A diagnostic write must not obscure the original failure.
        suffix = ' Private failure receipt: ' + str(receipt) if receipt else ''
        print('Catalog sync failed; inspect private sync-state backups before retrying. ' +
              type(error).__name__ + suffix, file=sys.stderr)
        return 1

def origin(value):
    parsed = urllib.parse.urlsplit(value)
    local = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
    if not (local or parsed.scheme == 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Gateway must be an explicit HTTPS origin, or loopback HTTP')
    return value.rstrip('/')


def fetch(endpoint, key, scope, cached=None):
    headers = {'Authorization': 'Bearer ' + key}
    identity = hashlib.sha256((origin(endpoint) + '\n' + scope + '\n' + key).encode()).hexdigest()
    if cached and cached.get('client_identity') != identity:
        cached = None
    if cached and cached.get('scope') == scope:
        headers['If-None-Match'] = '"' + cached['revision'] + '"'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), catalogs.NoRedirect())
    request = urllib.request.Request(origin(endpoint) + '/catalog/v1', headers=headers)
    try:
        with opener.open(request, timeout=50) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError('Catalog exceeds size limit')
            result = json.loads(raw)
    except urllib.error.HTTPError as error:
        if error.code == 304 and cached:
            result = cached
        else:
            raise ValueError('Gateway catalog unavailable: HTTP ' + str(error.code)) from None
    if result.get('schema') != 1 or result.get('scope') != scope or not re.fullmatch('[0-9a-f]{64}', result.get('revision', '')):
        raise ValueError('Catalog identity/schema mismatch')
    models = result.get('models')
    if not isinstance(models, list) or not models:
        raise ValueError('Empty catalog; retain saved definitions')
    seen = set()
    for model in models:
        route = model.get('slug')
        if not isinstance(route, str) or not route.startswith(scope + '/') or route in seen:
            raise ValueError('Foreign or duplicate route; no client changes')
        seen.add(route)
    result['client_identity'] = identity
    return result


def codex_endpoint(raw, endpoint):
    """Change only existing CPA provider URLs, preserving TOML and provider IDs."""
    parsed = tomllib.loads(raw)
    providers = parsed.get('model_providers', {})
    result = raw
    for name in providers:
        if not name.startswith('cpa'):
            continue
        pattern = r'(?ms)(^\[model_providers\.' + re.escape(name) + r'\]\s*\n)(.*?)(?=^\[|\Z)'
        def replace(match):
            body, count = re.subn(r'^base_url\s*=.*$', 'base_url = ' + json.dumps(endpoint + '/v1'), match[2], count=1, flags=re.M)
            if not count:
                raise ValueError('CPA provider has no base_url')
            return match[1] + body
        result, count = re.subn(pattern, replace, result, count=1)
        if count != 1:
            raise ValueError('Unsupported CPA TOML provider table; retain configuration')
    tomllib.loads(result)
    return result


def prepare_profile(root, scope, snapshot, endpoint, trust_templates, binaries=None, pi_native=False):
    profile = root / scope
    live = {m['slug']: catalogs.safe_model(m) for m in snapshot['models']}
    # Explicit null clears an unsupported generic reasoning default.
    for m in snapshot['models']:
        if 'default_reasoning_level' in m and m['default_reasoning_level'] is None:
            live[m['slug']]['default_reasoning_level'] = None
    changes = {}
    pending = []
    def prepare(path, after):
        before = path.read_bytes()
        if before != after:
            changes[path] = {'before': before, 'after': after}
    path = profile / 'catalogs/codex-catalog.json'
    if path.exists():
        before = catalogs.read(path)
        template_path = root / 'codex-desktop/trusted-templates.json'
        templates = catalogs.read(template_path) if template_path.is_file() else {'models': []}
        if trust_templates:
            # Deliberate administrator trust in this authenticated gateway's
            # separately maintained native template file, never generic metadata.
            templates = copy.deepcopy(templates)
            known = {m['slug'] for m in templates['models']}
            identities = {m.get('canonical_model_id') for m in live.values()}
            for model in snapshot.get('templates', []):
                if model.get('slug') in identities and model['slug'] not in known and isinstance(model.get('base_instructions'), str):
                    templates['models'].append(model)
                    known.add(model['slug'])
        updated, pending = catalogs.codex_update(before, live, scope, templates)
        for model in updated['models']:
            if model['slug'].startswith(scope + '/'):
                model['display_name'] = model_label(model['slug'])
        prepare(path, catalogs.encoded(updated))
    path = profile / 'codex/config.toml'
    if path.exists():
        prepare(path, codex_endpoint(path.read_text(), endpoint).encode())
    path = profile / 'config/opencode/opencode.json'
    if path.exists():
        binary = (binaries or {}).get('opencode')
        major = catalogs.opencode_major_version(binary)
        updated = catalogs.opencode_update(catalogs.read(path), live, scope, major_version=major)
        provider = updated['provider']['cpa-' + scope]
        provider.setdefault('options', {})['baseURL'] = endpoint + '/v1'
        for route, model in provider['models'].items():
            model['name'] = model_label(route)
        prepare(path, catalogs.encoded(updated))
    path = profile / 'pi/cliproxyapi-models.json'
    if path.exists():
        mapper, _, _ = catalogs.stock_pi_map(profile, live, (binaries or {}).get('pi'))
        updated = catalogs.pi_update(catalogs.read(path), mapper, live)
        for model in updated['models']:
            if model['id'].startswith(scope + '/'):
                model['name'] = model_label(model['id'])
        prepare(path, catalogs.encoded(updated))
        if pi_native:
            native_path = profile / 'pi/models.json'
            native = catalogs.pi_native_update(catalogs.read(native_path), updated, scope, endpoint)
            prepare(native_path, catalogs.encoded(native))
    path = profile / 'pi/cliproxyapi.json'
    if path.exists():
        updated = catalogs.read(path)
        updated['baseUrl'] = endpoint
        prepare(path, catalogs.encoded(updated))
    return changes, pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path.home() / ('Library/Application Support/Agent Profiles' if sys.platform == 'darwin' else '.config/cpa/profiles')
    parser.add_argument('--profiles', type=Path, default=default)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.profiles.expanduser().resolve()
    phase('read-settings', root=root, scope=None)
    settings = catalogs.read(root / 'gateway.json')
    # Scheduled jobs have a minimal environment. Use the path recorded during
    # installation so the installed stock Pi mapper can locate Pi and Bun.
    if settings.get('runtime_path'):
        os.environ['PATH'] = settings['runtime_path']
    endpoint = origin(settings['endpoint'])
    state = root / 'sync-state'; state.mkdir(mode=0o700, exist_ok=True)
    phase('protect-main-codex')
    main_config = Path.home() / '.codex/config.toml'
    forbidden = [main_config]
    if main_config.exists():
        active = tomllib.loads(main_config.read_text()).get('model_catalog_json')
        if active:
            path = Path(active).expanduser()
            forbidden.append(path if path.is_absolute() else main_config.parent / path)
    protected = {p: p.read_bytes() for p in forbidden if p.exists()}
    with (state / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        changes, receipts, snapshots = {}, [], {}
        for scope in ('personal', 'work'):
            phase('read-profile', scope=scope)
            key_path = root / scope / 'keys/downstream.key'
            if not key_path.exists():
                continue
            cache_path = state / (scope + '.json')
            cache = catalogs.read(cache_path) if cache_path.exists() else None
            phase('fetch-catalog', scope=scope)
            snapshot = fetch(endpoint, key_path.read_text().strip(), scope, cache)
            phase('prepare-profile')
            current, pending = prepare_profile(root, scope, snapshot, endpoint, settings.get('trust_gateway_templates') is True, settings.get('binaries'), settings.get('pi_native_catalog') is True)
            changes.update(current); snapshots[cache_path] = snapshot
            receipts.append({'scope': scope, 'revision': snapshot['revision'], 'modelCount': len(snapshot['models']),
                             'deferred': snapshot.get('deferred', []), 'missingTrustedTemplates': pending})
        if not receipts:
            raise ValueError('No scoped profile keys installed')
        extra_paths = {root / scope / relative for scope in ('personal', 'work')
                       for relative in ('codex/config.toml', 'pi/cliproxyapi.json', 'pi/models.json')}
        phase('validate-targets', scope=None)
        catalogs.validate_targets(changes, root, forbidden, extra_paths)
        backup = None
        if args.apply and changes:
            phase('apply-catalogs')
            backup = str(catalogs.apply_changes(changes, root, state / 'backups', forbidden, extra_paths))
        if args.apply:
            phase('publish-caches')
            for path, value in snapshots.items():
                catalogs.atomic_write(path, catalogs.encoded(value), 0o600)
        services = None
        if args.apply and settings.get('t3_opencode_services') is True:
            phase('reconcile-opencode-services')
            import opencode_services
            services = opencode_services.reconcile(root, changes)
        phase('verify-main-codex')
        if any(p.read_bytes() != raw for p, raw in protected.items()):
            raise ValueError('Main Codex changed externally during reconciliation')
        result = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'apply' if args.apply else 'preview',
                  'changedFiles': len(changes), 'profiles': receipts, 'backup': backup, 'mainCodexUntouched': True}
        if services is not None:
            result['opencode'] = services
        phase('publish-status')
        catalogs.atomic_write(state / 'status.json', catalogs.encoded(result), 0o600)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    sys.exit(run())
