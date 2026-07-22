#!/usr/bin/env python3
"""Inspect the YCX road schema through a forced read-only transaction.

This is a development/audit helper.  It never prints credentials and never
executes application DDL/DML.  Production imports receive credentials through
the Platform environment; ``--credentials-file`` exists only to validate a
local credential note such as docs/road_pg.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import asyncpg


ROAD_NAME_PARTS = ("inter", "link", "lane", "version")


def _credential_values(path: Path | None) -> dict[str, str]:
    values = {
        "host": os.getenv("YCX_DB_HOST", ""),
        "port": os.getenv("YCX_DB_PORT", "5432"),
        "user": os.getenv("YCX_DB_USER", ""),
        "pwd": os.getenv("YCX_DB_PASSWORD", ""),
        "db": os.getenv("YCX_DB_NAME", "road9"),
        "schame": os.getenv("YCX_DB_SCHEMA", "ycx"),
    }
    if path is None:
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        key = key.strip().lower()
        if key in values:
            values[key] = raw_value.strip()
    return values


async def _audit(
    values: dict[str, str],
    inter_id: str | None,
    summary_only: bool,
    search_name: str | None = None,
    near_gcj02: tuple[float, float] | None = None,
    radius_m: float = 200.0,
) -> dict:
    if not values["host"] or not values["user"] or not values["pwd"]:
        raise SystemExit("YCX credentials are incomplete")
    schema = values["schame"]
    connection = await asyncpg.connect(
        host=values["host"],
        port=int(values["port"]),
        user=values["user"],
        password=values["pwd"],
        database=values["db"],
        timeout=10,
    )
    try:
        async with connection.transaction(readonly=True):
            read_only = await connection.fetchval("SHOW transaction_read_only")
            table_rows = await connection.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = $1
                  AND table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_name
                """,
                schema,
            )
            tables = [row["table_name"] for row in table_rows]
            road_tables = [
                name for name in tables
                if any(part in name.lower() for part in ROAD_NAME_PARTS)
            ]
            column_rows = await connection.fetch(
                """
                SELECT table_name, column_name, data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = ANY($2::text[])
                ORDER BY table_name, ordinal_position
                """,
                schema,
                road_tables,
            )
            columns: dict[str, list[dict]] = {name: [] for name in road_tables}
            for row in column_rows:
                columns[row["table_name"]].append({
                    "name": row["column_name"],
                    "data_type": row["data_type"],
                    "udt_name": row["udt_name"],
                })
            result = {
                "database": values["db"],
                "schema": schema,
                "transaction_read_only": read_only,
                "road_tables": ({name: len(value) for name, value in columns.items()}
                                if summary_only else columns),
            }
            if search_name:
                version = await connection.fetchval(
                    f'SELECT version_id FROM "{schema}".dim_data_version '
                    "WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
                )
                matches = await connection.fetch(
                    f'SELECT inter_id, inter_name, '
                    "ST_AsGeoJSON(ST_GeomFromText(geom_center, 4326)) AS center_geojson "
                    f'FROM "{schema}".dim_inter_info '
                    "WHERE version_id=$1 AND inter_name ILIKE $2 ORDER BY inter_name, inter_id",
                    version,
                    f"%{search_name}%",
                )
                result["intersection_matches"] = [
                    {
                        "inter_id": row["inter_id"],
                        "name": row["inter_name"],
                        "center_gcj02": json.loads(row["center_geojson"])["coordinates"],
                    }
                    for row in matches
                ]
            if near_gcj02:
                version = await connection.fetchval(
                    f'SELECT version_id FROM "{schema}".dim_data_version '
                    "WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
                )
                lon, lat = near_gcj02
                matches = await connection.fetch(
                    f'SELECT inter_id, inter_name, '
                    "ST_AsGeoJSON(ST_GeomFromText(geom_center, 4326)) AS center_geojson, "
                    "ST_Distance(ST_GeomFromText(geom_center,4326)::geography, "
                    "ST_SetSRID(ST_MakePoint($2,$3),4326)::geography) AS distance_m "
                    f'FROM "{schema}".dim_inter_info '
                    "WHERE version_id=$1 AND ST_DWithin("
                    "ST_GeomFromText(geom_center,4326)::geography, "
                    "ST_SetSRID(ST_MakePoint($2,$3),4326)::geography, $4) "
                    "ORDER BY distance_m, inter_id",
                    version,
                    lon,
                    lat,
                    radius_m,
                )
                result["nearby_intersections"] = [
                    {
                        "inter_id": row["inter_id"],
                        "name": row["inter_name"],
                        "center_gcj02": json.loads(row["center_geojson"])["coordinates"],
                        "distance_m": round(float(row["distance_m"]), 2),
                    }
                    for row in matches
                ]
            if inter_id:
                version = await connection.fetchval(
                    f'SELECT version_id FROM "{schema}".dim_data_version '
                    "WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
                )
                intersection = await connection.fetchrow(
                    f'SELECT inter_id, inter_name, geom_center, geom_boundary '
                    f'FROM "{schema}".dim_inter_info '
                    "WHERE inter_id=$1 AND version_id=$2",
                    inter_id,
                    version,
                )
                link_count = await connection.fetchval(
                    f'SELECT count(*) FROM "{schema}".dim_link_info '
                    "WHERE version_id=$2 AND (f_inter_id=$1 OR t_inter_id=$1)",
                    inter_id,
                    version,
                )
                lane_count = await connection.fetchval(
                    f'SELECT count(*) FROM "{schema}".dim_lane_info '
                    "WHERE version_id=$2 AND (inter_id=$1 OR link_id IN ("
                    f'SELECT link_id FROM "{schema}".dim_link_info '
                    "WHERE version_id=$2 AND (f_inter_id=$1 OR t_inter_id=$1)))",
                    inter_id,
                    version,
                )
                result["requested_intersection"] = {
                    "inter_id": inter_id,
                    "active_version": version,
                    "found": intersection is not None,
                    "name": intersection["inter_name"] if intersection else None,
                    "center_format": (
                        str(intersection["geom_center"]).split("(", 1)[0]
                        if intersection and intersection["geom_center"] else None
                    ),
                    "boundary_format": (
                        str(intersection["geom_boundary"]).split("(", 1)[0]
                        if intersection and intersection["geom_boundary"] else None
                    ),
                    "link_count": link_count,
                    "lane_count": lane_count,
                }
            return result
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--inter-id")
    parser.add_argument("--search-name")
    parser.add_argument("--near-gcj02", nargs=2, type=float, metavar=("LON", "LAT"))
    parser.add_argument("--radius-m", type=float, default=200.0)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--exercise-importer", action="store_true")
    args = parser.parse_args()
    values = _credential_values(args.credentials_file)
    if args.exercise_importer:
        if not args.inter_id:
            parser.error("--exercise-importer requires --inter-id")
        from app.services.ycx_road_import import YcxRoadImporter

        settings = SimpleNamespace(
            ycx_db_host=values["host"], ycx_db_port=int(values["port"]),
            ycx_db_user=values["user"], ycx_db_password=values["pwd"],
            ycx_db_name=values["db"], ycx_db_schema=values["schame"],
        )
        imported = asyncio.run(YcxRoadImporter(settings).import_intersection(args.inter_id))
        result = {
            "transaction_contract": "readonly",
            "inter_id": imported.inter_id,
            "road_data_version": imported.road_data_version,
            "coordinate_system": imported.payload["coordinate_system"],
            "link_count": len(imported.payload["links"]),
            "lane_candidate_count": len(imported.payload["lanes"]),
            "checksum": imported.checksum,
        }
    else:
        result = asyncio.run(
            _audit(
                values,
                args.inter_id,
                args.summary_only,
                args.search_name,
                tuple(args.near_gcj02) if args.near_gcj02 else None,
                args.radius_m,
            )
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
