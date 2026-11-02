"""Exercise offline first-start plumbing without an NPU or production credentials."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_bootstrap", ROOT / "scripts/build_intranet_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
seed_spec = importlib.util.spec_from_file_location("seed_deployment", ROOT / "deploy/intranet/seed_sources.py")
seed = importlib.util.module_from_spec(seed_spec)
seed_spec.loader.exec_module(seed)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_source_catalog_covers_current_configuration_and_rejects_path_escape(tmp_path):
    catalog = seed.load_sources(ROOT / "deploy/intranet/test-sources.json")
    assert len(catalog["sources"]) == 16 and len(catalog["drones"]) == 7
    assert catalog["sources"][0]["video"]["mode"] == "local"
    paths = {row[kind]["location"].removeprefix("/app/test_videos/")
             for row in catalog["sources"] for kind in ("video", "telemetry")}
    assert paths == set((ROOT / "deploy/intranet/VIDEO_FILES.txt").read_text().splitlines())
    catalog["sources"][0]["video"]["location"] = "/app/test_videos/../../etc/passwd"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="mounted video"):
        seed.load_sources(bad)


@pytest.mark.parametrize("app_source", [False, True])
def test_flat_compose_preserves_dependencies_and_dotenv_special_characters(tmp_path, app_source):
    model = release.render_deployment_compose(tmp_path, app_source=app_source)
    assert set(model["services"]) == {"init-db", "platform", "console2"}
    assert model["services"]["platform"]["depends_on"]["init-db"]["condition"] == "service_completed_successfully"
    assert not model["services"]["init-db"].get("devices")
    assert model["services"]["platform"]["environment"]["PIPELINE_IMGSZ"] == "${PIPELINE_IMGSZ:-960}"
    assert model["services"]["platform"]["devices"] == [
        "${ASCEND_DAVINCI_DEVICE}:${ASCEND_DAVINCI_DEVICE}:rwm",
        "/dev/davinci_manager:/dev/davinci_manager:rwm",
        "/dev/devmm_svm:/dev/devmm_svm:rwm",
        "/dev/hisi_hdc:/dev/hisi_hdc:rwm",
    ]
    assert len(model["services"]["init-db"]["volumes"]) == (3 if app_source else 1)
    assert model["services"]["init-db"]["volumes"][0]["read_only"]
    assert "volumes" not in model
    assert all("build" not in service and service["pull_policy"] == "never" for service in model["services"].values())
    assert "__TA_ENV_" not in json.dumps(model)
    assert "/Users/" not in json.dumps(model)
    values = {}
    for line in (ROOT / "deploy/intranet/production.env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value or "fixture-only-secret"
    special = "Chinese中文 $dollar ${UNDEFINED} 'quote' \\\' backslash\\ end"
    values.update(ROAD9_PASSWORD=special, DORIS_MYSQL_PASSWORD=special, KAFKA_SASL_PASSWORD=special)
    source = tmp_path / "input.env"
    source.write_text("".join(f"{name}={release.dotenv_value(value)}\n" for name, value in values.items()))
    record = {"images": {name: {"reference": f"fixture/{name}:test"} for name in ("platform", "console")}}
    if app_source:
        record["application_source"] = "application"
    release.configure_deployment(tmp_path, record, source)
    result = subprocess.run(["docker", "compose", "--env-file", str(tmp_path / ".env"), "-f",
                             str(tmp_path / "docker-compose.yaml"), "config", "--format", "json"],
                            check=True, capture_output=True, text=True)
    parsed = json.loads(result.stdout)["services"]["platform"]["environment"]
    # Canonical Compose output escapes dollars for another interpolation pass.
    assert parsed["DB_PASSWORD"] == special.replace("$", "$$")
    assert parsed["DORIS_MYSQL_PASSWORD"] == special.replace("$", "$$")
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert parsed["DORIS_DATABASE"] == "ycx_xc"
    assert "YCX_DB_HOST" not in parsed and "YCX_DB_PASSWORD" not in parsed
    if app_source:
        services = json.loads(result.stdout)["services"]
        for name in ("platform", "init-db"):
            mount = next(m for m in services[name]["volumes"] if m["target"] == "/app")
            assert mount["source"] == str(tmp_path / "application/app")
            assert mount["read_only"] and not mount["bind"].get("create_host_path", False)
            assert "/app/deploy/intranet/run_logged.py" in services[name]["command"]
        assert services["platform"]["image"] == "fixture/platform:test"
        assert services["console2"]["image"] == "fixture/console:test"
        assert services["console2"]["volumes"][0]["read_only"]


@pytest.fixture
def delivery(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "deploy/intranet").mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/intranet/compose-bootstrap.sh", package / "deploy/intranet")
    shutil.copy2(ROOT / "deploy/intranet/docker-compose", package / "docker-compose")
    (package / "docker-compose").chmod(0o755)
    (package / ".env").write_text("CORS_ORIGINS=auto\nPUBLIC_HOST=fixture.internal\n")
    (package / "docker-compose.yaml").write_text("{}")
    (package / "IMAGES.txt").write_text("sha256:fixture  traffic-analyzer-platform:fixture-arm64\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text('''#!/bin/sh
case "$*" in
  *version*--short*) echo 2.24.4 ;;
  *version*) echo Compose ;;
  *config*--environment*) echo "unknown flag: --environment" >&2; exit 125 ;;
  *run*config-reader*) cat "$FIXTURE_ENV" ;;
  "run --rm --pull never --network none -i --entrypoint python3"*) for code do :; done; exec python3 -c "$code" ;;
  "image inspect"*) if [ -f "$FIXTURE_LOADED" ]; then echo sha256:fixture/arm64; else exit 1; fi ;;
  "load -i"*) touch "$FIXTURE_LOADED" ;;
  *) echo "Unexpected Docker command" >&2; exit 99 ;;
esac
''')
    fake.chmod(0o755)
    envfile = tmp_path / "fixture.env"
    assets, data = tmp_path / "assets", tmp_path / "data"
    envfile.write_text(f"CORS_ORIGINS=auto\nPUBLIC_HOST=fixture.internal\nCONSOLE_PORT=8009\nASSET_ROOT={assets}\nDATA_ROOT={data}\n")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", FIXTURE_ENV=str(envfile),
               FIXTURE_LOADED=str(tmp_path / "loaded"))
    return package, assets, env


def seal(package):
    files = sorted(path for path in package.rglob("*") if path.is_file() and path.name not in {".env", "SHA256SUMS"})
    (package / "SHA256SUMS").write_text("".join(f"{sha(path.read_bytes())}  {path.relative_to(package)}\n" for path in files))


def model_archive(package, extra=None):
    content = {"weights/ascend/manifest.json": b"{}", "weights/source.pt": b"fixture weights"}
    checks = "".join(f"{sha(value)}  {name}\n" for name, value in content.items())
    archive = package.parent / "models-test.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, value in dict(content, SHA256SUMS=checks.encode()).items():
            member = tarfile.TarInfo("models/" + name)
            member.size = len(value)
            tar.addfile(member, io.BytesIO(value))
        if extra:
            tar.addfile(extra)
    (package / "MODEL_ARCHIVE_SHA256SUMS").write_text(f"{sha(archive.read_bytes())}  {archive.name}\n")
    (package / "MODEL_SHA256SUMS").write_text(checks)


def launch(delivery, command):
    package, _, env = delivery
    return subprocess.run([str(package / "docker-compose"), command], env=env, capture_output=True, text=True)


def test_prepare_imports_separate_model_package_and_keeps_env_private(delivery):
    package, assets, _ = delivery
    model_archive(package)
    seal(package)
    result = launch(delivery, "prepare")
    assert result.returncode == 0, result.stderr
    assert (assets / "weights/source.pt").read_bytes() == b"fixture weights"
    assert not list(assets.glob(".model-import.*"))
    assert not list(package.glob(".compose-probe.*"))
    assert "http://fixture.internal:8009" in (package / ".env").read_text()
    assert (package / ".env").stat().st_mode & 0o777 == 0o600
    assert launch(delivery, "prepare").returncode == 0
    (assets / "weights/source.pt").write_text("corrupted")
    assert launch(delivery, "prepare").returncode != 0


@pytest.mark.parametrize("name,link", [("models/../../escaped", False), ("models/weights/escape", True)])
def test_prepare_rejects_unsafe_archives_and_cleans_staging(delivery, name, link):
    package, assets, _ = delivery
    extra = tarfile.TarInfo(name)
    if link:
        extra.type, extra.linkname = tarfile.SYMTYPE, "/tmp"
    model_archive(package, extra)
    seal(package)
    assert launch(delivery, "prepare").returncode != 0
    assert not (assets / "weights").exists()
    assert not list(assets.glob(".model-import.*"))


def test_load_verifies_and_imports_only_missing_images(delivery):
    package, _, env = delivery
    (package / "images").mkdir()
    (package / "images/runtime.tar").write_bytes(b"fixture image archive")
    (package / "IMAGES.txt").write_text("sha256:fixture  fixture/image:test\n")
    seal(package)
    assert launch(delivery, "load").returncode == 0
    assert Path(env["FIXTURE_LOADED"]).exists()
    (package / "images/runtime.tar").write_bytes(b"corrupted")
    assert launch(delivery, "load").returncode == 0  # Existing immutable ID needs no re-import.
    Path(env["FIXTURE_LOADED"]).unlink()
    assert launch(delivery, "load").returncode != 0


def test_production_entry_rejects_x86_host_before_loading_images(delivery):
    package, _, env = delivery
    binary = Path(env["PATH"].split(os.pathsep)[0]) / "uname"
    binary.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n')
    binary.chmod(0o755)
    seal(package)
    result = launch(delivery, "up")
    assert result.returncode != 0 and "aarch64/arm64" in result.stderr
    assert not Path(env["FIXTURE_LOADED"]).exists()


@pytest.mark.parametrize("state", ["original", "partial", "unknown", "compose_partial", "compose_unknown"])
def test_hotfix_preserves_configuration_checksums_and_rejects_unknown_scripts(delivery, tmp_path, state):
    package, _, env = delivery
    Path(env["FIXTURE_LOADED"]).touch()
    patch = tmp_path / "patch"
    patch.mkdir()
    original = b"#!/bin/sh\n# fixture of the previous release\n"
    bootstrap = package / "deploy/intranet/compose-bootstrap.sh"
    repaired = bootstrap.read_bytes()
    bootstrap.write_bytes(original)
    compose = package / "docker-compose.yaml"
    model = {"services": {"platform": {"devices": [{"source": "/dev/davinci0", "target": "/dev/davinci0", "permissions": "rwm"}],
                                         "environment": {"PIPELINE_IMGSZ": "${PIPELINE_IMGSZ}", "CUSTOM_SITE": "keep"}}}}
    compose.write_text(json.dumps(model, indent=2) + "\n")
    original_compose = compose.read_bytes()
    seal(package)
    before_checks = (package / "SHA256SUMS").read_text()
    before_env = (package / ".env").read_bytes()
    installer = (ROOT / "deploy/intranet/hotfix-compose-environment.sh").read_text()
    # Pin the synthetic previous-release fixture in place of the real published file.
    installer = installer.replace("196a76b8a98f5234b41820eb2dd0ddbd3e31ae2a954b3a9a0a15706b0d074f0e", sha(original))
    (patch / "apply.sh").write_text(installer)
    (patch / "compose-bootstrap.sh").write_bytes(repaired)
    seal(patch)
    if state == "partial":
        bootstrap.write_bytes(repaired)
    elif state == "unknown":
        bootstrap.write_bytes(b"unknown modification")
    if state in {"compose_partial", "compose_unknown"}:
        backup = package / ".compose-environment-hotfix-backup"
        backup.mkdir()
        (backup / "docker-compose.yaml").write_bytes(original_compose)
        model["services"]["platform"]["devices"] = ["/dev/davinci0:/dev/davinci0:rwm"]
        model["services"]["platform"]["environment"]["PIPELINE_IMGSZ"] = "${PIPELINE_IMGSZ:-960}"
        if state == "compose_unknown":
            model["services"]["platform"]["environment"]["CUSTOM_SITE"] = "unrecorded"
        compose.write_text(json.dumps(model, indent=2) + "\n")
    result = subprocess.run(["sh", str(patch / "apply.sh"), str(package)], env=env, capture_output=True, text=True)
    assert (package / ".env").read_bytes() == before_env
    if state in {"unknown", "compose_unknown"}:
        assert result.returncode != 0
        assert bootstrap.read_bytes() == (b"unknown modification" if state == "unknown" else original)
        assert (package / "SHA256SUMS").read_text() == before_checks
        return
    assert result.returncode == 0, result.stderr
    assert bootstrap.read_bytes() == repaired
    repaired_compose = compose.read_bytes()
    assert json.loads(repaired_compose)["services"]["platform"]["environment"]["CUSTOM_SITE"] == "keep"
    assert (package / "SHA256SUMS").read_text() == before_checks.replace(sha(original), sha(repaired)).replace(sha(original_compose), sha(repaired_compose))
    again = subprocess.run(["sh", str(patch / "apply.sh"), str(package)], env=env, capture_output=True, text=True)
    assert again.returncode == 0
    (patch / "compose-bootstrap.sh").write_bytes(b"corrupted patch")
    assert subprocess.run(["sh", str(patch / "apply.sh"), str(package)], env=env, capture_output=True).returncode != 0


def test_bundled_database_reuses_root_service_is_private_and_waited_for(tmp_path):
    model = release.render_deployment_compose(tmp_path, bundled_database=True)
    assert set(model['services']) == {'road9', 'init-db', 'platform', 'console2'}
    database = model['services']['road9']
    assert not database.get('ports') and not database.get('profiles')
    assert database['pull_policy'] == 'never'
    assert database['volumes'][0]['source'] == '${DATA_ROOT}/postgres'
    assert database['volumes'][0]['target'] == '/var/lib/postgresql/data'
    assert model['services']['init-db']['depends_on']['road9']['condition'] == 'service_healthy'
    assert 'timescaledb' in database['healthcheck']['test'][1] and 'postgis' in database['healthcheck']['test'][1]


@pytest.mark.parametrize('services,failed', [('road9\nplatform', False), ('road9\nplatform', True), ('platform\nconsole2', False)])
def test_database_starts_before_preflight_and_failure_stops_startup(tmp_path, services, failed):
    source = (ROOT / 'deploy/intranet/compose-bootstrap.sh').read_text()
    function = 'start_database() {' + source.split('start_database() {', 1)[1].split('\ncommand=${1:-up}', 1)[0]
    log = tmp_path / 'calls'
    script = '''set -eu
compose() {
 printf '%s\\n' "$*" >> "$CALLS"
 case "$1" in
  config) printf '%s\\n' "$SERVICES" ;;
  up) [ "$FAILED" = false ] ;;
 esac
}
''' + function + '\nstart_database\nprintf preflight >> "$CALLS"\n'
    env = dict(os.environ, CALLS=str(log), SERVICES=services, FAILED=str(failed).lower())
    result = subprocess.run(['sh', '-c', script], env=env, capture_output=True, text=True)
    calls = log.read_text()
    if failed:
        assert result.returncode != 0 and 'preflight' not in calls
    elif 'road9' in services:
        assert result.returncode == 0 and calls.index('up -d') < calls.index('preflight')
    else:
        assert result.returncode == 0 and 'up -d' not in calls and calls.endswith('preflight')


def test_backup_failure_removes_partial_file_and_keeps_existing_backups(tmp_path):
    root = tmp_path / 'release'
    (root / 'deploy/intranet').mkdir(parents=True)
    script = root / 'deploy/intranet/backup-db.sh'
    shutil.copy2(ROOT / 'deploy/intranet/backup-db.sh', script)
    wrapper = root / 'docker-compose'
    wrapper.write_text('#!/bin/sh\nprintf partial\nexit 42\n')
    wrapper.chmod(0o755)
    destination = tmp_path / 'private backups'
    destination.mkdir()
    sentinel = destination / 'existing.dump'
    sentinel.write_bytes(b'preserve existing backup')
    result = subprocess.run(['sh', str(script), str(destination)], capture_output=True, text=True)
    assert result.returncode != 0
    assert sentinel.read_bytes() == b'preserve existing backup'
    assert list(destination.iterdir()) == [sentinel]
