#!/usr/bin/env python3
"""Preview/apply the same display names to existing managed client catalogs.

Does not add/remove model routes or change capabilities, prompts, defaults or auth.
Main Codex and its active catalog are always protected. No process is restarted.
"""
from __future__ import annotations
import os
import argparse
import copy
import datetime
import json
import pathlib
import tempfile
import tomllib
from model_labels import model_label
from refresh_scoped_catalogs import atomic_write, digest, encoded

ROOT = pathlib.Path(os.environ.get('CPA_STATE_DIR', pathlib.Path.home()/'.local/state/cpa-stack'))
HOME = pathlib.Path.home()
PROFILES = HOME / 'Library/Application Support/Agent Profiles'


def without_names(value):
    """Compare model definitions independent of presentation, at model scope only."""
    value = copy.deepcopy(value)
    value.pop('name', None)
    value.pop('display_name', None)
    return value


def rename(model, route, field, changes):
    name = model_label(route)
    if name == route:  # Unknown account/source is deliberately not guessed.
        return
    if model.get(field) != name:
        before = copy.deepcopy(model)
        changes.append({'route': route, 'before': model.get(field), 'after': name})
        model[field] = name
        assert without_names(before) == without_names(model)


def transform(document, kind):
    result = copy.deepcopy(document)
    changes = []
    if kind in ('codex', 'pi'):
        field, identity = ('display_name', 'slug') if kind == 'codex' else ('name', 'id')
        for model in result['models']:
            rename(model, model[identity], field, changes)
    elif kind == 'opencode':
        for provider_id, provider in result.get('provider', {}).items():
            if provider_id not in ('cpa-personal', 'cpa-work'):
                continue
            for route, model in provider.get('models', {}).items():
                rename(model, route, 'name', changes)
    elif kind == 't3':
        for instance in result.get('providerInstances', {}).values():
            models = instance.get('config', {}).get('customModels', [])
            for index, entry in enumerate(models):
                route = entry if isinstance(entry, str) else entry['slug']
                if model_label(route) == route:
                    continue
                model = {'slug': route} if isinstance(entry, str) else entry
                rename(model, route, 'name', changes)
                models[index] = model
    else:
        raise ValueError('Unknown catalog type')
    return result, changes


def pi_overrides(document, cache):
    result = copy.deepcopy(document)
    changes = []
    for model in cache['models']:
        route = model['id']
        if model_label(route) == route:
            continue
        overrides = result.setdefault('providers', {}).setdefault('cliproxyapi', {}).setdefault('modelOverrides', {})
        rename(overrides.setdefault(route, {}), route, 'name', changes)
    return result, changes


def targets():
    result = []
    for scope in ('personal', 'work'):
        result.extend([(PROFILES/scope/'catalogs/codex-catalog.json', 'codex'),
                       (PROFILES/scope/'config/opencode/opencode.json', 'opencode'),
                       (PROFILES/scope/'pi/cliproxyapi-models.json', 'pi')])
    result.extend([(PROFILES/'codex-desktop/catalog.json', 'codex'),
                   (PROFILES/'codex-desktop/generated/codex-catalog.json', 'codex'),
                   (HOME/'.config/opencode/opencode.json', 'opencode'),
                   (HOME/'.pi/agent/cliproxyapi-models.json', 'pi'),
                   (HOME/'.t3/userdata/settings.json', 't3')])
    return result


def checked_target(path, protected):
    if path.resolve() in protected or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Protected or symlinked target')


def apply(changes, protected):
    root = ROOT/'private/model-names'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = pathlib.Path(tempfile.mkdtemp(prefix='labels-', dir=root))
    manifest = []
    for index, (path, before, after) in enumerate(changes):
        checked_target(path, protected)
        if (path.read_bytes() if path.exists() else None) != before:
            raise ValueError('A target changed after preview')
        if before is not None:
            backup = folder/str(index)
            backup.write_bytes(before)
            backup.chmod(0o600)
        manifest.append({'path': str(path), 'backup': str(index) if before is not None else None,
                         'beforeSha256': digest(before) if before is not None else None,
                         'afterSha256': digest(after)})
    (folder/'manifest.json').write_bytes(encoded(manifest))
    written = []
    try:
        for path, before, after in changes:
            if (path.read_bytes() if path.exists() else None) != before:
                raise ValueError('A target changed during apply')
            atomic_write(path, after, path.stat().st_mode & 0o777 if path.exists() else 0o600)
            written.append((path, before, after))
        if any(p.read_bytes() != data for p, data in protected.items()):
            raise ValueError('Protected main Codex changed externally')
    except BaseException:
        for path, before, after in reversed(written):
            if path.read_bytes() != after:
                continue
            if before is None:
                path.unlink()
            else:
                atomic_write(path, before, path.stat().st_mode & 0o777)
        raise
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=pathlib.Path, default=ROOT/'artifacts/model-names-2026-09-22/labels.json')
    args = parser.parse_args()
    if not args.report.resolve().is_relative_to((ROOT/'artifacts').resolve()):
        raise ValueError('Report must stay inside lab artifacts')
    main = HOME/'.codex/config.toml'
    protected = {main.resolve(): main.read_bytes()}
    main_config = tomllib.loads(main.read_text())
    if main_config.get('model_catalog_json'):
        active = pathlib.Path(main_config['model_catalog_json']).expanduser().resolve()
        protected[active] = active.read_bytes()
    changes, reports, skipped = [], [], []
    for path, kind in targets():
        if path.resolve() in protected:
            skipped.append(str(path))
            continue
        checked_target(path, protected)
        before = path.read_bytes()
        result, labels = transform(json.loads(before), kind)
        reports.append({'path': str(path), 'kind': kind, 'labels': labels})
        if labels:
            changes.append((path, before, encoded(result)))
        if kind == 'pi':
            # Stock Pi applies modelOverrides after every extension registration,
            # so background refresh cannot undo these presentation names.
            target = path.with_name('models.json')
            checked_target(target, protected)
            old = target.read_bytes() if target.exists() else None
            updated, overrides = pi_overrides(json.loads(old) if old else {}, result)
            reports.append({'path': str(target), 'kind': 'pi-overrides', 'labels': overrides})
            if overrides:
                changes.append((target, old, encoded(updated)))
    backup = apply(changes, protected) if args.apply and changes else None
    assert all(p.read_bytes() == raw for p, raw in protected.items())
    report = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'mode': 'apply' if args.apply else 'preview', 'filesChanged': len(changes),
              'labelChanges': sum(len(r['labels']) for r in reports), 'files': reports,
              'protectedFilesSkipped': skipped, 'mainCodexUntouched': True,
              'backup': str(backup) if backup else None}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(encoded(report))
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Name update failed ({type(error).__name__}); private values not displayed.')
        raise SystemExit(1)
