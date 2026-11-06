#!/usr/bin/env python3
"""Build and package pinned ARM64 images; source archives are explicitly separate."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def run(*arguments, capture=False):
    return subprocess.run(arguments, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect_image(name):
    item = json.loads(run("docker", "image", "inspect", name, capture=True))[0]
    if item["Architecture"] != "arm64" or item["Os"] != "linux":
        raise ValueError(f"Image must be linux/arm64: {name}")
    return {"reference": name, "id": item["Id"], "architecture": item["Architecture"],
            "repo_digests": item.get("RepoDigests", [])}


def validate_driver(directory):
    directory = Path(directory)
    if not (directory / "libpq.so.5").is_file():
        raise ValueError("Missing aarch64 HighGo libpq.so.5")
    files = {}
    for library in sorted(directory.iterdir()):
        if not library.is_file() or ".so" not in library.name or library.name.startswith("_psycopg"):
            continue
        with library.open("rb") as stream:
            header = stream.read(20)
        if header[:4] != b"\x7fELF" or header[5] != 1 or int.from_bytes(header[18:20], "little") != 183:
            raise ValueError(f"Non-aarch64 library: {library.name}")
        files[library.name] = digest(library)
    return files


def pinned_reference(value):
    if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", value):
        raise ValueError("All base images must include an immutable @sha256 digest")
    return value


def ensure_base_image(reference):
    try:
        inspect_image(reference)
    except subprocess.CalledProcessError:
        run("docker", "pull", "--platform", "linux/arm64", reference)
        inspect_image(reference)


def require_builder_space(nginx_reference):
    ensure_base_image(nginx_reference)
    output = run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none",
                 nginx_reference, "df", "-Pk", "/", capture=True)
    free_kib = int(output.splitlines()[-1].split()[3])
    if free_kib < 60 * 1024 * 1024:
        raise ValueError("Docker build storage needs at least 60 GiB free; expand Docker Desktop storage without deleting existing volumes")


def copy_delivery_files(target):
    files = [ROOT / "docker-compose.yaml", ROOT / "docs/DEPLOYMENT_INTRANET.md", ROOT / "docs/RELEASE_PACKAGING_GUIDE.md",
             ROOT / "docs/DEPLOYMENT_INTRANET_VALIDATION.md", ROOT / "docs/DORIS_INTEGRATION_VALIDATION_20261017.md",
             ROOT / "deploy/highgo-reference/ARM64_SOURCE.json"]
    files.extend(ROOT / "deploy/intranet" / name for name in (
        "Dockerfile", "base-images.json", "compose.yaml", "compose.postgres.yaml",
        "database/Dockerfile", "database/init-extensions.sh", "database/base-image.json", "backup-db.sh", "HIGHGO_CUTOVER.md", "production.env.example", "CHECK_TOOLS.md", "db_readonly_checks.sql",
        "runtime_check.py", "diagnose_live.py", "init_db.py", "init_kafka.py", "deploy.py", "topic_acl.py", "compose-bootstrap.sh", "docker-compose",
        "hotfix-compose-environment.sh",
        "hotfix-highgo-version.py", "hotfix-highgo-version.sh",
        "repair-highgo.sh.in",
        "seed_sources.py", "test-sources.json", "VIDEO_FILES.txt", "VIDEO_SHA256SUMS", "TEST_SOURCE_TOPIC_ACL.json",
    ))
    for source in files:
        destination = target / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def dotenv_value(value):
    value = str(value)
    if any(char in value for char in "\n\r\0"):
        raise ValueError("Deployment environment values must be single-line")
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def render_deployment_compose(target, *, bundled_database=False, app_source=False):
    """Resolve the maintained root+overlay, then restore .env substitutions."""
    files = (ROOT / "docker-compose.yaml", ROOT / "deploy/intranet/compose.yaml")
    if bundled_database:
        files += (ROOT / "deploy/intranet/compose.postgres.yaml",)
    if app_source:
        files += (ROOT / "deploy/intranet/source-compose.yaml",)
    names = sorted(set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", "\n".join(p.read_text() for p in files))))
    fake = {name: f"__TA_ENV_{name}__" for name in names}
    for name in ("ASSET_ROOT", "DATA_ROOT", "ASCEND_DAVINCI_DEVICE", "APP_ROOT"):
        if name in fake:
            fake[name] = "/" + fake[name]
    for index, name in enumerate(sorted(n for n in names if n.endswith("_PORT"))):
        fake[name] = str(58000 + index)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env") as environment:
        environment.write("".join(f"{name}={dotenv_value(value)}\n" for name, value in fake.items()))
        environment.flush()
        result = run("docker", "compose", "-p", "ta_release_render", "--env-file", environment.name,
                     *(arg for path in files for arg in ("-f", str(path))), "config", "--format", "json",
                     "--no-path-resolution", capture=True)
    model = json.loads(result)
    model.pop("name", None)
    model.pop("volumes", None)
    model["services"] = {name: model["services"][name] for name in (("road9", "init-db", "platform", "console2") if bundled_database else ("init-db", "platform", "console2"))}
    for network in model.get("networks", {}).values():
        network.pop("name", None)
    for service in model["services"].values():
        service.pop("build", None)
        # Older Compose V2 accepts device mappings only in short string syntax.
        if "devices" in service:
            service["devices"] = [
                f"{device['source']}:{device['target']}:{device.get('permissions', 'rwm')}"
                if isinstance(device, dict) else device
                for device in service["devices"]
            ]
        for mount in service.get("volumes", []):
            if mount.get("read_only"):
                mount.setdefault("bind", {})["create_host_path"] = False

    def restore(value):
        if isinstance(value, dict):
            return {key: restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [restore(item) for item in value]
        if isinstance(value, str):
            for name, sentinel in sorted(fake.items(), key=lambda item: -len(item[1])):
                # The private .env may omit this inherited numeric setting.
                expression = "${PIPELINE_IMGSZ:-960}" if name == "PIPELINE_IMGSZ" else "${" + name + "}"
                value = value.replace(sentinel, expression)
        return value

    model = restore(model)
    (target / "docker-compose.yaml").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    shutil.copy2(ROOT / "deploy/intranet/docker-compose", target / "docker-compose")
    (target / "docker-compose").chmod(0o755)
    return model


def configure_deployment(target, record, environment_file):
    environment = target / ".env"
    shutil.copy2(environment_file, environment)
    environment.chmod(0o600)
    content = environment.read_text()
    image_fields = [("PLATFORM_IMAGE", "platform"), ("CONSOLE_IMAGE", "console")]
    if "database" in record["images"]:
        image_fields.append(("DATABASE_IMAGE", "database"))
    if record.get("application_source"):
        image_fields.extend((("APP_PLATFORM_IMAGE", "platform"), ("APP_CONSOLE_IMAGE", "console")))
        content = re.sub(r"^APP_ROOT=.*\n?", "", content, flags=re.M)
        content += '\nAPP_ROOT="./application/app"\n'
    for name, service in image_fields:
        value = dotenv_value(record["images"][service]["reference"])
        content, count = re.subn(rf"^{name}=.*$", lambda _: f"{name}={value}", content, flags=re.M)
        if not count:
            content += f"\n{name}={value}\n"
    environment.write_text(content)
    result = subprocess.run(["docker", "compose", "-p", "ta_release_validate", "--env-file", str(environment),
                             "-f", str(target / "docker-compose.yaml"), "config", "--format", "json"],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError("Private deployment .env cannot be parsed; check required configuration fields")
    services = json.loads(result.stdout)["services"]
    settings = services["platform"]["environment"]
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_SCHEMA", "DB_USER", "DB_PASSWORD", "JWT_SECRET_KEY",
                "BOOTSTRAP_ADMIN_PASSWORD", "KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD",
                "DORIS_MYSQL_HOST", "DORIS_MYSQL_USER", "DORIS_MYSQL_PASSWORD", "DORIS_DATABASE")
    missing = [name for name in required if not settings.get(name) or "REPLACE_" in settings[name]]
    if missing:
        raise ValueError("Private deployment .env is incomplete: " + ", ".join(missing))
    if not services["console2"]["environment"].get("MINEMAP_KEY"):
        raise ValueError("Private deployment .env requires MINEMAP_KEY")
    if settings["DB_NAME"] == "road9" or settings["DB_SCHEMA"] in {"public", "pg_catalog", "information_schema"}:
        raise ValueError("Production deployment must target an explicitly configured external application database and private schema")
    return environment


def seal_archive(directory, archive, mutable=()):
    checksums = [f"{digest(p)}  {p.relative_to(directory).as_posix()}" for p in sorted(directory.rglob('*'))
                 if p.is_file() and p.relative_to(directory).as_posix() not in mutable]
    (directory / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    temporary = archive.with_suffix(archive.suffix + ".tmp")
    temporary.touch(mode=0o600, exist_ok=False)
    with tarfile.open(temporary, "w:gz", compresslevel=3) as stream:
        stream.add(directory, arcname=directory.name)
    temporary.replace(archive)
    archive.with_name(archive.name + ".sha256").write_text(f"{digest(archive)}  {archive.name}\n")


def build(args):
    if (args.output / f"build-{args.version}.json").exists():
        raise FileExistsError("This release is already built; package it or use a new version")
    driver = validate_driver(args.highgo_driver)
    locked = json.loads((ROOT / "deploy/intranet/base-images.json").read_text())
    bases = {key: pinned_reference(getattr(args, key) or locked[key]) for key in ("cann_base", "node_base", "nginx_base")}
    if "9.0.0-310p-ubuntu22.04-py3.11" not in bases["cann_base"]:
        raise ValueError("Use the CANN 9.0.0 / 310P / Ubuntu 22.04 / Python 3.11 base")
    require_builder_space(bases["nginx_base"])
    staged = ROOT / "deploy/intranet/highgo-driver/arm64"
    staged.mkdir(parents=True, exist_ok=True)
    # Do not retain stale libraries from an earlier vendor release.
    if staged.resolve() != args.highgo_driver.resolve() and any(staged.iterdir()):
        if validate_driver(staged) != driver:
            raise ValueError("Staged HighGo libraries differ from the selected vendor release")
    for name in driver:
        if staged.resolve() != args.highgo_driver.resolve():
            shutil.copy2(args.highgo_driver / name, staged / name)
    images = {service: f"traffic-analyzer-{service}:{args.version}-arm64" for service in ("platform", "console")}
    images["model_converter"] = f"traffic-analyzer-model-converter:{args.version}-arm64"
    for reference in bases.values():
        ensure_base_image(reference)
    run("docker", "build", "--platform", "linux/arm64", "-f", "deploy/intranet/Dockerfile",
        "--build-arg", f"CANN_BASE_IMAGE={bases['cann_base']}", "-t", images["platform"], ".")
    run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none", images["platform"],
        "python3", "/app/deploy/runtime_check.py", "--libraries-only")
    run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none", images["platform"], "python3", "-c",
        "from app.main import app; from nodes.DetectionNode import DetectionNode; "
        "from ultralytics.utils.nms import non_max_suppression; "
        "from app.core.database import _alembic_head, _replay_v2_alembic_head; "
        "assert _alembic_head() and _replay_v2_alembic_head(); "
        "print('Platform and detector imports passed; routes:', len(app.routes))")
    run("docker", "build", "--platform", "linux/arm64", "--target", "model-converter",
        "--build-arg", f"CANN_BASE_IMAGE={bases['cann_base']}", "-f", "deploy/intranet/Dockerfile",
        "-t", images["model_converter"], ".")
    run("docker", "build", "--platform", "linux/arm64", "--build-arg", f"NODE_IMAGE={bases['node_base']}",
        "--build-arg", f"NGINX_IMAGE={bases['nginx_base']}", "-t", images["console"], "console2")
    if getattr(args, "bundled_database", False):
        database = json.loads((ROOT / "deploy/intranet/database/base-image.json").read_text())
        reference = pinned_reference(database["reference"])
        ensure_base_image(reference)
        images["database"] = f"traffic-analyzer-database:{args.version}-arm64"
        run("docker", "build", "--platform", "linux/arm64", "-f", "deploy/intranet/database/Dockerfile",
            "--build-arg", f"DATABASE_BASE_IMAGE={reference}", "-t", images["database"], ".")
        run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none", "--entrypoint", "sh",
            images["database"], "-c", "test -f /usr/local/share/postgresql/extension/postgis.control && test -f /usr/local/share/postgresql/extension/timescaledb.control && postgres --version")
    record = {"version": args.version, "database_mode": "bundled_postgresql" if "database" in images else "external_highgo", "bases": bases, "driver_sha256": driver,
              "validation_status": "passed",
              "images": {key: inspect_image(value) for key, value in images.items()},
              "git_commit": run("git", "rev-parse", "HEAD", capture=True).strip(),
              "workspace_dirty": bool(run("git", "status", "--porcelain", capture=True).strip())}
    (args.output / f"build-{args.version}.json").write_text(json.dumps(record, indent=2) + "\n")


def package(args):
    from utils_local.ascend_model_manifest import load_manifest
    manifest = load_manifest(args.model_manifest)[0] if args.model_manifest else None
    environment_file = getattr(args, "deployment_env", None)
    resource_archive = getattr(args, "model_resource_archive", None)
    if environment_file and not manifest:
        raise ValueError("Configured one-command deployment requires a separate model manifest")
    record = json.loads((args.output / f"build-{args.version}.json").read_text())
    if record.get("validation_status") != "passed":
        raise ValueError("Release images must pass library and application-import checks before packaging")
    record["images"]["model_converter"] = inspect_image(f"traffic-analyzer-model-converter:{args.version}-arm64")
    for item in record["images"].values():
        if inspect_image(item["reference"])["id"] != item["id"]:
            raise ValueError("A release image changed after build")
    archive = args.output / f"traffic-analyzer-{args.version}-linux-arm64.tar.gz"
    if archive.exists():
        raise FileExistsError(archive)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        delivery = Path(temporary) / archive.name.removesuffix(".tar.gz")
        delivery.mkdir()
        copy_delivery_files(delivery)
        bundled = "database" in record["images"]
        app_source = getattr(args, "app_source", None)
        if app_source:
            from deploy.intranet.upgrade_source import verify_package
            application = verify_package(app_source)
            if application["version"] != args.version or application["images"] != {key: record["images"][key] for key in ("platform", "console")}:
                raise ValueError("Application source version/images must match the full release")
            shutil.copytree(app_source, delivery / "application")
            record["application_source"] = "application"
        render_deployment_compose(delivery, bundled_database=bundled, app_source=bool(app_source))
        if environment_file:
            configure_deployment(delivery, record, environment_file.resolve(strict=True))
        mutable = [".env"]
        if bundled:
            if not getattr(args, "highgo_env", None):
                raise ValueError("Bundled PostgreSQL release requires the retained HighGo environment")
            with tempfile.TemporaryDirectory() as highgo_temporary:
                highgo_dir = Path(highgo_temporary)
                render_deployment_compose(highgo_dir)
                configure_deployment(highgo_dir, record, args.highgo_env.resolve(strict=True))
                shutil.copy2(highgo_dir / "docker-compose.yaml", delivery / "docker-compose.hg.yaml")
                shutil.copy2(highgo_dir / ".env", delivery / ".env.hg")
            mutable.append(".env.hg")
        (delivery / "images").mkdir()
        run("docker", "save", "-o", str(delivery / "images/runtime.tar"),
            *(item["reference"] for item in record["images"].values()))
        if manifest:
            requirements = {"source_sha256": manifest["source_sha256"], "names": manifest["names"], "state": "prepared_separately"}
        else:
            weights = (args.weights or ROOT / "weights/yolo11s-visdrone.pt").resolve(strict=True)
            metadata = run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none",
                           "--memory", "1g", "--cpus", "1", "--mount", f"type=bind,source={weights},target=/weights/source.pt,readonly",
                           record["images"]["platform"]["reference"], "python3", "-c",
                           "import json; from ultralytics import YOLO; print('MODEL_NAMES_JSON='+json.dumps(YOLO('/weights/source.pt').names))", capture=True)
            names = json.loads(next(line.partition("=")[2] for line in metadata.splitlines() if line.startswith("MODEL_NAMES_JSON=")))
            requirements = {"source_sha256": digest(weights), "names": names, "state": "requires_conversion"}
        requirements.update({"schema_version": "uav.resource-requirements/v1", "cann_version": "9.0.0",
                             "soc_version": "Ascend310P3", "sizes": [640, 960, 1280],
                             "weights_path": "weights/yolo11s-visdrone.pt", "manifest_path": "weights/ascend/manifest.json"})
        record.update({"kind": "offline-images", "site_acceptance": "not_evaluated", "model_manifest": manifest,
                       "resource_status": requirements["state"], "single_compose": True,
                       "contains_private_configuration": bool(environment_file), "mutable_files": mutable})
        (delivery / "RESOURCE_REQUIREMENTS.json").write_text(json.dumps(requirements, ensure_ascii=False, indent=2) + "\n")
        (delivery / "RELEASE.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        dependencies = run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none", "--entrypoint", "cat",
                           record["images"]["platform"]["reference"], "/app/python-dependencies.txt", capture=True)
        (delivery / "PYTHON_DEPENDENCIES.txt").write_text(dependencies)
        os_dependencies = run("docker", "run", "--rm", "--platform", "linux/arm64", "--network", "none", "--entrypoint", "cat",
                              record["images"]["platform"]["reference"], "/app/os-dependencies.txt", capture=True)
        (delivery / "OS_DEPENDENCIES.txt").write_text(os_dependencies)
        shutil.copy2(ROOT / "console2/package-lock.json", delivery / "CONSOLE_DEPENDENCIES.json")
        example = delivery / "deploy/intranet/production.env.example"
        content = example.read_text()
        for key, service in (("PLATFORM_IMAGE", "platform"), ("CONSOLE_IMAGE", "console")):
            content = re.sub(rf"^{key}=.*$", f"{key}={record['images'][service]['reference']}", content, flags=re.M)
        example.write_text(content)
        if bundled:
            content = re.sub(r"^DB_HOST=.*$", "DB_HOST=road9", content, flags=re.M)
            content = re.sub(r"^DB_PORT=.*$", "DB_PORT=5432", content, flags=re.M)
            content = re.sub(r"^DB_TIMESCALE_REQUIRED=.*$", "DB_TIMESCALE_REQUIRED=true", content, flags=re.M)
            content += "\nDATABASE_IMAGE=" + record["images"]["database"]["reference"] + "\n"
            example.write_text(content)
        shutil.copy2(example, delivery / ".env.example")
        (delivery / "IMAGES.txt").write_text("".join(f"{item['id']}  {item['reference']}\n" for item in record["images"].values()))
        if manifest:
            checksums = {"weights/" + manifest["source_name"]: manifest["source_sha256"],
                         "weights/ascend/manifest.json": digest(args.model_manifest)}
            checksums.update({"weights/ascend/" + item["path"]: item["sha256"] for item in manifest["models"].values()})
            (delivery / "MODEL_SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in checksums.items()))
        if resource_archive:
            (delivery / "MODEL_ARCHIVE_SHA256SUMS").write_text(f"{digest(resource_archive)}  {resource_archive.name}\n")
        (delivery / "README.md").write_text("""# 内网部署\n\n1. 将独立模型资源包放在本解压目录或其上一级，视频/遥测放入.env中ASSET_ROOT/videos。\n2. 在Linux ARM64/310P3生产主机运行：\n\n```sh\n./docker-compose up -d\n```\n\n入口自动校验/导入离线镜像、导入模型、识别访问IP、检查设备与外部连接，并由Compose先初始化数据库后启动两个常驻服务。系统原生Compose不能从tar自动导入镜像；首次完成后也可直接使用`docker compose up -d`。\n\n所有现场参数及初始admin密码均在根目录.env，权限600；本包含私有连接信息，请按私有配置传输。数据库和schema以根.env的DB_NAME/DB_SCHEMA为准，需DBA预备；TimescaleDB按DB_TIMESCALE_REQUIRED=false为可选，路网/路况从Doris只读；不会自动建库、安装扩展或导入历史数据。\n\n状态：`./docker-compose ps`；日志：`./docker-compose logs --tail 200`；停止：`./docker-compose down`。详情见docs/DEPLOYMENT_INTRANET.md。\n""")
        if bundled:
            readme = delivery / "README.md"
            text = readme.read_text().replace(
                "数据库和schema以根.env的DB_NAME/DB_SCHEMA为准，需DBA预备；TimescaleDB按DB_TIMESCALE_REQUIRED=false为可选，路网/路况从Doris只读；不会自动建库、安装扩展或导入历史数据。",
                "本包先启动同机PostgreSQL并创建应用库/schema，启用PostGIS与TimescaleDB，再预检和初始化应用；数据持久化于DATA_ROOT/postgres，数据库不映射宿主机端口。路网/路况仍从Doris只读。")
            text += "\nHG原连接保存在.env.hg，外部HG拓扑为docker-compose.hg.yaml；切回前必须停止写入、备份并制定数据迁移方案，不能只换连接后丢弃临时库数据。备份工具：sh deploy/intranet/backup-db.sh。\n"
            readme.write_text(text)
        if app_source:
            with (delivery / "README.md").open("a") as stream:
                stream.write("\n本版首次启动即使用application/app宿主只读源码，Platform/init-db共享同版；模型、视频均不在本包内。后续使用app-package源码更新，prepare/apply命令及全量打包步骤见docs/RELEASE_PACKAGING_GUIDE.md。依赖或迁移变化必须重新发布全量包。\n")
        for path in delivery.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
        seal_archive(delivery, archive, mutable=tuple(mutable))
        if environment_file:
            archive.chmod(0o600)
    print(archive)


def models(args):
    locked = json.loads((ROOT / "deploy/intranet/base-images.json").read_text())
    base = pinned_reference(args.cann_base or locked["cann_base"])
    if not args.weights or not args.model_output:
        raise ValueError("models requires --weights and --model-output")
    weights = args.weights.resolve(strict=True)
    output = args.model_output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("Model output must be an empty resource release directory")
    require_builder_space(locked["nginx_base"])
    memory = json.loads(run("docker", "info", "--format", "{{json .MemTotal}}", capture=True))
    if memory < 9 * 1024**3:
        raise ValueError("ATC requires a Docker VM configured with at least 10 GiB RAM; use a dedicated Linux build host or expand memory before conversion")
    image = f"traffic-analyzer-model-converter:{args.version}-arm64"
    run("docker", "build", "--platform", "linux/arm64", "--target", "model-converter",
        "--build-arg", f"CANN_BASE_IMAGE={base}", "-f", "deploy/intranet/Dockerfile", "-t", image, ".")
    container_weights = f"/weights/{weights.name}"
    # Keep model compilation from exhausting the shared development Docker VM.
    run("docker", "run", "--rm", "--network", "none", "--platform", "linux/arm64",
        "--memory", "8g", "--memory-swap", "10g", "--cpus", "2", "--oom-score-adj", "1000",
        "--mount", f"type=bind,source={weights},target={container_weights},readonly",
        "--mount", f"type=bind,source={output},target=/models", image,
        "python3", "/app/scripts/convert_ascend_models.py", "--weights", container_weights, "--output", "/models")
    from utils_local.ascend_model_manifest import load_manifest
    manifest, _ = load_manifest(output / "manifest.json")
    if digest(weights) != manifest["source_sha256"]:
        raise ValueError("Source weights changed during conversion")
    archive = args.output / f"traffic-analyzer-models-{args.version}-ascend310p3.tar.gz"
    if archive.exists():
        raise FileExistsError(archive)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        delivery = Path(temporary) / archive.name.removesuffix(".tar.gz")
        resource_dir = delivery / "weights/ascend"
        resource_dir.mkdir(parents=True)
        shutil.copy2(weights, delivery / "weights" / weights.name)
        shutil.copy2(output / "manifest.json", resource_dir / "manifest.json")
        for item in manifest["models"].values():
            for name in (item["path"], item["onnx_path"]):
                path = (output / name).resolve()
                if not path.is_relative_to(output):
                    raise ValueError("Model resource escapes its release directory")
                shutil.copy2(path, resource_dir / path.name)
        (delivery / "RESOURCE.json").write_text(json.dumps({
            "kind": "model-resources", "version": args.version,
            "cann_version": "9.0.0", "soc_version": "Ascend310P3", "hardware_validation": "not_evaluated",
        }, indent=2) + "\n")
        seal_archive(delivery, archive)
    print(archive)


def source_package(args):
    archive = args.output / f"traffic-analyzer-{args.version}-source.tar.gz"
    if archive.exists():
        raise FileExistsError(archive)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        delivery = Path(temporary) / archive.name.removesuffix(".tar.gz")
        delivery.mkdir()
        copy_delivery_files(delivery)
        for name in ("platform", "nodes", "elements", "byte_tracker", "utils_local", "services", "configs", "console2", "scripts", "test", "deploy/highgo-reference"):
            source = ROOT / name
            destination = delivery / name
            for path in source.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(source)
                if any((part.startswith('.') and part != '.dockerignore') or part in {"node_modules", "dist", "logs", "influxdb_data", "__pycache__", "highgo-driver"} for part in relative.parts):
                    continue
                if name == "configs" and relative != Path("app_config.yaml") and relative.parts[0] != "hydra":
                    continue
                if name == "services" and path.parent != source:
                    continue
                if path.suffix.lower() not in {".py", ".toml", ".ini", ".yaml", ".yml", ".json", ".js", ".jsx", ".mjs", ".cjs", ".css", ".html", ".sh", ".txt", ".md", ".svg", ".png", ".jpg", ".ico", ".woff2", ".conf", ".example"} and ".so" not in path.name and not path.name.startswith(("Dockerfile", ".dockerignore")):
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        for name in ("run_platform.py", "main_optimized.py", "Dockerfile", "Dockerfile.detector", "requirements.txt", ".dockerignore", ".gitignore", "AGENTS.md"):
            shutil.copy2(ROOT / name, delivery / name)
        for source in (ROOT / "docs").glob("*.md"):
            if source.name in {"AGENTS.md", "ARCHITECTURE.md", "BUSINESS_LOGIC.md", "API_CONTRACTS.md", "DATABASE_SCHEMA.md", "DECISIONS.md", "PROJECT_STRUCTURE.md", "TASKS.md"}:
                shutil.copy2(source, delivery / "docs" / source.name)
        (delivery / "RELEASE.json").write_text(json.dumps({
            "version": args.version, "kind": "source-preparation-only", "runnable_offline": False,
            "platform": "linux/arm64",
            "deployment_package": f"traffic-analyzer-{args.version}-linux-arm64.tar.gz",
            "requires": ["aarch64 vendor HighGo libpq and dependencies", "separate application image package",
                         "separate model/video resources", "310P3/site acceptance"],
        }, indent=2) + "\n")
        seal_archive(delivery, archive)
    print(archive)


def image_source_files(image, paths):
    """Read the runtime baseline without executing an application container."""
    container = run("docker", "create", "--entrypoint", "/bin/true", image, capture=True).strip()
    contents = {}
    try:
        for name in paths:
            data = subprocess.check_output(["docker", "cp", f"{container}:/app/{name}", "-"])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for member in archive:
                    relative = Path(name).parent / member.name
                    if member.isfile() and "__pycache__" not in relative.parts and not relative.name.endswith(".pyc"):
                        contents[relative.as_posix()] = archive.extractfile(member).read()
    finally:
        run("docker", "rm", container, capture=True)
    return contents


def copy_app_sources(target):
    # Nested read-only asset/log binds need mountpoints inside the read-only /app.
    for name in ("weights", "test_videos", "logs"):
        (target / name).mkdir()
    for name in ("run_platform.py", "main_optimized.py"):
        shutil.copy2(ROOT / name, target / name)
    directories = ("platform/app", "platform/alembic", "platform/alembic_replay_v2",
                   "nodes", "elements", "byte_tracker", "utils_local", "configs/hydra")
    for name in directories:
        source = ROOT / name
        shutil.copytree(source, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*"))
    for pattern in ("platform/*.ini", "platform/*.toml", "platform/pipeline-*.txt", "services/*.py"):
        for source in ROOT.glob(pattern):
            destination = target / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (target / "configs").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "configs/app_config.yaml", target / "configs/app_config.yaml")
    tools = target / "deploy/intranet"
    tools.mkdir(parents=True)
    for name in ("runtime_check.py", "init_db.py", "init_kafka.py", "seed_sources.py", "test-sources.json", "topic_acl.py",
                 "source_check.py", "run_logged.py", "TEST_SOURCE_TOPIC_ACL.json"):
        shutil.copy2(ROOT / "deploy/intranet" / name, tools / name)


def app_package(args):
    """Ship current application files while keeping runtime dependencies immutable."""
    archive = args.output / f"traffic-analyzer-{args.version}-app-source.tar.gz"
    if archive.exists():
        raise FileExistsError(archive)
    images = {"platform": inspect_image(args.runtime_platform_image), "console": inspect_image(args.runtime_console_image)}
    baseline_files = ("platform/pyproject.toml", "platform/pipeline-requirements.txt", "platform/pipeline-constraints.txt",
                      "platform/alembic.ini", "platform/alembic_replay_v2.ini", "platform/alembic", "platform/alembic_replay_v2")
    baseline = image_source_files(args.runtime_platform_image, baseline_files)
    migrations = {p.relative_to(ROOT).as_posix() for folder in ("platform/alembic", "platform/alembic_replay_v2")
                  for p in (ROOT / folder).rglob("*") if p.is_file()
                  and "__pycache__" not in p.parts and not p.name.endswith(".pyc")}
    if migrations != {name for name in baseline if name.startswith(("platform/alembic/", "platform/alembic_replay_v2/"))}:
        raise ValueError("Migration file set changed; requires a separate schema release")
    for name, content in baseline.items():
        if not (ROOT / name).is_file() or (ROOT / name).read_bytes() != content:
            raise ValueError(f"Runtime dependency/migration baseline changed: {name}; requires a separate runtime/schema release")
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "console2", check=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        delivery = Path(temporary) / archive.name.removesuffix(".tar.gz")
        app = delivery / "app"
        app.mkdir(parents=True)
        copy_app_sources(app)
        for name, content in image_source_files(args.runtime_platform_image, ("python-dependencies.txt", "os-dependencies.txt")).items():
            (app / name).write_bytes(content)
        console = app / "console"
        shutil.copytree(ROOT / "console2/dist", console / "html", ignore=shutil.ignore_patterns(".*"))
        shutil.copy2(ROOT / "console2/public/runtime-config.template.js", console / "html/runtime-config.template.js")
        shutil.copy2(ROOT / "console2/nginx.conf", console / "nginx.conf")
        shutil.copy2(ROOT / "console2/docker-entrypoint.d/40-amap-runtime-config.sh", console / "configure.sh")
        shutil.copy2(ROOT / "deploy/intranet/console-runtime/entrypoint.sh", console / "entrypoint.sh")
        for name in ("upgrade_source.py", "source-compose.yaml"):
            shutil.copy2(ROOT / "deploy/intranet" / name, delivery / name)
        shutil.copy2(ROOT / "docs/RELEASE_PACKAGING_GUIDE.md", delivery / "RELEASE_PACKAGING_GUIDE.md")
        (delivery / "APP_RELEASE.json").write_text(json.dumps({
            "kind": "app-source", "version": args.version, "platform": "linux/arm64", "images": images,
            "runtime_baseline": {name: hashlib.sha256(content).hexdigest() for name, content in baseline.items()},
            "migration_policy": "no changes; read-only installed-head validation; no automatic DDL",
            "site_acceptance": "not_evaluated",
        }, indent=2) + "\n")
        (delivery / "README.md").write_text("""# Application source update\n\nRequires host Python 3.10+, Docker Compose >=2.24.4, existing runtime images/model/video resources and the original private deployment directory. No pip install, image build or download is performed.\n\nFrom this extracted source package:\n\n```sh\npython3 upgrade_source.py --deployment-root /absolute/path/to/existing/deployment prepare\npython3 upgrade_source.py --deployment-root /absolute/path/to/existing/deployment apply\n```\n\nPrepare verifies files, immutable runtime IDs, imports and installed database heads without NPU inference or stopping services. Apply repeats these checks, stops only Platform/Console, runs the full NPU/connection preflight, recreates those two applications and waits for health checks. It does not run migrations or change private .env, database, assets or models. Failure restores the previous application configuration. Run updates during an approved task maintenance window.\n\nUse the generated `./app-compose ps`, `./app-compose logs --tail 200`, `./app-compose up -d` and `./app-compose stop` in the original deployment directory. The old `./docker-compose` remains the unchanged original image launcher.\n\nRollback: `python3 app/upgrade_source.py --deployment-root \"$PWD\" rollback` from the deployment directory. The previous code/resources are retained in app/releases. Host logs are in DATA_ROOT/logs (containers, deployment, pipelines, nginx); each managed stream retains 6 files of up to 20 MiB. Docker logs remain available.\n""")
        for path in delivery.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        delivery.chmod(0o755)
        seal_archive(delivery, archive)
    print(archive)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "package", "source", "models", "app-package"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--highgo-driver", type=Path, default=ROOT / "deploy/intranet/highgo-driver/arm64")
    parser.add_argument("--cann-base", default="")
    parser.add_argument("--node-base", default="")
    parser.add_argument("--nginx-base", default="")
    parser.add_argument("--bundled-database", action="store_true", help="Include the temporary onsite PostgreSQL/PostGIS/TimescaleDB service")
    parser.add_argument("--highgo-env", type=Path, help="Preserve the later HighGo target as private .env.hg")
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--deployment-env", type=Path, help="Explicitly include private configuration as root .env")
    parser.add_argument("--model-resource-archive", type=Path, help="External model archive; record checksum without including its bytes")
    parser.add_argument("--app-source", type=Path, help="Verified extracted app-package directory to mount from the first full deployment")
    parser.add_argument("--runtime-platform-image", default="traffic-analyzer-platform:2026.10.17-intranet.3-arm64")
    parser.add_argument("--runtime-console-image", default="traffic-analyzer-console:2026.10.17-intranet.3-arm64")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.version):
        parser.error("Invalid release version")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    {"build": build, "package": package, "source": source_package, "models": models, "app-package": app_package}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"Release blocked: {exc}", file=sys.stderr)
        sys.exit(1)
