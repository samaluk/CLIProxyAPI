"""Local presentation policy. Never use these labels as routing identities."""
import re

SOURCES = {'codex-oauth': 'CX', 'claude-oauth': 'CL', 'commandcode': 'CC',
           'opencode-go': 'GO', 'litellm': 'LL', 'antigravity': 'AG'}
# Verified deployment aliases. Do not infer account ownership from model family.
ALIAS_PREFIXES = {'commandcode/': 'personal/commandcode/',
                  'opencode-go/': 'personal/opencode-go/'}
ALIASES = {'personal/gpt-6-sol': 'personal/codex-oauth/gpt-6-sol',
           'personal/gpt-6-luna': 'personal/codex-oauth/gpt-6-luna',
           'work/claude-opus-5-5': 'work/claude-oauth/claude-opus-5-5'}


def canonical_route(route):
    if route in ALIASES:
        return ALIASES[route]
    for prefix, replacement in ALIAS_PREFIXES.items():
        if route.startswith(prefix):
            return replacement + route[len(prefix):]
    return route


def readable_model(model):
    """Retain versions, snapshots and variants while normalizing presentation."""
    if model.startswith('claude-'):
        body = model[7:]
        match = re.fullmatch(r'(?:(\d{1,2}(?:-\d{1,2})?)-)?(opus|sonnet|haiku|fable)(?:-(\d{1,2}(?:-\d{1,2})?))?(-\d{8})?', body)
        if match:
            before, family, after, snapshot = match.groups()
            version = (before or after or '').replace('-', '.')
            return ' '.join(x for x in [family.title(), version, (snapshot or '').lstrip('-')] if x)
        model = body
    elif model.startswith('gpt-'):
        model = model[4:]
    elif model.startswith('xai-grok-'):
        model = model[4:]
    words = {'deepseek': 'DeepSeek', 'glm': 'GLM', 'kimi': 'Kimi', 'minimax': 'MiniMax',
             'longcat': 'LongCat', 'mimo': 'MiMo', 'hy3': 'HY3', 'hy4': 'HY4'}
    result = []
    for part in re.split(r'[-:]', model):
        low = part.lower()
        if low.startswith('qwen'):
            name = 'Qwen ' + part[4:]
        elif re.fullmatch(r'[vkm]\d+(?:\.\d+)*|\d+b|a\d+b', low):
            name = part.upper()
        else:
            name = words.get(low, part[:1].upper() + part[1:].lower())
        result.append(name.strip())
    return ' '.join(result)


def model_label(route):
    canonical = canonical_route(route)
    parts = canonical.split('/', 2)
    if len(parts) != 3 or parts[0] not in ('personal', 'work') or parts[1] not in SOURCES:
        return route
    scope, source, model = parts
    label = f"{'P' if scope == 'personal' else 'W'}/{SOURCES[source]} · {readable_model(model)}"
    return label + (' · alias' if canonical != route else '')
