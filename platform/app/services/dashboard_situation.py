"""Read the server YCX typical situation matrix without mutating it."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from app.core.doris_connection import active_road_version, geometry_geojson, query
from app.core.deployment_diagnostics import DiagnosticError


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


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
        monotonic: Callable[[], float] = time.monotonic,
        cache_ttl_sec: float = 300,
        cache_limit: int = 64,
    ):
        self._settings = settings
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

    async def _doris_rows(self, day, step):
        database = self._settings.doris_database
        version = await active_road_version(self._settings)
        evaluation = f"`{database}`.dws_tfc_inter_index_m_5mi"
        status = f"`{database}`.dws_tfc_link_index_m_5mi"
        months = await query(self._settings,
            f"SELECT MAX(i.stat_month) AS stat_month FROM (SELECT DISTINCT stat_month FROM {evaluation} "
            "WHERE version_id=%s AND COALESCE(is_deleted,0)=0) i JOIN "
            f"(SELECT DISTINCT stat_month FROM {status} WHERE COALESCE(is_deleted,0)=0) l "
            "ON i.stat_month=l.stat_month", version)
        month = months[0]["stat_month"] if months else None
        if month is None:
            raise DiagnosticError("DORIS_METRICS_EMPTY", "Doris没有共同可用的路口/路段指标月份",
                                  "核对两张月度典型指标表及启用的路网版本；不混合不同月份。")
        available = await query(self._settings,
            f"SELECT DISTINCT day_of_week FROM {evaluation} WHERE stat_month=%s AND version_id=%s "
            "AND COALESCE(is_deleted,0)=0 ORDER BY day_of_week", month, version)
        intersections = await query(self._settings,
            "SELECT i.inter_id, i.inter_name, ST_X(ST_GeomFromText(i.geom_center)) AS longitude, "
            "ST_Y(ST_GeomFromText(i.geom_center)) AS latitude, e.delay_index, e.avg_speed_kmh, "
            "e.unbalance_index, e.update_time, NULL AS saturation_max, NULL AS saturation_avg, "
            "NULL AS level_of_service "
            f"FROM `{database}`.dim_inter_info i JOIN (SELECT DISTINCT inter_id FROM {evaluation} "
            "WHERE stat_month=%s AND version_id=%s AND COALESCE(is_deleted,0)=0) scope "
            "ON scope.inter_id=i.inter_id LEFT JOIN (SELECT inter_id, "
            "MAX(avg_jam_delay_index_avg) AS delay_index, AVG(avg_speed_avg) AS avg_speed_kmh, "
            "AVG(imbalance_index_avg) AS unbalance_index, MAX(update_time) AS update_time "
            f"FROM {evaluation} WHERE stat_month=%s AND version_id=%s AND day_of_week=%s "
            "AND step_index=%s AND COALESCE(is_deleted,0)=0 GROUP BY inter_id) e ON e.inter_id=i.inter_id "
            "WHERE i.version_id=%s ORDER BY i.inter_id",
            month, version, month, version, day, step, version)
        segments = await query(self._settings,
            "SELECT l.t_inter_id AS inter_id, l.link_id, l.road_name AS link_name, l.t_dir8 AS dir8_code, "
            "NULL AS dir8_label, l.geom AS geometry_wkt, s.delay_index_avg AS delay_index, "
            "s.stop_time_sec_avg AS stop_time_sec, s.avg_nostop_speed_avg AS avg_nostop_speed, "
            "NULL AS queue_len_est_m, s.update_time "
            f"FROM `{database}`.dim_link_info l JOIN (SELECT DISTINCT link_id FROM {status} "
            "WHERE stat_month=%s AND COALESCE(is_deleted,0)=0) scope ON scope.link_id=l.link_id "
            f"LEFT JOIN {status} s ON s.link_id=l.link_id AND s.stat_month=%s AND s.day_of_week=%s "
            "AND s.step_index=%s AND COALESCE(s.is_deleted,0)=0 WHERE l.version_id=%s ORDER BY l.link_id",
            month, month, day, step, version)
        for row in segments:
            row["geometry_geojson"] = geometry_geojson(row.pop("geometry_wkt"))
        return available, intersections, segments, version, month

    async def situation(self, *, day_of_week: int, step_index: int) -> dict:
        if not getattr(self._settings, "road_features_enabled", True):
            raise DiagnosticError("ROAD_FEATURES_DISABLED", "路网态势图层已关闭",
                                  "当前生产暂不使用路网标注、匹配和导入，视频检测和轨迹回放继续。")
        cached = self._cached_slot(day_of_week, step_index)
        now = self._monotonic()
        if cached and now - cached[1] <= self._cache_ttl_sec:
            result = deepcopy(cached[2])
            result["cache"] = {"status": "hit", "stale": False}
            return result

        try:
            available_rows, intersection_rows, segment_rows, road_version, month = await self._doris_rows(
                day_of_week, step_index)
        except (OSError, TimeoutError, DiagnosticError):
            stale = self._cached_slot(day_of_week, step_index)
            if stale:
                result = deepcopy(stale[2])
                result["cache"] = {"status": "stale", "stale": True, "reason": "server_unavailable"}
                return result
            raise

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
                "delay_index": _number(row["delay_index"]),
                "avg_speed_kmh": _number(row["avg_speed_kmh"]),
                "saturation_avg": _number(row["saturation_avg"]),
                "unbalance_index": _number(row["unbalance_index"]),
                "level_of_service": row["level_of_service"],
                "status": _segment_status(_number(row["delay_index"])),
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
                  for status in ("smooth", "slow", "congested", "missing")}
        segment_counts = {f"{status}_segments": sum(1 for row in segments if row["status"] == status)
                          for status in ("smooth", "slow", "congested", "missing")}
        result = {
            "schema_version": self.schema_version,
            "source": {
                "database": self._settings.doris_database,
                "metrics_backend": "doris",
                "metrics_database": self._settings.doris_database,
                "road_schema": self._settings.doris_database,
                "metrics_schema": self._settings.doris_database,
                "intersection_table": "dws_tfc_inter_index_m_5mi",
                "segment_table": "dws_tfc_link_index_m_5mi",
                "intersection_metric": "delay_index",
                "intersection_aggregation": "max_direction_monthly_mean",
                "stat_month": str(month),
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
        cache_key = (str(road_version) + ":" + str(month), day_of_week, step_index)
        self._cache[cache_key] = (now, deepcopy(result))
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)
        return result
