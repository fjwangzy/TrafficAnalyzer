"""Install the offline source overlay in a deployment directory, preserving settings."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import io
import zipfile


OVERLAY_FILES = {
    'config.py': '/app/platform/app/core/config.py',
    'highgo_dialect.py': '/app/platform/app/core/highgo_dialect.py',
    'runtime_check.py': '/app/deploy/runtime_check.py',
    'deployment_diagnostics.py': '/app/platform/app/core/deployment_diagnostics.py',
    'database.py': '/app/platform/app/core/database.py',
    'init_db.py': '/app/deploy/init_db.py',
    'ycx_connection.py': '/app/platform/app/core/ycx_connection.py',
    'doris_connection.py': '/app/platform/app/core/doris_connection.py',
    'timeseries.py': '/app/platform/app/core/timeseries.py',
    'dashboard_situation.py': '/app/platform/app/services/dashboard_situation.py',
    'ycx_road_import.py': '/app/platform/app/services/ycx_road_import.py',
    'replay_v2_metric_store.py': '/app/platform/app/services/replay_v2_metric_store.py',
    'api_dashboard.py': '/app/platform/app/api/v1/dashboard.py',
    'api_calibration.py': '/app/platform/app/api/v1/calibration.py',
    'main.py': '/app/platform/app/main.py',
    'migration_timeseries.py': '/app/platform/alembic/versions/20260715_0004_timeseries_metric_store.py',
    'migration_v2_timeseries.py': '/app/platform/alembic_replay_v2/versions/20260804_rv2_0002_metric_sample_timescale.py',
    'pipeline_manager.py': '/app/platform/app/services/pipeline_manager.py',
    'runtime_map.py': '/app/utils_local/runtime_map.py',
    'main_optimized.py': '/app/main_optimized.py',
    'pymysql.zip': '/app/vendor/pymysql.zip',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(path, content):
    fd, temporary = tempfile.mkstemp(prefix=".highgo-patch-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(root, payload):
    checks_path = root / "SHA256SUMS"
    checks = {}
    for line in checks_path.read_text().splitlines():
        checksum, name = line.split(maxsplit=1)
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or name in checks
                or not (root / path).resolve().is_relative_to(root.resolve())):
            raise RuntimeError("Invalid deployment checksum list")
        checks[name] = checksum
        if name != "images/runtime.tar" and digest(root / name) != checksum:
            raise RuntimeError(f"Deployment checksum mismatch: {name}")
    compose_path = root / "docker-compose.yaml"
    if "docker-compose.yaml" not in checks:
        raise RuntimeError("Missing deployment Compose checksum")
    model = json.loads(compose_path.read_text())
    destination = root / "deploy/intranet/highgo-version-hotfix"
    if not destination.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Overlay directory resolves outside the deployment")
    files = OVERLAY_FILES
    def content(name):
        return base64.b64decode((payload / (name + ".b64")).read_text(), validate=True) if name == "pymysql.zip" else (payload / name).read_bytes()
    for service_name in ("platform", "init-db"):
        service = model["services"][service_name]
        environment = service.setdefault("environment", {})
        defaults = {"ROAD_FEATURES_ENABLED": "false", "DB_TIMESCALE_REQUIRED": "false", "YCX_METRICS_BACKEND": "doris", "YCX_ROAD_VERSION": "",
                    "DORIS_MYSQL_HOST": "", "DORIS_MYSQL_PORT": "9030", "DORIS_MYSQL_USER": "",
                    "DORIS_MYSQL_PASSWORD": "", "DORIS_DATABASE": "ycx_xc"}
        for key, value in defaults.items():
            environment[key] = "${" + key + ":-" + value + "}"
        environment["PYTHONPATH"] = "/app/vendor/pymysql.zip:/app/platform:/app"
        volumes = service.setdefault("volumes", [])
        for name, target in files.items():
            source = f"./deploy/intranet/highgo-version-hotfix/{name}"
            mount = {"type": "bind", "source": source, "target": target, "read_only": True,
                     "bind": {"create_host_path": False}}
            existing = [v for v in volumes if (v.get("target") if isinstance(v, dict) else v.split(":")[1]) == target]
            if existing and existing != [mount]:
                raise RuntimeError(f"Existing custom mount conflicts: {target}")
            if not existing:
                volumes.append(mount)
    for name in files:
        target = destination / name
        if target.exists() and target.read_bytes() != content(name):
            if target.relative_to(root).as_posix() not in checks:
                raise RuntimeError(f"Untracked existing overlay differs: {name}")
    backup = root / ".highgo-version-hotfix-backup"
    if not backup.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Backup directory resolves outside the deployment")
    if not backup.exists():
        backup.mkdir(mode=0o700)
        shutil.copy2(compose_path, backup / "docker-compose.yaml")
        shutil.copy2(checks_path, backup / "SHA256SUMS")
    source_backup = backup / "sources-before-schema-fix"
    for name in files:
        target = destination / name
        if target.exists() and target.read_bytes() != content(name):
            source_backup.mkdir(mode=0o700, exist_ok=True)
            if not (source_backup / name).exists():
                shutil.copy2(target, source_backup / name)
    destination.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = destination / name
        replace(target, content(name))
        checks[target.relative_to(root).as_posix()] = digest(target)
    # The existing Console image serves these rebuilt assets; no onsite rebuild/pull.
    static_payload = payload / "console-static.zip.b64"
    if static_payload.is_file():
        console_root = root / "deploy/intranet/console-hotfix"
        console_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(static_payload.read_text(), validate=True))) as archive:
            for entry in archive.infolist():
                relative = Path(entry.filename)
                target = console_root / relative
                if relative.is_absolute() or ".." in relative.parts or not target.resolve().is_relative_to(console_root.resolve()) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError("Invalid Console static payload path")
                if entry.is_dir():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.read_bytes() != archive.read(entry) and target.relative_to(root).as_posix() not in checks:
                    raise RuntimeError("Untracked Console static file conflicts with repair")
                replace(target, archive.read(entry))
                checks[target.relative_to(root).as_posix()] = digest(target)
        console = model["services"]["console2"]
        console.setdefault("environment", {})["ROAD_FEATURES_ENABLED"] = "${ROAD_FEATURES_ENABLED:-false}"
        for source, target, readonly in (
            ("./deploy/intranet/console-hotfix", "/usr/share/nginx/html", False),
            ("./deploy/intranet/highgo-version-hotfix/console-entrypoint.sh", "/docker-entrypoint.d/40-amap-runtime-config.sh", True),
        ):
            volumes = console.setdefault("volumes", [])
            mount = {"type": "bind", "source": source, "target": target, "read_only": readonly, "bind": {"create_host_path": False}}
            existing = [value for value in volumes if (value.get("target") if isinstance(value, dict) else value.split(":")[1]) == target]
            if existing and existing != [mount]:
                raise RuntimeError("Custom Console mount conflicts with repair")
            if not existing:
                volumes.append(mount)
        entrypoint = destination / "console-entrypoint.sh"
        replace(entrypoint, (payload / "console-entrypoint.sh").read_bytes())
        entrypoint.chmod(0o755)
        checks[entrypoint.relative_to(root).as_posix()] = digest(entrypoint)
    compose_content = (json.dumps(model, ensure_ascii=False, indent=2) + "\n").encode()
    checks["docker-compose.yaml"] = hashlib.sha256(compose_content).hexdigest()
    before_compose, before_checks = compose_path.read_bytes(), checks_path.read_bytes()
    try:
        replace(compose_path, compose_content)
        replace(checks_path, "".join(f"{value}  {key}\n" for key, value in checks.items()).encode())
    except BaseException:
        replace(compose_path, before_compose)
        replace(checks_path, before_checks)
        raise
    defaults_file = payload / "site-defaults.env"
    if defaults_file.is_file():
        environment_file = root / ".env"
        original = environment_file.read_text()
        existing = {line.split("=", 1)[0].strip() for line in original.splitlines() if "=" in line and not line.lstrip().startswith("#")}
        additions = []
        updated = original
        allowed = {"ROAD_FEATURES_ENABLED", "DB_TIMESCALE_REQUIRED", "YCX_METRICS_BACKEND", "YCX_ROAD_VERSION", "DORIS_MYSQL_HOST", "DORIS_MYSQL_PORT", "DORIS_MYSQL_USER", "DORIS_MYSQL_PASSWORD", "DORIS_DATABASE"}
        for line in defaults_file.read_text().splitlines():
            key = line.split("=", 1)[0]
            if key not in allowed or "=" not in line:
                raise RuntimeError("Invalid optional dependency default")
            if key in {"ROAD_FEATURES_ENABLED", "DB_TIMESCALE_REQUIRED", "YCX_METRICS_BACKEND"}:
                updated, count = re.subn(r"^(?:export\s+)?" + key + r"\s*=.*$", lambda _: line, updated, flags=re.M)
                if count:
                    continue
            if key not in existing:
                additions.append(line)
                existing.add(key)
        if additions or updated != original:
            backup_env = backup / "environment-before-optional-dependencies.env"
            if not backup_env.exists():
                shutil.copy2(environment_file, backup_env)
                backup_env.chmod(0o600)
            content = updated + ("\n# Optional external dependencies\n" + "\n".join(additions) + "\n" if additions else "")
            replace(environment_file, content.encode())
            environment_file.chmod(0o600)
        print("Production feature flags updated; existing connection credentials and asset paths retained.")
    print("HighGo version hotfix applied; .env and persistent data preserved.")


if __name__ == "__main__":
    apply(Path("/release"), Path("/patch"))
