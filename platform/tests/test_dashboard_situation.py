"""Doris-only typical situation: monthly/directional grain, cache and geometry."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.deployment_diagnostics import DiagnosticError
from app.services import dashboard_situation as situation


def _settings(**overrides):
    return SimpleNamespace(doris_database="ycx_xc", ycx_road_version="confirmed", **overrides)


@pytest.fixture
def queries(monkeypatch):
    calls = []

    async def query(settings, sql, *args):
        calls.append((sql, args))
        assert sql.startswith("SELECT ") and 'road11' not in sql and '$1' not in sql
        if "MAX(i.stat_month)" in sql:
            assert args == ("confirmed",)
            return [{"stat_month": "202609"}]
        if "DISTINCT day_of_week" in sql:
            assert args == ("202609", "confirmed")
            return [{"day_of_week": 2}, {"day_of_week": 5}]
        if "dim_inter_info" in sql:
            assert args[:2] == ("202609", "confirmed")
            assert "MAX(avg_jam_delay_index_avg)" in sql and "GROUP BY inter_id" in sql
            return [{
                "inter_id": "i1", "inter_name": "路口", "longitude": 117, "latitude": 36.7,
                "saturation_max": None, "saturation_avg": None, "level_of_service": None,
                "delay_index": 2.1, "avg_speed_kmh": 18, "unbalance_index": None,
                "update_time": datetime(2026, 10, 9, 13),
            }, {
                "inter_id": "gray", "inter_name": "空时槽", "longitude": 117.01, "latitude": 36.71,
                "saturation_max": None, "saturation_avg": None, "level_of_service": None,
                "delay_index": None, "avg_speed_kmh": None, "unbalance_index": None, "update_time": None,
            }]
        if "dim_link_info" in sql:
            assert args[:2] == ("202609", "202609")
            assert "l.version_id=%s" in sql
            return [{
                "inter_id": "i1", "link_id": "l1", "link_name": "道路", "dir8_code": "2",
                "dir8_label": None, "delay_index": 2.2, "stop_time_sec": 42,
                "avg_nostop_speed": 18.4, "queue_len_est_m": None,
                "geometry_wkt": "LINESTRING(117 36.7,117.01 36.7)", "update_time": None,
            }]
        raise AssertionError(sql)

    monkeypatch.setattr(situation, "query", query)
    return calls


def test_geometry_paths_accept_lines_and_reject_invalid_coordinates():
    assert situation._paths('{"type":"LineString","coordinates":[[117,36],[117.1,36.1]]}') == [[[117.0,36.0],[117.1,36.1]]]
    assert situation._paths({"type": "MultiLineString", "coordinates": [[[117,36],[117.1,36.1]]]}) == [[[117.0,36.0],[117.1,36.1]]]
    assert situation._paths('{invalid') == []
    assert situation._paths({"type": "LineString", "coordinates": [[999,36],[117,36]]}) == []


@pytest.mark.asyncio
async def test_situation_is_doris_only_preserves_missing_fields_and_monthly_grain(queries):
    result = await situation.DashboardSituationReadModel(_settings()).situation(day_of_week=5, step_index=95)
    assert len(queries) == 4
    assert result['source']['database'] == result['source']['road_schema'] == 'ycx_xc'
    assert result['source']['stat_month'] == '202609'
    assert result['source']['intersection_metric'] == 'delay_index'
    assert result['time_profile']['start_time'] == '07:55'
    assert result['time_profile']['available_days'] == [2, 5]
    assert result['intersections'][0]['status'] == 'congested'
    assert result['intersections'][0]['saturation_max'] is None
    assert result['intersections'][1]['status'] == 'missing'
    assert result['segments'][0]['status'] == 'congested'
    assert result['segments'][0]['paths_gcj02'] == [[[117.0,36.7],[117.01,36.7]]]
    assert result['segments'][0]['queue_len_est_m'] is None
    assert result['summary']['congested'] == result['summary']['missing'] == 1


@pytest.mark.asyncio
async def test_cache_is_defensive_bounded_and_stale_only_for_same_slot(monkeypatch, queries):
    clock = [0.0]
    model = situation.DashboardSituationReadModel(_settings(), monotonic=lambda: clock[0], cache_limit=2)
    first = await model.situation(day_of_week=5, step_index=95)
    first['intersections'].clear()
    hit = await model.situation(day_of_week=5, step_index=95)
    assert len(queries) == 4 and len(hit['intersections']) == 2
    assert hit['cache'] == {'status':'hit','stale':False}
    clock[0] = 301
    async def fail(*args): raise DiagnosticError('DORIS_TIMEOUT','超时','稍后重试')
    monkeypatch.setattr(situation, 'query', fail)
    stale = await model.situation(day_of_week=5, step_index=95)
    assert stale['cache']['stale'] is True
    with pytest.raises(DiagnosticError, match='DORIS_TIMEOUT'):
        await model.situation(day_of_week=5, step_index=96)
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_cache_evicts_oldest_slot(queries):
    model = situation.DashboardSituationReadModel(_settings(), cache_limit=2)
    for step in range(3): await model.situation(day_of_week=1, step_index=step)
    assert list(model._cache) == [('confirmed:202609',1,1),('confirmed:202609',1,2)]


@pytest.mark.asyncio
async def test_no_common_month_does_not_mix_stores(monkeypatch):
    async def query(*args): return [{'stat_month': None}]
    monkeypatch.setattr(situation,'query',query)
    with pytest.raises(DiagnosticError,match='DORIS_METRICS_EMPTY'):
        await situation.DashboardSituationReadModel(_settings()).situation(day_of_week=1,step_index=0)
