#!/usr/bin/env python3
"""Add native config files for newly installed harnesses to existing CPA profiles.

Requires the already-provisioned downstream keys. Never copies vendor tokens,
changes existing configurations, or touches conversation directories.
"""
import argparse
import json
from pathlib import Path
import tomllib

import install_remote_sync as installer
import refresh_scoped_catalogs as catalogs
import remote_sync


def targets(root, endpoint, binaries):
    result = {}
    for scope in ('personal', 'work'):
        profile = root / scope
        if not (profile / 'keys/downstream.key').is_file():
            continue
        cfg = profile / 'codex/config.toml'
        codex_model = tomllib.loads(cfg.read_text()).get('model') if cfg.exists() else None
        codex_model = codex_model or ('personal/codex-oauth/gpt-5.6-luna' if scope == 'personal' else 'work/litellm/gpt-5.6-luna')
        claude_model = codex_model if scope == 'personal' else 'work/claude-oauth/claude-fable-5-1'
        def add(relative, value):
            path = profile / relative
            if not path.exists():
                data = value.encode() if isinstance(value, str) else catalogs.encoded(value)
                result[path] = (data, 0o600, None)
        if 'codex' in binaries:
            add('codex/config.toml', f'model = {json.dumps(codex_model)}\nmodel_provider = "cpa-{scope}"\nmodel_catalog_json = {json.dumps(str(profile / "catalogs/codex-catalog.json"))}\ncli_auth_credentials_store = "file"\n[model_providers.cpa-{scope}]\nname = "CLIProxyAPI {scope.title()}"\nbase_url = {json.dumps(endpoint + "/v1")}\nwire_api = "responses"\nrequires_openai_auth = true\n')
            add('catalogs/codex-catalog.json', {'models': []})
        if 'claude' in binaries:
            add('claude/settings.json', {'model': claude_model})
        if 'opencode' in binaries:
            provider = 'cpa-' + scope
            add('config/opencode/opencode.json', {
                '$schema': 'https://opencode.ai/config.json', 'enabled_providers': [provider],
                'model': provider + '/' + codex_model, 'small_model': provider + '/' + codex_model,
                'provider': {provider: {'name': 'CLIProxyAPI ' + scope.title(), 'npm': '@ai-sdk/openai-compatible',
                                       'options': {'baseURL': endpoint + '/v1', 'apiKey': '{env:CPA_API_KEY}'}, 'models': {}}}})
        if 'pi' in binaries:
            add('pi/settings.json', {'packages': [], 'defaultProvider': 'cliproxyapi', 'defaultModel': codex_model,
                                    'enabledModels': ['cliproxyapi/' + scope + '/**']})
            add('pi/models.json', {'providers': {'cliproxyapi': {
                'name': 'CPA ' + scope.title(), 'api': 'openai-responses',
                'baseUrl': endpoint + '/v1', 'apiKey': '${CPA_API_KEY}', 'models': []}}})
            add('pi/cliproxyapi-models.json', {'models': [], 'fastModelIds': []})
            add('pi/auth.json', {})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--binary', action='append', default=[], metavar='NAME=ABSOLUTE_PATH')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.profiles.expanduser().resolve()
    endpoint = remote_sync.origin(args.endpoint)
    binaries = dict(item.split('=', 1) for item in args.binary)
    for name, path in binaries.items():
        if name not in ('codex', 'claude', 'opencode', 'pi') or not Path(path).is_absolute() or not Path(path).is_file():
            raise ValueError('Expected an installed native harness path')
    planned = targets(root, endpoint, binaries)
    if args.apply and planned:
        import datetime
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        installer.write_transaction(planned, root / 'sync-state/provision-backups' / stamp)
    print(json.dumps({'applied': args.apply, 'newFiles': [str(p) for p in planned]}, indent=2))


if __name__ == '__main__':
    main()
