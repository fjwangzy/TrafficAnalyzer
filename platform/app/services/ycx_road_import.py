"""Read-only YCX road-network import into canonical GCJ-02 snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.core.doris_connection import active_road_version, geometry_geojson, query
from utils_local.coordinates import TRANSFORM_VERSION, gcj02_to_enu

from app.core.config import Settings


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

    async def nearby_intersections(
        self,
        center_gcj02: list[float],
        radius_m: float = 250.0,
    ) -> list[dict[str, Any]]:
        """Find candidate intersections in Doris without a PostGIS dependency."""
        version = await active_road_version(self._settings)
        database = self._settings.doris_database
        rows = await query(
            self._settings,
            f"SELECT inter_id, inter_name, ST_X(ST_GeomFromText(geom_center)) AS longitude, "
            f"ST_Y(ST_GeomFromText(geom_center)) AS latitude FROM `{database}`.dim_inter_info "
            "WHERE version_id=%s AND ST_Distance_Sphere("
            "ST_X(ST_GeomFromText(geom_center)), ST_Y(ST_GeomFromText(geom_center)), %s, %s)<=%s "
            "ORDER BY ST_Distance_Sphere(ST_X(ST_GeomFromText(geom_center)), "
            "ST_Y(ST_GeomFromText(geom_center)), %s, %s), inter_id LIMIT 20",
            version, float(center_gcj02[0]), float(center_gcj02[1]), float(radius_m),
            float(center_gcj02[0]), float(center_gcj02[1]),
        )
        return [{
            "inter_id": row["inter_id"], "name": row["inter_name"] or row["inter_id"],
            "center_gcj02": [float(row["longitude"]), float(row["latitude"])],
            "road_data_version": str(version), "quality_status": "candidate", "source": "ycx_readonly",
        } for row in rows]

    async def import_intersection(
        self,
        inter_id: str,
        road_data_version: str | None = None,
    ) -> ImportedRoadContext:
        version = await active_road_version(self._settings, road_data_version)
        database = self._settings.doris_database
        intersections = await query(
            self._settings,
            f"SELECT inter_id, inter_name, geom_center, geom_boundary FROM `{database}`.dim_inter_info "
            "WHERE inter_id=%s AND version_id=%s", inter_id, version,
        )
        if not intersections:
            raise LookupError(f"YCX intersection not found: {inter_id}@{version}")
        intersection = intersections[0]
        intersection["center_geojson"] = geometry_geojson(intersection["geom_center"])
        intersection["boundary_geojson"] = geometry_geojson(intersection["geom_boundary"])
        links = await query(
            self._settings,
            f"SELECT link_id, road_name, f_inter_id, t_inter_id, f_angle, t_angle, lane_num, c_lane_num, "
            f"lane_info, road_level, formway, max_speed, turn_move, geom FROM `{database}`.dim_link_info "
            "WHERE version_id=%s AND (f_inter_id=%s OR t_inter_id=%s) ORDER BY link_id",
            version, inter_id, inter_id,
        )
        link_ids = [row["link_id"] for row in links]
        link_filter = " OR link_id IN (" + ",".join(["%s"] * len(link_ids)) + ")" if link_ids else ""
        lanes = await query(
            self._settings,
            f"SELECT lane_id, link_id, lane_no, lane_func_code, width, length, inter_id, turn_move, geom "
            f"FROM `{database}`.dim_lane_info WHERE version_id=%s AND (inter_id=%s{link_filter}) "
            "ORDER BY link_id, lane_no, lane_id", version, inter_id, *link_ids,
        )
        for row in [*links, *lanes]:
            row["geom_geojson"] = geometry_geojson(row["geom"])

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
