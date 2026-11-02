import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "deploy/intranet/hotfix-highgo-version.py"
spec = importlib.util.spec_from_file_location("highgo_hotfix", path)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def test_overlay_reaches_init_and_runtime_and_preserves_configuration(tmp_path):
    root, payload = tmp_path / "release", tmp_path / "patch"
    root.mkdir()
    payload.mkdir()
    for name in patcher.OVERLAY_FILES:
        if name == "pymysql.zip":
            (payload / (name + ".b64")).write_text(base64.b64encode(b"fixture-zip").decode())
        else:
            (payload / name).write_text(f"# fixture {name}\n")
    before = {"services": {name: {"environment": {"DB_SCHEMA": "custom_schema"},
                                     "volumes": [{"type": "bind", "source": "../site-assets", "target": "/app/weights", "read_only": True}]}
                           for name in ("platform", "init-db")}}
    compose = root / "docker-compose.yaml"
    compose.write_text(json.dumps(before))
    env = root / ".env"
    env.write_text("PASSWORD=keep-exactly\n")
    env.chmod(0o600)
    checks = root / "SHA256SUMS"
    original = f"{hashlib.sha256(compose.read_bytes()).hexdigest()}  docker-compose.yaml\n"
    checks.write_text(original)
    patcher.apply(root, payload)
    patcher.apply(root, payload)
    assert env.read_text() == "PASSWORD=keep-exactly\n" and env.stat().st_mode & 0o777 == 0o600
    services = json.loads(compose.read_text())["services"]
    for name in services:
        assert services[name]["environment"]["DB_SCHEMA"] == "custom_schema"
        assert services[name]["environment"]["DB_TIMESCALE_REQUIRED"] == "${DB_TIMESCALE_REQUIRED:-false}"
        assert services[name]["volumes"][0] == before["services"][name]["volumes"][0]
    assert len(services["platform"]["volumes"]) == 1 + len(patcher.OVERLAY_FILES)
    assert len(services["init-db"]["volumes"]) == 1 + len(patcher.OVERLAY_FILES)
    assert (root / ".highgo-version-hotfix-backup/SHA256SUMS").read_text() == original
    for line in checks.read_text().splitlines():
        checksum, filename = line.split(maxsplit=1)
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == checksum
    (payload / "highgo_dialect.py").write_text("# fixture schema session fix\n")
    patcher.apply(root, payload)
    assert (root / "deploy/intranet/highgo-version-hotfix/highgo_dialect.py").read_text() == "# fixture schema session fix\n"
    assert (root / ".highgo-version-hotfix-backup/sources-before-schema-fix/highgo_dialect.py").read_text() == "# fixture highgo_dialect.py\n"
    (payload / "site-defaults.env").write_text("DORIS_MYSQL_PASSWORD='private $dollar value'\nROAD_FEATURES_ENABLED='false'\n")
    original_env = env.read_text()
    patcher.apply(root, payload)
    patcher.apply(root, payload)
    assert env.read_text().startswith(original_env)
    assert env.read_text().count("DORIS_MYSQL_PASSWORD=") == 1
    assert env.stat().st_mode & 0o777 == 0o600
    assert (root / ".highgo-version-hotfix-backup/environment-before-optional-dependencies.env").read_text() == original_env
    compose.write_text("unrecorded change")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        patcher.apply(root, payload)
