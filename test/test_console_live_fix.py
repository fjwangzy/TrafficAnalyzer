import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('console_live_fix', ROOT / 'deploy/intranet/console-fix/apply.py')
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


@pytest.fixture
def release(tmp_path):
    root, payload = tmp_path / 'release', tmp_path / 'patch'
    root.mkdir(); (payload / 'console/html').mkdir(parents=True)
    (root / '.env').write_text("ROAD9_PASSWORD='keep ! $value'\nDATA_ROOT=../persistent-data\n")
    (root / 'IMAGES.txt').write_text('sha256:fixture traffic-analyzer-platform:fixture-arm64\n')
    model = {'services': {'road9': {'volumes': ['../data/postgres:/var/lib/postgresql/data']},
                          'platform': {'environment': {'DB_HOST': 'road9'}}, 'init-db': {'depends_on': ['road9']},
                          'console2': {'image': 'fixture/console:arm64', 'environment': {'MINEMAP_DOMAIN': 'http://map.internal'}}}}
    (root / 'docker-compose.yaml').write_text(json.dumps(model))
    (root / 'SHA256SUMS').write_text(f"{fix.sha(root / 'docker-compose.yaml')}  docker-compose.yaml\n")
    (payload / 'console/html/index.html').write_text('<html>fixed</html>')
    (payload / 'console/40-amap-runtime-config.sh').write_text('#!/bin/sh\nexit 0\n')
    (payload / 'diagnose_live.py').write_text('print("read only")\n')
    return root, payload, model


def test_fix_preserves_database_platform_and_private_env_and_checksums(release):
    root, payload, before = release
    private = (root / '.env').read_bytes()
    record = fix.apply(root, payload)
    model = json.loads((root / 'docker-compose.yaml').read_text())
    assert {k: v for k, v in model['services'].items() if k != 'console2'} == {k: v for k, v in before['services'].items() if k != 'console2'}
    assert (root / '.env').read_bytes() == private
    assert (root / record['backup'] / 'docker-compose.yaml').read_text() == json.dumps(before)
    mounts = model['services']['console2']['volumes']
    assert mounts[0]['target'] == '/usr/share/nginx/html' and not mounts[0]['read_only']
    assert mounts[1]['read_only']
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


def test_reapply_keeps_runtime_configuration_and_original_backup(release):
    root, payload, _ = release
    first = fix.apply(root, payload)
    generated = root / fix.DIRECTORY / 'html/runtime-config.js'
    generated.write_text('private runtime key remains here')
    assert fix.apply(root, payload) == first
    assert generated.read_text() == 'private runtime key remains here'
    assert 'runtime-config.js' not in (root / 'SHA256SUMS').read_text()


def test_unrecognized_site_change_is_rejected_before_any_mutation(release):
    root, payload, _ = release
    compose = root / 'docker-compose.yaml'
    compose.write_text(compose.read_text() + '\n')
    with pytest.raises(ValueError, match='checksum'):
        fix.apply(root, payload)
    assert not (root / fix.DIRECTORY).exists()
    assert not (root / f'.{fix.DIRECTORY}-backup').exists()
