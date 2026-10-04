"""Discover model capabilities for the authenticated account, never from a plan name.

Only structured capability fields cross the remote trust boundary. This makes no inference request,
does not refresh credentials and does not write native Codex state.
"""
import json
import pathlib
import re
import tomllib
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def provider_capabilities(model):
    """Validate data, retaining explicit empty lists and excluding provider prose."""
    result = {}
    for name in ('context_window', 'max_context_window', 'max_tokens', 'max_output_tokens', 'max_completion_tokens'):
        value = model.get(name)
        if type(value) is int and value > 0:
            result[name] = value
    for name in ('input_modalities', 'supported_input_modalities', 'output_modalities'):
        value = model.get(name)
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            result[name] = list(dict.fromkeys(value))
    levels = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
    if isinstance(model.get('supported_reasoning_levels'), list):
        result['supported_reasoning_levels'] = [
            {'effort': x['effort'], 'description': x['effort']}
            for x in model['supported_reasoning_levels']
            if isinstance(x, dict) and x.get('effort') in levels]
    if model.get('default_reasoning_level') in levels or ('default_reasoning_level' in model and model['default_reasoning_level'] is None):
        result['default_reasoning_level'] = model['default_reasoning_level']
    if isinstance(model.get('service_tiers'), list):
        result['service_tiers'] = [{'id': t['id']} for t in model['service_tiers']
                                  if isinstance(t, dict) and isinstance(t.get('id'), str)]
    if isinstance(model.get('additional_speed_tiers'), list):
        result['additional_speed_tiers'] = [x for x in ('fast', 'ultrafast')
                                           if x in model['additional_speed_tiers']]
    return result


def route_tiers(credentials, native_account_id, models):
    by_id = {m['slug']: m for m in models if isinstance(m, dict) and isinstance(m.get('slug'), str)}
    result = {}
    for auth in credentials:
        if auth.get('disabled') or not native_account_id or auth.get('account_id') != native_account_id:
            continue
        prefix = auth.get('prefix', '').strip('/')
        if prefix not in ('personal', 'work'):
            continue  # Account ownership must be explicitly configured.
        for alias in auth.get('model_aliases', []):
            if not isinstance(alias, dict) or not isinstance(alias.get('alias'), str):
                continue
            model = by_id.get(alias.get('name'))
            if model is None:
                continue  # A missing model is not evidence of a tier restriction.
            fields = provider_capabilities(model)
            if fields:
                result[prefix + '/' + alias['alias']] = fields
    return result


def discover(base_url, native_cache, home=None):
    """Verify native account identity against local gateway auth before discovery."""
    home = pathlib.Path.home() if home is None else pathlib.Path(home)
    data = home / 'Library/Application Support/com.cpa.gui'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(url, headers):
        with opener.open(urllib.request.Request(url, headers=headers), timeout=15) as response:
            return json.load(response)

    try:
        origin = urllib.parse.urlsplit(base_url)
        if origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', 'localhost') or origin.port is None or origin.username or origin.password or origin.path not in ('', '/') or origin.query or origin.fragment:
            raise ValueError('Account discovery requires the local gateway')
        tokens = json.loads((home / '.codex/auth.json').read_text()).get('tokens') or {}
        account = tokens.get('account_id')
        version = native_cache.get('client_version')
        if not account or not tokens.get('access_token') or not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', version):
            return {}, {'status': 'unavailable', 'reason': 'native account or client version unavailable'}
        secret = tomllib.loads((data / 'config.toml').read_text())['management-secret-key']
        records = get(base_url.rstrip('/') + '/v0/management/auth-files', {'Authorization': 'Bearer ' + secret})['files']
        credentials = []
        for record in records:
            if record.get('provider') != 'codex' or record.get('disabled') or not record.get('path'):
                continue
            path = (data / 'cpa-core' / record['path']).resolve()
            if not path.is_relative_to(data.resolve()):
                continue  # Do not follow a remote path outside the local gateway data.
            auth = json.loads(path.read_text())
            if auth.get('account_id') == account:
                credentials.append(auth)
        if not credentials:
            return {}, {'status': 'unavailable', 'reason': 'no matching gateway account'}
        native = get('https://chatgpt.com/backend-api/codex/models?' + urllib.parse.urlencode({'client_version': version}),
                     {'Authorization': 'Bearer ' + tokens['access_token'], 'ChatGPT-Account-Id': account,
                      'User-Agent': 'codex_cli_rs/' + version, 'originator': 'codex_cli_rs'})
        models = native.get('models')
        if not isinstance(models, list) or not models:
            raise ValueError('Empty native model discovery')
        tiers = route_tiers(credentials, account, models)
        return tiers, {'status': 'verified', 'source': 'authenticated Codex model discovery',
                       'clientVersion': version, 'matchedRoutes': len(tiers),
                       'fieldsByRoute': {route: sorted(fields) for route, fields in tiers.items()},
                       'reportedSpeeds': sorted({x for m in tiers.values() for x in m.get('additional_speed_tiers', [])})}
    except Exception as error:
        # Never emit remote bodies, local credential paths, tokens or account IDs.
        return {}, {'status': 'unavailable', 'reason': type(error).__name__}


def apply(live, overrides):
    """Apply only verified route-specific capability fields, keeping other metadata."""
    applied = {}
    for route, fields in overrides.items():
        if route in live:
            # Normalize synonymous fields so stale generic values cannot beat
            # an account value merely because a harness reads another key first.
            normalized = dict(fields)
            maximum = next((fields[k] for k in ('max_tokens', 'max_output_tokens', 'max_completion_tokens') if k in fields), None)
            if maximum is not None:
                normalized.update(max_tokens=maximum, max_output_tokens=maximum, max_completion_tokens=maximum)
            inputs = fields.get('input_modalities', fields.get('supported_input_modalities'))
            if inputs is not None:
                normalized.update(input_modalities=inputs, supported_input_modalities=inputs)
            if 'service_tiers' in fields and 'additional_speed_tiers' not in fields:
                ids = {tier['id'] for tier in fields['service_tiers']}
                normalized['additional_speed_tiers'] = (['fast'] if ids & {'fast', 'priority'} else []) + (['ultrafast'] if 'ultrafast' in ids else [])
            live[route].update(normalized)
            if 'supported_reasoning_levels' in fields:
                allowed = {item['effort'] for item in fields['supported_reasoning_levels']}
                if live[route].get('default_reasoning_level') not in allowed:
                    live[route]['default_reasoning_level'] = None
                    normalized['default_reasoning_level'] = None
            applied[route] = sorted(normalized)
    return applied


def verified_routes(live, overrides, scope):
    """Defer unverified Codex routes; never erase their saved client entries."""
    deferred = sorted(route for route in live if route.startswith(scope + '/codex-oauth/') and route not in overrides)
    for route in deferred:
        del live[route]
    return deferred
