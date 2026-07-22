import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.services import ycx_road_import


class _ReadonlyConnection:
    def __init__(self):
        self.queries = []
        self.closed = False
        self.readonly = None

    @asynccontextmanager
    async def transaction(self, *, readonly=False):
        self.readonly = readonly
        yield

    async def fetchval(self, sql, *args):
        self.queries.append(sql)
        return "20260501"

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        return {
            "inter_id": args[0], "inter_name": "测试路口",
            "center_geojson": json.dumps({"type": "Point", "coordinates": [117.0, 36.0]}),
            "boundary_geojson": None,
        }

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "FROM dim_link_info" in sql:
            return [{
                "link_id": "011-link", "road_name": "测试路", "f_inter_id": "from",
                "t_inter_id": args[0], "f_angle": 0, "t_angle": 180,
                "lane_num": 1, "c_lane_num": 1, "lane_info": "C",
                "road_level": "2", "formway": 1, "max_speed": 40,
                "turn_move": "straight",
                "geom_geojson": json.dumps({"type": "LineString", "coordinates": [[116.999, 36.0], [117.0, 36.0]]}),
            }]
        return [{
            "lane_id": "011-lane", "link_id": "011-link", "lane_no": 1,
            "lane_func_code": "C", "width": 3.5, "length": 30,
            "inter_id": args[0], "turn_move": "straight",
            "geom_geojson": json.dumps({"type": "LineString", "coordinates": [[116.999, 36.0], [117.0, 36.0]]}),
        }]

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_ycx_import_is_readonly_postgis_and_keeps_geomhash_ids_opaque(monkeypatch):
    connection = _ReadonlyConnection()
    connect_args = {}

    async def connect(**kwargs):
        connect_args.update(kwargs)
        return connection

    monkeypatch.setattr(ycx_road_import.asyncpg, "connect", connect)
    settings = SimpleNamespace(
        ycx_db_host="readonly.example", ycx_db_port=5432,
        ycx_db_user="reader", ycx_db_password="secret",
        ycx_db_name="ycx", ycx_db_schema="road9",
    )
    imported = await ycx_road_import.YcxRoadImporter(settings).import_intersection(
        "011wwe0z19700001"
    )

    assert connection.readonly is True
    assert connection.closed is True
    assert connect_args["server_settings"]["search_path"] == "road9,public"
    assert any("ST_GeomFromText" in query for query in connection.queries)
    assert not any(
        token in query.upper()
        for query in connection.queries
        for token in (" INSERT ", " UPDATE ", " DELETE ", " TRUNCATE ")
    )
    assert imported.payload["source_id_semantics"] == "opaque_geomhash"
    assert imported.payload["links"][0]["link_id"] == "011-link"
    assert imported.payload["lanes"][0]["lane_id"] == "011-lane"
    assert imported.payload["lanes"][0]["geometry_source"] == "link_offset_derived"
