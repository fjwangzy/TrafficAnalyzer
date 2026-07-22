"""Read-only YCX road-network import into canonical GCJ-02 snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.core.config import Settings
from utils_local.coordinates import TRANSFORM_VERSION, gcj02_to_enu


@dataclass(frozen=True)
class ImportedRoadContext:
    inter_id: str
    road_data_version: str
    checksum: str
    anchor_gcj02: list[float]
    payload: dict[str, Any]
    geometry_gcj02: dict[str, Any]
    geometry_enu_m: dict[str, Any]
    topology: dict[str, Any]


def _geojson(raw: str | None) -> dict | None:
    return json.loads(raw) if raw else None


def _map_coordinates(value: Any, transform) -> Any:
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        x, y = transform(float(value[0]), float(value[1]))
        return [round(x, 3), round(y, 3), *value[2:]]
    if isinstance(value, list):
        return [_map_coordinates(item, transform) for item in value]
    return value


def geometry_to_enu(geometry: dict | None, anchor_gcj02: list[float]) -> dict | None:
    if not geometry:
        return None
    return {
        **geometry,
        "coordinates": _map_coordinates(
            geometry.get("coordinates"),
            lambda lon, lat: gcj02_to_enu(lon, lat, anchor_gcj02),
        ),
    }


class YcxRoadImporter:
    def __init__(self, settings: Settings):
        self._settings = settings
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", settings.ycx_db_schema):
            raise ValueError("YCX_DB_SCHEMA contains unsupported characters")

    async def import_intersection(
        self,
        inter_id: str,
        road_data_version: str | None = None,
    ) -> ImportedRoadContext:
        if not self._settings.ycx_db_host or not self._settings.ycx_db_user:
            raise RuntimeError("YCX read-only database credentials are not configured")
        connection = await asyncpg.connect(
            host=self._settings.ycx_db_host,
            port=self._settings.ycx_db_port,
            user=self._settings.ycx_db_user,
            password=self._settings.ycx_db_password,
            database=self._settings.ycx_db_name,
            timeout=10,
            server_settings={
                "search_path": f"{self._settings.ycx_db_schema},public"
            },
        )
        try:
            async with connection.transaction(readonly=True):
                version = road_data_version or await connection.fetchval(
                    "SELECT version_id FROM dim_data_version WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
                )
                if not version:
                    raise LookupError("YCX active road version not found")
                intersection = await connection.fetchrow(
                    """
                    SELECT inter_id, inter_name,
                           CASE WHEN NULLIF(BTRIM(geom_center), '') IS NULL THEN NULL
                                ELSE ST_AsGeoJSON(ST_GeomFromText(geom_center, 4326)) END
                                AS center_geojson,
                           CASE WHEN NULLIF(BTRIM(geom_boundary), '') IS NULL THEN NULL
                                ELSE ST_AsGeoJSON(ST_GeomFromText(geom_boundary, 4326)) END
                                AS boundary_geojson
                    FROM dim_inter_info
                    WHERE inter_id=$1 AND version_id=$2
                    """,
                    inter_id,
                    version,
                )
                if intersection is None:
                    raise LookupError(f"YCX intersection not found: {inter_id}@{version}")
                links = await connection.fetch(
                    """
                    SELECT link_id, road_name, f_inter_id, t_inter_id, f_angle, t_angle,
                           lane_num, c_lane_num, lane_info, road_level, formway,
                           max_speed, turn_move,
                           CASE WHEN NULLIF(BTRIM(geom), '') IS NULL THEN NULL
                                ELSE ST_AsGeoJSON(ST_GeomFromText(geom, 4326)) END
                                AS geom_geojson
                    FROM dim_link_info
                    WHERE version_id=$2 AND (f_inter_id=$1 OR t_inter_id=$1)
                    ORDER BY link_id
                    """,
                    inter_id,
                    version,
                )
                link_ids = [row["link_id"] for row in links]
                lanes = await connection.fetch(
                    """
                    SELECT lane_id, link_id, lane_no, lane_func_code, width, length,
                           inter_id, turn_move,
                           CASE WHEN NULLIF(BTRIM(geom), '') IS NULL THEN NULL
                                ELSE ST_AsGeoJSON(ST_GeomFromText(geom, 4326)) END
                                AS geom_geojson
                    FROM dim_lane_info
                    WHERE version_id=$2 AND (inter_id=$1 OR link_id=ANY($3::text[]))
                    ORDER BY link_id, lane_no, lane_id
                    """,
                    inter_id,
                    version,
                    link_ids,
                )
        finally:
            await connection.close()

        center = _geojson(intersection["center_geojson"])
        if not center or center.get("type") != "Point":
            raise ValueError("YCX intersection center must be a GCJ-02 Point")
        anchor_gcj02 = [float(center["coordinates"][0]), float(center["coordinates"][1])]
        link_values = [
            {
                "link_id": row["link_id"], "road_name": row["road_name"],
                "f_inter_id": row["f_inter_id"], "t_inter_id": row["t_inter_id"],
                "f_angle": float(row["f_angle"]) if row["f_angle"] is not None else None,
                "t_angle": float(row["t_angle"]) if row["t_angle"] is not None else None,
                "lane_num": int(row["lane_num"]) if row["lane_num"] is not None else None,
                "c_lane_num": int(row["c_lane_num"]) if row["c_lane_num"] is not None else None,
                "lane_info": row["lane_info"], "road_level": row["road_level"],
                "formway": row["formway"], "max_speed": row["max_speed"],
                "turn_move": row["turn_move"], "geometry_gcj02": _geojson(row["geom_geojson"]),
            }
            for row in links
        ]
        lane_values = [
            {
                "lane_id": row["lane_id"], "link_id": row["link_id"], "lane_no": row["lane_no"],
                "lane_func_code": row["lane_func_code"],
                "width": float(row["width"]) if row["width"] is not None else None,
                "length": float(row["length"]) if row["length"] is not None else None,
                "inter_id": row["inter_id"], "turn_move": row["turn_move"],
                "geometry_gcj02": _geojson(row["geom_geojson"]),
                "geometry_source": "link_offset_derived",
            }
            for row in lanes
        ]
        boundary = _geojson(intersection["boundary_geojson"])
        geometry_gcj02 = {
            "intersection_boundary": boundary,
            "links": {item["link_id"]: item["geometry_gcj02"] for item in link_values},
            "lane_candidates": {item["lane_id"]: item["geometry_gcj02"] for item in lane_values},
        }
        geometry_enu_m = {
            "intersection_boundary": geometry_to_enu(boundary, anchor_gcj02),
            "links": {key: geometry_to_enu(value, anchor_gcj02) for key, value in geometry_gcj02["links"].items()},
            "lane_candidates": {key: geometry_to_enu(value, anchor_gcj02) for key, value in geometry_gcj02["lane_candidates"].items()},
        }
        topology = {
            "links": [
                {key: item.get(key) for key in ("link_id", "f_inter_id", "t_inter_id", "lane_num", "c_lane_num")}
                for item in link_values
            ]
        }
        payload = {
            "coordinate_system": "GCJ02",
            "coordinate_transform_version": TRANSFORM_VERSION,
            "source_id_semantics": "opaque_geomhash",
            "intersection": {
                "inter_id": intersection["inter_id"], "name": intersection["inter_name"],
                "center_gcj02": anchor_gcj02, "boundary_gcj02": boundary,
            },
            "links": link_values,
            "lanes": lane_values,
            "lane_geometry_authority": "candidate_only",
        }
        checksum = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ImportedRoadContext(
            inter_id=inter_id, road_data_version=str(version), checksum=checksum,
            anchor_gcj02=anchor_gcj02, payload=payload,
            geometry_gcj02=geometry_gcj02, geometry_enu_m=geometry_enu_m, topology=topology,
        )
