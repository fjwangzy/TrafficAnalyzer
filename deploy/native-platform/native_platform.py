#!/usr/bin/env python3
"""Offline native application lifecycle; Docker is used only for retained services."""
import argparse
import ctypes
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

import host_platform as common

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
LOG = logging.getLogger('traffic-native')
common.ROOT = ROOT
common.STATE = STATE
ASSETS = ('/app/weights', '/app/test_videos', '/app/logs', '/hls', '/pipeline-output',
          '/pipeline-spool', '/survey', '/calibration', '/trajectory-archive')
PIPELINE_LOG_TAIL_BYTES = 256 * 1024
THREAD_VARS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')


def save(name, value):
    # Commit private state atomically so an interrupted operation remains recoverable.
    temporary = STATE / (name + '.tmp')
    common.private_json(temporary, value)
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    temporary.replace(STATE / name)


def load():
    return json.loads((STATE / 'site.json').read_text())


def capture(command, env=None):
    return common.captured(command, env)


def inspect(cid):
    return json.loads(capture(['docker', 'inspect', cid]))[0]


def service(state, name, running=False):
    ids = capture(['docker', 'ps', *([] if running else ['-a']), '-q', '--filter',
                   'label=com.docker.compose.project=' + state['project'], '--filter',
                   'label=com.docker.compose.service=' + name]).split()
    if len(ids) != 1:
        raise ValueError('SERVICE_DISCOVERY: expected exactly one ' + name + ' container')
    return inspect(ids[0])


def compose(state, filename, *args):
    return ['docker', 'compose', '--project-directory', state['deployment_root'], '-p',
            state['project'], '-f', str(STATE / filename), *args]


def execute(command, **kwargs):
    # Never print resolved Compose configuration or its environment on failures.
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        from utils_local.runtime_logging import redact_log_text
        error = result.stderr.decode(errors='replace') if isinstance(result.stderr, bytes) else result.stderr
        LOG.error('COMMAND_FAILED %s', redact_log_text((error or '')[-4000:]))
        raise RuntimeError('COMMAND_FAILED: ' + ' '.join(str(x) for x in command[:2]))
    return result


def config_for(item, root):
    labels = item['Config']['Labels']
    command = ['docker', 'compose', '--project-directory', str(root), '--env-file', str(root / '.env'),
               '-p', labels['com.docker.compose.project']]
    environment = dict(os.environ)
    current = root / 'app/state.json'
    if current.is_file():
        release = json.loads(current.read_text()).get('current')
        if release:
            manifest = json.loads((Path(release) / 'APP_RELEASE.json').read_text())
            environment.update(APP_ROOT=str(Path(release) / 'app'),
                               APP_PLATFORM_IMAGE=manifest['images']['platform']['reference'],
                               APP_CONSOLE_IMAGE=manifest['images']['console']['reference'])
    for name in labels['com.docker.compose.project.config_files'].split(','):
        if not Path(name).is_file():
            raise ValueError('COMPOSE_SOURCE_MISSING: ' + name)
        command += ['-f', name]
    return json.loads(capture(command + ['config', '--format', 'json'], environment))


def container_text(cid, path):
    result = subprocess.run(['docker', 'cp', cid + ':' + path, '-'], capture_output=True)
    if result.returncode:
        raise ValueError('CONSOLE_CONFIG_MISSING: ' + path)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive:
            if member.isfile():
                return archive.extractfile(member).read().decode()
    raise ValueError('CONSOLE_CONFIG_EMPTY')


def previous_alias(deployment):
    alias = Path('/app')
    if not alias.exists() and not alias.is_symlink():
        return None
    if alias.is_symlink() and alias.resolve() == ROOT / 'app':
        return None
    if alias.is_symlink():
        old = alias.resolve().parent
        manifest = old / 'HOST_RELEASE.json'
        site = old / 'state/site.json'
        if alias.resolve() == old / 'app' and manifest.is_file() and site.is_file():
            release = json.loads(manifest.read_text())
            config = json.loads(site.read_text())
            if (release.get('kind') in {'native-host-platform', 'native-platform-full'}
                    and Path(config['deployment_root']).resolve() == deployment):
                return str(old)
    raise ValueError('APP_PATH_OCCUPIED: /app does not belong to this deployment')




def check_owned_writable_path(path, *, owner_required=False):
    """Check access before private logging opens/chmods a file; never change ownership."""
    path = Path(path)
    if not path.exists():
        if path.is_symlink():
            raise PermissionError('RUNTIME_PERMISSION: broken path ' + str(path))
        return
    info = path.stat()
    uid = os.geteuid()
    access = os.W_OK | (os.X_OK if path.is_dir() else 0)
    if ((owner_required and uid != 0 and info.st_uid != uid)
            or not os.access(path, access, effective_ids=True)):
        raise PermissionError(
            f'RUNTIME_PERMISSION: uid={uid} cannot manage {path} (owner_uid={info.st_uid}); '
            'in this package directory use sudo ./traffic start (first start: keep --deployment-root); '
            'use the same account for all lifecycle commands; do not recursively chown the database/assets')


def check_runtime_permissions(state):
    check_owned_writable_path(STATE, owner_required=True)
    env = state['environment']
    log_root = Path(env['TRAFFIC_LOG_DIR'])
    roots = json.loads(env.get('HOST_RESOURCE_DIRECTORIES', '[]'))
    for path in {str(log_root), *roots}:
        check_owned_writable_path(path)
    # These existing files/directories are explicitly chmodded by private logging.
    # Do not scan or change the retained Console's nginx logs or database tree.
    for name in ('containers', 'pipelines', 'source-check'):
        directory = log_root / name
        check_owned_writable_path(directory, owner_required=(name == 'pipelines'))
        if directory.is_dir():
            for path in directory.rglob('*'):
                if path.is_dir() or path.is_file():
                    check_owned_writable_path(path, owner_required=True)
    for key in ('CALIBRATION_DB_PATH', 'LANE_ANNOTATION_DB_PATH'):
        if env.get(key):
            check_owned_writable_path(env[key])


def verify_package():
    LOG.info('PACKAGE_VERIFY_BEGIN checksums=full')
    done = threading.Event()
    begun = time.monotonic()
    def progress():
        if done.wait(5):
            return
        while not done.is_set():
            LOG.info('PACKAGE_VERIFY_WAIT elapsed_sec=%.1f', time.monotonic() - begun)
            done.wait(30)
    reporter = threading.Thread(target=progress, daemon=True)
    reporter.start()
    try:
        common.verify()
    finally:
        done.set()
        reporter.join(timeout=1)


def install(deployment):
    root = deployment.resolve(strict=True)
    if not (root / '.env').is_file() or (root / '.env').stat().st_mode & 0o077:
        raise ValueError('PRIVATE_ENV: existing deployment .env must have mode 600')
    platform = common.discover(root)
    project = platform['Config']['Labels']['com.docker.compose.project']
    state = {'deployment_root': str(root), 'project': project, 'phase': 'prepared'}
    console_item = service(state, 'console2')
    original = config_for(platform, root)
    actual_console = config_for(console_item, root)['services']['console2']
    state['previous_console_running'] = console_item.get('State', {}).get('Running', True)
    # Store exact effective Console settings, including a previous native upstream.
    original['services']['console2'] = actual_console
    volumes = {m['Destination']: m['Source'] for m in platform['Mounts'] if m['Type'] == 'bind'}
    for target in ASSETS:
        if target not in volumes or not Path(volumes[target]).is_dir():
            raise ValueError('RESOURCE_DIRECTORY: missing existing bind ' + target)
    mapping = {**volumes, '/app': str(ROOT / 'app')}
    raw = dict(x.split('=', 1) for x in platform['Config']['Env'] if '=' in x)
    # Container runtime/linker paths must never leak into the native interpreter.
    environment = {k: common.translate(v, mapping) if k.endswith(('_PATH', '_DIR', '_ROOT', '_ROOTS', '_MANIFEST')) else v
                   for k, v in raw.items() if k not in {'PATH', 'HOME', 'HOSTNAME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONPATH', 'PYTHONHOME'}
                   and (k == 'ASCEND_MODEL_MANIFEST' or not k.startswith(('ASCEND_', 'NNA', 'CANN', 'TBE')))}
    manifest = environment.get('PIPELINE_ASCEND_MANIFEST') or environment.get('ASCEND_MODEL_MANIFEST')
    if not manifest or (environment.get('ASCEND_MODEL_MANIFEST') and environment.get('PIPELINE_ASCEND_MANIFEST')
                        and environment['ASCEND_MODEL_MANIFEST'] != environment['PIPELINE_ASCEND_MANIFEST']):
        raise ValueError('MODEL_PATH_CONFIG: missing or inconsistent model manifests')
    environment.update(ASCEND_MODEL_MANIFEST=manifest, PIPELINE_ASCEND_MANIFEST=manifest,
                       ASCEND_DEVICE_ID=raw.get('ASCEND_DEVICE_ID', '0'), PIPELINE_DEVICE='ascend', DEPLOYMENT_MODE='production',
                       DEBUG='false', DB_AUTO_MIGRATE='false', PIPELINE_PROJECT_ROOT=str(ROOT / 'app'),
                       PIPELINE_PYTHON=str(ROOT / 'bin/python3'), VIDEO_BIND_HOST='127.0.0.1',
                       PIPELINE_VIDEO_BASE='http://127.0.0.1:8100/video', PSYCOPG_IMPL='python',
                       TRAFFIC_LOG_DIR=volumes['/app/logs'], KAFKA_SPOOL_DIR=volumes['/pipeline-spool'],
                       HOST_RESOURCE_DIRECTORIES=json.dumps([volumes[k] for k in ASSETS if k not in {'/app/weights', '/app/test_videos'}]),
                       YOLO_CONFIG_DIR=str(STATE / 'ultralytics'), MPLCONFIGDIR=str(STATE / 'matplotlib'))
    environment.update({name: '1' for name in THREAD_VARS})
    environment.update(PIPELINE_EGRESS_ENABLED='true', HISTORY_SAMPLING_ENABLED='true')
    environment['OMP_PROC_BIND'] = 'false'
    candidates = []
    for network in set(platform['NetworkSettings']['Networks']) & set(console_item['NetworkSettings']['Networks']):
        info = json.loads(capture(['docker', 'network', 'inspect', network]))[0]
        if info['Driver'] == 'bridge':
            for address in info['IPAM']['Config']:
                gateway = address.get('Gateway', '')
                if gateway and ':' not in gateway:
                    candidates.append((network, gateway))
    if len(candidates) != 1:
        raise ValueError('BRIDGE_NETWORK: expected one shared IPv4 bridge')
    network, gateway = candidates[0]
    state.update(environment=environment, mounts=volumes, network=network, bind_address=gateway,
                 database_service='road9' if raw.get('DB_HOST') == 'road9' else None,
                 kafka_bootstrap=raw.get('KAFKA_BOOTSTRAP', ''), previous_native=previous_alias(root))
    check_runtime_permissions(state)
    # Support both source-mounted Console and images with the configuration built in.
    console = json.loads(json.dumps(actual_console))
    nginx_target = '/opt/traffic-console/nginx.conf'
    bundled_console = (ROOT / 'console/html/index.html').is_file()
    if bundled_console:
        nginx = (ROOT / 'console/nginx.conf').read_text()
    else:
        source_mounts = [m for m in console.get('volumes', []) if m.get('target') == nginx_target]
        if source_mounts:
            nginx = Path(source_mounts[0]['source']).read_text()
        else:
            try:
                nginx = container_text(console_item['Id'], nginx_target)
            except ValueError:
                nginx_target = '/etc/nginx/conf.d/default.conf'
                nginx = container_text(console_item['Id'], nginx_target)
    import re
    nginx, changed = re.subn(r'(?<=http://)(?:platform|host\.traffic\.internal):8000\b',
                            'host.traffic.internal:8000', nginx)
    if not changed:
        raise ValueError('CONSOLE_UPSTREAM: unrecognised existing Platform upstream')
    (STATE / 'nginx.conf').write_text(nginx)
    (STATE / 'nginx.conf').chmod(0o644)  # Nginx in the retained container must read this bind.
    console['depends_on'] = {}
    hosts = console.get('extra_hosts', {})
    if isinstance(hosts, list):
        hosts = dict(x.replace('=', ':', 1).split(':', 1) for x in hosts)
    console['extra_hosts'] = {**hosts, 'host.traffic.internal': gateway}
    console['volumes'] = [m for m in console.get('volumes', []) if m.get('target') != nginx_target]
    if bundled_console:
        console['volumes'] = [m for m in console['volumes']
                              if not (m.get('target', '') == '/opt/traffic-console'
                                      or m.get('target', '').startswith('/opt/traffic-console/'))
                              and m.get('target') != '/etc/nginx/conf.d/default.conf']
        console['volumes'].append({'type': 'bind', 'source': str(ROOT / 'console'),
                                   'target': '/opt/traffic-console', 'read_only': True})
        console['entrypoint'] = ['/bin/sh', '/opt/traffic-console/entrypoint.sh']
        console['command'] = []
    console['volumes'].append({'type': 'bind', 'source': str(STATE / 'nginx.conf'), 'target': nginx_target, 'read_only': True})
    native = {k: v for k, v in original.items() if k != 'services'}
    native['services'] = {'console2': console}
    save('docker-original.json', common.literal_compose(original))
    save('docker-host.json', common.literal_compose(native))
    for name in ('weights', 'test_videos', 'logs'):
        path = ROOT / 'app' / name
        source = Path(volumes['/app/' + name])
        if path.is_symlink():
            if path.resolve() != source.resolve():
                raise ValueError('ASSET_LINK_CONFLICT: ' + name)
        else:
            if path.exists():
                path.rmdir()  # Only empty packaged mountpoints may be replaced.
            path.symlink_to(source, target_is_directory=True)
    refresh(state)
    save('site.json', state)
    LOG.info('SITE_IMPORTED resources=existing credentials=private no_migration=true')
    return state


def refresh(state):
    platform = service(state, 'platform')
    console = service(state, 'console2')
    network = state['network']
    info = json.loads(capture(['docker', 'network', 'inspect', network]))[0]
    gateways = [x.get('Gateway') for x in info['IPAM']['Config']]
    if state['bind_address'] not in gateways or network not in console['NetworkSettings']['Networks']:
        raise ValueError('BRIDGE_CHANGED: original Console bridge is unavailable')
    if state['database_service']:
        database = service(state, state['database_service'], running=True)
        address = database['NetworkSettings']['Networks'].get(network, {}).get('IPAddress')
        if not address:
            raise ValueError('DATABASE_ADDRESS: no address on retained bridge')
        state['environment']['DB_HOST'] = address
    brokers = []
    for endpoint in state['kafka_bootstrap'].split(','):
        host, separator, port = endpoint.strip().rpartition(':')
        if host == 'kafka' and separator:
            kafka = service(state, 'kafka', running=True)
            address = kafka['NetworkSettings']['Networks'].get(network, {}).get('IPAddress')
            if not address:
                raise ValueError('KAFKA_ADDRESS: no address on retained bridge')
            endpoint = address + ':' + port
        if endpoint:
            brokers.append(endpoint)
    state['environment']['KAFKA_BOOTSTRAP'] = ','.join(brokers)
    state['platform_running'] = platform['State']['Running']


def environment(state):
    result = common.env_for(state)
    # The shipped ARM64 PyTorch/OpenMP fork handler otherwise narrows workers
    # to CPU0. Disable runtime binding, retaining OS/cgroup/taskset restrictions.
    result['OMP_PROC_BIND'] = 'false'
    result.setdefault('PIPELINE_EGRESS_ENABLED','true')
    result.setdefault('HISTORY_SAMPLING_ENABLED','true')
    result['TRAFFIC_NATIVE_OWNER'] = str(ROOT)
    result['TRAFFIC_NATIVE_PYTHON'] = str(ROOT / 'bin/python3')
    return result


def check_baseline():
    import hashlib
    manifest = json.loads((ROOT / 'HOST_RELEASE.json').read_text())
    for name, checksum in manifest['runtime_baseline'].items():
        if hashlib.sha256((ROOT / 'app' / name).read_bytes()).hexdigest() != checksum:
            raise ValueError('DEPENDENCY_BASELINE: ' + name)


def logged(state, name, script, *args):
    LOG.info('CHECK_BEGIN stage=%s log=%s/containers/%s.log', name, state['environment']['TRAFFIC_LOG_DIR'], name)
    command = [str(ROOT / 'bin/python3'), str(ROOT / 'app/deploy/intranet/run_logged.py'), name,
               str(ROOT / 'bin/python3'), str(ROOT / 'app/deploy/intranet' / script), *args]
    process = subprocess.Popen(command, env=environment(state), cwd=ROOT / 'app')
    begun = time.monotonic()
    wait_at = begun + 5
    while process.poll() is None:
        if time.monotonic() >= wait_at:
            LOG.info('CHECK_WAIT stage=%s elapsed_sec=%.1f', name, time.monotonic() - begun)
            wait_at = time.monotonic() + 30
        time.sleep(0.2)
    if process.returncode:
        raise RuntimeError('CHECK_FAILED: ' + name + '; inspect its log for the failed item')
    LOG.info('CHECK_END stage=%s', name)


def prepare(state):
    check_runtime_permissions(state)
    check_baseline()
    refresh(state)
    save('site.json', state)
    logged(state, 'source-check', 'source_check.py', '--database')


def process_record(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'start_ticks': fields[19], 'ppid': int(fields[1]), 'status': fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def alive(record):
    current = process_record(record['pid'])
    return current and current['start_ticks'] == record['start_ticks'] and current['status'] != 'Z'


def owned_pid():
    path = STATE / 'pid.json'
    if path.exists():
        record = json.loads(path.read_text())
        if alive(record):
            return record['pid']
    return None


def owned_children():
    records = []
    marker = ('TRAFFIC_NATIVE_OWNER=' + str(ROOT)).encode()
    for path in Path('/proc').glob('[0-9]*/environ'):
        try:
            if marker in path.read_bytes().split(b'\0'):
                record = process_record(int(path.parent.name))
                if record and record['pid'] != os.getpid() and record['status'] != 'Z':
                    records.append(record)
        except OSError:
            continue
    return records


def terminate(records, signum):
    for record in records:
        if alive(record):
            try:
                os.kill(record['pid'], signum)
            except ProcessLookupError:
                pass


def cleanup_children():
    # Native children use separate sessions; killing only Platform's process group leaks workers.
    terminate(owned_children(), signal.SIGTERM)
    deadline = time.monotonic() + 15
    while owned_children() and time.monotonic() < deadline:
        time.sleep(0.1)
    terminate(owned_children(), signal.SIGKILL)
    deadline = time.monotonic() + 5
    while owned_children() and time.monotonic() < deadline:
        time.sleep(0.1)
    if owned_children():
        raise RuntimeError('CHILDREN_REMAIN: inspect diagnose before starting another Platform')


def stop():
    pid = owned_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 45
        while owned_pid() and time.monotonic() < deadline:
            time.sleep(0.1)
        if owned_pid():
            raise RuntimeError('STOP_TIMEOUT: native supervisor still running')
    cleanup_children()
    (STATE / 'pid.json').unlink(missing_ok=True)
    LOG.info('NATIVE_STOPPED')


def cpu_snapshot(pids):
    result = {}
    for pid in pids:
        tasks = {}
        for path in Path(f'/proc/{pid}/task').glob('*/status'):
            try:
                values = dict(x.split(':', 1) for x in path.read_text().splitlines() if ':' in x)
                tasks[path.parent.name] = {k: values[k].strip() for k in ('Name', 'Cpus_allowed_list') if k in values}
            except OSError:
                pass
        cgroup = Path(f'/proc/{pid}/cgroup')
        result[str(pid)] = {'threads': tasks, 'cgroup': cgroup.read_text() if cgroup.exists() else 'unavailable'}
    limits = {}
    try:
        for line in Path('/proc/self/cgroup').read_text().splitlines():
            hierarchy, controllers, relative = line.split(':', 2)
            if hierarchy == '0':
                directory = Path('/sys/fs/cgroup') / relative.lstrip('/')
                for parent in [directory, *directory.parents]:
                    if not parent.is_relative_to('/sys/fs/cgroup'):
                        break
                    for name in ('cpu.max', 'cpu.stat', 'cpuset.cpus.effective'):
                        path = parent / name
                        if path.is_file():
                            limits[str(path)] = path.read_text().strip()
            else:
                for controller in controllers.split(','):
                    directory = Path('/sys/fs/cgroup') / controller / relative.lstrip('/')
                    for parent in [directory, *directory.parents]:
                        if not parent.is_relative_to(Path('/sys/fs/cgroup') / controller):
                            break
                        for name in ('cpu.cfs_quota_us', 'cpu.cfs_period_us', 'cpu.stat', 'cpuset.cpus'):
                            path = parent / name
                            if path.is_file():
                                limits[str(path)] = path.read_text().strip()
    except OSError:
        pass
    return {'online': Path('/sys/devices/system/cpu/online').read_text().strip(),
            'processes': result, 'cgroup_limits': limits or 'unavailable'}


def diagnose(state):
    from utils_local.runtime_logging import redact_log_text
    data = {'version': json.loads((ROOT / 'HOST_RELEASE.json').read_text())['version'],
            'phase': state['phase'], 'native_pid': owned_pid(),
            'cpu': cpu_snapshot([os.getpid(), *[r['pid'] for r in owned_children()], *([owned_pid()] if owned_pid() else [])]),
            'site_npu_acceptance': 'not_evaluated', 'pipeline_log_tail_bytes': PIPELINE_LOG_TAIL_BYTES, 'logs': {}}
    for key, path in [('launcher', STATE / 'launcher.log'),
                      ('platform', Path(state['environment']['TRAFFIC_LOG_DIR']) / 'containers/platform.log')]:
        if path.is_file():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 16000))
                data['logs'][key] = redact_log_text(stream.read().decode(errors='replace'))
    pipelines = Path(state['environment']['TRAFFIC_LOG_DIR']) / 'pipelines'
    for path in sorted(pipelines.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - PIPELINE_LOG_TAIL_BYTES))
            data['logs'][path.name] = redact_log_text(stream.read().decode(errors='replace'))
    save('diagnosis.json', data)
    LOG.info('DIAGNOSIS_SAVED %s (private; review before sharing)', STATE / 'diagnosis.json')


def alias_set(state):
    alias = Path('/app')
    if alias.is_symlink() and alias.resolve() == ROOT / 'app':
        return
    previous = previous_alias(Path(state['deployment_root']))
    if previous != state.get('previous_native'):
        raise ValueError('APP_PATH_CHANGED: refusing to replace /app')
    if alias.is_symlink():
        alias.unlink()
    alias.symlink_to(ROOT / 'app', target_is_directory=True)


def alias_restore(state):
    alias = Path('/app')
    if alias.is_symlink() and alias.resolve() == ROOT / 'app':
        alias.unlink()
        if state.get('previous_native'):
            alias.symlink_to(Path(state['previous_native']) / 'app', target_is_directory=True)


def old_native(state, command):
    old = state.get('previous_native')
    if old:
        root = Path(old)
        entry = root / ('traffic' if (root / 'traffic').exists() else 'host-platform')
        execute([str(entry), command])


def restore(state):
    raw_root = state['environment'].get('TRAJECTORY_ARCHIVE_SPOOL_DIR')
    transport_marker = Path(raw_root) / 'fixed-topics-v2.active' if raw_root else None
    if transport_marker is not None and transport_marker.exists():
        previous = state.get('previous_native')
        manifest = json.loads((Path(previous) / 'HOST_RELEASE.json').read_text()) if previous else {}
        if 'uav-fixed/v2' not in manifest.get('transport_versions', []) and (state.get('previous_native_running') or state.get('previous_platform_running')):
            raise ValueError('DATA_CONTRACT_DOWNGRADE: incremental fixed-Topic data requires a compatible consumer')
    marker = Path(raw_root) / 'sampling-v2.active' if raw_root else None
    if marker is not None and marker.exists():
        previous = state.get('previous_native')
        compatible = False
        if previous:
            manifest = json.loads((Path(previous) / 'HOST_RELEASE.json').read_text())
            compatible = 'event-faithful/v2' in manifest.get('sampling_versions', [])
        if not compatible and (state.get('previous_native_running') or state.get('previous_platform_running')):
            raise ValueError('DATA_CONTRACT_DOWNGRADE: v2 sampling data exists; keep a v2-capable consumer, disable sampling for new tasks instead')
    stop()
    alias_restore(state)
    if state.get('previous_native_running'):
        old_native(state, 'start')
    elif state.get('previous_platform_running'):
        execute(compose(state, 'docker-original.json', 'up', '-d', '--no-deps', '--pull', 'never', 'platform'))
    if state.get('previous_console_running', True):
        execute(compose(state, 'docker-original.json', 'up', '-d', '--no-deps', '--pull', 'never', 'console2'))
    else:
        execute(compose(state, 'docker-original.json', 'stop', '--timeout', '30', 'console2'))
    state['phase'] = 'rolled_back'
    save('site.json', state)
    LOG.info('RESTORE_SUCCEEDED previous_platform_running=%s previous_native_running=%s',
             state.get('previous_platform_running'), state.get('previous_native_running'))


def ready(state):
    url = 'http://' + state['bind_address'] + ':8000/ready'
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
        return json.load(response).get('status') == 'ready'


def launch(state):
    if owned_children():
        raise ValueError('NATIVE_ORPHANS: run ./traffic stop before starting')
    launcher = STATE / 'launcher.log'
    if launcher.exists() and launcher.stat().st_size >= 1024 * 1024:
        launcher.replace(STATE / 'launcher.log.1')
    with launcher.open('a') as output:
        process = subprocess.Popen([str(ROOT / 'traffic'), 'run'], stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('NATIVE_EXITED: inspect state/launcher.log')
        try:
            if ready(state):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError('READY_TIMEOUT: inspect DATA_ROOT/logs/containers/platform.log')


def console_ready(state):
    console = service(state, 'console2', running=True)
    for _ in range(30):
        result = subprocess.run(['docker', 'exec', console['Id'], 'wget', '-q', '-O', '-',
                                 'http://127.0.0.1:8080/ready'], capture_output=True)
        try:
            if result.returncode == 0 and json.loads(result.stdout).get('status') == 'ready':
                return
        except ValueError:
            pass
        time.sleep(1)
    raise RuntimeError('CONSOLE_UPSTREAM: retained Console cannot reach native /ready; inspect bridge/firewall')


def check_port(state):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((state['bind_address'], 8000))


def start(state):
    if owned_pid():
        if service(state, 'platform')['State']['Running']:
            raise ValueError('DUPLICATE_PLATFORM: Docker and native Platform are both running')
        if ready(state):
            console_ready(state)
            LOG.info('ALREADY_RUNNING pid=%s', owned_pid())
            return
        raise ValueError('NATIVE_UNHEALTHY: run diagnose or restart')
    prepare(state)
    if state['phase'] == 'switching':
        raise ValueError('INTERRUPTED_SWITCH: run rollback before retrying start')
    previous_running = state['platform_running']
    old = state.get('previous_native')
    old_record = Path(old) / 'state/pid.json' if old else None
    previous_native_running = False
    if old_record and old_record.is_file():
        previous_native_running = bool(alive(json.loads(old_record.read_text())))
    state.setdefault('previous_platform_running', previous_running)
    state.setdefault('previous_native_running', previous_native_running)
    state['phase'] = 'switching'
    save('site.json', state)
    try:
        old_native(state, 'stop')
        execute(compose(state, 'docker-original.json', 'stop', '--timeout', '30', 'platform'))
        alias_set(state)
        check_port(state)
        logged(state, 'preflight', 'runtime_check.py')
        launch(state)
        execute(compose(state, 'docker-host.json', 'up', '-d', '--no-deps', '--pull', 'never', 'console2'))
        console_ready(state)
        state['phase'] = 'native'
        save('site.json', state)
        LOG.info('START_SUCCEEDED native_platform=true native_detector=true web_port=8009')
    except BaseException:
        LOG.exception('START_FAILED; restoring previous application state')
        try:
            restore(state)
        except BaseException:
            LOG.exception('RESTORE_FAILED; keep state snapshots and inspect diagnose')
        raise


def supervise(state):
    if service(state, 'platform')['State']['Running']:
        raise ValueError('DOCKER_PLATFORM_RUNNING')
    # Adopt orphaned workers, including pipelines which create their own sessions.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')
    from utils_local.runtime_logging import rotating_log_handler, redact_log_text
    logger = logging.getLogger('native-platform-output')
    logger.setLevel(logging.INFO)
    handler = rotating_log_handler(Path(state['environment']['TRAFFIC_LOG_DIR']) / 'containers/platform.log')
    logger.addHandler(handler)
    # Native services have no Docker stdout collector. Keep long-running output only
    # in the bounded file; launcher.log is reserved for supervisor/loader failures.
    logger.propagate = False
    command = [str(ROOT / 'bin/python3'), '-m', 'uvicorn', 'app.main:app',
               '--host', state['bind_address'], '--port', '8000']
    process = subprocess.Popen(command, cwd=ROOT / 'app/platform', env=environment(state),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    record = process_record(os.getpid())
    save('pid.json', record)
    stopping = threading.Event()
    def shutdown(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    def drain():
        # Bound partial lines so malformed child output cannot grow memory without limit.
        while chunk := process.stdout.readline(65536):
            logger.info('%s', redact_log_text(chunk.decode(errors='replace').rstrip()))
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    logger.info('NATIVE_BEGIN cpu=%s numerical_threads=1', json.dumps(cpu_snapshot([os.getpid(), process.pid])))
    try:
        while process.poll() is None and not stopping.wait(0.25):
            pass
    finally:
        cleanup_children()
        process.wait(timeout=5)
        reader.join(timeout=3)
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        (STATE / 'pid.json').unlink(missing_ok=True)
        handler.close()
    return process.returncode if not stopping.is_set() else 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'stop', 'restart', 'status', 'check', 'diagnose', 'rollback', 'init-db', 'init-kafka', 'run'))
    parser.add_argument('--deployment-root', type=Path)
    parser.add_argument('--partitions',type=int,default=3)
    parser.add_argument('--replication-factor',type=int)
    args = parser.parse_args()
    check_owned_writable_path(STATE, owner_required=True)
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    logging.basicConfig(level=logging.INFO)
    from utils_local.runtime_logging import RuntimeFormatter
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RuntimeFormatter())
    with (STATE / ('run.lock' if args.command == 'run' else 'control.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (STATE / 'site.json').exists():
            if args.command not in {'start', 'check', 'init-db', 'init-kafka'} or not args.deployment_root:
                raise ValueError('FIRST_START: ./traffic start --deployment-root /absolute/existing/deployment')
            verify_package()
            state = install(args.deployment_root)
        else:
            state = load()
            if args.deployment_root and args.deployment_root.resolve() != Path(state['deployment_root']):
                raise ValueError('DEPLOYMENT_ROOT_CHANGED: use a fresh extracted package')
        import re
        os.environ.update({k: v for k, v in state['environment'].items()
                           if re.search(r'(?:^|_)(?:PASSWORD|PASSWD|SECRET|SECRET_KEY|TOKEN|API_KEY|ACCESS_KEY|KEY)$', k)})
        try:
            if args.command == 'start':
                start(state)
            elif args.command == 'restart':
                stop()
                start(state)
            elif args.command == 'stop':
                stop()
            elif args.command == 'run':
                return supervise(state)
            elif args.command == 'status':
                LOG.info('STATUS phase=%s pid=%s docker_platform_running=%s logs=%s', state['phase'], owned_pid(),
                         service(state, 'platform')['State']['Running'], state['environment']['TRAFFIC_LOG_DIR'])
            elif args.command == 'check':
                prepare(state)
                logged(state, 'preflight', 'runtime_check.py')
            elif args.command == 'diagnose':
                diagnose(state)
            elif args.command == 'rollback':
                restore(state)
            elif args.command == 'init-kafka':
                if not args.replication_factor or args.replication_factor<1 or args.partitions<1:
                    raise ValueError('INIT_KAFKA_REQUIRES_EXPLICIT_REPLICATION: preserve the verified broker policy')
                refresh(state)
                state['environment']['KAFKA_TOPIC_PARTITIONS']=str(args.partitions)
                state['environment']['KAFKA_TOPIC_REPLICATION_FACTOR']=str(args.replication_factor)
                save('site.json',state)
                logged(state,'init-kafka','init_kafka.py','--partitions',str(args.partitions),'--replication-factor',str(args.replication_factor))
            elif args.command == 'init-db':
                refresh(state)
                if owned_pid() or owned_children() or state['platform_running']:
                    raise ValueError('INIT_DB_REQUIRES_STOPPED: stop all Platform instances first')
                if state.get('previous_native'):
                    old_record = Path(state['previous_native']) / 'state/pid.json'
                    if old_record.is_file() and alive(json.loads(old_record.read_text())):
                        raise ValueError('INIT_DB_REQUIRES_STOPPED: previous native Platform is running')
                save('site.json', state)
                check_baseline()
                logged(state, 'init-db', 'init_db.py')
        except BaseException:
            if args.command != 'run':
                try:
                    diagnose(state)
                except Exception:
                    LOG.exception('DIAGNOSIS_FAILED')
            raise
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        from utils_local.runtime_logging import redact_log_text
        LOG.exception('OPERATION_FAILED type=%s detail=%s; inspect state/launcher.log and DATA_ROOT/logs/containers',
                  type(exc).__name__, redact_log_text(str(exc)))
        sys.exit(1)
