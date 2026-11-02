"""Bounded SELECT queries through the reference project's Doris MySQL channel."""
import asyncio
import re
import json


def _query(settings, sql, parameters):
    from app.core.deployment_diagnostics import DiagnosticError
    if not settings.doris_mysql_host or not settings.doris_mysql_user:
        raise DiagnosticError("DORIS_NOT_CONFIGURED", "Doris路网/指标源未配置", "补齐.env的DORIS_MYSQL_*，其他业务可继续。")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", settings.doris_database):
        raise ValueError("Invalid Doris database identifier")
    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("Doris access is SELECT-only")
    import pymysql
    connection = None
    try:
        connection = pymysql.connect(
            host=settings.doris_mysql_host, port=settings.doris_mysql_port,
            user=settings.doris_mysql_user, password=settings.doris_mysql_password,
            database=settings.doris_database, charset="utf8mb4", connect_timeout=5,
            read_timeout=10, write_timeout=5, autocommit=True, cursorclass=pymysql.cursors.DictCursor,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters or None)
            return list(cursor.fetchall())
    except pymysql.Error as exc:
        number = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        code = {1045: "DORIS_AUTH", 1044: "DORIS_PERMISSION", 1142: "DORIS_PERMISSION",
                1049: "DORIS_DATABASE", 1146: "DORIS_TABLE", 2003: "DORIS_CONNECTION",
                2013: "DORIS_TIMEOUT"}.get(number, "DORIS_QUERY")
        raise DiagnosticError(code, "Doris路网/指标读取不可用",
                              "核对DORIS_MYSQL_*、DORIS_DATABASE及路网/指标表的SELECT权限；无需在瀚高创建外部表。",
                              {"driver_error_number": number}) from exc
    finally:
        if connection is not None:
            connection.close()


async def query(settings, sql, *parameters):
    return await asyncio.to_thread(_query, settings, sql, parameters)


async def active_road_version(settings, explicit=None):
    from app.core.deployment_diagnostics import DiagnosticError
    version = explicit or getattr(settings, "ycx_road_version", "")
    if version:
        return version
    rows = await query(settings, f"SELECT version_id FROM `{settings.doris_database}`.dim_data_version "
                       "WHERE is_enabled=1 ORDER BY version_id DESC LIMIT 1")
    if not rows:
        raise DiagnosticError("YCX_VERSION_UNAVAILABLE", "Doris没有已启用的路网版本",
                              "设置已确认的YCX_ROAD_VERSION或启用正确的路网版本；不猜测版本。")
    return rows[0]["version_id"]


def geometry_geojson(value):
    """Decode upstream WKT with the existing geometry library; never invent geometry."""
    from shapely import wkt
    from shapely.geometry import mapping
    from shapely.errors import ShapelyError
    from app.core.deployment_diagnostics import DiagnosticError
    if value is None or not value.strip():
        return None
    try:
        geometry = wkt.loads(value)
        return None if geometry.is_empty else json.dumps(mapping(geometry))
    except (ShapelyError, ValueError, TypeError) as exc:
        raise DiagnosticError("DORIS_GEOMETRY", "Doris路网WKT几何无效",
                              "核对路网几何；不生成替代坐标或正式车道。") from exc
