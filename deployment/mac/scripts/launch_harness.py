#!/usr/bin/env python3
"""Launch a harness with a Personal-only or Work-only proxy and config home.
An ordinary configuration/routing boundary, not a same-user security sandbox.
"""
import os
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent

MODEL_CREDENTIAL_PREFIXES = (
    'OPENAI_', 'AZURE_OPENAI_', 'ANTHROPIC_', 'GEMINI_', 'GOOGLE_API_',
    'GROQ_', 'CEREBRAS_', 'XAI_', 'FIREWORKS_', 'TOGETHER_', 'BASETEN_',
    'OPENROUTER_', 'AI_GATEWAY_', 'ZAI_', 'MISTRAL_', 'MINIMAX_',
    'MOONSHOT_', 'KIMI_', 'META_API_', 'QWEN_TOKEN_', 'XIAOMI_', 'DEEPSEEK_',
    'NVIDIA_API_', 'ANT_LING_', 'COMMANDCODE_', 'CURSOR_',
)

def gateway_settings():
    settings = json.loads((ROOT / 'gateway.json').read_text())
    # This file is installed by the administrator; never derive origins or
    # executable paths from a model catalog.
    from urllib.parse import urlsplit
    endpoint = settings['endpoint'].rstrip('/')
    parsed = urlsplit(endpoint)
    if not (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError('Invalid gateway origin')
    return settings, endpoint


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('personal', 'work') or sys.argv[2] not in ('codex', 'claude', 'opencode', 'pi'):
        sys.exit('Usage: launch-harness.py personal|work codex|claude|opencode|pi [arguments]')
    scope, harness = sys.argv[1:3]
    profile = ROOT / scope
    settings, endpoint = gateway_settings()
    key = (profile / 'keys/downstream.key').read_text().strip()
    if not key:
        sys.exit('Missing profile key; refusing to launch')
    env = dict(os.environ)
    if settings.get('proxy_only') is True:
        arguments = sys.argv[3:]
        if arguments[:1] == ['login'] or arguments[:2] == ['auth', 'login']:
            sys.exit('Provider login belongs on the proxy; this harness only uses its scoped gateway key.')
        cursor_exception = scope == 'personal' and harness == 'pi' and settings.get('pi_cursor_personal') is True
        for name in list(env):
            if name.startswith(MODEL_CREDENTIAL_PREFIXES) and not (cursor_exception and name.startswith('CURSOR_')):
                env.pop(name, None)
            elif name in ('AWS_BEARER_TOKEN_BEDROCK', 'GOOGLE_APPLICATION_CREDENTIALS'):
                env.pop(name, None)
    # Prevent inherited login/provider settings from selecting a different
    # upstream. Project settings and deliberate absolute paths are not sandboxed.
    # T3 generates a per-process password for its local OpenCode server.
    # Preserve only transport authentication for `serve`; account and config
    # overrides must still be cleared before applying the chosen profile.
    server_auth = ('OPENCODE_PASSWORD', 'OPENCODE_SERVER_PASSWORD') if (
        harness == 'opencode' and sys.argv[3:4] == ['serve']) else ()
    for name in list(env):
        if name in server_auth:
            continue
        if name.startswith(('ANTHROPIC_', 'CLAUDE_CODE_OAUTH_', 'CODEX_EXEC_SERVER_', 'OPENCODE_', 'CLIPROXYAPI_')) or name in (
                'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_API_BASE', 'CODEX_ELECTRON_USER_DATA_PATH',
                'CLAUDE_CODE_MAX_CONTEXT_TOKENS', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS',
                'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
            env.pop(name, None)
    personal = scope == 'personal'
    codex_model = 'personal/codex-oauth/gpt-5.6-luna' if personal else 'work/litellm/gpt-5.6-luna'
    claude_model = codex_model if personal else 'work/claude-oauth/claude-fable-5-1'
    env.update({
        'AGENT_PROFILE': scope,
        'CPA_API_KEY': key,
        'CLIPROXYAPI_API_KEY': key,
        'CLIPROXYAPI_BASE_URL': endpoint,
        'CODEX_HOME': str(profile / 'codex'),
        'CLAUDE_CONFIG_DIR': str(profile / 'claude'),
        'PI_CODING_AGENT_DIR': str(profile / 'pi'),
        'XDG_CONFIG_HOME': str(profile / 'config'),
        'XDG_DATA_HOME': str(profile / 'data'),
        'XDG_STATE_HOME': str(profile / 'state'),
        'XDG_CACHE_HOME': str(profile / 'cache'),
        'MISE_CONFIG_DIR': str(Path.home() / '.config/mise'),
        'MISE_DATA_DIR': str(Path.home() / '.local/share/mise'),
        'PATH': str(profile / 'bin') + os.pathsep + env.get('PATH', '/opt/homebrew/bin:/usr/bin:/bin'),
    })
    if harness == 'claude':
        env.update({
            'ANTHROPIC_BASE_URL': endpoint,
            'ANTHROPIC_AUTH_TOKEN': key,
            'ANTHROPIC_API_KEY': '',
            'ANTHROPIC_MODEL': claude_model,
            'ANTHROPIC_DEFAULT_SONNET_MODEL': claude_model,
            'ANTHROPIC_DEFAULT_OPUS_MODEL': claude_model,
            'ANTHROPIC_DEFAULT_HAIKU_MODEL': claude_model if personal else 'work/claude-oauth/claude-haiku-4-5-20251001',
            'CLAUDE_CODE_SUBAGENT_MODEL': claude_model,
        })
        model = claude_model
        args = sys.argv[3:]
        for i, arg in enumerate(args):
            if arg == '--model' and i + 1 < len(args):
                model = args[i + 1]
            elif arg.startswith('--model='):
                model = arg.split('=', 1)[1]
        catalog = json.loads((profile / 'catalogs/codex-catalog.json').read_text())
        definition = next((m for m in catalog['models'] if m['slug'] == model), {})
        # Non-Codex models may have capabilities but no trusted Codex prompt.
        # Claude can still consume their authenticated scoped limits directly.
        snapshot_path = ROOT / 'sync-state' / (scope + '.json')
        if snapshot_path.is_file() and model.startswith(scope + '/'):
            snapshot = json.loads(snapshot_path.read_text())
            if snapshot.get('scope') == scope:
                fresh = next((m for m in snapshot.get('models', []) if m['slug'] == model), {})
                definition = {**definition, **fresh}
        for field, variable in [('context_window', 'CLAUDE_CODE_MAX_CONTEXT_TOKENS'), ('max_tokens', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS')]:
            value = definition.get(field)
            if isinstance(value, int) and value > 0:
                env[variable] = str(value)
    if harness == 'opencode':
        config = profile / 'config/opencode/opencode.json'
        if not config.exists():
            sys.exit('OpenCode profile has not been configured yet; refusing to use a legacy configuration')
        env['OPENCODE_CONFIG'] = str(config)
    if settings.get('proxy_only') is True:
        env['CPA_PROXY_ONLY'] = '1'
        env['CPA_PROXY_SCOPE'] = scope
    binary = settings['binaries'][harness]
    if not Path(binary).is_absolute():
        sys.exit('Harness binary must be an absolute path')
    os.execve(binary, [binary, *sys.argv[3:]], env)

if __name__ == '__main__':
    main()
