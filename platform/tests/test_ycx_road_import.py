"""Read-only Doris roads preserve canonical geometry and opaque source IDs."""
from types import SimpleNamespace

import pytest

from app.services import ycx_road_import


@pytest.mark.asyncio
@pytest.mark.parametrize('has_links', [True, False])
async def test_import_uses_only_doris_binds_ids_and_handles_empty_link_scope(monkeypatch, has_links):
    calls = []
    async def query(settings, sql, *args):
        calls.append((sql,args))
        assert sql.startswith('SELECT ') and '$' not in sql and 'ANY(' not in sql
        if 'dim_inter_info' in sql:
            return [{'inter_id': args[0], 'inter_name':'测试路口','geom_center':'POINT(117 36)', 'geom_boundary':None}]
        if 'dim_link_info' in sql:
            return [{'link_id':'opaque-link','road_name':'路','f_inter_id':'from','t_inter_id':args[1],
                'f_angle':0,'t_angle':180,'lane_num':1,'c_lane_num':1,'lane_info':'C','road_level':'2',
                'formway':'1','max_speed':40,'turn_move':'straight','geom':'LINESTRING(116.999 36,117 36)'}] if has_links else []
        if 'dim_lane_info' in sql:
            assert ('link_id IN (%s)' in sql) is has_links
            assert args == ('confirmed', "literal' id", *(['opaque-link'] if has_links else []))
            return [{'lane_id':'opaque-lane','link_id':'opaque-link','lane_no':1,'lane_func_code':'C',
                'width':3.5,'length':30,'inter_id':args[1],'turn_move':'straight','geom':'LINESTRING(116.999 36,117 36)'}]
        raise AssertionError(sql)
    monkeypatch.setattr(ycx_road_import,'query',query)
    imported = await ycx_road_import.YcxRoadImporter(SimpleNamespace(doris_database='ycx_xc',ycx_road_version='confirmed')).import_intersection("literal' id")
    assert len(calls) == 3
    assert all("literal' id" not in sql for sql,_ in calls)
    assert imported.anchor_gcj02 == [117,36]
    assert imported.payload['source_id_semantics'] == 'opaque_geomhash'
    assert imported.payload['lanes'][0]['lane_id'] == 'opaque-lane'
    assert imported.geometry_enu_m['lane_candidates']['opaque-lane']['coordinates'][-1] == [0.0,0.0]
    assert imported.payload['lane_geometry_authority'] == 'candidate_only'


@pytest.mark.asyncio
async def test_nearby_binds_center_radius_and_preserves_version(monkeypatch):
    async def query(settings,sql,*args):
        assert 'ST_Distance_Sphere' in sql and 'LIMIT 20' in sql
        assert args == ('confirmed',117.0,36.0,250.0,117.0,36.0)
        return [{'inter_id':'opaque','inter_name':None,'longitude':117,'latitude':36}]
    monkeypatch.setattr(ycx_road_import,'query',query)
    result = await ycx_road_import.YcxRoadImporter(SimpleNamespace(doris_database='ycx_xc',ycx_road_version='confirmed')).nearby_intersections([117,36])
    assert result[0]['inter_id'] == 'opaque' and result[0]['road_data_version'] == 'confirmed'


@pytest.mark.asyncio
async def test_import_api_reports_missing_doris_id_as_404_without_writes(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.api.v1 import calibration
    monkeypatch.setattr(calibration, '_require_admin', lambda request: None)
    monkeypatch.setattr(calibration, '_lock_intersection', AsyncMock())
    monkeypatch.setattr(calibration, 'YcxRoadImporter', lambda settings: SimpleNamespace(
        import_intersection=AsyncMock(side_effect=LookupError('missing'))))
    with pytest.raises(HTTPException) as error:
        await calibration.import_ycx_road_context(calibration.YcxRoadImportPayload(inter_id='missing'), object(), object())
    assert error.value.status_code == 404
    assert error.value.detail['code'] == 'DORIS_INTERSECTION_NOT_FOUND'
