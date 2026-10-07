#!/usr/bin/env python3
"""Preview live capability reconciliation; --apply updates only scoped catalogs.

Provider IDs, defaults, prompts, credentials and user options are preserved.
Pi uses its installed stock mapper; its cache remains combined because the stock
provider has no scope filter. Missing routes are retained unless explicitly retired.
"""
from __future__ import annotations
import argparse, copy, datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, tomllib, urllib.parse, urllib.request
from model_labels import model_label, canonical_route
import codex_account_tiers

ROOT = pathlib.Path(os.environ.get('CPA_STATE_DIR', str(pathlib.Path.home()/'.local/state/cpa-stack')))
PROFILES = pathlib.Path.home() / 'Library/Application Support/Agent Profiles'
RETIRED = {'personal/codex-oauth/gpt-5.3-codex-spark'}
SCOPES = ('personal', 'work')
CAP_FIELDS = ('canonical_model_id', 'context_window', 'max_context_window', 'max_tokens', 'max_output_tokens', 'max_completion_tokens', 'input_modalities', 'supported_input_modalities', 'output_modalities', 'default_reasoning_level', 'supported_reasoning_levels', 'visibility', 'supports_parallel_tool_calls', 'supports_image_detail_original', 'support_verbosity')
CODEX_FIELDS = ('context_window', 'max_context_window', 'max_tokens', 'input_modalities', 'default_reasoning_level', 'supported_reasoning_levels', 'service_tiers', 'additional_speed_tiers', 'supports_parallel_tool_calls', 'supports_image_detail_original', 'support_verbosity')
PI_FIELDS = ('reasoning', 'input', 'contextWindow', 'maxTokens', 'thinkingLevelMap')
PI_THINKING_LEVELS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
PROMPT_FIELDS = ('base_instructions', 'model_messages', 'include_apps_usage_instructions', 'include_plugin_usage_instructions', 'include_skills_usage_instructions')
TIER_NAMES = {'default': 'Standard', 'auto': 'Automatic', 'priority': 'Fast', 'fast': 'Fast', 'ultrafast': 'Ultrafast', 'flex': 'Flex'}

def encoded(obj): return (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode()
def digest(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_text())

def validate_origin(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port is None or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Only explicit local proxy origins are supported')
    return value.rstrip('/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None

def safe_model(model):
    """Discard all remote prose/instruction/auth fields at the ingress boundary."""
    out = {'slug': model['slug']}
    for name in CAP_FIELDS:
        if name in model and model[name] is not None:
            out[name] = copy.deepcopy(model[name])
    if 'supported_reasoning_levels' in out:
        out['supported_reasoning_levels'] = [dict(effort=x['effort'], description=x['effort']) for x in out['supported_reasoning_levels'] if x.get('effort') in EFFORTS]
    if isinstance(model.get('service_tiers'), list):
        out['service_tiers'] = [{'id': x['id']} for x in model['service_tiers'] if isinstance(x, dict) and isinstance(x.get('id'), str)]
    if isinstance(model.get('additional_speed_tiers'), list):
        out['additional_speed_tiers'] = [x for x in model['additional_speed_tiers'] if x in ('fast', 'ultrafast')]
    return out

def live_models(profile, base_url):
    key = (profile / 'keys/downstream.key').read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(validate_origin(base_url) + '/v1/models?client_version=pi', headers={'Authorization': 'Bearer ' + key})
    with opener.open(request, timeout=15) as response:
        payload = json.load(response)
    values = payload.get('models')
    if not isinstance(values, list) or not values:
        raise ValueError('Expected a non-empty rich catalog; no changes prepared')
    result = {}
    for model in values:
        item = safe_model(model)
        if item['slug'] in result: raise ValueError('Duplicate live route ID')
        result[item['slug']] = item
    return result

def efforts(model):
    return [x['effort'] for x in model.get('supported_reasoning_levels', [])]

def output_limit(model):
    return next((model[k] for k in ('max_tokens', 'max_output_tokens', 'max_completion_tokens') if isinstance(model.get(k), int) and model[k] > 0), None)

def template_catalog_from_native(trusted, native):
    """Add exact missing templates from a read-only local native cache.

    Existing reviewed templates and model prompts are never overwritten. This
    function is never passed the proxy response or another remote catalog.
    """
    result = copy.deepcopy(trusted)
    models = result.setdefault('models', [])
    known = {m['slug'] for m in models}
    added = []
    for model in native.get('models', []):
        slug = model.get('slug')
        messages = model.get('model_messages')
        prompt = messages.get('instructions_template') if isinstance(messages, dict) else None
        if not isinstance(slug, str) or slug in known or not isinstance(prompt, str) or not prompt.strip():
            continue
        value = copy.deepcopy(model)
        value['base_instructions'] = prompt
        value.setdefault('supports_parallel_tool_calls', True)
        models.append(value)
        known.add(slug)
        added.append(slug)
    return result, sorted(added)


def registration_candidates(native, catalogs, known_routes):
    """Report new native IDs missing upstream; never assign account ownership."""
    represented = {m.get('canonical_model_id', m['slug']) for models in catalogs.values() for m in models}
    # Retained configured routes may be temporarily unavailable or deliberately
    # excluded. They are not new releases requiring initial registration.
    known = {route.rsplit('/', 1)[-1] for route in known_routes}
    return sorted({m['slug'] for m in native.get('models', [])
                   if isinstance(m.get('slug'), str) and m.get('visibility', 'list') == 'list'
                   and m['slug'] not in represented and m['slug'] not in known})


def codex_update(document, live, scope, templates=None):
    result = copy.deepcopy(document)
    existing = {m['slug'] for m in result['models']}
    # New prompt-bearing entries need an explicit, reviewed local template. A
    # source name resembling a native model is not enough evidence to copy one.
    pending = []
    templates = {m['slug']: m for m in (templates or {}).get('models', [])}
    for route, fresh in live.items():
        if not route.startswith(scope + '/') or route in existing or route in RETIRED: continue
        template = templates.get(fresh.get('canonical_model_id'))
        if template is None:
            pending.append(route)
            continue
        model = copy.deepcopy(template)
        model.update(slug=route, display_name=model_label(route), visibility='list')
        result['models'].append(model)
    result['models'] = [m for m in result['models'] if m['slug'] not in RETIRED]
    for model in result['models']:
        route = model['slug']
        if route not in live or not route.startswith(scope + '/'): continue
        fresh = live[route]
        for name in CODEX_FIELDS:
            if name in fresh:
                if name == 'default_reasoning_level' and fresh[name] is None:
                    model.pop(name, None)
                elif name == 'supported_reasoning_levels':
                    old_levels = {x['effort']: x for x in model.get(name, [])}
                    model[name] = [copy.deepcopy(old_levels.get(x['effort'], x)) for x in fresh[name]]
                elif name == 'service_tiers':
                    # Only IDs cross the remote trust boundary. Keep existing
                    # local labels, and use local names for newly declared tiers.
                    previous = {x['id']: x for x in model.get(name, [])}
                    model[name] = []
                    for tier in fresh[name]:
                        value = copy.deepcopy(previous.get(tier['id'], {'id': tier['id']}))
                        value.setdefault('name', TIER_NAMES.get(tier['id'], tier['id']))
                        value.setdefault('description', value['name'] + ' service tier')
                        model[name].append(value)
                    if 'additional_speed_tiers' not in fresh:
                        ids = {x['id'] for x in fresh[name]}
                        speeds = (['fast'] if ids & {'fast', 'priority'} else []) + (['ultrafast'] if 'ultrafast' in ids else [])
                        if speeds or 'additional_speed_tiers' in model:
                            model['additional_speed_tiers'] = speeds
                else:
                    model[name] = copy.deepcopy(fresh[name])
        limit = output_limit(fresh)
        if limit is not None: model['max_tokens'] = limit
    return result, pending

def opencode_major_version(binary=None):
    binary = binary or shutil.which('opencode')
    if not binary:
        raise ValueError('OpenCode executable is required to choose its config format')
    try:
        result = subprocess.run([binary, '--version'], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Could not determine installed OpenCode version') from None
    match = re.search(r'^(?:opencode\s+)?v?(\d+)\.\d+\.\d+(?:[-+][^\s]+)?\s*$', result.stdout.strip())
    if result.returncode or not match or int(match[1]) not in (1, 2):
        raise ValueError('Unsupported OpenCode version; retain saved configuration')
    return int(match[1])


def opencode_update(document, live, scope, *, major_version=1):
    result = copy.deepcopy(document)
    provider = result.get('provider', {}).get('cpa-' + scope)
    if not isinstance(provider, dict): raise ValueError('Expected existing scoped OpenCode provider')
    models = provider.setdefault('models', {})
    for route in RETIRED: models.pop(route, None)
    sources = {route: fresh for route, fresh in live.items()
               if route.startswith(scope + '/') and route not in RETIRED}
    # Refresh only explicitly verified aliases; never infer ownership from a family.
    for route in models:
        canonical = canonical_route(route)
        if canonical != route and canonical in sources:
            sources[route] = sources[canonical]
    if major_version == 2:
        # V2's V1 importer exposes disabled entries as selectable variants.
        # This also repairs saved models with temporarily unavailable metadata.
        for model in models.values():
            if isinstance(model.get('variants'), dict):
                model['variants'] = {name: entry for name, entry in model['variants'].items()
                                     if entry.get('disabled') is not True}
    for route, fresh in sources.items():
        model = models.setdefault(route, {'name': model_label(route)})
        context = fresh.get('context_window', fresh.get('max_context_window'))
        maximum = output_limit(fresh)
        limits = copy.deepcopy(model.get('limit', {}))
        if isinstance(context, int) and context > 0: limits['context'] = context
        if maximum is not None: limits['output'] = maximum
        if all(isinstance(limits.get(k), int) and limits[k] > 0 for k in ('context', 'output')):
            model['limit'] = limits
        for source, target in [('supported_input_modalities', 'input'), ('output_modalities', 'output')]:
            values = fresh.get(source)
            if source == 'supported_input_modalities' and values is None: values = fresh.get('input_modalities')
            if values is not None:
                # No generic file -> pdf guess: only types the stock schema accepts.
                model.setdefault('modalities', {})[target] = [x for x in values if x in ('text', 'image', 'audio', 'video', 'pdf')]
        if 'supported_reasoning_levels' in fresh:
            allowed = efforts(fresh)
            model['reasoning'] = any(x != 'none' for x in allowed)
            variants = model.setdefault('variants', {})
            for level in EFFORTS:
                if major_version == 2 and level not in allowed:
                    variants.pop(level, None)
                    continue
                entry = variants.setdefault(level, {})
                if level in allowed:
                    entry.pop('disabled', None)
                    entry['reasoningEffort'] = level
                else:
                    entry['disabled'] = True
            # Preserve valid user defaults; a removed effort cannot remain active.
            options = model.get('options', {})
            if options.get('reasoningEffort') not in (None, *allowed):
                default = fresh.get('default_reasoning_level')
                if default in allowed: options['reasoningEffort'] = default
                else: options.pop('reasoningEffort', None)
    return result

def pi_model_map(live):
    """Render gateway metadata without depending on an npm-based Pi runtime."""
    models = []
    for declared in live.values():
        route = declared['slug'].strip()
        if not route or str(declared.get('visibility', '')).lower() == 'hide':
            continue
        supported = set(efforts(declared))
        inputs = list(dict.fromkeys(str(value).strip().lower()
                      for value in declared.get('input_modalities', [])
                      if str(value).strip().lower() in ('text', 'image')))
        if 'text' not in inputs:
            inputs.insert(0, 'text')
        context = next((declared[key] for key in ('context_window', 'max_context_window')
                        if isinstance(declared.get(key), int) and declared[key] > 0), 128000)
        model = {'id': route, 'name': route, 'reasoning': bool(supported - {'none'}),
                 'input': inputs, 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
                 'contextWindow': context, 'maxTokens': output_limit(declared) or 16384}
        if supported:
            model['thinkingLevelMap'] = {
                level: ('none' if 'none' in supported else None) if level == 'off'
                else level if level in supported else None
                for level in (*PI_THINKING_LEVELS, 'ultra')
            }
        models.append(model)
    return models


def stock_pi_map(profile, live, executable=None):
    package = profile / 'pi/npm/node_modules/@router-for-me/pi-cliproxyapi-provider'
    info = read(package / 'package.json')
    if info.get('name') != '@router-for-me/pi-cliproxyapi-provider': raise ValueError('Unexpected Pi mapping package')
    module = package / 'extensions/lib.ts'
    source = "const {toPiModel}=await import(process.argv[1]); const input=await Bun.stdin.json(); process.stdout.write(JSON.stringify(input.map(m=>toPiModel(m)).filter(Boolean)));"
    executable = executable or shutil.which('pi')
    runtime_modules = next((p for p in pathlib.Path(executable).resolve().parents if p.name == 'node_modules'), None) if executable else None
    if runtime_modules is None: raise ValueError('Could not locate installed stock Pi runtime modules')
    environment = os.environ.copy(); environment['NODE_PATH'] = str(runtime_modules)
    process = subprocess.run(['bun', '-e', source, str(module)], input=json.dumps(list(live.values())).encode(), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode: raise ValueError('Installed stock Pi mapper failed; private input/output not displayed')
    cli_source = runtime_modules/'@earendil-works/pi-coding-agent/dist/cli/args.js'
    match = re.search(r'VALID_THINKING_LEVELS\s*=\s*(\[[^\]]*\])', cli_source.read_text()) if cli_source.is_file() else None
    native_levels = json.loads(match[1]) if match else None
    return json.loads(process.stdout), info['version'], native_levels

def pi_update(document, mapped, live):
    result = copy.deepcopy(document)
    old = {m['id']: m for m in result['models'] if m['id'] not in RETIRED}
    for fresh in mapped:
        route = fresh['id']
        if route in RETIRED: continue
        model = old.setdefault(route, copy.deepcopy(fresh))
        declared = live[route]
        for field in PI_FIELDS:
            if field == 'contextWindow' and not any(declared.get(k) for k in ('context_window', 'max_context_window')): continue
            if field == 'maxTokens' and output_limit(declared) is None: continue
            if field == 'input' and 'input_modalities' not in declared: continue
            if field in ('reasoning', 'thinkingLevelMap') and 'supported_reasoning_levels' not in declared: continue
            if field in fresh: model[field] = copy.deepcopy(fresh[field])
            elif field == 'thinkingLevelMap': model.pop(field, None)
        model.pop('stale', None); model.pop('staleSince', None)
        # Preserve existing cost, name and last-seen bookkeeping; no pricing guess.
    result['models'] = list(old.values())
    result['fastModelIds'] = [x for x in result.get('fastModelIds', []) if x not in RETIRED]
    # Missing non-retired routes stay cached, matching stock provider retention.
    return result

def pi_native_update(document, cache, scope, endpoint, authoritative=False):
    """Use scoped native Responses definitions instead of combined discovery.

    Retain saved in-scope IDs, overrides and capabilities. Never register the
    other account or ambiguous unscoped aliases in an account-specific home.
    """
    result = copy.deepcopy(document)
    providers = result.setdefault('providers', {})
    if set(providers) - {'cliproxyapi'}:
        raise ValueError('Native Pi profile must contain only the managed gateway provider')
    provider = providers.setdefault('cliproxyapi', {})
    previous_names = {model['id']: model.get('name') for model in provider.get('models', [])}
    models = []
    for old in cache['models']:
        if not old['id'].startswith(scope + '/') or old['id'] in RETIRED:
            continue
        model = {key: copy.deepcopy(old[key]) for key in
                 ('id', 'name', 'cost', *PI_FIELDS) if key in old}
        model['api'] = 'openai-responses'
        override = provider.get('modelOverrides', {}).get(old['id'])
        if isinstance(override, dict) and 'name' in override and override['name'] in (
                model_label(old['id']), previous_names.get(old['id'])):
            # Inherit the generated model name on every later sync. Recognize
            # overrides already relabelled by an earlier helper as well.
            # Deliberate custom names and unrelated override fields stay.
            override.pop('name')
        models.append(model)
    if not models and not authoritative:
        raise ValueError('Empty native Pi scope; retain saved configuration')
    provider.update(name='CPA ' + scope.title(), api='openai-responses',
                    apiKey='${CPA_API_KEY}', baseUrl=endpoint + '/v1', models=models)
    return result

def projection(document, kind, scope):
    if kind == 'codex': return {m['slug']: {k: m[k] for k in CODEX_FIELDS if k in m} for m in document['models']}
    if kind == 'pi': return {m['id']: {k: m[k] for k in PI_FIELDS if k in m} for m in document['models']}
    allowed = ('limit', 'modalities', 'reasoning')
    out = {}
    for route, m in document['provider']['cpa-' + scope]['models'].items():
        out[route] = {k: m[k] for k in allowed if k in m}
        out[route]['efforts'] = {k: {'disabled': v.get('disabled', False), 'reasoningEffort': v.get('reasoningEffort')} for k, v in m.get('variants', {}).items() if k in EFFORTS}
    return out

def change_report(before, after, kind, scope):
    first, second = projection(before, kind, scope), projection(after, kind, scope)
    return {'added': sorted(second.keys() - first.keys()), 'removed': sorted(first.keys() - second.keys()),
            'updated': [{'route': k, 'fields': sorted(f for f in first[k].keys() | second[k].keys() if first[k].get(f) != second[k].get(f))} for k in sorted(first.keys() & second.keys()) if first[k] != second[k]]}

def permitted_paths(profiles):
    return {profiles/s/rel for s in SCOPES for rel in ('catalogs/codex-catalog.json', 'config/opencode/opencode.json', 'pi/cliproxyapi-models.json')}

def validate_targets(paths, profiles, forbidden=(), extra_paths=()):
    permitted = permitted_paths(profiles) | set(extra_paths)
    forbidden = {p.resolve() for p in forbidden}
    for path in paths:
        if path not in permitted or path.resolve() in forbidden: raise ValueError('Refusing non-scoped or main Codex target')
        if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Refusing symlinked catalog target')
        if not path.is_file(): raise ValueError('Scoped target must already exist')

def atomic_write(path, raw, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def apply_changes(changes, profiles, backup_root, forbidden=(), extra_paths=()):
    validate_targets(changes, profiles, forbidden, extra_paths)
    for path, item in changes.items():
        if path.read_bytes() != item['before']: raise ValueError('A target changed after preview; rerun preview')
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = pathlib.Path(tempfile.mkdtemp(prefix='scoped-catalog-', dir=backup_root)); backup.chmod(0o700)
    manifest = []
    for index, (path, item) in enumerate(changes.items()):
        saved = backup / str(index); saved.write_bytes(item['before']); saved.chmod(0o600)
        manifest.append({'path': str(path), 'backup': str(index), 'beforeSha256': digest(item['before']), 'afterSha256': digest(item['after'])})
    (backup/'manifest.json').write_bytes(encoded(manifest)); (backup/'manifest.json').chmod(0o600)
    written = []
    try:
        for path, item in changes.items():
            if path.read_bytes() != item['before']: raise ValueError('A target changed during apply')
            atomic_write(path, item['after'], path.stat().st_mode & 0o777)
            written.append(path)
    except BaseException:
        conflicts = []
        for path in reversed(written):
            item = changes[path]
            if path.read_bytes() == item['after']: atomic_write(path, item['before'], path.stat().st_mode & 0o777)
            else: conflicts.append(str(path))
        if conflicts: raise RuntimeError('Concurrent changes prevented rollback; private backups retained')
        raise
    return backup

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--standardize-names', action='store_true', help='Also preview/apply display names across managed clients after reconciliation; names cover both scopes and staged desktop catalogs')
    parser.add_argument('--scope', action='append', choices=SCOPES)
    parser.add_argument('--base-url', default='http://127.0.0.1:8317')
    parser.add_argument('--report', type=pathlib.Path, default=ROOT/'artifacts/update-2026-09-20/scoped-catalog-preview.json')
    parser.add_argument('--template-catalog', type=pathlib.Path, default=PROFILES/'codex-desktop/trusted-templates.json', help='Read-only trusted local native templates; exact canonical ID match only')
    args = parser.parse_args()
    validate_origin(args.base_url)
    main_config = pathlib.Path.home()/'.codex/config.toml'
    parsed = tomllib.loads(main_config.read_text())
    forbidden = [main_config, pathlib.Path(parsed['model_catalog_json']).expanduser()] if parsed.get('model_catalog_json') else [main_config]
    protected = {p: p.read_bytes() for p in forbidden if p.is_file()}
    if not args.report.resolve().is_relative_to((ROOT/'artifacts').resolve()): raise ValueError('Report must stay inside lab artifacts')
    templates = read(args.template_catalog) if args.template_catalog.is_file() else {}
    native = {}; native_cache_status = 'not-used-with-custom-main-provider'
    native_cache = pathlib.Path.home()/'.codex/models_cache.json'
    if parsed.get('model_provider') in (None, 'openai') and not parsed.get('model_catalog_json'):
        native_cache_status = 'unavailable'
        if native_cache.is_file():
            try:
                candidate = read(native_cache)
                if isinstance(candidate, dict) and isinstance(candidate.get('models'), list) and all(isinstance(m, dict) for m in candidate['models']):
                    native = candidate
                    native_cache_status = 'read-only'
            except (OSError, ValueError):
                native_cache_status = 'unreadable'
    templates, native_template_ids = template_catalog_from_native(templates, native)
    # Client version is not a prompt template. A future main-Codex gateway
    # cutover must not disable authenticated provider discovery.
    discovery_client = native
    if not discovery_client and native_cache.is_file():
        try:
            discovery_client = {'client_version': read(native_cache).get('client_version')}
        except (OSError, ValueError, AttributeError):
            discovery_client = {}
    account_capabilities, account_receipt = codex_account_tiers.discover(args.base_url, discovery_client)
    changes = {}; reports = []; snapshot = {}; known_routes = set(); deferred = {}; authenticated_fields = {}
    for scope in args.scope or SCOPES:
        profile = PROFILES/scope; live = live_models(profile, args.base_url)
        # The authenticated provider response outranks generic proxy/model metadata.
        authenticated_fields.update(codex_account_tiers.apply(live, account_capabilities))
        # Pi intentionally keeps a combined cache. Defer unverifiable routes
        # in both scopes before handing that combined catalog to its mapper.
        deferred[scope] = [route for owner in SCOPES for route in codex_account_tiers.verified_routes(live, account_capabilities, owner)]
        snapshot[scope] = list(live.values())
        mapper, version, native_levels = stock_pi_map(profile, live)
        for kind, rel in [('codex', 'catalogs/codex-catalog.json'), ('opencode', 'config/opencode/opencode.json'), ('pi', 'pi/cliproxyapi-models.json')]:
            path = profile/rel; before = path.read_bytes(); document = json.loads(before)
            pending = []
            known_routes.update(projection(document, kind, scope))
            if kind == 'codex':
                updated, pending = codex_update(document, live, scope, templates)
            elif kind == 'opencode': updated = opencode_update(document, live, scope, major_version=opencode_major_version())
            else: updated = pi_update(document, mapper, live)
            report = {'scope': scope, 'harness': kind, 'path': str(path), **change_report(document, updated, kind, scope)}
            report['retainedMissingRoutes'] = sorted(k for k in projection(updated, kind, scope) if k not in live)
            if pending: report['newCodexRoutesNeedingTrustedTemplate'] = pending
            if kind == 'pi':
                report.update(stockMapperVersion=version, scopeFilter='unsupported; combined cache preserved', nativeThinkingLevels=native_levels)
                report['providerEffortsWithoutNativeCLILevel'] = sorted({level for value in live.values() for level in efforts(value) if native_levels is not None and ('off' if level == 'none' else level) not in native_levels})
                report['routesWithStockFallbackLimits'] = sorted(k for k,v in live.items() if not v.get('context_window',v.get('max_context_window')) or output_limit(v) is None)
            if kind == 'opencode': report['legacyAliasesRetainedForSavedThreads'] = sorted(k for k in projection(updated, kind, scope) if not k.startswith(scope+'/'))
            reports.append(report)
            after = encoded(updated)
            if json.loads(before) != updated: changes[path] = {'before': before, 'after': after}
    validate_targets(changes, PROFILES, forbidden)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {'checkedAt': stamp, 'mode': 'apply' if args.apply else 'preview', 'filesChanged': len(changes), 'catalogCounts': {k: len(v) for k,v in snapshot.items()}, 'files': reports, 'mainCodexUntouched': True}
    result['providerCapabilityPolicy'] = 'authenticated account discovery > provider route metadata > retained local fallback; no plan or model-name entitlement rules'
    result['codexAccountCapabilities'] = account_receipt
    result['codexRoutesDeferredWithoutAccountMetadata'] = deferred
    result['capabilitySources'] = {scope: {m['slug']: {
        'authenticatedProviderFields': sorted(account_capabilities.get(m['slug'], {})),
        'authenticatedDerivedFields': sorted(set(authenticated_fields.get(m['slug'], [])) - set(account_capabilities.get(m['slug'], {}))),
        'proxyMetadataFields': sorted(k for k in m if k != 'slug' and k not in authenticated_fields.get(m['slug'], [])),
        'missingFieldsRetainExistingValues': True,
    } for m in models} for scope, models in snapshot.items()}
    result['nativeCacheStatus'] = native_cache_status
    result['nativeTemplatesAvailableInMemory'] = native_template_ids
    result['nativeModelsNeedingProxyRegistration'] = registration_candidates(native, snapshot, known_routes)
    result['newCodexRoutesNeedingTrustedTemplate'] = sorted({route for report in reports for route in report.get('newCodexRoutesNeedingTrustedTemplate', [])})
    result['advertisedServiceTiers'] = {scope: sorted({tier['id'] for model in models if model['slug'].startswith(scope + '/') for tier in model.get('service_tiers', [])}) for scope, models in snapshot.items()}
    if result['nativeModelsNeedingProxyRegistration']:
        result['discoveryAction'] = 'Register the model on its verified account in Easy and refresh the proxy registry. Client catalog refresh only reconciles already exported routes; native cache presence does not prove CPA account access.'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.with_name(args.report.stem+'-live.json').write_bytes(encoded({'checkedAt':stamp, 'catalogs':snapshot}))
    if args.apply and changes:
        result['backup'] = str(apply_changes(changes, PROFILES, ROOT/'private/catalog-refresh', forbidden))
    if any(p.read_bytes() != raw for p,raw in protected.items()): raise RuntimeError('Main Codex changed externally during reconciliation')
    args.report.write_bytes(encoded(result))
    summary = {k: result.get(k) for k in ('mode', 'filesChanged', 'backup', 'catalogCounts', 'advertisedServiceTiers', 'nativeModelsNeedingProxyRegistration', 'newCodexRoutesNeedingTrustedTemplate')}
    summary['report'] = str(args.report)
    if result.get('discoveryAction'): summary['discoveryAction'] = result['discoveryAction']
    print(json.dumps(summary, indent=2), flush=True)
    if args.standardize_names:
        # Separate name-only transaction with its own report and private backup.
        # Running after reconciliation includes newly added routes in Pi overrides.
        command = [sys.executable, str(pathlib.Path(__file__).with_name('standardize_model_names.py')),
                   '--report', str(args.report.with_name(args.report.stem+'-names.json'))]
        if args.apply: command.append('--apply')
        subprocess.run(command, check=True)

if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Do not include exception response bodies/config fragments in public logs.
        print(f'Catalog reconciliation failed ({type(error).__name__}); no sensitive values displayed.', file=sys.stderr)
        raise SystemExit(1)
