#!/usr/bin/env python3
"""Repair the 2026.10.20.1 native host manifest environment without reinstalling."""
import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile

BEFORE = '0709bd73b04b53dc714e4439da005b1e006fa1c7fb69c459d2965dab77bdbf7b'
AFTER = '94a3089da011e9dc7ed63f54c1d2fd0f19fce450a1097360ec0c52e75beeb40e'
PATCHES = [(
    "    result.update(state['environment'])\n",
    "    result.update(state['environment'])\n"
    "    # Packages installed before the manifest fix filtered ASCEND_* variables.\n"
    "    # The Platform setting survived and already contains the translated host path.\n"
    "    if not result.get('ASCEND_MODEL_MANIFEST') and result.get('PIPELINE_ASCEND_MANIFEST'):\n"
    "        result['ASCEND_MODEL_MANIFEST'] = result['PIPELINE_ASCEND_MANIFEST']\n",
), (
    "                   and not k.startswith(('ASCEND_', 'NNA', 'CANN', 'TBE'))}",
    "                   and (k == 'ASCEND_MODEL_MANIFEST' or not k.startswith(('ASCEND_', 'NNA', 'CANN', 'TBE')))}",
)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode):
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def repair(root):
    root = root.resolve(strict=True)
    release = json.loads((root / 'HOST_RELEASE.json').read_text())
    if release.get('kind') != 'native-host-platform' or release.get('version') != '2026.10.20.1':
        raise ValueError('Only native host package 2026.10.20.1 is supported')
    state = root / 'state'
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / 'control.lock').open('a') as control, (state / 'run.lock').open('a') as running:
        fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(running, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = root / 'host_platform.py'
        inventory = root / 'SHA256SUMS'
        if target.is_symlink() or inventory.is_symlink():
            raise ValueError('Refusing symlinked controller or checksum inventory')
        original = target.read_bytes()
        checksum = digest(original)
        if checksum not in {BEFORE, AFTER}:
            raise ValueError('Controller differs from known release; no files changed')
        lines = inventory.read_text().splitlines()
        indexes = [i for i, line in enumerate(lines) if line.endswith('  host_platform.py')]
        if len(indexes) != 1 or lines[indexes[0]].split('  ', 1)[0] not in {BEFORE, AFTER}:
            raise ValueError('Controller checksum inventory differs from known release')
        updated = original
        if checksum == BEFORE:
            text = original.decode()
            for old, new in PATCHES:
                if text.count(old) != 1:
                    raise ValueError('Unexpected source patch location')
                text = text.replace(old, new, 1)
            updated = text.encode()
        if digest(updated) != AFTER:
            raise ValueError('Repaired controller checksum does not match')
        compile(updated, str(target), 'exec')
        backup = state / 'manifest-fix-backup'
        backup.mkdir(mode=0o700, exist_ok=True)
        for name, data in [('host_platform.py', original), ('SHA256SUMS', inventory.read_bytes())]:
            path = backup / name
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(data)
                path.chmod(0o600)
        lines[indexes[0]] = AFTER + '  host_platform.py'
        atomic_write(target, updated, 0o755)
        atomic_write(inventory, ('\n'.join(lines) + '\n').encode(), 0o644)
        logging.info('Manifest environment repair complete; existing site.json and Docker configuration retained')


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s pid=%(process)d %(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    repair(args.package_root)


if __name__ == '__main__':
    main()
