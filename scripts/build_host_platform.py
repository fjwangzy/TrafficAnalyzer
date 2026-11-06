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
from build_intranet_release import (ROOT, copy_app_sources, image_source_files,
                                    inspect_image, seal_archive)

BASELINE = ('platform/pyproject.toml', 'platform/pipeline-requirements.txt', 'platform/pipeline-constraints.txt',
            'platform/alembic.ini', 'platform/alembic_replay_v2.ini', 'platform/alembic', 'platform/alembic_replay_v2')


def copy_verified_runtime(package, destination, image, baseline):
    """Reuse immutable bytes with independent COW files, never hardlinks."""
    package = package.resolve()
    release = json.loads((package / 'HOST_RELEASE.json').read_text())
    expected_baseline = {name: hashlib.sha256(value).hexdigest() for name, value in baseline.items()}
    if release['runtime_image']['id'] != image['id'] or release['runtime_baseline'] != expected_baseline:
        raise ValueError('Reused runtime image/dependency/migration baseline differs')
    checksums = {}
    runtime_root = package / 'runtime'
    for path in runtime_root.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(runtime_root):
            raise ValueError('Runtime symlink escapes package')
    for line in (package / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        if name.startswith('runtime/'):
            path = package / name
            if not path.resolve().is_relative_to(runtime_root):
                raise ValueError('Runtime path escapes package')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
                    raise ValueError('Reused runtime checksum mismatch: ' + name)
            checksums[name] = checksum
    actual = {p.relative_to(package).as_posix() for p in (package / 'runtime').rglob('*') if p.is_file()}
    if not checksums or set(checksums) != actual:
        raise ValueError('Reused runtime file manifest differs')
    if sys.platform == 'darwin':
        subprocess.run(['cp', '-cR', str(package / 'runtime'), str(destination)], check=True)
    else:
        subprocess.run(['cp', '--reflink=auto', '-a', str(package / 'runtime'), str(destination)], check=True)
    return {'package': package.name, 'runtime_files_verified': len(checksums), 'copy': 'independent files; COW when supported'}


def frontend_sources():
    files = [p for folder in ('src', 'public') for p in (ROOT / 'console2' / folder).rglob('*')
             if p.is_file() and p.name != '.DS_Store']
    files += [p for pattern in ('package*.json', 'vite.config.*', 'index.html') for p in (ROOT / 'console2').glob(pattern)]
    return {p.relative_to(ROOT / 'console2').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', required=True)
    p.add_argument('--readme', type=Path, help='Native release operation guide')
    p.add_argument('--validation-report', type=Path, help='Native release validation report')
    p.add_argument('--stage-only', action='store_true', help='Prepare runtime for validation before sealing')
    p.add_argument('--runtime-from', type=Path, help='Reuse checksum-verified identical runtime from a full package, using independent COW files')
    p.add_argument('--native-release', action='store_true', help='Build the one-command full native application release')
    p.add_argument('--image', default='traffic-analyzer-platform:2026.10.19-intranet.1-arm64')
    p.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = p.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.version):
        raise ValueError('Invalid version')
    target = args.output / (('traffic-analyzer-native-' if args.native_release else 'traffic-analyzer-host-platform-') + args.version)
    archive = target.with_suffix(target.suffix + '.tar.gz')
    if target.exists() or archive.exists():
        raise FileExistsError(target)
    image = inspect_image(args.image)
    runtime_image = image['id']
    baseline = image_source_files(runtime_image, BASELINE)
    actual = {p.relative_to(ROOT).as_posix() for folder in ('platform/alembic', 'platform/alembic_replay_v2')
              for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    expected = {name for name in baseline if name.startswith(('platform/alembic/', 'platform/alembic_replay_v2/'))}
    if actual != expected or any((ROOT / name).read_bytes() != value for name, value in baseline.items()):
        raise ValueError('Runtime dependency/migration baseline changed: build a new baseline')
    target.mkdir(parents=True)
    app = target / 'app'
    app.mkdir()
    copy_app_sources(app)
    for name, data in image_source_files(runtime_image, ('python-dependencies.txt', 'os-dependencies.txt')).items():
        (app / name).write_bytes(data)
    (target / 'bin').mkdir()
    (target / 'bootstrap').mkdir()
    shutil.copy2(ROOT / 'deploy/host-platform/sitecustomize.py', target / 'bootstrap/sitecustomize.py')
    for source, dest in [('python3', 'bin/python3'), ('media-tool', 'bin/ffmpeg'),
                         ('media-tool', 'bin/ffprobe'), ('host-platform', 'host-platform'),
                         ('host_platform.py', 'host_platform.py')]:
        shutil.copy2(ROOT / 'deploy/host-platform' / source, target / dest)
        (target / dest).chmod(0o755)
    if args.native_release:
        frontend = frontend_sources()
        subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'console2', check=True)
        if frontend_sources() != frontend:
            raise ValueError('Console inputs changed during build; rebuild a consistent snapshot')
        (target / 'CONSOLE_RELEASE.json').write_text(json.dumps({'version': args.version, 'source_sha256': frontend}, indent=2) + '\n')
        console = target / 'console'
        shutil.copytree(ROOT / 'console2/dist', console / 'html')
        shutil.copy2(ROOT / 'console2/public/runtime-config.template.js', console / 'html/runtime-config.template.js')
        shutil.copy2(ROOT / 'console2/nginx.conf', console / 'nginx.conf')
        shutil.copy2(ROOT / 'console2/docker-entrypoint.d/40-amap-runtime-config.sh', console / 'configure.sh')
        shutil.copy2(ROOT / 'deploy/intranet/console-runtime/entrypoint.sh', console / 'entrypoint.sh')
        (target / 'state').mkdir(mode=0o700)
        for name in ('traffic', 'native_platform.py', 'runtime_smoke.py'):
            shutil.copy2(ROOT / 'deploy/native-platform' / name, target / name)
            (target / name).chmod(0o755)
        (target / 'host-platform').unlink()
        shutil.copy2(args.readme or ROOT / 'docs/NATIVE_DEPLOYMENT.md', target / 'README.md')
        shutil.copy2(ROOT / 'docs/FOUR_PROCESS_SAMPLING_20261103.md', target / 'FOUR_PROCESS_SAMPLING.md')
        wrapper = target / 'bin/python3'
        wrapper.write_text(wrapper.read_text().replace('export PATH=', 'export TRAFFIC_NATIVE_PYTHON="$root/bin/python3"\nexport OMP_PROC_BIND=false\nexport PIPELINE_EGRESS_ENABLED="${PIPELINE_EGRESS_ENABLED:-true}"\nexport HISTORY_SAMPLING_ENABLED="${HISTORY_SAMPLING_ENABLED:-true}"\nexport PATH='))
        with (target / 'bootstrap/sitecustomize.py').open('a') as stream:
            stream.write('\n# All spawned interpreters re-enter the private loader wrapper.\n'
                         'if os.environ.get("TRAFFIC_NATIVE_PYTHON"):\n'
                         '    import sys\n'
                         '    sys.executable = os.environ["TRAFFIC_NATIVE_PYTHON"]\n')
    else:
        shutil.copy2(ROOT / 'docs/HOST_PLATFORM_RUNBOOK_20261020.md', target / 'README.md')
    # A private userspace loader keeps Ubuntu libraries off the host's global linker path.
    # Dereference only the system library tree (alternatives links can leave that tree).
    runtime = target / 'runtime'
    reused = None
    if args.runtime_from:
        print('BEGIN verify and copy existing immutable runtime', flush=True)
        reused = copy_verified_runtime(args.runtime_from, runtime, image, baseline)
    else:
        export_runtime(runtime_image, runtime)
    release = {'kind': 'native-platform-full' if args.native_release else 'native-host-platform', 'version': args.version, 'platform': 'linux/arm64',
               'runtime_image': image, 'runtime_baseline': {n: hashlib.sha256(v).hexdigest() for n, v in baseline.items()},
               'migration_policy': 'validate installed heads; explicit init-db only; no automatic migration',
               'site_acceptance': 'not_evaluated', 'runtime': 'private Python 3.11.15 + CANN 9.0.0 + native ELF loader; no container/chroot'}
    if reused:
        release['runtime_reuse'] = reused
    if args.native_release:
        release['sampling_versions'] = ['event-faithful/v1', 'event-faithful/v2']
        release['transport_versions'] = ['uav-fixed/v2']
        release['pipeline_workers'] = 4
        release['console_resources'] = 'console/html; automatically mounted in retained Console container'
    (target / 'HOST_RELEASE.json').write_text(json.dumps(release, indent=2) + '\n')
    if args.native_release:
        shutil.copy2(args.validation_report or ROOT / 'docs/NATIVE_DEPLOYMENT_VALIDATION.md', target / 'VALIDATION.md')
    if args.stage_only:
        print(target, flush=True)
        return
    print('BEGIN SHA256 and archive', flush=True)
    seal_archive(target, archive)
    print(archive, flush=True)


def export_runtime(runtime_image, runtime):
    cid = subprocess.check_output(['docker', 'create', '--entrypoint', '/bin/sleep', runtime_image, 'infinity'], text=True).strip()
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


if __name__ == '__main__':
    main()
