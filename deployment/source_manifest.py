"""Verify exported source identity before version stamping or compilation."""
import hashlib
import json
import os


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            kind, value = 'symlink', os.readlink(path).encode()
        elif path.is_file():
            kind, value = ('executable' if path.stat().st_mode & 0o111 else 'file'), path.read_bytes()
        elif path.is_dir():
            continue
        else:
            raise ValueError('Unsupported source entry')
        name = path.relative_to(root).as_posix()
        digest.update(json.dumps([name, kind, hashlib.sha256(value).hexdigest()], separators=(',', ':')).encode() + b'\n')
    return digest.hexdigest()


def verify_source(sources, component):
    name = component['repository'].split('/')[1]
    manifest = json.loads((sources / 'manifest.json').read_text())
    actual = manifest.get(name, {})
    if actual.get('repository') != component['repository'] or actual.get('commit') != component['commit']:
        raise ValueError(name + ': exported source does not match current lock; prepare sources again')
    if tree_digest(sources / name) != actual.get('tree_sha256'):
        raise ValueError(name + ': exported source content changed')
    return actual['tree_sha256']
