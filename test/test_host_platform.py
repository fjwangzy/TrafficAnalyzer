"""Native diagnostic deployment preserves identity, secrets and rollback ordering."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_host', ROOT / 'deploy/host-platform/host_platform.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def test_mapped_paths_keep_persisted_video_layout_and_json_roots():
    mounts = {'/app': '/native/app', '/app/test_videos': '/data/videos', '/survey': '/data/survey'}
    assert host.translate('/app/test_videos/a clip.mp4', mounts) == '/data/videos/a clip.mp4'
    assert json.loads(host.translate('["/app/test_videos", "/survey", "/survey2"]', mounts)) == [
        '/data/videos', '/data/survey', '/survey2']
    assert host.translate('password$/app', mounts) == 'password$/app'


def test_compose_snapshot_keeps_literal_dollars_and_private_permissions(tmp_path):
    path = tmp_path / 'private.json'
    model = {'services': {'console2': {'environment': {'KEY': 'a$secret${literal}'}}}}
    host.private_json(path, host.literal_compose(model))
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())['services']['console2']['environment']['KEY'] == 'a$$secret$${literal}'
    assert model['services']['console2']['environment']['KEY'] == 'a$secret${literal}'


def test_database_recreation_is_rejected_before_connecting(monkeypatch):
    state = {'bundled_database': True, 'project': 'site', 'network': 'site_default',
             'database_address': '172.28.0.3', 'environment': {'DB_HOST': '172.28.0.3'}}
    monkeypatch.setattr(host, 'captured', lambda cmd: 'cid')
    monkeypatch.setattr(host, 'inspect_container', lambda cid: {
        'NetworkSettings': {'Networks': {'site_default': {'IPAddress': '172.28.0.9'}}}})
    with pytest.raises(ValueError, match='address changed'):
        host.check_database_address(state)


def test_failed_native_switch_stops_native_before_docker_restore(monkeypatch):
    events = []
    monkeypatch.setattr(host, 'prepare', lambda state: events.append('prepare'))
    monkeypatch.setattr(host, 'compose', lambda state, filename, *args: [filename, *args])
    monkeypatch.setattr(host.subprocess, 'run', lambda cmd, **kw: events.append(tuple(cmd)))
    monkeypatch.setattr(host, 'logged', lambda *a: events.append('preflight'))
    monkeypatch.setattr(host, 'start', lambda *a: (_ for _ in ()).throw(RuntimeError('native failed')))
    monkeypatch.setattr(host, 'stop', lambda: events.append('stop-native'))
    with pytest.raises(RuntimeError, match='native failed'):
        host.switch({})
    assert events == ['prepare', ('docker-original.json', 'stop', '--timeout', '30', 'platform'),
                      'preflight', 'stop-native', ('docker-original.json', 'up', '-d', '--no-deps',
                                                  '--pull', 'never', 'platform', 'console2')]
    assert not any('init-db' in str(event) for event in events)


def test_runtime_environment_cannot_reintroduce_container_linker_paths(monkeypatch):
    monkeypatch.setenv('LD_PRELOAD', '/opt/wrong.so')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/usr/lib/wrong')
    monkeypatch.setenv('HOST_RUNTIME_LOADER', '/native/loader')
    env = host.env_for({'environment': {'DB_NAME': 'ycx_prod', 'DB_SCHEMA': 'drone'}})
    assert 'LD_PRELOAD' not in env and 'LD_LIBRARY_PATH' not in env
    assert env['HOST_RUNTIME_LOADER'] == '/native/loader'
    assert env['DB_NAME'] == 'ycx_prod'


def test_install_uses_running_mounts_and_keeps_database_container(monkeypatch, tmp_path):
    root = tmp_path / 'native'
    site = tmp_path / 'site'
    root.mkdir(); site.mkdir()
    (site / '.env').write_text('PRIVATE=true\n'); (site / '.env').chmod(0o600)
    (site / 'docker-compose.yaml').write_text('services: {}')
    statepath = root / 'state'; statepath.mkdir()
    app = root / 'app'; app.mkdir()
    for name in ('weights', 'test_videos', 'logs'):
        (app / name).mkdir()
    names = ('/app', '/app/weights', '/app/test_videos', '/app/logs', '/hls', '/pipeline-output',
             '/pipeline-spool', '/survey', '/calibration', '/trajectory-archive')
    mounts = {}
    for index, name in enumerate(names):
        path = site / ('mount-' + str(index)); path.mkdir(); mounts[name] = str(path)
    nginx = site / 'nginx.conf'; nginx.write_text('proxy_pass http://platform:8000;')
    labels = {'com.docker.compose.project': 'site', 'com.docker.compose.project.config_files': str(site / 'docker-compose.yaml')}
    item = {'Id': 'platform-cid', 'Image': 'sha256:runtime', 'Config': {'Labels': labels, 'Env': [
        'DB_HOST=road9', 'DB_NAME=ycx_prod', 'DB_SCHEMA=drone', 'DB_PASSWORD=p$a${s}',
        'SURVEY_ASSET_ROOTS=["/app/test_videos"]', 'ASCEND_DEVICE_ID=0',
        'PIPELINE_ASCEND_MANIFEST=/app/weights/ascend/manifest.json',
        'ASCEND_MODEL_MANIFEST=/app/weights/ascend/manifest.json', 'LD_PRELOAD=/opt/highgo/lib/libpq.so.5']},
        'Mounts': [{'Destination': k, 'Source': v, 'Type': 'bind'} for k, v in mounts.items()],
        'NetworkSettings': {'Networks': {'site_default': {}}}}
    model = {'services': {'platform': {'volumes': [{'target': '/app', 'source': mounts['/app']}]},
                          'console2': {'environment': {'KEY': 'k$1'}, 'depends_on': {'platform': {}},
                                       'volumes': [{'target': '/opt/traffic-console/nginx.conf', 'source': str(nginx)}]}}}
    (root / 'HOST_RELEASE.json').write_text(json.dumps({'runtime_image': {'id': 'sha256:runtime'}}))
    monkeypatch.setattr(host, 'ROOT', root); monkeypatch.setattr(host, 'STATE', statepath)
    monkeypatch.setattr(host, 'verify', lambda: None)
    monkeypatch.setattr(host, 'discover', lambda deployment: item)
    monkeypatch.setattr(host, 'inspect_container', lambda cid: {'NetworkSettings': {'Networks': {'site_default': {'IPAddress': '172.28.0.3'}}}})
    operations = []
    def capture(cmd, env=None):
        operations.append(cmd)
        if cmd[:3] == ['docker', 'network', 'inspect']:
            return json.dumps([{'Driver': 'bridge', 'IPAM': {'Config': [{'Gateway': '172.28.0.1'}]}}])
        if cmd[:2] == ['docker', 'ps']:
            return 'database-cid'
        return json.dumps(model)
    monkeypatch.setattr(host, 'captured', capture)
    # Use an unoccupied alias in this test without touching real host /app.
    realpath = host.Path
    monkeypatch.setattr(host, 'Path', lambda value: tmp_path / 'unused-alias' if value == '/app' else realpath(value))
    host.install(site)
    saved = json.loads((statepath / 'site.json').read_text())
    assert saved['environment']['DB_HOST'] == '172.28.0.3'
    assert saved['environment']['DB_NAME'] == 'ycx_prod'
    assert saved['environment']['DB_SCHEMA'] == 'drone'
    assert saved['environment']['DB_PASSWORD'] == 'p$a${s}'
    assert saved['environment']['PIPELINE_ASCEND_MANIFEST'] == mounts['/app/weights'] + '/ascend/manifest.json'
    assert saved['environment']['ASCEND_MODEL_MANIFEST'] == mounts['/app/weights'] + '/ascend/manifest.json'
    assert host.env_for(saved)['ASCEND_MODEL_MANIFEST'] == mounts['/app/weights'] + '/ascend/manifest.json'
    assert json.loads(saved['environment']['SURVEY_ASSET_ROOTS']) == [mounts['/app/test_videos']]
    assert 'LD_PRELOAD' not in saved['environment']
    original = json.loads((statepath / 'docker-original.json').read_text())
    native = json.loads((statepath / 'docker-host.json').read_text())
    assert original['services']['console2']['depends_on'] == {'platform': {}}
    assert native['services']['console2']['depends_on'] == {}
    assert native['services']['console2']['extra_hosts'] == {'host.traffic.internal': '172.28.0.1'}
    assert 'host.traffic.internal:8000' in (statepath / 'nginx.conf').read_text()
    assert (app / 'test_videos').resolve() == realpath(mounts['/app/test_videos'])
    assert not any(x in command for command in operations for x in ('stop', 'up', 'down'))


def test_native_detector_stream_is_bound_to_loopback(monkeypatch):
    from nodes.FlaskServerVideoNode import VideoServer
    monkeypatch.setenv('VIDEO_BIND_HOST', '127.0.0.1')
    monkeypatch.setenv('VIDEO_PORT', '0')
    server = VideoServer({'video_server_node': {'host_ip': '0.0.0.0', 'port': 8100,
        'index_page': 'index.html', 'template_folder': '.', 'output_size': [16, 16]}})
    try:
        assert server._httpd.server_address[0] == '127.0.0.1'
        assert server._httpd.server_address[1] > 0
    finally:
        server.stop_server()


def test_existing_native_state_restores_manifest_for_preflight(monkeypatch):
    monkeypatch.delenv('ASCEND_MODEL_MANIFEST', raising=False)
    manifest = '/existing/assets/weights/ascend/manifest.json'
    state = {'environment': {'PIPELINE_ASCEND_MANIFEST': manifest}}
    environment = host.env_for(state)
    assert environment['ASCEND_MODEL_MANIFEST'] == manifest
    assert 'ASCEND_MODEL_MANIFEST' not in state['environment']


def test_native_explicit_manifest_is_preserved():
    state = {'environment': {'PIPELINE_ASCEND_MANIFEST': '/mapped/model.json',
                             'ASCEND_MODEL_MANIFEST': '/explicit/model.json'}}
    assert host.env_for(state)['ASCEND_MODEL_MANIFEST'] == '/explicit/model.json'


def test_model_preflight_receives_manifest_from_existing_state(monkeypatch):
    received = []
    monkeypatch.setattr(host.subprocess, 'run', lambda command, **kwargs: received.append((command, kwargs)))
    host.logged({'environment': {'PIPELINE_ASCEND_MANIFEST': '/assets/weights/ascend/manifest.json'}},
                'preflight', 'runtime_check.py')
    assert received[0][0][-1].endswith('/runtime_check.py')
    assert received[0][1]['env']['ASCEND_MODEL_MANIFEST'] == '/assets/weights/ascend/manifest.json'


@pytest.mark.parametrize('already_fixed', [False, True])
def test_manifest_repair_is_idempotent_and_preserves_installed_secrets(tmp_path, already_fixed):
    repair_spec = importlib.util.spec_from_file_location('manifest_repair', ROOT / 'deploy/host-platform/repair_manifest.py')
    repair = importlib.util.module_from_spec(repair_spec)
    repair_spec.loader.exec_module(repair)
    after = (ROOT / 'deploy/host-platform/host_platform.py').read_bytes()
    original_text = after.decode()
    for old, new in reversed(repair.PATCHES):
        original_text = original_text.replace(new, old, 1)
    before = original_text.encode()
    assert repair.digest(before) == repair.BEFORE
    assert repair.digest(after) == repair.AFTER
    (tmp_path / 'HOST_RELEASE.json').write_text(json.dumps({'kind': 'native-host-platform', 'version': '2026.10.20.1'}))
    target = tmp_path / 'host_platform.py'; target.write_bytes(after if already_fixed else before)
    inventory = tmp_path / 'SHA256SUMS'
    inventory.write_text(repair.digest(target.read_bytes()) + '  host_platform.py\n' + 'a' * 64 + '  untouched.py\n')
    state = tmp_path / 'state'; state.mkdir()
    site = state / 'site.json'
    secret_state = b'{"environment":{"DB_PASSWORD":"private-sentinel","PIPELINE_ASCEND_MANIFEST":"/assets/model.json"}}'
    site.write_bytes(secret_state); site.chmod(0o600)
    for _ in range(2):
        repair.repair(tmp_path)
        assert target.read_bytes() == after
        assert site.read_bytes() == secret_state and site.stat().st_mode & 0o777 == 0o600
        assert inventory.read_text() == repair.AFTER + '  host_platform.py\n' + 'a' * 64 + '  untouched.py\n'
        assert (state / 'manifest-fix-backup/host_platform.py').stat().st_mode & 0o777 == 0o600
    target.write_bytes(b'unexpected edits')
    saved = inventory.read_bytes()
    with pytest.raises(ValueError, match='differs from known release'):
        repair.repair(tmp_path)
    assert target.read_bytes() == b'unexpected edits'
    assert inventory.read_bytes() == saved
