#!/usr/bin/env python3
"""Prepare a reversible Console-only overlay in an existing private release."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

VERSION = '2026.10.18-console.2'
DIRECTORY = 'console-fix-20261018-2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(root, payload):
    root, payload = Path(root), Path(payload)
    compose = root / 'docker-compose.yaml'
    marker = root / f'.{DIRECTORY}.json'
    if marker.exists():
        record = json.loads(marker.read_text())
        if record['version'] != VERSION or sha(compose) != record['compose_sha256']:
            raise ValueError('Compose changed since this fix; retain the backup and reconcile changes first')
        return record
    if not (root / '.env').is_file() or not (root / 'IMAGES.txt').is_file():
        raise ValueError('Target must be an extracted private offline release')
    model = json.loads(compose.read_text())
    services = model['services']
    if not {'platform', 'init-db', 'console2'}.issubset(services):
        raise ValueError('Unexpected deployment services')
    target = root / DIRECTORY
    backup = root / f'.{DIRECTORY}-backup'
    if target.exists() or backup.exists():
        raise ValueError('Partial fix exists; inspect the existing backup before retrying')
    checks = dict((line.split('  ', 1)[1], line.split('  ', 1)[0])
                  for line in (root / 'SHA256SUMS').read_text().splitlines())
    if checks.get('docker-compose.yaml') != sha(compose):
        raise ValueError('Compose does not match its checksum; reconcile existing site changes first')
    console = services['console2']
    mounts = [item for item in console.get('volumes', [])
              if (item.get('target') if isinstance(item, dict) else item.split(':')[1])
              not in {'/usr/share/nginx/html', '/docker-entrypoint.d/40-amap-runtime-config.sh'}]
    for source, destination, readonly in (
        ('html', '/usr/share/nginx/html', False),
        ('40-amap-runtime-config.sh', '/docker-entrypoint.d/40-amap-runtime-config.sh', True),
    ):
        mounts.append({'type': 'bind', 'source': f'./{DIRECTORY}/{source}',
                       'target': destination, 'read_only': readonly, 'bind': {'create_host_path': False}})
    console['volumes'] = mounts
    for name in ('MINEMAP_SDK_BASE_URL', 'MINEMAP_SERVICE_URL', 'MINEMAP_SERVER_DOMAIN', 'MINEMAP_STYLE_URL'):
        console.setdefault('environment', {}).setdefault(name, '${' + name + ':-}')
    backup.mkdir(mode=0o700)
    for name in ('docker-compose.yaml', 'SHA256SUMS'):
        shutil.copy2(root / name, backup / name)
    shutil.copytree(payload / 'console', target)
    tools = root / 'deploy/intranet'
    tools.mkdir(parents=True, exist_ok=True)
    if (tools / 'diagnose_live.py').exists():
        shutil.copy2(tools / 'diagnose_live.py', backup / 'diagnose_live.py')
    shutil.copy2(payload / 'diagnose_live.py', tools / 'diagnose_live.py')
    temporary = root / '.console-compose.tmp'
    temporary.write_text(json.dumps(model, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(compose)
    for path in target.rglob('*'):
        if path.is_file() and path.name != 'runtime-config.js':
            checks[path.relative_to(root).as_posix()] = sha(path)
    checks['docker-compose.yaml'] = sha(compose)
    checks['deploy/intranet/diagnose_live.py'] = sha(tools / 'diagnose_live.py')
    (root / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in sorted(checks.items())))
    record = {'version': VERSION, 'compose_sha256': sha(compose), 'backup': backup.name}
    marker.write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    print(json.dumps(apply(sys.argv[1], sys.argv[2]), ensure_ascii=False))
