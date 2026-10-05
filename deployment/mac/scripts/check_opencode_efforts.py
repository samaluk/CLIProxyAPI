#!/usr/bin/env python3
"""Compare running stock OpenCode 2 variants with the scoped gateway evidence.

No prompts or inference requests. Existing service credentials stay in memory.
"""
import json
from pathlib import Path
import sys
import urllib.parse

import opencode_services
import refresh_scoped_catalogs as catalogs


def check(root):
    results = []
    for scope in ('personal', 'work'):
        registry = catalogs.read(root / scope / 'state/opencode/service.json')
        if registry['url'] != f'http://127.0.0.1:{49374 if scope == "personal" else 49375}':
            raise ValueError('Unexpected scoped OpenCode service URL')
        snapshot = catalogs.read(root / 'sync-state' / (scope + '.json'))
        path = '/api/model?' + urllib.parse.urlencode({'location[directory]': str(Path.home())})
        models = opencode_services.request(registry['url'], registry['password'], path)['data']
        actual = {m['id']: m for m in models if m['providerID'] == 'cpa-' + scope}
        mismatches = []
        checked = 0
        for model in snapshot['models']:
            if 'supported_reasoning_levels' not in model:
                continue
            checked += 1
            expected = {level['effort'] for level in model['supported_reasoning_levels']}
            observed = {variant['id'] for variant in actual.get(model['slug'], {}).get('variants', [])}
            if expected != observed:
                mismatches.append({'model': model['slug'], 'expected': sorted(expected), 'actual': sorted(observed)})
        results.append({'scope': scope, 'checked': checked, 'mismatches': mismatches})
    return results


if __name__ == '__main__':
    root = Path.home() / ('Library/Application Support/Agent Profiles' if sys.platform == 'darwin' else '.config/cpa/profiles')
    results = check(root)
    print(json.dumps(results, indent=2))
    sys.exit(1 if any(r['mismatches'] for r in results) else 0)
