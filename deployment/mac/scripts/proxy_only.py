"""Local, administrator-selected policy for default harness configuration.

Only downstream gateway keys enter harness files. Provider tokens are archived
by the install transaction; conversation directories are never modified.
"""
import copy
import json
from pathlib import Path
import re
import tomllib

import refresh_scoped_catalogs as catalogs


def root_values(raw, values):
    """Update root TOML assignments without rewriting unrelated tables."""
    position = re.search(r'(?m)^\[', raw)
    index = position.start() if position else len(raw)
    head, rest = raw[:index], raw[index:]
    for name, value in values.items():
        line = name + ' = ' + json.dumps(value)
        head, count = re.subn(r'(?m)^' + re.escape(name) + r'\s*=.*$', lambda _: line, head)
        if count > 1:
            raise ValueError('Duplicate root TOML assignment')
        if not count:
            head = head.rstrip() + '\n' + line + '\n'
    result = head.rstrip() + '\n\n' + rest
    tomllib.loads(result)
    return result


def provider_config(raw, scope, endpoint, key, catalog_path, model):
    sections = re.split(r'(?m)(?=^\[)', raw)
    raw = ''.join(section for section in sections if not re.match(r'^\[model_providers\.', section))
    raw = root_values(raw, {'model_provider': 'cpa-' + scope, 'model': model,
                           'model_catalog_json': str(catalog_path),
                           'forced_login_method': 'api', 'cli_auth_credentials_store': 'file'})
    # The API-key auth.json file also works for the stock desktop app, which
    # does not inherit the profile launcher's environment. Requiring API auth
    # lets T3 recognize this as an API-backed profile rather than probing an
    # absent ChatGPT subscription account.
    raw = raw.rstrip() + (f'\n\n[model_providers.cpa-{scope}]\nname = "CLIProxyAPI {scope.title()}"\n'
            f'base_url = {json.dumps(endpoint + "/v1")}\nwire_api = "responses"\n'
            'requires_openai_auth = true\n')
    parsed = tomllib.loads(raw)
    if 'agents' in parsed:
        pattern = r'(?ms)(^\[agents\]\s*\n)(.*?)(?=^\[|\Z)'
        def update(match):
            body, count = re.subn(r'(?m)^default_subagent_model\s*=.*$',
                                  lambda _: 'default_subagent_model = ' + json.dumps(model), match[2])
            if not count:
                body = 'default_subagent_model = ' + json.dumps(model) + '\n' + body
            return match[1] + body
        raw = re.sub(pattern, update, raw)
    else:
        raw += '\n[agents]\ndefault_subagent_model = ' + json.dumps(model) + '\n'
    tomllib.loads(raw)
    return raw.encode()


def choose_route(value, scope, allowed, fallback):
    if value in allowed:
        return value
    for source in ('codex-oauth', 'claude-oauth', 'litellm', 'opencode-go', 'commandcode'):
        candidate = scope + '/' + source + '/' + str(value)
        if candidate in allowed:
            return candidate
    return fallback


def default_home_targets(root, settings, prepared=None, home=None, snapshots=None):
    """Prepare default homes from local scoped files, never from remote prose."""
    home = home or Path.home()
    prepared = prepared or {}
    scope = settings.get('default_proxy_scope', 'personal')
    if scope not in ('personal', 'work'):
        raise ValueError('Invalid default proxy scope')
    profile = root / scope
    endpoint = settings['endpoint'].rstrip('/')
    key = (profile / 'keys/downstream.key').read_text().strip()
    binaries = settings['binaries']
    targets = {}

    def read_scoped(path):
        return prepared[path]['after'] if path in prepared else path.read_bytes()

    def emit(path, content):
        raw = content if isinstance(content, bytes) else catalogs.encoded(content)
        targets[path] = (raw, 0o600, path.read_bytes() if path.exists() else None)

    if 'codex' in binaries:
        path = home / '.codex/config.toml'
        raw = path.read_text() if path.exists() else ''
        document = tomllib.loads(raw)
        scoped = tomllib.loads(read_scoped(profile / 'codex/config.toml').decode())
        catalog_path = profile / 'catalogs/codex-catalog.json'
        allowed = {m['slug'] for m in json.loads(read_scoped(catalog_path))['models']}
        model = choose_route(document.get('model'), scope, allowed, scoped['model'])
        updated = provider_config(raw, scope, endpoint, key, catalog_path, model).decode()
        if 'model_reasoning_effort' in scoped:
            updated = root_values(updated, {'model_reasoning_effort': scoped['model_reasoning_effort']})
        limits = {k: v for k, v in scoped.get('agents', {}).items() if k in ('max_threads', 'max_depth')}
        if limits:
            import harness_settings
            updated = harness_settings.agents(updated, limits)
        emit(path, updated.encode())
        emit(home / '.codex/auth.json', {'OPENAI_API_KEY': key})

    if 'claude' in binaries:
        path = home / '.claude/settings.json'
        value = json.loads(path.read_text()) if path.exists() else {}
        environment = value.setdefault('env', {})
        model = environment.get('ANTHROPIC_MODEL')
        snapshot_path = root / 'sync-state' / (scope + '.json')
        snapshot = (snapshots or {}).get(snapshot_path)
        if snapshot is None:
            snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {'models': []}
        allowed = {m['slug'] for m in snapshot['models']}
        fallback = 'personal/codex-oauth/gpt-5.6-luna' if scope == 'personal' else 'work/claude-oauth/claude-fable-5-1'
        model = choose_route(model or value.get('model'), scope, allowed, fallback)
        environment = {k: v for k, v in environment.items() if not k.startswith(('ANTHROPIC_', 'CLAUDE_CODE_OAUTH_'))
                       and k not in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
                                     'CLAUDE_CODE_MAX_CONTEXT_TOKENS', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS')}
        environment.update(ANTHROPIC_BASE_URL=endpoint, ANTHROPIC_AUTH_TOKEN=key,
                           ANTHROPIC_API_KEY='', ANTHROPIC_MODEL=model,
                           ANTHROPIC_DEFAULT_OPUS_MODEL=model, ANTHROPIC_DEFAULT_SONNET_MODEL=model,
                           ANTHROPIC_DEFAULT_HAIKU_MODEL=model, CLAUDE_CODE_SUBAGENT_MODEL=model,
                           CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='1')
        definition = next((m for m in snapshot['models'] if m['slug'] == model), {})
        for field, name in (('context_window', 'CLAUDE_CODE_MAX_CONTEXT_TOKENS'),
                            ('max_tokens', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS')):
            if isinstance(definition.get(field), int) and definition[field] > 0:
                environment[name] = str(definition[field])
        value.update(env=environment, model=model)
        scoped = json.loads(read_scoped(profile / 'claude/settings.json'))
        for name in ('effortLevel', 'autoCompactEnabled'):
            if name in scoped:
                value[name] = scoped[name]
        value.pop('apiKeyHelper', None)
        emit(path, value)
        path = home / '.claude/.credentials.json'
        if path.exists():
            targets[path] = (None, 0o600, path.read_bytes())

    if 'opencode' in binaries:
        path = home / '.config/opencode/opencode.json'
        value = json.loads(path.read_text()) if path.exists() else {}
        scoped = json.loads(read_scoped(profile / 'config/opencode/opencode.json'))
        provider_id = 'cpa-' + scope
        provider = copy.deepcopy(scoped['provider'][provider_id])
        provider.setdefault('options', {}).update(baseURL=endpoint + '/v1', apiKey=key)
        value.pop('providers', None)
        value.pop('disabled_providers', None)
        value.update(provider={provider_id: provider}, enabled_providers=[provider_id],
                     model=scoped['model'], small_model=scoped.get('small_model', scoped['model']))
        for name in ('autoupdate', 'share', 'permission'):
            if name in scoped:
                value[name] = copy.deepcopy(scoped[name])
        emit(path, value)
        emit(home / '.local/share/opencode/auth.json', {})

    if 'pi' in binaries:
        path = home / '.pi/agent/settings.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        scoped = json.loads(read_scoped(profile / 'pi/settings.json'))
        previous.update({name: copy.deepcopy(scoped[name]) for name in
                         ('defaultProvider', 'defaultModel', 'enabledModels', 'defaultThinkingLevel',
                          'hideThinkingBlock', 'compaction') if name in scoped})
        # Package/extension selection is maintained in the managed profile. This
        # removes the old mixed discovery and preserves the Personal Cursor SDK.
        previous['packages'] = copy.deepcopy(scoped.get('packages', []))
        previous['extensions'] = copy.deepcopy(scoped.get('extensions', []))
        emit(path, previous)
        native = json.loads(read_scoped(profile / 'pi/models.json'))
        native['providers']['cliproxyapi']['apiKey'] = key
        emit(home / '.pi/agent/models.json', native)
        auth_path = home / '.pi/agent/auth.json'
        scoped_auth = profile / 'pi/auth.json'
        auth = json.loads(read_scoped(scoped_auth)) if scoped_auth.exists() or scoped_auth in prepared else (
            json.loads(auth_path.read_text()) if auth_path.exists() else {})
        emit(auth_path, {'cursor': auth['cursor']} if scope == 'personal' and settings.get('pi_cursor_personal') and 'cursor' in auth else {})
    return targets


def shell_targets(settings, home=None):
    """Route ordinary shell entrypoints and stop exporting a legacy model key."""
    home = home or Path.home()
    targets = {}
    body = '# Managed proxy-only harness entrypoints.\nexport PATH="$HOME/.local/bin:$PATH"\n'
    body += 'unset OPENCODE_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n'
    for harness in settings['binaries']:
        body += f'{harness}() {{ "$HOME/.local/bin/{harness}" "$@"; }}\n'
    targets[home / '.config/cpa/proxy-shell.sh'] = (body.encode(), 0o600)
    block = ('\n# BEGIN CPA PROXY-ONLY HARNESS ENTRYPOINTS\n'
             '[ ! -f "$HOME/.config/cpa/proxy-shell.sh" ] || . "$HOME/.config/cpa/proxy-shell.sh"\n'
             '# END CPA PROXY-ONLY HARNESS ENTRYPOINTS\n')
    for name in ('.zshenv', '.zprofile', '.zshrc', '.bashrc', '.profile'):
        path = home / name
        raw = path.read_text() if path.exists() else ''
        raw = re.sub(r'\n?# BEGIN CPA PROXY-ONLY HARNESS ENTRYPOINTS\n.*?# END CPA PROXY-ONLY HARNESS ENTRYPOINTS\n?',
                     '', raw, flags=re.S)
        targets[path] = ((raw.rstrip() + '\n' + block).encode(), path.stat().st_mode & 0o777 if path.exists() else 0o600)
    path = home / '.config/zsh/30-secrets.zsh'
    if path.exists():
        raw = path.read_text()
        after = re.sub(r'(?m)^\s*(?:export\s+)?OPENCODE_API_KEY=.*\n?', '', raw)
        if after != raw:
            targets[path] = (after.encode(), path.stat().st_mode & 0o777)
    return targets


def scoped_auth_targets(root, settings):
    targets = {}
    cursor = None
    legacy = Path.home() / '.pi/agent/auth.json'
    if settings.get('pi_cursor_personal') and legacy.exists():
        cursor = json.loads(legacy.read_text()).get('cursor')
    for scope in ('personal', 'work'):
        profile = root / scope
        key_path = profile / 'keys/downstream.key'
        if not key_path.exists():
            continue
        if 'codex' in settings['binaries']:
            path = profile / 'codex/auth.json'
            targets[path] = (catalogs.encoded({'OPENAI_API_KEY': key_path.read_text().strip()}), 0o600)
            path = profile / 'codex/config.toml'
            raw = root_values(path.read_text(), {'forced_login_method': 'api', 'cli_auth_credentials_store': 'file'})
            pattern = r'(?ms)(^\[model_providers\.cpa-' + scope + r'\]\s*\n)(.*?)(?=^\[|\Z)'
            def require_api_auth(match):
                body, count = re.subn(r'(?m)^requires_openai_auth\s*=.*$',
                                      'requires_openai_auth = true', match[2])
                if not count:
                    body += '\nrequires_openai_auth = true\n'
                return match[1] + body
            raw, count = re.subn(pattern, require_api_auth, raw)
            if count != 1:
                raise ValueError('Expected a single scoped CPA Codex provider')
            tomllib.loads(raw)
            targets[path] = (raw.encode(), 0o600)
        if 'pi' in settings['binaries']:
            path = profile / 'pi/auth.json'
            old = json.loads(path.read_text()) if path.exists() else {}
            chosen = old.get('cursor', cursor)
            auth = {'cursor': chosen} if scope == 'personal' and settings.get('pi_cursor_personal') and chosen else {}
            targets[path] = (catalogs.encoded(auth), 0o600)
        for relative in ('claude/.credentials.json', 'data/opencode/auth.json'):
            path = profile / relative
            if path.exists():
                targets[path] = (None, 0o600)
    return targets
