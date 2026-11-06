#!/usr/bin/env python3
"""Read-only dependency probes; temporary output write tests remove their own files."""
import argparse
import asyncio
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

for candidate in Path(__file__).resolve().parents:
    if (candidate / "platform/app").is_dir():
        sys.path[:0] = [str(candidate), str(candidate / "platform")]
        break

from app.core.deployment_diagnostics import DiagnosticError, Report, explain as explain  # noqa: E402 - private app path set above

_step = "initialization"


def progress(step):
    global _step
    _step = step
    print(f"Preflight: {step}", file=sys.stderr, flush=True)


def report_failure(exc):
    report = Report()
    report.error(_step, exc)
    report.emit()


def require(condition, code, title, action, facts=None):
    if not condition:
        raise DiagnosticError(code, title, action, facts)


def check_libraries():
    require(platform.machine() in {"aarch64", "arm64"} and sys.platform == "linux",
            "IMAGE_ARCH", "生产镜像系统或架构不匹配", "使用Linux ARM64版本，Mac继续原生MPS启动。",
            {"architecture": platform.machine(), "system": sys.platform})
    directory = Path(os.environ.get("HIGHGO_LIBRARY_DIR", "/opt/highgo/lib")).resolve()
    require((directory / "libpq.so.5").is_file(), "HIGHGO_LIB_MISSING", "厂商国密libpq缺失", "使用完整ARM64离线镜像。")
    for library in directory.iterdir():
        if not library.is_file() or ".so" not in library.name:
            continue
        with library.open("rb") as stream:
            header = stream.read(20)
        require(header[:4] == b"\x7fELF" and int.from_bytes(header[18:20], "little") == 183,
                "HIGHGO_LIB_ARCH", "国密动态库不是ARM64", "使用厂商aarch64库及配套依赖。", {"library": library.name})
        loader = os.environ.get("HOST_RUNTIME_LOADER")
        command = ([loader, "--library-path", os.environ["HOST_RUNTIME_LIBRARY_PATH"], "--list", str(library)]
                   if loader else ["ldd", str(library)])
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        require("not found" not in result.stdout, "HIGHGO_LIB_DEPENDENCY", "国密库依赖未加载完整",
                "核对镜像中libssl.so.1.1/libcrypto.so.1.1及ldd；不伪造OpenSSL跨版本软链接。", {"library": library.name})
    import psycopg
    from psycopg import pq
    loaded = [line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines() if "libpq" in line]
    require(pq.__impl__ == "python" and loaded and all(Path(name).parent == directory for name in loaded),
            "HIGHGO_LIB_SELECTION", "未使用指定的厂商libpq/纯Python psycopg", "核对PSYCOPG_IMPL、LD_PRELOAD和离线镜像。")
    return {"architecture": platform.machine(), "psycopg": psycopg.__version__, "libpq": pq.version()}


def configuration():
    from app.core.config import settings
    require(settings.db_name and settings.db_name != "road9" and settings.db_schema not in {"public", "pg_catalog", "information_schema"}, "CONFIG_DB_TARGET",
            "应用库/schema配置与发布目标不符", "核对已确认的生产DB_NAME/DB_SCHEMA；不能指向本机road9或公共/系统schema，路网/路况只读使用Doris。",
            {"configured_database": settings.db_name, "configured_schema": settings.db_schema})
    require(settings.db_driver == "psycopg", "CONFIG_DB_DRIVER", "生产瀚高连接没有选择国密libpq适配路径",
            "生产DB_DRIVER应为psycopg；本地开发继续asyncpg，不改本地.env。")
    require(1 <= settings.db_port <= 65535 and 1 <= settings.doris_mysql_port <= 65535,
            "CONFIG_PORT_RANGE", "DB/Doris端口超出1..65535", "核对DB_PORT和DORIS_MYSQL_PORT。")
    from urllib.parse import urlsplit
    invalid_origins = []
    for origin in settings.cors_origins:
        try:
            parsed = urlsplit(origin)
            valid = origin == origin.strip() and origin.startswith(("http://", "https://")) and bool(parsed.hostname) and not (
                parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path)
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            invalid_origins.append(True)
    require(not invalid_origins, "CONFIG_CORS", "CORS来源不是有效的HTTP(S) origin",
            "填写http://服务器IP:8009这样的JSON列表，不附加路径、认证信息或通配符。")
    return settings


async def database_checks(report, settings):
    from sqlalchemy import text
    try:
        from app.core.database import engine, _alembic_head, _replay_v2_alembic_head
    except Exception as exc:
        report.error("database.driver", exc)
        return
    connection = await report.arun("database.connect", engine.connect)
    if connection is None:
        for stage in ("identity", "schema", "timescaledb", "objects", "migrations"):
            report.skip("database." + stage, "数据库连接不可用，未检查本项")
        await engine.dispose()
        return

    async def query_check(stage, function):
        if connection.closed or connection.invalidated:
            report.skip(stage, "数据库连接在前一检查后不可用，未继续查询")
            return None
        async def isolated():
            async with connection.begin_nested():
                return await function()
        return await report.arun(stage, isolated, optional=(stage == "database.timescaledb" and not settings.db_timescale_required))

    try:
        readonly = await report.arun("database.readonly", lambda: connection.execute(text("SET TRANSACTION READ ONLY")))
        if readonly is None:
            report.skip("database.metadata", "无法建立只读检查事务")
            return

        async def identity():
            database, current = (await connection.execute(text("SELECT current_database(), current_schema()"))).one()
            facts = {"actual_database": database, "actual_schema": current, "expected_database": settings.db_name,
                     "expected_schema": settings.db_schema, "search_path": await connection.scalar(text("SHOW search_path"))}
            require(database == settings.db_name, "DB_DATABASE_MISMATCH", "实际连入的数据库与DB_NAME不一致", "核对DB_HOST/DB_PORT/DB_NAME及数据库路由。", facts)
            return facts
        await query_check("database.identity", identity)

        async def schema():
            namespace = (await connection.execute(text(
                "SELECT has_schema_privilege(current_user, oid, 'USAGE'), has_schema_privilege(current_user, oid, 'CREATE') "
                "FROM pg_namespace WHERE nspname=:schema"), {"schema": settings.db_schema})).one_or_none()
            current = await connection.scalar(text("SELECT current_schema()"))
            facts = {"schema": settings.db_schema, "actual_schema": current, "exists": namespace is not None,
                     "usage": bool(namespace and namespace[0]), "create": bool(namespace and namespace[1])}
            require(namespace is not None, "DB_SCHEMA_MISSING", "配置的生产schema尚未预建", "由DBA在DB_NAME对应的库中预建DB_SCHEMA并分配授权，再执行启动。", facts)
            require(namespace[0], "DB_SCHEMA_USAGE", "当前账号没有配置schema的USAGE权限", "由DBA向当前运行/迁移账号授予该schema的USAGE。", facts)
            require(current == settings.db_schema, "DB_SEARCH_PATH", "会话未选中配置的DB_SCHEMA", "核对DB_SCHEMA及专用方言加载；检查服务端是否覆盖会话search_path。", facts)
            return facts
        schema_info = await query_check("database.schema", schema)

        async def timescale():
            version = await connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='timescaledb'"))
            require(bool(version), "TIMESCALE_MISSING", "配置的生产库未启用TimescaleDB", "由DBA在DB_NAME对应的库中启用配套TimescaleDB；不要在其他库启用后视为通过。")
            await connection.execute(text("SELECT 1 FROM timescaledb_information.hypertables LIMIT 1"))
            return {"extension_version": version, "catalog_readable": True}
        await query_check("database.timescaledb", timescale)

        async def objects():
            rows = (await connection.execute(text(
                "SELECT c.relname, has_table_privilege(current_user,c.oid,'SELECT'), "
                "has_table_privilege(current_user,c.oid,'INSERT'), has_table_privilege(current_user,c.oid,'UPDATE'), "
                "has_table_privilege(current_user,c.oid,'DELETE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind IN ('r','p') AND left(c.relname,4)='uav_'"), {"schema": settings.db_schema})).all()
            denied = [{"table": row[0], "missing": [name for name, allowed in zip(("SELECT", "INSERT", "UPDATE", "DELETE"), row[1:]) if not allowed]}
                      for row in rows if not all(row[1:])]
            require(not denied, "DB_TABLE_PERMISSION", "现有应用表的读写权限不足", "由DBA按运行角色补齐对应应用表权限及默认权限，不授权或修改YCX外部表。", {"denied": denied})
            sequences = (await connection.execute(text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relkind='S' AND left(c.relname,4)='uav_' "
                "AND NOT has_sequence_privilege(current_user,c.oid,'USAGE')"), {"schema": settings.db_schema})).scalars().all()
            require(not sequences, "DB_SEQUENCE_PERMISSION", "应用序列缺少USAGE权限", "由DBA补齐列出的应用序列权限及默认序列权限。", {"sequences": list(sequences)})
            return {"existing_application_tables": len(rows)}
        if schema_info is not None:
            await query_check("database.objects", objects)
        else:
            report.skip("database.objects", "schema未通过，未验证应用对象权限")

        async def migrations():
            from alembic.script import ScriptDirectory
            from alembic.config import Config
            from app.core import database as module
            pending = []
            facts = {}
            for table, folder, head in (("uav_alembic_version", "alembic", _alembic_head()),
                                        ("uav_replay_v2_alembic_version", "alembic_replay_v2", _replay_v2_alembic_head())):
                exists = await connection.scalar(text("SELECT to_regclass(:name)"), {"name": f'"{settings.db_schema}"."{table}"'})
                revision = await connection.scalar(text(f'SELECT version_num FROM "{settings.db_schema}"."{table}"')) if exists else None
                if revision:
                    config = Config()
                    config.set_main_option("script_location", str(Path(module.__file__).resolve().parents[2] / folder))
                    try:
                        ScriptDirectory.from_config(config).get_revision(revision)
                    except Exception:
                        raise DiagnosticError("MIGRATION_UNKNOWN", "数据库包含本版本未知的迁移版本", "停止应用降级/覆盖，核对应用版本与数据库版本；不修改版本表或自动降级。", {"version_table": table}) from None
                facts[table] = {"installed": revision, "target": head}
                if revision != head:
                    pending.append(table)
            if pending:
                can_create = await connection.scalar(text("SELECT has_schema_privilege(current_user,oid,'CREATE') FROM pg_namespace WHERE nspname=:schema"), {"schema": settings.db_schema})
                require(can_create, "DB_MIGRATION_PERMISSION", "需要初始化/迁移，但当前账号没有schema CREATE权限", "使用DBA授权的迁移账号执行init-db，再按手册切换运行账号。", {"pending": pending})
                report.add("database.initialization", "pending_init", title="基础/V2迁移将在init-db中执行", facts={"pending": pending})
            return facts
        if schema_info is not None:
            await query_check("database.migrations", migrations)
        else:
            report.skip("database.migrations", "schema未通过，未验证应用迁移状态")
    finally:
        await report.arun("database.close", connection.close)
        await report.arun("database.dispose", engine.dispose)


async def ycx_checks(report, settings):
    if not getattr(settings, "road_features_enabled", True):
        report.skip("ycx.road_features", "路网标注、匹配和导入已按生产配置关闭，不探测外部路网依赖")
        return
    from app.core.doris_connection import active_road_version, query
    for table in ("dim_data_version", "dim_inter_info", "dim_link_info", "dim_lane_info"):
        await report.arun("ycx." + table,
            lambda table=table: query(settings, f"SELECT 1 FROM `{settings.doris_database}`.`{table}` LIMIT 1"),
            optional=True)
    await report.arun("ycx.active_version", lambda: active_road_version(settings), optional=True)


async def doris_checks(report, settings):
    if getattr(settings, "ycx_metrics_backend", "postgresql") != "doris":
        return
    from app.core.doris_connection import query
    for table in ("dws_tfc_inter_index_m_5mi", "dws_tfc_link_index_m_5mi"):
        await report.arun("doris." + table, lambda table=table: query(settings, f"SELECT 1 FROM `{settings.doris_database}`.`{table}` LIMIT 1"), optional=True)


async def kafka_checks(report, settings):
    consumer = None
    try:
        from aiokafka import AIOKafkaConsumer
        consumer = AIOKafkaConsumer(bootstrap_servers=settings.kafka_bootstrap, **settings.kafka_security_options,
                                   group_id=None, enable_auto_commit=False, request_timeout_ms=10000)
        async def metadata():
            await consumer.start()
            topics = await consumer.topics()
            # Native deployments must reach advertised endpoints, not just bootstrap.
            if os.environ.get("TRAFFIC_NATIVE_OWNER"):
                import socket
                brokers = list(consumer._client.cluster.brokers())
                require(bool(brokers), "KAFKA_ADVERTISED_EMPTY", "Kafka未返回broker地址", "核对Kafka元数据与监听配置。")
                for broker in brokers:
                    def probe(broker=broker):
                        with socket.create_connection((broker.host, broker.port), timeout=5):
                            pass
                    try:
                        await asyncio.to_thread(probe)
                    except OSError:
                        raise DiagnosticError("KAFKA_ADVERTISED_UNREACHABLE", "宿主无法访问Kafka公布的broker地址",
                                              "核对advertised.listeners的宿主DNS、路由和端口；不修改认证或消费offset。") from None
            return {"visible_topics": len(topics), "security_protocol": settings.kafka_security_protocol,
                    "sasl_mechanism": settings.kafka_sasl_mechanism, "publishes_messages": False}
        await report.arun("kafka.authentication_and_metadata", metadata, timeout=30)
        from utils_local.kafka_topic_preflight import check_fixed_topics
        await report.arun("kafka.fixed_topics", lambda: asyncio.to_thread(check_fixed_topics,settings.kafka_bootstrap,settings.kafka_security_options), timeout=30)
        report.add("kafka.business_acl", "warning", code="KAFKA_ACL_NOT_EVALUATED",
                   title="只读预检不证明发布、事务及消费者组ACL", action="按Topic/Group清单授权，并在真实任务验收；不会用发测试业务消息验证权限。")
    except Exception as exc:
        report.error("kafka.configuration", exc)
    finally:
        if consumer is not None:
            await report.arun("kafka.close", consumer.stop)


async def check_connections(report=None, settings=None):
    report = report or Report()
    settings = settings or configuration()
    # Database, YCX and Kafka are independent: one failure must not suppress the rest.
    for stage, function in (("database", database_checks), ("ycx", ycx_checks), ("doris", doris_checks), ("kafka", kafka_checks)):
        try:
            await function(report, settings)
        except Exception as exc:
            report.error(stage, exc)
            if stage in {"ycx", "doris"}:
                report.checks[-1]["status"] = "warning"
    return report


def model_checks(report):
    manifest_path = os.environ.get("ASCEND_MODEL_MANIFEST", "")
    def manifest():
        from utils_local.ascend_model_manifest import load_manifest, sha256
        require(bool(manifest_path), "MODEL_PATH_CONFIG", "未配置ASCEND_MODEL_MANIFEST", "核对生产Compose中的模型清单容器路径。")
        data, _ = load_manifest(manifest_path)
        path = os.environ.get("DETECTION_WEIGHT_PATH", "")
        require(bool(path) and Path(path).is_file(), "MODEL_SOURCE_MISSING", "原始PT权重缺失", "拷贝完整模型资源包，核对DETECTION_WEIGHT_PATH。")
        require(sha256(path) == data["source_sha256"], "MODEL_SOURCE_HASH", "原始权重与OM清单不一致", "使用同一版本模型包，按MODEL_SHA256SUMS核验，不混用PT和OM。")
        return {"manifest": Path(manifest_path).name, "tiers": [640, 960, 1280], "soc": data["soc_version"]}
    valid = report.run("models.manifest_and_source_hash", manifest)
    if valid is None:
        report.skip("ascend.inference", "模型清单或源权重未通过，不加载设备模型")
        return
    def load():
        require(Path(os.environ.get("ASCEND_RUNTIME_CANN_ROOT", "/usr/local/Ascend/cann-9.0.0")).is_dir(), "CANN_VERSION", "运行环境中没有CANN9.0.0", "使用本次310P/CANN9.0.0运行环境，核对宿主机配套驱动。")
        from utils_local.ascend_detector import AscendDetector
        try:
            device = int(os.getenv("ASCEND_DEVICE_ID", "0"))
        except ValueError:
            raise DiagnosticError("CONFIG_ASCEND_DEVICE", "ASCEND_DEVICE_ID不是整数", "按设备映射填写非负设备号。") from None
        require(device >= 0 and Path(f"/dev/davinci{device}").exists(), "ASCEND_DEVICE_MISSING", "宿主昇腾设备不可见" if os.environ.get("TRAFFIC_NATIVE_OWNER") else "检测设备没有映射到容器",
                "核对宿主驱动、设备权限、ASCEND_DEVICE_ID和npu-smi。" if os.environ.get("TRAFFIC_NATIVE_OWNER") else "核对ASCEND_DEVICE_ID、ASCEND_DAVINCI_DEVICE和宿主机npu-smi。", {"device_id": device})
        return AscendDetector(manifest_path, device)
    model = report.run("ascend.device_and_model_load", load)
    if model is None:
        for size in (640, 960, 1280):
            report.skip(f"ascend.inference_{size}", "设备或模型加载失败")
        return
    try:
        import numpy as np
        for size in (640, 960, 1280):
            report.run(f"ascend.inference_{size}", lambda size=size: model.predict(
                np.zeros((480, 640, 3), np.uint8), imgsz=size, conf=0.05, iou=0.4, classes=None))
    finally:
        report.run("ascend.close", model.close)


def resource_checks(report):
    locations = json.loads(os.environ.get("HOST_RESOURCE_DIRECTORIES", "null"))
    for location in locations if locations is not None else ("/hls", "/pipeline-output", "/pipeline-spool", "/calibration", "/survey", "/trajectory-archive", "/app/logs"):
        def writable(location=location):
            path = Path(location)
            require(path.is_dir(), "RESOURCE_DIRECTORY", "持久化目录缺失", "核对DATA_ROOT及该容器目录的Compose绑定。", {"path": location})
            with tempfile.TemporaryFile(prefix=".traffic-preflight-", dir=path) as stream:
                stream.write(b"preflight")
                stream.flush()
            free = shutil.disk_usage(path).free
            require(free > 0, "DISK_FULL", "输出目录磁盘已满", "核对DATA_ROOT容量及保留策略。", {"path": location})
            if free < 1024**3:
                report.add("resources." + location, "warning", code="DISK_LOW", title="可用空间不足1GiB，不代表业务容量足够",
                           action="按视频、证据和spool保留需求扩容。", facts={"free_bytes": free})
            return {"path": location, "temporary_write": True, "free_bytes": free}
        report.run("resources." + location, writable)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--libraries-only", action="store_true")
    parser.add_argument("--connections-only", action="store_true", help="Read-only DB/YCX/Kafka checks without NPU/resource mounts")
    args = parser.parse_args()
    os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/Ultralytics")
    if args.libraries_only:
        progress("libraries")
        print(json.dumps({"libraries": check_libraries()}, ensure_ascii=False, indent=2))
        return 0
    report = Report()
    report.run("libraries", check_libraries)
    settings = report.run("configuration", configuration)
    if not args.connections_only:
        model_checks(report)
        resource_checks(report)
    if settings is not None:
        asyncio.run(check_connections(report, settings))
    else:
        for stage in ("database", "ycx", "kafka"):
            report.skip(stage, "生产配置未通过，未使用无效凭据连接")
    report.emit()
    return 1 if report.failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        report_failure(exc)
        sys.exit(1)
