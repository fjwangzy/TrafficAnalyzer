import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_upgrade", ROOT / "deploy/intranet/upgrade_source.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def seal(directory):
    (directory / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(directory).as_posix()}\n"
        for path in sorted(directory.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"))


def package(directory, version="fixture.1"):
    app = directory / "app"
    (app / "platform/alembic/versions").mkdir(parents=True)
    (app / "platform/alembic_replay_v2/versions").mkdir(parents=True)
    (app / "platform/alembic/versions/base.py").write_text("revision='base'\n")
    (app / "platform/alembic_replay_v2/versions/base.py").write_text("revision='replay'\n")
    (app / "main_optimized.py").write_text("print('fixture')\n")
    (directory / "upgrade_source.py").write_text("# fixture\n")
    (directory / "source-compose.yaml").write_text("services: {}\n")
    baseline = {p.relative_to(app).as_posix(): upgrade.digest(p) for p in app.rglob("*.py") if "versions" in p.parts}
    (directory / "APP_RELEASE.json").write_text(json.dumps({
        "kind": "app-source", "platform": "linux/arm64", "version": version, "runtime_baseline": baseline,
        "images": {name: {"reference": name + ":fixture", "id": "sha256:fixture"} for name in ("platform", "console")},
    }))
    seal(directory)
    return directory


def deployment(directory, current=None):
    instance = upgrade.Deployment.__new__(upgrade.Deployment)
    instance.root = directory
    instance.directory = directory / "app"
    instance.directory.mkdir()
    instance.state_path = instance.directory / "state.json"
    instance.state = {"current": str(current)} if current else {}
    instance.base_files = [str(directory / "original-compose.yaml")]
    instance.logger = logging.getLogger("source-upgrade-test")
    instance.compatible = lambda directory: upgrade.verify_package(directory)
    instance.secrets = ["private-password"]
    return instance


def test_source_package_rejects_tampering_unlisted_secrets_and_added_migration(tmp_path):
    candidate = package(tmp_path / "candidate")
    assert upgrade.verify_package(candidate)["version"] == "fixture.1"
    (candidate / "app/main_optimized.py").write_text("changed\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        upgrade.verify_package(candidate)
    seal(candidate)
    (candidate / ".env").write_text("private-password")
    with pytest.raises(ValueError, match="unlisted"):
        upgrade.verify_package(candidate)
    (candidate / ".env").unlink()
    (candidate / "app/platform/alembic/versions/new.py").write_text("revision='new'\n")
    seal(candidate)
    with pytest.raises(ValueError, match="Migration file set"):
        upgrade.verify_package(candidate)


def test_source_package_rejects_changed_existing_migration_and_links(tmp_path):
    candidate = package(tmp_path / "candidate")
    (candidate / "app/platform/alembic/versions/base.py").write_text("revision='changed'\n")
    seal(candidate)
    with pytest.raises(ValueError, match="dependency or migration changed"):
        upgrade.verify_package(candidate)
    (candidate / "app/main_optimized.py").unlink()
    (candidate / "app/main_optimized.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError):
        upgrade.verify_package(candidate)


def test_stage_is_repeatable_normalizes_private_umask_and_only_checks_schema(tmp_path):
    candidate = package(tmp_path / "candidate")
    instance = deployment(tmp_path)
    calls = []
    instance.run = lambda command, release=None: calls.append((command, release))
    original_umask = os.umask(0o077)
    try:
        staged = instance.stage(candidate)
    finally:
        os.umask(original_umask)
    assert (staged / "app").stat().st_mode & 0o777 == 0o755
    assert (staged / "app/main_optimized.py").stat().st_mode & 0o777 == 0o644
    assert instance.stage(candidate) == staged
    assert all("source_check.py" in " ".join(command) and "--database" in command for command, _ in calls)
    assert all("init_db.py" not in " ".join(command) and "runtime_check.py" not in " ".join(command) for command, _ in calls)
    assert not instance.state_path.exists()


def test_failed_preflight_occurs_after_stop_and_restores_previous_code(tmp_path):
    old = package(tmp_path / "old", "old")
    new = package(tmp_path / "new", "new")
    instance = deployment(tmp_path, old)
    calls = []

    def run(command, release=None):
        calls.append((command, release))
        if "runtime_check.py" in " ".join(command):
            raise RuntimeError("fixture preflight failed")

    instance.run = run
    with pytest.raises(RuntimeError, match="fixture preflight failed"):
        instance.switch(new)
    assert calls[0][0][0] == "stop" and calls[0][1] == old
    assert "runtime_check.py" in " ".join(calls[1][0]) and calls[1][1] == new
    assert calls[-1][0][0] == "up" and calls[-1][1] == old
    assert instance.state["current"] == str(old)
    assert not instance.state_path.exists()


def test_switch_and_image_mode_rollback_do_not_run_migrations_or_change_env(tmp_path):
    new = package(tmp_path / "new")
    instance = deployment(tmp_path)
    env = tmp_path / ".env"
    env.write_text("PASSWORD=fixture\n")
    env.chmod(0o600)
    calls = []
    instance.run = lambda command, release=None: calls.append((command, release))
    instance.switch(new)
    assert instance.state["previous"] is None
    assert (instance.directory / "current").resolve() == new
    assert (tmp_path / "app-compose").stat().st_mode & 0o777 == 0o755
    instance.switch(new)
    assert instance.state["previous"] is None
    instance.switch(None)
    assert not (instance.directory / "current").exists()
    assert instance.state["previous"] == str(new)
    assert env.read_text() == "PASSWORD=fixture\n" and env.stat().st_mode & 0o777 == 0o600
    assert not any("init_db.py" in " ".join(command) for command, _ in calls)
    assert all("--no-deps" in command for command, _ in calls if command[0] == "up")
    assert '"$root/app/upgrade_source.py"' in (tmp_path / "app-compose").read_text()
    assert (instance.directory / "upgrade_source.py").exists()


def test_host_upgrade_output_redacts_dsn_fields_and_actual_env_values():
    value = 'postgresql://sysdba:db-secret@db/ycx password=private-password JWT_SECRET_KEY=other-secret plain-private-password Authorization: Bearer bearer-secret password="quoted spaced secret"'
    rendered = upgrade.redact_log_text(value, ("private-password", "other-secret"))
    assert "db-secret" not in rendered and "private-password" not in rendered and "other-secret" not in rendered
    assert "bearer-secret" not in rendered and "quoted spaced secret" not in rendered


def test_failed_start_collects_image_entrypoint_logs_before_propagating(tmp_path):
    instance = deployment(tmp_path)
    calls = []

    def operation(arguments, release=None):
        calls.append(arguments)
        if arguments[0] == "up":
            raise RuntimeError("startup failed")

    instance.run = operation
    with pytest.raises(RuntimeError, match="startup failed"):
        instance.start(None)
    assert calls[-1] == ["logs", "--no-color", "--tail", "200", "platform", "console2"]


@pytest.mark.parametrize("command,code,event", [
    ([sys.executable, "-c", "print('password=fixture-secret'); raise SystemExit(7)"], 7, "CONTAINER_EXIT"),
    (["/nonexistent/fixture-program"], 1, "CONTAINER_LAUNCH_FAILED"),
])
def test_container_wrapper_persists_stdout_errors_exit_and_redacts(tmp_path, command, code, event):
    result = subprocess.run([sys.executable, str(ROOT / "deploy/intranet/run_logged.py"), "preflight", *command],
                            env={**os.environ, "PYTHONPATH": str(ROOT), "TRAFFIC_LOG_DIR": str(tmp_path)},
                            text=True, capture_output=True)
    logfile = tmp_path / "containers/preflight.log"
    assert result.returncode == code
    assert "CONTAINER_START" in result.stdout and event in result.stdout
    assert event in logfile.read_text() and "pid=" in logfile.read_text() and "INFO" in logfile.read_text()
    assert "fixture-secret" not in result.stdout + result.stderr + logfile.read_text()
    assert logfile.stat().st_mode & 0o777 == 0o600


def test_source_overlay_resets_old_mounts_and_keeps_app_and_init_same_version(tmp_path):
    if not shutil_which_docker():
        pytest.skip("Docker Compose is unavailable")
    base = tmp_path / "compose.yaml"
    base.write_text("""services:
  platform:
    image: fixture
    volumes: ["./old.py:/app/platform/app/main.py:ro"]
  init-db:
    image: fixture
    volumes: ["./old-init.py:/app/deploy/init_db.py:ro"]
  console2:
    image: fixture
    volumes: ["./old-html:/usr/share/nginx/html"]
""")
    result = subprocess.run(["docker", "compose", "-f", str(base), "-f", str(ROOT / "deploy/intranet/source-compose.yaml"),
                             "config", "--format", "json"], capture_output=True, text=True,
                            env={**os.environ, "APP_ROOT": str(tmp_path / "source 中文"), "ASSET_ROOT": str(tmp_path / "assets"),
                                 "DATA_ROOT": str(tmp_path / "data"), "APP_PLATFORM_IMAGE": "platform:fixture",
                                 "APP_CONSOLE_IMAGE": "console:fixture"})
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for service in ("platform", "init-db"):
        source = next(mount for mount in services[service]["volumes"] if mount["target"] == "/app")
        assert source["read_only"] and source["source"].endswith("source 中文")
        assert services[service]["logging"]["options"] == {"max-size": "20m", "max-file": "6"}
        assert not any(Path(mount["source"]).name.startswith("old") for mount in services[service]["volumes"])
    assert len(services["console2"]["volumes"]) == 5
    assert all(m["read_only"] for m in services["console2"]["volumes"] if m["target"].startswith("/opt/"))


def shutil_which_docker():
    import shutil
    return shutil.which("docker")
