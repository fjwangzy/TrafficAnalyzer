import base64
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('console_repair', ROOT / 'deploy/intranet/repair_console_403.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def fixture(root, monkeypatch):
    directory = root / 'application'
    entrypoint = directory / 'app/console/entrypoint.sh'
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(b'old fixture\n')
    monkeypatch.setattr(repair, 'OLD_SHA256', repair.digest(entrypoint.read_bytes()))
    (directory / 'SHA256SUMS').write_text(f'{repair.OLD_SHA256}  app/console/entrypoint.sh\n')
    (root / 'SHA256SUMS').write_bytes(repair.sealed({
        p.relative_to(root).as_posix(): repair.digest(p.read_bytes()) for p in (entrypoint, directory / 'SHA256SUMS')}))
    (root / '.env').write_text('password=private-fixture\n')
    (root / '.env').chmod(0o600)
    return directory, entrypoint


def test_repair_updates_both_manifests_preserves_env_and_is_repeatable(tmp_path, monkeypatch):
    directory, entrypoint = fixture(tmp_path, monkeypatch)
    before = (tmp_path / '.env').read_bytes()
    repair.install(tmp_path, [directory])
    assert entrypoint.read_bytes() == base64.b64decode(repair.PAYLOAD)
    for folder in (tmp_path, directory):
        for name, checksum in repair.checks(folder / 'SHA256SUMS').items():
            assert repair.digest((folder / name).read_bytes()) == checksum
    repair.install(tmp_path, [directory])
    assert (tmp_path / '.env').read_bytes() == before
    assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600
    assert (tmp_path / '.console-403-backup-20261019/application/app/console/entrypoint.sh').read_bytes() == b'old fixture\n'


@pytest.mark.parametrize('tamper', ['entrypoint', 'outer', 'payload'])
def test_repair_refuses_unknown_content_before_writes(tmp_path, monkeypatch, tamper):
    directory, entrypoint = fixture(tmp_path, monkeypatch)
    if tamper == 'entrypoint':
        entrypoint.write_text('site customization\n')
    elif tamper == 'outer':
        (tmp_path / 'SHA256SUMS').write_text('0' * 64 + '  application/app/console/entrypoint.sh\n')
    else:
        monkeypatch.setattr(repair, 'PAYLOAD', base64.b64encode(b'damaged').decode())
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        repair.install(tmp_path, [directory])
    assert all(p.read_bytes() == content for p, content in before.items())
    assert not (tmp_path / '.console-403-backup-20261019').exists()


def test_embedded_payload_is_current_console_startup():
    payload = base64.b64decode(repair.PAYLOAD)
    assert payload == (ROOT / 'deploy/intranet/console-runtime/entrypoint.sh').read_bytes()
    assert hashlib.sha256(payload).hexdigest() == repair.PAYLOAD_SHA256
