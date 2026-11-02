#!/usr/bin/env python3
"""Repair the 2026.10.19 host-source Console without restarting Platform."""
import base64
import fcntl
import hashlib
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

OLD_SHA256 = '44d09fc9fd26e1df2d00506d647d2edc22c2c637d1a59f0cca216d5758517301'
PAYLOAD_SHA256 = 'aa737333d1b87a4001c11af56202a452a0d35066f35c73bdc6190b51ae1cdc35'
PAYLOAD = 'IyEvYmluL3NoCiMgSG9zdCBhcHBsaWNhdGlvbiBmaWxlcyBzdGF5IHJlYWQtb25seTsgZ2VuZXJhdGVkIGNvbmZpZ3VyYXRpb24gbGl2ZXMgaW4gdGhlIGNvbnRhaW5lci4Kc2V0IC1ldQp1bWFzayAwMjcKcnVudGltZT0vdmFyL3J1bi90cmFmZmljLWNvbnNvbGUKbG9ncz0ke1RSQUZGSUNfTE9HX0RJUjotL3Zhci9sb2cvdHJhZmZpYy1hbmFseXplcn0vbmdpbngKbWtkaXIgLXAgIiRydW50aW1lIiAiJGxvZ3MiCmNobW9kIDc1NSAiJHJ1bnRpbWUiCgpyb3RhdGVfZmlsZSgpIHsKICAgIGZpbGU9JDEKICAgIFsgLWYgIiRmaWxlIiBdIHx8IHJldHVybiAxCiAgICBbICIkKHdjIC1jIDwgIiRmaWxlIikiIC1nZSAyMDk3MTUyMCBdIHx8IHJldHVybiAxCiAgICBybSAtZiAiJGZpbGUuNSIKICAgIG51bWJlcj00CiAgICB3aGlsZSBbICIkbnVtYmVyIiAtZ3QgMCBdOyBkbwogICAgICAgIFsgISAtZiAiJGZpbGUuJG51bWJlciIgXSB8fCBtdiAiJGZpbGUuJG51bWJlciIgIiRmaWxlLiQoKG51bWJlciArIDEpKSIKICAgICAgICBudW1iZXI9JCgobnVtYmVyIC0gMSkpCiAgICBkb25lCiAgICBtdiAiJGZpbGUiICIkZmlsZS4xIgp9CgpzdGFydHVwX2xvZygpIHsKICAgIHByaW50ZiAnJXMgbGV2ZWw9SU5GTyBjb21wb25lbnQ9Y29uc29sZS1zdGFydHVwIHBpZD0lcyAlc1xuJyAiJChkYXRlIC11ICcrJVktJW0tJWRUJUg6JU06JVNaJykiICIkJCIgIiQqIiB8IHRlZSAtYSAiJGxvZ3Mvc3RhcnR1cC5sb2ciCn0KCnJ1bl9zdGVwKCkgewogICAgc3RhcnR1cF9sb2cgInN0YWdlPSQxIGV2ZW50PUJFR0lOIgogICAgbmFtZT0kMQogICAgc2hpZnQKICAgIGlmICIkQCIgPiAiJHJ1bnRpbWUvc3RlcC5sb2ciIDI+JjE7IHRoZW4KICAgICAgICBjYXQgIiRydW50aW1lL3N0ZXAubG9nIiB8IHRlZSAtYSAiJGxvZ3Mvc3RhcnR1cC5sb2ciCiAgICAgICAgc3RhcnR1cF9sb2cgInN0YWdlPSRuYW1lIGV2ZW50PUVORCIKICAgIGVsc2UKICAgICAgICBzdGF0dXM9JD8KICAgICAgICBjYXQgIiRydW50aW1lL3N0ZXAubG9nIiB8IHRlZSAtYSAiJGxvZ3Mvc3RhcnR1cC5sb2ciID4mMgogICAgICAgIHN0YXJ0dXBfbG9nICJzdGFnZT0kbmFtZSBldmVudD1FUlJPUiBleGl0X2NvZGU9JHN0YXR1cyIKICAgICAgICByZXR1cm4gIiRzdGF0dXMiCiAgICBmaQp9CgojIE5naW54IGVycm9ycyBjYW4gaW5jbHVkZSB0aGUgb3JpZ2luYWwgVVJJOyBmaWx0ZXIgcXVlcnkgY3JlZGVudGlhbHMgYmVmb3JlIGVpdGhlciBzaW5rLgpybSAtZiAiJHJ1bnRpbWUvZXJyb3IucGlwZSIKbWtmaWZvICIkcnVudGltZS9lcnJvci5waXBlIgpleGVjIDM8PiAiJHJ1bnRpbWUvZXJyb3IucGlwZSIKKAogICAgd2hpbGUgSUZTPSByZWFkIC1yIGxpbmU7IGRvCiAgICAgICAgcHJpbnRmICclc1xuJyAiJGxpbmUiIHwgc2VkIC1FIFwKICAgICAgICAgICAgLWUgJ3MvKFs/XCZdKGFjY2Vzc190b2tlbnx0b2tlbnxwYXNzd29yZHxzZWNyZXR8YXBpX2tleSk9KVteXCZbOnNwYWNlOl0iXSovXDFbcmVkYWN0ZWRdL2cnIFwKICAgICAgICAgICAgLWUgJ3MjKFthLXpdKzovLylbXi9AWzpzcGFjZTpdXSs6W14vQFs6c3BhY2U6XV0rQCNcMVtyZWRhY3RlZF1AI2cnIFwKICAgICAgICAgICAgfCB0ZWUgLWEgIiRsb2dzL2Vycm9yLmxvZyIgPiYyCiAgICBkb25lIDwmMwopICYKCnJvdGF0ZV9maWxlICIkbG9ncy9zdGFydHVwLmxvZyIgfHwgdHJ1ZQpzdGFydHVwX2xvZyAnZXZlbnQ9U1RBUlQgcmVhZG9ubHlfaG9zdF9yZXNvdXJjZXM9dHJ1ZScKZm9yIHJlcXVpcmVkIGluIGluZGV4Lmh0bWwgcnVudGltZS1jb25maWcudGVtcGxhdGUuanM7IGRvCiAgICBpZiBbICEgLXIgIi9vcHQvdHJhZmZpYy1jb25zb2xlL2h0bWwvJHJlcXVpcmVkIiBdOyB0aGVuCiAgICAgICAgc3RhcnR1cF9sb2cgImV2ZW50PUVSUk9SIHVucmVhZGFibGVfcmVzb3VyY2U9JHJlcXVpcmVkIgogICAgICAgIGV4aXQgMQogICAgZmkKZG9uZQoKIyBFeHRyYWN0aW9uIGNhbiBsZWF2ZSByZWFkLW9ubHkgaG9zdCBmaWxlcyBhdCA3MDAvNjAwOyBOZ2lueCB3b3JrZXJzIG5lZWQgcHVibGljIGNvcGllcy4KcHJlcGFyZV9odG1sKCkgewogICAgcm0gLXJmICIkcnVudGltZS9odG1sIgogICAgY3AgLVIgL29wdC90cmFmZmljLWNvbnNvbGUvaHRtbCAiJHJ1bnRpbWUvaHRtbCIKICAgIGZpbmQgIiRydW50aW1lL2h0bWwiIC10eXBlIGQgLWV4ZWMgY2htb2QgNzU1IHt9ICsKICAgIGZpbmQgIiRydW50aW1lL2h0bWwiIC10eXBlIGYgLWV4ZWMgY2htb2QgNjQ0IHt9ICsKfQpydW5fc3RlcCBwcmVwYXJlLWh0bWwgcHJlcGFyZV9odG1sCgojIExvZyB0aGUgVVJJIHdpdGhvdXQgaXRzIHF1ZXJ5IHN0cmluZyBzbyBXZWJTb2NrZXQgdG9rZW5zIHN0YXkgb3V0IG9mIGFjY2VzcyBsb2dzLgpjYXQgPiAvZXRjL25naW54L2NvbmYuZC9kZWZhdWx0LmNvbmYgPDwnTkdJTlgnCmxvZ19mb3JtYXQgdHJhZmZpY19zb3VyY2UgJyR0aW1lX2lzbzg2MDEgbGV2ZWw9SU5GTyBjb21wb25lbnQ9bmdpbnggcGlkPSRwaWQgbWV0aG9kPSRyZXF1ZXN0X21ldGhvZCB1cmk9IiR1cmkiIHN0YXR1cz0kc3RhdHVzIGJ5dGVzPSRib2R5X2J5dGVzX3NlbnQgZHVyYXRpb249JHJlcXVlc3RfdGltZSB1cHN0cmVhbT0kdXBzdHJlYW1fcmVzcG9uc2VfdGltZSc7Ck5HSU5YCmF3ayAtdiBkaXJlY3Rvcnk9IiRsb2dzIiAtdiBodG1sPSIkcnVudGltZS9odG1sIiAnCiAgICAvYWNjZXNzX2xvZyBvZmY7LyB7bmV4dH0KICAgIHtnc3ViKC9cL29wdFwvdHJhZmZpYy1jb25zb2xlXC9odG1sLywgaHRtbCk7IHByaW50fQogICAgL15zZXJ2ZXIgXHsvIHsKICAgICAgICBwcmludCAiICAgIGFjY2Vzc19sb2cgL2Rldi9zdGRvdXQgdHJhZmZpY19zb3VyY2U7IgogICAgICAgIHByaW50ICIgICAgYWNjZXNzX2xvZyBcIiIgZGlyZWN0b3J5ICIvYWNjZXNzLmxvZ1wiIHRyYWZmaWNfc291cmNlOyIKICAgICAgICBwcmludCAiICAgIGVycm9yX2xvZyAvdmFyL3J1bi90cmFmZmljLWNvbnNvbGUvZXJyb3IucGlwZSB3YXJuOyIKICAgICAgICBwcmludCAiICAgIGxvY2F0aW9uID0gL3J1bnRpbWUtY29uZmlnLmpzIHsiCiAgICAgICAgcHJpbnQgIiAgICAgICAgYWxpYXMgL3Zhci9ydW4vdHJhZmZpYy1jb25zb2xlL3J1bnRpbWUtY29uZmlnLmpzOyIKICAgICAgICBwcmludCAiICAgICAgICBhZGRfaGVhZGVyIENhY2hlLUNvbnRyb2wgXCJuby1zdG9yZVwiIGFsd2F5czsiCiAgICAgICAgcHJpbnQgIiAgICAgICAgYWRkX2hlYWRlciBDb250ZW50LVNlY3VyaXR5LVBvbGljeSAkY29uc29sZV9jc3AgYWx3YXlzOyIKICAgICAgICBwcmludCAiICAgICAgICBhZGRfaGVhZGVyIFgtQ29udGVudC1UeXBlLU9wdGlvbnMgXCJub3NuaWZmXCIgYWx3YXlzOyIKICAgICAgICBwcmludCAiICAgIH0iCiAgICB9CicgL29wdC90cmFmZmljLWNvbnNvbGUvbmdpbnguY29uZiA+PiAvZXRjL25naW54L2NvbmYuZC9kZWZhdWx0LmNvbmYKZXhwb3J0IENPTlNPTEVfUlVOVElNRV9DT05GSUdfUEFUSD0iJHJ1bnRpbWUvcnVudGltZS1jb25maWcuanMiCnJ1bl9zdGVwIGNvbmZpZ3VyZSBzaCAvb3B0L3RyYWZmaWMtY29uc29sZS9jb25maWd1cmUuc2gKcnVuX3N0ZXAgbmdpbngtY2hlY2sgbmdpbnggLXQKKAogICAgd2hpbGUgc2xlZXAgMzA7IGRvCiAgICAgICAgcmVvcGVuPWZhbHNlCiAgICAgICAgZm9yIHRhcmdldCBpbiBhY2Nlc3MgZXJyb3I7IGRvCiAgICAgICAgICAgIGlmIHJvdGF0ZV9maWxlICIkbG9ncy8kdGFyZ2V0LmxvZyI7IHRoZW4gcmVvcGVuPXRydWU7IGZpCiAgICAgICAgZG9uZQogICAgICAgIHJvdGF0ZV9maWxlICIkbG9ncy9zdGFydHVwLmxvZyIgfHwgdHJ1ZQogICAgICAgIGlmIFsgIiRyZW9wZW4iID0gdHJ1ZSBdOyB0aGVuIG5naW54IC1zIHJlb3BlbiA+L2Rldi9udWxsIDI+JjEgfHwgdHJ1ZTsgZmkKICAgIGRvbmUKKSAmCnN0YXJ0dXBfbG9nICdldmVudD1SRUFEWSBsaXN0ZW49ODA4MCcKZXhlYyBuZ2lueCAtZyAnZGFlbW9uIG9mZjsnCg=='


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checks(path):
    return dict((name, checksum) for checksum, name in
                (line.split('  ', 1) for line in path.read_text().splitlines()))


def sealed(values):
    return ''.join(f'{checksum}  {name}\n' for name, checksum in sorted(values.items())).encode()


def replace(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install(root, directories):
    payload = base64.b64decode(PAYLOAD, validate=True)
    if digest(payload) != PAYLOAD_SHA256:
        raise ValueError('Repair payload checksum mismatch')
    outer = root / 'SHA256SUMS'
    outer_checks = checks(outer)
    updates = {}
    for directory in dict.fromkeys(directories):
        if not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError('Source release must be inside the deployment directory')
        entrypoint = directory / 'app/console/entrypoint.sh'
        checksum_file = directory / 'SHA256SUMS'
        if entrypoint.is_symlink() or checksum_file.is_symlink():
            raise ValueError('Source repair refuses symbolic file links')
        before = digest(entrypoint.read_bytes())
        inner = checks(checksum_file)
        if before not in {OLD_SHA256, PAYLOAD_SHA256} or inner.get('app/console/entrypoint.sh') != before:
            raise ValueError('Console entrypoint differs from the supported release; refusing to overwrite')
        for path in (entrypoint, checksum_file):
            name = path.relative_to(root).as_posix()
            if name in outer_checks and outer_checks[name] != digest(path.read_bytes()):
                raise ValueError('Source checksum differs from the outer release manifest')
        if before == PAYLOAD_SHA256:
            continue
        inner['app/console/entrypoint.sh'] = PAYLOAD_SHA256
        updates[entrypoint] = payload
        updates[checksum_file] = sealed(inner)
    if not updates:
        print('Console permission repair is already installed')
        return
    for path, data in updates.items():
        name = path.relative_to(root).as_posix()
        if name in outer_checks:
            outer_checks[name] = digest(data)
    updates[outer] = sealed(outer_checks)
    backup = root / '.console-403-backup-20261019'
    if backup.exists():
        raise ValueError('An incomplete/different repair backup exists; refusing to replace it')
    backup.mkdir(mode=0o700)
    originals = {path: path.read_bytes() for path in updates}
    for path in updates:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    try:
        for path, data in updates.items():
            replace(path, data)
    except BaseException:
        for path, data in originals.items():
            replace(path, data)
        raise
    print('Installed Console permission repair; source checksum manifests updated')


def main():
    sys.dont_write_bytecode = True
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve(strict=True)
    baseline = root / 'application'
    spec = importlib.util.spec_from_file_location('console_source_upgrade', baseline / 'upgrade_source.py')
    upgrade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upgrade)
    deployment = upgrade.Deployment(root)
    with (deployment.directory / 'upgrade.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = Path(deployment.state['current']) if deployment.state.get('current') else None
        directories = [baseline] + ([current] if current else [])
        for directory in directories:
            upgrade.verify_package(directory)
        install(root, directories)
        target = current or baseline
        for directory in directories:
            upgrade.verify_package(directory)
        deployment.run(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate',
                        '--wait', '--wait-timeout', '60', 'console2'], current)
        html = (target / 'app/console/html/index.html').read_text()
        paths = ['/', '/login', '/index.html', '/runtime-config.js']
        paths += re.findall(r'(?:src|href)="(/assets/[A-Za-z0-9_.-]+\.(?:js|css))"', html)
        for path in dict.fromkeys(paths):
            deployment.run(['exec', '-T', 'console2', 'wget', '-q', '-O', '/dev/null',
                            'http://127.0.0.1:8080' + path], current)
        print('PASS: Console HTML/runtime/initial assets are readable; only Console was recreated')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f'Console repair failed: {type(exc).__name__}; no success is claimed. Check Console logs.', file=sys.stderr)
        sys.exit(1)
