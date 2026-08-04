"""Read the server YCX typical situation matrix without mutating it."""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from typing import Any, Awaitable, Callable

import asyncpg


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _saturation_status(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 0.85:
        return "good"
    if value <= 0.95:
        return "near_saturated"
    return "oversaturated"


def _segment_status(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 1.5:
        return "smooth"
    if value <= 2.0:
        return "slow"
    return "congested"


def _paths(raw: str | dict | None) -> list[list[list[float]]]:
    try:
        geometry = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "LineString":
        candidates = [coordinates]
    elif geometry.get("type") == "MultiLineString":
        candidates = coordinates
    else:
        return []
    result = []
    for candidate in candidates or []:
        path = []
        for point in candidate or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            lon, lat = _number(point[0]), _number(point[1])
            if lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90:
                path.append([lon, lat])
        if len(path) >= 2:
            result.append(path)
    return result


class DashboardSituationReadModel:
    """Deep read module for one weekday/5-minute typical situation slot."""

    schema_version = "uav.dashboard-situation/v1"

    def __init__(
        self,
        settings,
        *,
        connect: Callable[..., Awaitable[Any]] = asyncpg.connect,
        monotonic: Callable[[], float] = time.monotonic,
        cache_ttl_sec: float = 300,
        cache_limit: int = 64,
    ):
        for setting_name in ("ycx_db_schema", "ycx_metrics_schema"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", getattr(settings, setting_name)):
                raise ValueError(f"{setting_name.upper()} contains unsupported characters")
        self._settings = settings
        self._connect = connect
        self._monotonic = monotonic
        self._cache_ttl_sec = cache_ttl_sec
        self._cache_limit = cache_limit
        self._cache: OrderedDict[tuple[str, int, int], tuple[float, dict]] = OrderedDict()

    def _cached_slot(self, day_of_week: int, step_index: int) -> tuple[tuple[str, int, int], float, dict] | None:
        matches = [
            (key, cached_at, payload)
            for key, (cached_at, payload) in self._cache.items()
            if key[1:] == (day_of_week, step_index)
        ]
        return matches[-1] if matches else None

    async def situation(self, *, day_of_week: int, step_index: int) -> dict:
        cached = self._cached_slot(day_of_week, step_index)
        now = self._monotonic()
        if cached and now - cached[1] <= self._cache_ttl_sec:
            result = deepcopy(cached[2])
            result["cache"] = {"status": "hit", "stale": False}
            return result

        connection = None
        road_schema = self._settings.ycx_db_schema
        metrics_schema = self._settings.ycx_metrics_schema
        try:
            if not self._settings.ycx_db_host or not self._settings.ycx_db_user:
                raise OSError("YCX read-only connection is not configured")
            connection = await self._connect(
                host=self._settings.ycx_db_host,
                port=self._settings.ycx_db_port,
                user=self._settings.ycx_db_user,
                password=self._settings.ycx_db_password,
                database=self._settings.ycx_db_name,
                timeout=10,
            )
            async with connection.transaction(readonly=True):
                road_version = await connection.fetchval(
                    f'SELECT version_id FROM "{road_schema}".dim_data_version '
                    "WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
                )
                if road_version is None:
                    raise OSError("YCX has no enabled road data version")
                available_rows = await connection.fetch(
                    f'SELECT DISTINCT day_of_week FROM "{metrics_schema}".dws_inter_evaluation_5min_mm '
                    "WHERE COALESCE(is_deleted, 0) = 0 ORDER BY day_of_week"
                )
                intersection_rows = await connection.fetch(
                    f'''WITH situation_scope AS (
                            SELECT DISTINCT inter_id
                            FROM "{metrics_schema}".dws_inter_evaluation_5min_mm
                            WHERE COALESCE(is_deleted, 0) = 0
                        ), selected_slot AS (
                            SELECT *
                            FROM "{metrics_schema}".dws_inter_evaluation_5min_mm
                            WHERE day_of_week = $2 AND step_index = $3
                              AND COALESCE(is_deleted, 0) = 0
                        )
                        SELECT scope.inter_id, COALESCE(e.inter_name, i.inter_name) AS inter_name,
                               ST_X(ST_GeomFromText(i.geom_center, 4326)) AS longitude,
                               ST_Y(ST_GeomFromText(i.geom_center, 4326)) AS latitude,
                               e.saturation_max, e.saturation_avg, e.unbalance_index,
                               e.level_of_service, e.update_time
                        FROM situation_scope scope
                        JOIN "{road_schema}".dim_inter_info i
                          ON i.inter_id = scope.inter_id AND i.version_id = $1
                        LEFT JOIN selected_slot e ON e.inter_id = scope.inter_id
                        WHERE NULLIF(BTRIM(i.geom_center), '') IS NOT NULL
                        ORDER BY scope.inter_id''',
                    road_version,
                    day_of_week,
                    step_index,
                )
                segment_rows = await connection.fetch(
                    f'''WITH situation_scope AS (
                            SELECT DISTINCT inter_id, link_id
                            FROM "{metrics_schema}".dws_inter_link_status_5min_mm
                            WHERE COALESCE(is_deleted, 0) = 0
                        ), selected_slot AS (
                            SELECT *
                            FROM "{metrics_schema}".dws_inter_link_status_5min_mm
                            WHERE day_of_week = $2 AND step_index = $3
                              AND COALESCE(is_deleted, 0) = 0
                        )
                        SELECT scope.inter_id, scope.link_id, COALESCE(s.link_name, l.road_name) AS link_name,
                               s.dir8_code, s.dir8_label, s.delay_index, s.stop_time_sec,
                               s.avg_nostop_speed, s.queue_len_est_m,
                               ST_AsGeoJSON(ST_GeomFromText(l.geom, 4326)) AS geometry_geojson,
                               s.update_time
                        FROM situation_scope scope
                        JOIN "{road_schema}".dim_link_info l
                          ON l.link_id = scope.link_id AND l.version_id = $1
                        LEFT JOIN selected_slot s
                          ON s.inter_id = scope.inter_id AND s.link_id = scope.link_id
                        WHERE NULLIF(BTRIM(l.geom), '') IS NOT NULL
                        ORDER BY scope.inter_id, scope.link_id''',
                    road_version,
                    day_of_week,
                    step_index,
                )
        except (OSError, TimeoutError, asyncpg.PostgresError):
            stale = self._cached_slot(day_of_week, step_index)
            if stale:
                result = deepcopy(stale[2])
                result["cache"] = {"status": "stale", "stale": True, "reason": "server_unavailable"}
                return result
            raise
        finally:
            if connection is not None:
                await connection.close()

        intersections = []
        for row in intersection_rows:
            longitude = _number(row["longitude"])
            latitude = _number(row["latitude"])
            if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                continue
            saturation_max = _number(row["saturation_max"])
            intersections.append({
                "inter_id": row["inter_id"],
                "name": row["inter_name"] or row["inter_id"],
                "lon": longitude,
                "lat": latitude,
                "saturation_max": saturation_max,
                "saturation_avg": _number(row["saturation_avg"]),
                "unbalance_index": _number(row["unbalance_index"]),
                "level_of_service": row["level_of_service"],
                "status": _saturation_status(saturation_max),
                "updated_at": _iso(row["update_time"]),
            })

        segments = []
        for row in segment_rows:
            paths = _paths(row["geometry_geojson"])
            if not paths:
                continue
            delay_index = _number(row["delay_index"])
            segments.append({
                "id": f'{row["inter_id"]}:{row["link_id"]}',
                "inter_id": row["inter_id"],
                "link_id": row["link_id"],
                "name": row["link_name"] or row["link_id"],
                "dir8_code": row["dir8_code"],
                "direction": row["dir8_label"],
                "delay_index": delay_index,
                "stop_time_sec": _number(row["stop_time_sec"]),
                "avg_nostop_speed": _number(row["avg_nostop_speed"]),
                "queue_len_est_m": _number(row["queue_len_est_m"]),
                "status": _segment_status(delay_index),
                "paths_gcj02": paths,
                "updated_at": _iso(row["update_time"]),
            })

        counts = {status: sum(1 for row in intersections if row["status"] == status)
                  for status in ("good", "near_saturated", "oversaturated", "missing")}
        segment_counts = {f"{status}_segments": sum(1 for row in segments if row["status"] == status)
                          for status in ("smooth", "slow", "congested", "missing")}
        result = {
            "schema_version": self.schema_version,
            "source": {
                "database": self._settings.ycx_db_name,
                "road_schema": road_schema,
                "metrics_schema": metrics_schema,
                "road_version": str(road_version),
                "read_mode": "readonly",
            },
            "time_profile": {
                "kind": "typical_5min",
                "timezone": "Asia/Shanghai",
                "day_of_week": day_of_week,
                "step_index": step_index,
                "start_time": f"{step_index // 12:02d}:{step_index % 12 * 5:02d}",
                "available_days": [int(row["day_of_week"]) for row in available_rows],
            },
            "cache": {"status": "miss", "stale": False},
            "summary": {
                "intersections_total": len(intersections),
                **counts,
                "segments_total": len(segments),
                **segment_counts,
            },
            "intersections": intersections,
            "segments": segments,
        }
        cache_key = (str(road_version), day_of_week, step_index)
        self._cache[cache_key] = (now, deepcopy(result))
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)
        return result
