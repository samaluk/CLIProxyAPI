#!/usr/bin/env python3
"""Reconcile managed client catalogs from one explicitly configured TLS gateway.

The server owns discovery. Clients retain prompts, routing IDs, user options and
missing saved models. No upstream OAuth credentials are needed on a client.
"""
import argparse
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
import urllib.error
import urllib.parse
import urllib.request

import refresh_scoped_catalogs as catalogs
from model_labels import model_label


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


def prepare_profile(root, scope, snapshot, endpoint, trust_templates, binaries=None):
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
        updated = catalogs.opencode_update(catalogs.read(path), live, scope)
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
    settings = catalogs.read(root / 'gateway.json')
    # Scheduled jobs have a minimal environment. Use the path recorded during
    # installation so the installed stock Pi mapper can locate Pi and Bun.
    if settings.get('runtime_path'):
        os.environ['PATH'] = settings['runtime_path']
    endpoint = origin(settings['endpoint'])
    state = root / 'sync-state'; state.mkdir(mode=0o700, exist_ok=True)
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
            key_path = root / scope / 'keys/downstream.key'
            if not key_path.exists():
                continue
            cache_path = state / (scope + '.json')
            cache = catalogs.read(cache_path) if cache_path.exists() else None
            snapshot = fetch(endpoint, key_path.read_text().strip(), scope, cache)
            current, pending = prepare_profile(root, scope, snapshot, endpoint, settings.get('trust_gateway_templates') is True, settings.get('binaries'))
            changes.update(current); snapshots[cache_path] = snapshot
            receipts.append({'scope': scope, 'revision': snapshot['revision'], 'modelCount': len(snapshot['models']),
                             'deferred': snapshot.get('deferred', []), 'missingTrustedTemplates': pending})
        if not receipts:
            raise ValueError('No scoped profile keys installed')
        extra_paths = {root / scope / relative for scope in ('personal', 'work')
                       for relative in ('codex/config.toml', 'pi/cliproxyapi.json')}
        catalogs.validate_targets(changes, root, forbidden, extra_paths)
        backup = None
        if args.apply and changes:
            backup = str(catalogs.apply_changes(changes, root, state / 'backups', forbidden, extra_paths))
        if args.apply:
            for path, value in snapshots.items():
                catalogs.atomic_write(path, catalogs.encoded(value), 0o600)
        if any(p.read_bytes() != raw for p, raw in protected.items()):
            raise ValueError('Main Codex changed externally during reconciliation')
        result = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'apply' if args.apply else 'preview',
                  'changedFiles': len(changes), 'profiles': receipts, 'backup': backup, 'mainCodexUntouched': True}
        catalogs.atomic_write(state / 'status.json', catalogs.encoded(result), 0o600)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never serialize a failed HTTP request, credential, or provider body.
        print('Catalog sync failed; saved configuration retained. ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
