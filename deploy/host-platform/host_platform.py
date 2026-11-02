#!/usr/bin/env python3
"""Manage a private native Platform against an existing Docker deployment."""
import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
LOG = logging.getLogger('host-platform')


def captured(command, env=None):
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    if result.returncode:
        # Docker config and application diagnostics can contain credentials.
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in command[:2]) + '; see private logs')
    return result.stdout


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def literal_compose(value):
    if isinstance(value, dict):
        return {k: literal_compose(v) for k, v in value.items()}
    if isinstance(value, list):
        return [literal_compose(v) for v in value]
    return value.replace('$', '$$') if isinstance(value, str) else value


def verify():
    if sys.platform != 'linux' or os.uname().machine not in {'aarch64', 'arm64'}:
        raise ValueError('Only Linux ARM64; macOS continues using its existing MPS entrypoint')
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        path = ROOT / name
        if Path(name).is_absolute() or '..' in Path(name).parts or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('Invalid package checksum entry')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != checksum:
            raise ValueError('Package checksum mismatch: ' + name)
    LOG.info('Package checksums verified')


def translate(value, mounts):
    # Covers plain paths and paths inside JSON arrays without changing arbitrary secrets.
    if isinstance(value, list):
        return [translate(x, mounts) for x in value]
    if isinstance(value, dict):
        return {k: translate(v, mounts) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    if value.startswith(('[', '{')):
        try:
            return json.dumps(translate(json.loads(value), mounts), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    for target, source in sorted(mounts.items(), key=lambda x: -len(x[0])):
        if value == target or value.startswith(target + '/'):
            return source + value[len(target):]
    return value


def inspect_container(container):
    return json.loads(captured(['docker', 'inspect', container]))[0]


def discover(root):
    ids = captured(['docker', 'ps', '-a', '-q', '--filter', 'label=com.docker.compose.service=platform']).split()
    matches = []
    for cid in ids:
        item = inspect_container(cid)
        labels = item['Config']['Labels']
        directory = labels.get('com.docker.compose.project.working_dir', '')
        if directory and Path(directory).resolve() == root:
            matches.append(item)
    if len(matches) != 1:
        raise ValueError('Expected exactly one existing Platform container for deployment-root; keep it until rollback')
    return matches[0]


def env_for(state):
    # Retain native runtime variables set by bin/python3, discard developer/site dotenv loading.
    keep = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE',
            'ASCEND_HOME_PATH', 'ASCEND_OPP_PATH', 'ASCEND_AICPU_PATH', 'ASCEND_TOOLKIT_HOME',
            'ASCEND_RUNTIME_CANN_ROOT', 'HIGHGO_LIBRARY_DIR', 'HOST_RUNTIME_LOADER', 'HOST_RUNTIME_LIBRARY_PATH')
    result = {key: os.environ[key] for key in keep if key in os.environ}
    result.update(state['environment'])
    # Packages installed before the manifest fix filtered ASCEND_* variables.
    # The Platform setting survived and already contains the translated host path.
    if not result.get('ASCEND_MODEL_MANIFEST') and result.get('PIPELINE_ASCEND_MANIFEST'):
        result['ASCEND_MODEL_MANIFEST'] = result['PIPELINE_ASCEND_MANIFEST']
    result.update(PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
    return result


def compose(state, filename, *arguments):
    return ['docker', 'compose', '--project-directory', state['deployment_root'], '-p', state['project'],
            '-f', str(STATE / filename), *arguments]


def install(deployment):
    verify()
    if (STATE / 'site.json').exists():
        raise ValueError('Already installed; retain this state for rollback. Use a new extracted package for a new site')
    root = deployment.resolve(strict=True)
    if not (root / '.env').is_file() or (root / '.env').stat().st_mode & 0o077:
        raise ValueError('Original private deployment .env must exist with mode 600')
    item = discover(root)
    release = json.loads((ROOT / 'HOST_RELEASE.json').read_text())
    if item['Image'] != release['runtime_image']['id']:
        raise ValueError('Existing Platform image differs from packaged dependency/migration baseline')
    labels = item['Config']['Labels']
    project = labels['com.docker.compose.project']
    rawenv = dict(x.split('=', 1) for x in item['Config']['Env'] if '=' in x)
    mounts = {m['Destination']: m['Source'] for m in item['Mounts'] if m['Type'] == 'bind'}
    required = ('/app', '/app/weights', '/app/test_videos', '/app/logs', '/hls', '/pipeline-output',
                '/pipeline-spool', '/survey', '/calibration', '/trajectory-archive')
    if any(name not in mounts or not Path(mounts[name]).is_dir() for name in required):
        raise ValueError('Expected existing intranet.1+ bind mounts and assets; no new data directories will be guessed')
    app_alias = Path('/app')
    if app_alias.exists() or app_alias.is_symlink():
        if not app_alias.is_symlink() or app_alias.resolve() != ROOT / 'app':
            raise ValueError('Host /app is already occupied; refusing to overwrite it (stored video paths need /app)')
    mountmap = {**mounts, '/app': str(ROOT / 'app')}
    asset_links = [('weights', '/app/weights'), ('test_videos', '/app/test_videos'), ('logs', '/app/logs')]
    for name, target in asset_links:
        path = ROOT / 'app' / name
        if path.is_symlink() or any(path.iterdir()):
            raise ValueError('Package asset mountpoint is not empty: ' + name)
    environment = {k: translate(v, mountmap) if k.endswith(('_PATH', '_DIR', '_ROOT', '_ROOTS', '_MANIFEST')) or k in {'PIPELINE_PROJECT_ROOT', 'DETECTION_WEIGHT_PATH'} else v
                   for k, v in rawenv.items() if k not in {'PATH', 'HOME', 'HOSTNAME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONPATH', 'PYTHONHOME'}
                   and (k == 'ASCEND_MODEL_MANIFEST' or not k.startswith(('ASCEND_', 'NNA', 'CANN', 'TBE')))}
    environment.update(DEPLOYMENT_MODE='production', DEBUG='false', DB_AUTO_MIGRATE='false',
                       PIPELINE_PROJECT_ROOT=str(ROOT / 'app'), PIPELINE_PYTHON=str(ROOT / 'bin/python3'),
                       VIDEO_BIND_HOST='127.0.0.1', PIPELINE_VIDEO_BASE='http://127.0.0.1:8100/video',
                       TRAFFIC_LOG_DIR=mounts['/app/logs'], PSYCOPG_IMPL='python',
                       HOST_RESOURCE_DIRECTORIES=json.dumps(sorted({mounts[x] for x in required if not x.startswith('/app')} | {mounts['/app/logs']})),
                       YOLO_CONFIG_DIR=str(STATE / 'ultralytics'), MPLCONFIGDIR=str(STATE / 'matplotlib'))
    # Device choice and ID remain exactly as configured in the existing deployment.
    environment['ASCEND_DEVICE_ID'] = rawenv.get('ASCEND_DEVICE_ID', '0')
    environment['KAFKA_SPOOL_DIR'] = mounts['/pipeline-spool']
    networks = item['NetworkSettings']['Networks']
    candidates = []
    for network_name in networks:
        info = json.loads(captured(['docker', 'network', 'inspect', network_name]))[0]
        if info['Driver'] == 'bridge':
            gateway = next((c['Gateway'] for c in info['IPAM']['Config'] if c.get('Gateway') and ':' not in c['Gateway']), None)
            if gateway:
                candidates.append((network_name, gateway))
    if len(candidates) != 1:
        raise ValueError('Expected one IPv4 Linux bridge network; configure an explicit network before using this diagnostic package')
    network_name, gateway = candidates[0]
    bundled_database = environment.get('DB_HOST') == 'road9'
    if bundled_database:
        db_ids = captured(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + project,
                           '--filter', 'label=com.docker.compose.service=road9']).split()
        if len(db_ids) != 1:
            raise ValueError('Existing road9 container must be running')
        environment['DB_HOST'] = inspect_container(db_ids[0])['NetworkSettings']['Networks'][network_name]['IPAddress']
        if not environment['DB_HOST']:
            raise ValueError('Database has no IPv4 bridge address')
    files = labels['com.docker.compose.project.config_files'].split(',')
    config_env = dict(os.environ)
    current = root / 'app/state.json'
    if current.is_file():
        current_release = json.loads(current.read_text()).get('current')
        if current_release:
            manifest = json.loads((Path(current_release) / 'APP_RELEASE.json').read_text())
            config_env.update(APP_ROOT=str(Path(current_release) / 'app'),
                              APP_PLATFORM_IMAGE=manifest['images']['platform']['reference'],
                              APP_CONSOLE_IMAGE=manifest['images']['console']['reference'])
    command = ['docker', 'compose', '--project-directory', str(root), '--env-file', str(root / '.env'), '-p', project]
    for name in files:
        if not Path(name).is_file():
            raise ValueError('Original Compose file is missing: ' + name)
        command += ['-f', name]
    config = json.loads(captured(command + ['config', '--format', 'json'], config_env))
    # Ensure the rollback snapshot actually describes the currently mounted source.
    saved_app = next(m['source'] for m in config['services']['platform']['volumes'] if m['target'] == '/app')
    if Path(saved_app).resolve() != Path(mounts['/app']).resolve():
        raise ValueError('Resolved Compose /app differs from running container; fix source state before installing')
    console = config['services']['console2']
    nginx_sources = [m for m in console.get('volumes', []) if m['target'] == '/opt/traffic-console/nginx.conf']
    if len(nginx_sources) != 1:
        raise ValueError('Expected existing source-mounted Console configuration')
    nginx = Path(nginx_sources[0]['source']).read_text()
    if 'platform:8000' not in nginx:
        raise ValueError('Console upstream differs from expected platform:8000')
    (STATE / 'nginx.conf').write_text(nginx.replace('platform:8000', 'host.traffic.internal:8000'))
    private_json(STATE / 'docker-original.json', literal_compose(config))
    console['depends_on'] = {}
    console['extra_hosts'] = {'host.traffic.internal': gateway}
    nginx_sources[0]['source'] = str(STATE / 'nginx.conf')
    native_config = {k: v for k, v in config.items() if k != 'services'}
    native_config['services'] = {'console2': console}
    private_json(STATE / 'docker-host.json', literal_compose(native_config))
    state = {'deployment_root': str(root), 'project': project, 'network': network_name, 'bind_address': gateway,
             'database_address': environment.get('DB_HOST'), 'bundled_database': bundled_database,
             'environment': environment, 'platform_container': item['Id']}
    for name, target in asset_links:
        path = ROOT / 'app' / name
        path.rmdir()
        path.symlink_to(mounts[target], target_is_directory=True)
    private_json(STATE / 'site.json', state)
    LOG.info('Installed private configuration; original .env and containers retained; run prepare next')


def state_read():
    return json.loads((STATE / 'site.json').read_text())


def check_database_address(state):
    if state['environment'].get('DB_HOST') != state.get('database_address'):
        raise ValueError('Unexpected database address')
    if state['environment'].get('DB_HOST') and 'road9' in state['environment'].get('DB_HOST', ''):
        raise ValueError('Docker service DNS cannot be used by native Platform')
    # Container IPs are dynamic: refuse a stale address after a database recreation.
    if not state['bundled_database']:
        return
    ids = captured(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + state['project'],
                    '--filter', 'label=com.docker.compose.service=road9']).split()
    if len(ids) != 1:
        raise ValueError('Existing bundled database must remain running')
    if ids:
        address = inspect_container(ids[0])['NetworkSettings']['Networks'][state['network']]['IPAddress']
        if state['environment']['DB_HOST'] != address:
            raise ValueError('Database bridge address changed; create a fresh install/state before continuing')


def logged(state, name, script, *arguments):
    command = [str(ROOT / 'bin/python3'), str(ROOT / 'app/deploy/intranet/run_logged.py'), name,
               str(ROOT / 'bin/python3'), '-u', str(ROOT / 'app/deploy/intranet' / script), *arguments]
    subprocess.run(command, cwd=ROOT / 'app', env=env_for(state), check=True)


def prepare(state):
    check_database_address(state)
    logged(state, 'source-check', 'source_check.py', '--database')
    LOG.info('Native imports and installed schema heads passed; no migrations executed')


def owned_pid():
    path = STATE / 'pid.json'
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    try:
        fields = Path('/proc/' + str(record['pid']) + '/stat').read_text().rsplit(')', 1)[1].split()
        if fields[19] == record['start_ticks'] and fields[0] != 'Z':
            return record['pid']
    except FileNotFoundError:
        pass
    return None


def stop():
    pid = owned_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(60):
            if not owned_pid():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Native shutdown exceeded 30s; inspect private logs before rollback')
    (STATE / 'pid.json').unlink(missing_ok=True)


def wait_ready(state):
    url = 'http://' + state['bind_address'] + ':8000/ready'
    for _ in range(90):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
                if json.load(response).get('status') == 'ready':
                    return
        except Exception:
            pass
        if not owned_pid():
            raise RuntimeError('Native process exited; see DATA_ROOT/logs/containers/platform.log')
        time.sleep(1)
    raise RuntimeError('Native Platform did not become ready')


def run(state):
    if inspect_container(state['platform_container'])['State']['Running']:
        raise ValueError('Docker Platform is still running; stop it before native run')
    if owned_pid():
        raise ValueError('Native Platform is already running')
    with socket.socket() as listener:
        listener.bind((state['bind_address'], 8000))
    if Path('/app').is_symlink():
        if Path('/app').resolve() != ROOT / 'app':
            raise ValueError('Host /app points to another application')
    elif Path('/app').exists():
        raise ValueError('Host /app is occupied')
    else:
        Path('/app').symlink_to(ROOT / 'app', target_is_directory=True)
    ticks = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    private_json(STATE / 'pid.json', {'pid': os.getpid(), 'start_ticks': ticks})
    environment = env_for(state)
    command = [str(ROOT / 'bin/python3'), str(ROOT / 'app/deploy/intranet/run_logged.py'), 'platform',
               str(ROOT / 'bin/python3'), '-m', 'uvicorn', 'app.main:app', '--host', state['bind_address'], '--port', '8000']
    os.chdir(ROOT / 'app/platform')
    os.execve(command[0], command, environment)


def start(state):
    if owned_pid():
        raise ValueError('Native Platform is already running')
    launcher = STATE / 'launcher.log'
    if launcher.exists() and launcher.stat().st_size > 1024 * 1024:
        launcher.replace(STATE / 'launcher.log.1')
    with launcher.open('a') as output:
        subprocess.Popen([str(ROOT / 'host-platform'), 'run'], stdin=subprocess.DEVNULL, stdout=output,
                         stderr=subprocess.STDOUT, start_new_session=True)
    # Allow the launcher to record its PID before readiness polling.
    for _ in range(50):
        if owned_pid():
            break
        time.sleep(0.1)
    wait_ready(state)


def switch(state):
    prepare(state)
    subprocess.run(compose(state, 'docker-original.json', 'stop', '--timeout', '30', 'platform'), check=True)
    try:
        logged(state, 'preflight', 'runtime_check.py')
        start(state)
        subprocess.run(compose(state, 'docker-host.json', 'up', '-d', '--no-deps', '--pull', 'never', 'console2'), check=True)
        cid = captured(compose(state, 'docker-host.json', 'ps', '-q', 'console2')).strip()
        # Exercise the actual container-to-host API path, not only static HTML health.
        for attempt in range(30):
            result = subprocess.run(['docker', 'exec', cid, 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8080/ready'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Console cannot reach native Platform; verify host firewall and bridge route')
        LOG.info('Native Platform ready; Console remains in Docker; database and Kafka retained')
    except BaseException:
        LOG.error('Native switch failed; restoring Docker applications')
        stop()
        subprocess.run(compose(state, 'docker-original.json', 'up', '-d', '--no-deps', '--pull', 'never', 'platform', 'console2'), check=True)
        raise


def main():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'prepare', 'check', 'switch-host', 'run', 'start', 'stop', 'status', 'rollback', 'init-db'))
    parser.add_argument('--deployment-root', type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s pid=%(process)d %(name)s %(message)s')
    from utils_local.runtime_logging import RuntimeFormatter
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RuntimeFormatter())
    with (STATE / ('run.lock' if args.command == 'run' else 'control.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Keep the run lock across exec and through the supervisor lifetime.
        if args.command == 'run':
            os.set_inheritable(lock.fileno(), True)
        if args.command == 'install':
            if args.deployment_root is None:
                raise ValueError('--deployment-root is required for install')
            install(args.deployment_root)
            return
        state = state_read()
        if args.command == 'prepare':
            prepare(state)
        elif args.command == 'check':
            check_database_address(state)
            logged(state, 'preflight', 'runtime_check.py')
        elif args.command == 'switch-host':
            switch(state)
        elif args.command == 'run':
            run(state)
        elif args.command == 'start':
            prepare(state)
            logged(state, 'preflight', 'runtime_check.py')
            start(state)
        elif args.command == 'stop':
            stop()
        elif args.command == 'status':
            LOG.info('Native PID=%s bind=%s:8000', owned_pid(), state['bind_address'])
        elif args.command == 'rollback':
            stop()
            subprocess.run(compose(state, 'docker-original.json', 'up', '-d', '--no-deps', '--pull', 'never', 'platform', 'console2'), check=True)
            if Path('/app').is_symlink() and Path('/app').resolve() == ROOT / 'app':
                Path('/app').unlink()
            LOG.info('Docker Platform/Console restored; data and original configuration retained')
        elif args.command == 'init-db':
            if owned_pid() or inspect_container(state['platform_container'])['State']['Running']:
                raise ValueError('Stop both native and Docker Platform before explicit init-db')
            logged(state, 'init-db', 'init_db.py')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not include library errors containing connection URLs or credentials.
        from utils_local.runtime_logging import redact_log_text
        LOG.exception('HOST_OPERATION_FAILED type=%s message=%s; inspect private runtime logs and runbook',
                  type(exc).__name__, redact_log_text(str(exc)))
        sys.exit(1)
