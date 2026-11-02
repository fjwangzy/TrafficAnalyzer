#!/usr/bin/env python3
"""Export the immutable ARM64 native runtime and current application for onsite A/B diagnosis."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_intranet_release import (ROOT, copy_app_sources, digest, image_source_files,
                                    inspect_image, seal_archive)

BASELINE = ('platform/pyproject.toml', 'platform/pipeline-requirements.txt', 'platform/pipeline-constraints.txt',
            'platform/alembic.ini', 'platform/alembic_replay_v2.ini', 'platform/alembic', 'platform/alembic_replay_v2')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', required=True)
    p.add_argument('--image', default='traffic-analyzer-platform:2026.10.19-intranet.1-arm64')
    p.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = p.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.version):
        raise ValueError('Invalid version')
    target = args.output / ('traffic-analyzer-host-platform-' + args.version)
    archive = target.with_suffix(target.suffix + '.tar.gz')
    if target.exists() or archive.exists():
        raise FileExistsError(target)
    image = inspect_image(args.image)
    baseline = image_source_files(args.image, BASELINE)
    actual = {p.relative_to(ROOT).as_posix() for folder in ('platform/alembic', 'platform/alembic_replay_v2')
              for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    expected = {name for name in baseline if name.startswith(('platform/alembic/', 'platform/alembic_replay_v2/'))}
    if actual != expected or any((ROOT / name).read_bytes() != value for name, value in baseline.items()):
        raise ValueError('Runtime dependency/migration baseline changed: build a new baseline')
    target.mkdir(parents=True)
    app = target / 'app'
    app.mkdir()
    copy_app_sources(app)
    for name, data in image_source_files(args.image, ('python-dependencies.txt', 'os-dependencies.txt')).items():
        (app / name).write_bytes(data)
    (target / 'bin').mkdir()
    (target / 'bootstrap').mkdir()
    shutil.copy2(ROOT / 'deploy/host-platform/sitecustomize.py', target / 'bootstrap/sitecustomize.py')
    for source, dest in [('python3', 'bin/python3'), ('media-tool', 'bin/ffmpeg'),
                         ('media-tool', 'bin/ffprobe'), ('host-platform', 'host-platform'),
                         ('host_platform.py', 'host_platform.py')]:
        shutil.copy2(ROOT / 'deploy/host-platform' / source, target / dest)
        (target / dest).chmod(0o755)
    shutil.copy2(ROOT / 'docs/HOST_PLATFORM_RUNBOOK_20261020.md', target / 'README.md')
    # A private userspace loader keeps Ubuntu libraries off the host's global linker path.
    # Dereference only the system library tree (alternatives links can leave that tree).
    cid = subprocess.check_output(['docker', 'create', '--entrypoint', '/bin/sleep', args.image, 'infinity'], text=True).strip()
    runtime = target / 'runtime'
    runtime.mkdir()
    try:
        subprocess.run(['docker', 'start', cid], check=True, stdout=subprocess.DEVNULL)
        groups = [(False, ['usr/local/python3.11.15', 'usr/local/Ascend']),
                  (True, ['usr/lib/aarch64-linux-gnu', 'opt/highgo/lib', 'usr/bin/ffmpeg', 'usr/bin/ffprobe'])]
        for dereference, names in groups:
            print('BEGIN runtime export: ' + ', '.join(names), flush=True)
            process = subprocess.Popen(['docker', 'exec', cid, 'tar', '-C', '/', '-chf' if dereference else '-cf', '-', *names], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=process.stdout, mode='r|') as stream:
                for member in stream:
                    # Trusted immutable local image, but disallow escaping file destinations.
                    name = Path(member.name)
                    if name.is_absolute() or '..' in name.parts:
                        raise ValueError('Unsafe runtime member')
                    if '__pycache__' in name.parts or name.suffix == '.pyc':
                        continue
                    stream.extract(member, runtime, set_attrs=False, filter='fully_trusted')
                    destination = runtime / member.name
                    if not destination.is_symlink():
                        destination.chmod((member.mode | 0o700) if member.isdir() else (member.mode | 0o600))
            if process.wait():
                raise RuntimeError('Runtime export failed')
        for path in runtime.rglob('*'):
            if path.is_symlink():
                link = os.readlink(path)
                if link.startswith('/'):
                    path.unlink()
                    path.symlink_to(os.path.relpath(runtime / link.lstrip('/'), path.parent))
                # No symlink may reach host /usr, /opt or /etc.
                if not path.resolve().is_relative_to(runtime.resolve()):
                    raise ValueError(f'Runtime symlink escapes private directory: {path}')
    finally:
        subprocess.run(['docker', 'rm', '-f', cid], check=True, stdout=subprocess.DEVNULL)
    release = {'kind': 'native-host-platform', 'version': args.version, 'platform': 'linux/arm64',
               'runtime_image': image, 'runtime_baseline': {n: hashlib.sha256(v).hexdigest() for n, v in baseline.items()},
               'migration_policy': 'validate installed heads; explicit init-db only; no automatic migration',
               'site_acceptance': 'not_evaluated', 'runtime': 'private Python 3.11.15 + CANN 9.0.0 + native ELF loader; no container/chroot'}
    (target / 'HOST_RELEASE.json').write_text(json.dumps(release, indent=2) + '\n')
    print('BEGIN SHA256 and archive', flush=True)
    seal_archive(target, archive)
    print(archive, flush=True)


if __name__ == '__main__':
    main()
