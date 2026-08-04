from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.dashboard_situation import DashboardSituationReadModel, _paths


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.readonly_transactions += 1

    async def __aexit__(self, *_args):
        return False


class _Connection:
    def __init__(self):
        self.readonly_transactions = 0
        self.closed = False
        self.fetch_calls = []

    def transaction(self, *, readonly):
        assert readonly is True
        return _Transaction(self)

    async def fetchval(self, query, *_args):
        assert "dim_data_version" in query
        return "20260501"

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        if "DISTINCT day_of_week" in query:
            return [{"day_of_week": 1}, {"day_of_week": 2}, {"day_of_week": 5}]
        if "dws_inter_evaluation_5min_mm" in query:
            return [{
                "inter_id": "INT-1",
                "inter_name": "测试路口",
                "longitude": 117.01,
                "latitude": 36.7,
                "saturation_max": 0.96,
                "saturation_avg": 0.72,
                "unbalance_index": 0.18,
                "level_of_service": "E",
                "update_time": datetime(2026, 8, 3, 18, 0),
            }]
        if "dws_inter_link_status_5min_mm" in query:
            return [{
                "inter_id": "INT-1",
                "link_id": "LINK-1",
                "link_name": "测试路段",
                "dir8_code": 2,
                "dir8_label": "东进口",
                "delay_index": 2.1,
                "stop_time_sec": 42.0,
                "avg_nostop_speed": 18.4,
                "queue_len_est_m": 96.0,
                "geometry_geojson": '{"type":"LineString","coordinates":[[117.0,36.7],[117.01,36.7]]}',
                "update_time": datetime(2026, 8, 3, 18, 5),
            }]
        raise AssertionError(query)

    async def close(self):
        self.closed = True


def _settings(**overrides):
    values = {
        "ycx_db_host": "server",
        "ycx_db_port": 5432,
        "ycx_db_user": "reader",
        "ycx_db_password": "secret",
        "ycx_db_name": "ycx",
        "ycx_db_schema": "road9",
        "ycx_metrics_schema": "xianchang",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_situation_rejects_untrusted_schema_identifiers():
    with pytest.raises(ValueError, match="YCX_METRICS_SCHEMA"):
        DashboardSituationReadModel(_settings(ycx_metrics_schema='xianchang"; DROP SCHEMA road9; --'))

    with pytest.raises(ValueError, match="YCX_DB_SCHEMA"):
        DashboardSituationReadModel(_settings(ycx_db_schema="road9.public"))


def test_situation_converts_linestring_and_multilinestring_geometry():
    assert _paths({"type": "LineString", "coordinates": [[117, 36.7], [117.1, 36.8]]}) == [
        [[117.0, 36.7], [117.1, 36.8]],
    ]
    assert _paths({"type": "MultiLineString", "coordinates": [
        [[117, 36.7], [117.1, 36.8]],
        [[117.1, 36.8], [117.2, 36.9]],
    ]}) == [
        [[117.0, 36.7], [117.1, 36.8]],
        [[117.1, 36.8], [117.2, 36.9]],
    ]


@pytest.mark.asyncio
async def test_situation_returns_readonly_server_intersections_and_segments():
    connection = _Connection()

    async def connect(**_kwargs):
        return connection

    model = DashboardSituationReadModel(
        _settings(),
        connect=connect,
    )

    result = await model.situation(day_of_week=2, step_index=120)

    assert connection.readonly_transactions == 1
    assert connection.closed is True
    intersection_query, intersection_args = next(
        call for call in connection.fetch_calls
        if 'dws_inter_evaluation_5min_mm' in call[0] and 'DISTINCT day_of_week' not in call[0]
    )
    segment_query, segment_args = next(
        call for call in connection.fetch_calls if 'dws_inter_link_status_5min_mm' in call[0]
    )
    assert intersection_args == ('20260501', 2, 120)
    assert segment_args == ('20260501', 2, 120)
    assert intersection_query.count('COALESCE(is_deleted, 0) = 0') == 2
    assert segment_query.count('COALESCE(is_deleted, 0) = 0') == 2
    assert result["source"]["road_version"] == "20260501"
    assert result["time_profile"] == {
        "kind": "typical_5min",
        "timezone": "Asia/Shanghai",
        "day_of_week": 2,
        "step_index": 120,
        "start_time": "10:00",
        "available_days": [1, 2, 5],
    }
    assert result["intersections"] == [pytest.approx({
        "inter_id": "INT-1",
        "name": "测试路口",
        "lon": 117.01,
        "lat": 36.7,
        "saturation_max": 0.96,
        "saturation_avg": 0.72,
        "unbalance_index": 0.18,
        "level_of_service": "E",
        "status": "oversaturated",
        "updated_at": "2026-08-03T18:00:00",
    })]
    assert result["segments"][0]["status"] == "congested"
    assert result["segments"][0]["paths_gcj02"] == [[[117.0, 36.7], [117.01, 36.7]]]
    assert result["summary"] == {
        "intersections_total": 1,
        "good": 0,
        "near_saturated": 0,
        "oversaturated": 1,
        "missing": 0,
        "segments_total": 1,
        "smooth_segments": 0,
        "slow_segments": 0,
        "congested_segments": 1,
        "missing_segments": 0,
    }
    assert result["cache"]["status"] == "miss"


@pytest.mark.asyncio
async def test_situation_reuses_fresh_cache_and_serves_stale_same_slot_on_failure():
    clock = [0.0]
    connect_calls = [0]
    fail = [False]

    async def connect(**_kwargs):
        connect_calls[0] += 1
        if fail[0]:
            raise OSError("server unavailable")
        return _Connection()

    model = DashboardSituationReadModel(
        _settings(),
        connect=connect,
        monotonic=lambda: clock[0],
        cache_ttl_sec=300,
        cache_limit=64,
    )

    first = await model.situation(day_of_week=2, step_index=120)
    second = await model.situation(day_of_week=2, step_index=120)

    assert first["cache"]["status"] == "miss"
    assert second["cache"] == {"status": "hit", "stale": False}
    assert connect_calls[0] == 1

    clock[0] = 301.0
    fail[0] = True
    stale = await model.situation(day_of_week=2, step_index=120)

    assert connect_calls[0] == 2
    assert stale["cache"]["status"] == "stale"
    assert stale["cache"]["stale"] is True
    assert stale["cache"]["reason"] == "server_unavailable"


@pytest.mark.asyncio
async def test_situation_requires_external_readonly_connection_settings():
    model = DashboardSituationReadModel(_settings(ycx_db_host="", ycx_db_user=""))

    with pytest.raises(OSError, match="YCX read-only connection is not configured"):
        await model.situation(day_of_week=1, step_index=0)


@pytest.mark.asyncio
async def test_situation_rejects_missing_enabled_road_version_and_closes_connection():
    class NoVersionConnection(_Connection):
        async def fetchval(self, query, *_args):
            assert 'is_enable = 1' in query
            return None

    connection = NoVersionConnection()

    async def connect(**_kwargs):
        return connection

    model = DashboardSituationReadModel(_settings(), connect=connect)

    with pytest.raises(OSError, match="no enabled road data version"):
        await model.situation(day_of_week=1, step_index=0)
    assert connection.readonly_transactions == 1
    assert connection.closed is True


@pytest.mark.asyncio
async def test_situation_keeps_scope_gray_for_an_empty_slot_and_filters_invalid_map_data():
    class EmptySlotConnection(_Connection):
        async def fetch(self, query, *args):
            self.fetch_calls.append((query, args))
            if 'DISTINCT day_of_week' in query:
                return [{"day_of_week": 5}]
            if 'dws_inter_evaluation_5min_mm' in query:
                return [
                    {
                        "inter_id": "INT-GRAY", "inter_name": "暂无指标路口",
                        "longitude": 117.0, "latitude": 36.7,
                        "saturation_max": None, "saturation_avg": None,
                        "unbalance_index": None, "level_of_service": None,
                        "update_time": None,
                    },
                    {
                        "inter_id": "INT-BAD", "inter_name": "无效坐标",
                        "longitude": 999.0, "latitude": 36.7,
                        "saturation_max": 0.9, "saturation_avg": 0.8,
                        "unbalance_index": 0.1, "level_of_service": "D",
                        "update_time": None,
                    },
                ]
            if 'dws_inter_link_status_5min_mm' in query:
                return [
                    {
                        "inter_id": "INT-GRAY", "link_id": "LINK-GRAY",
                        "link_name": "暂无指标路段", "dir8_code": None,
                        "dir8_label": None, "delay_index": None,
                        "stop_time_sec": None, "avg_nostop_speed": None,
                        "queue_len_est_m": None,
                        "geometry_geojson": '{"type":"LineString","coordinates":[[117,36.7],[117.1,36.8]]}',
                        "update_time": None,
                    },
                    {
                        "inter_id": "INT-GRAY", "link_id": "LINK-EMPTY",
                        "link_name": "空几何", "dir8_code": None,
                        "dir8_label": None, "delay_index": 1.2,
                        "stop_time_sec": None, "avg_nostop_speed": None,
                        "queue_len_est_m": None,
                        "geometry_geojson": '{"type":"LineString","coordinates":[]}',
                        "update_time": None,
                    },
                ]
            raise AssertionError(query)

    async def connect(**_kwargs):
        return EmptySlotConnection()

    result = await DashboardSituationReadModel(_settings(), connect=connect).situation(
        day_of_week=5,
        step_index=0,
    )

    assert [row["inter_id"] for row in result["intersections"]] == ["INT-GRAY"]
    assert result["intersections"][0]["status"] == "missing"
    assert [row["link_id"] for row in result["segments"]] == ["LINK-GRAY"]
    assert result["segments"][0]["status"] == "missing"
    assert result["summary"]["missing"] == 1
    assert result["summary"]["missing_segments"] == 1


@pytest.mark.asyncio
async def test_situation_first_timeout_has_no_cross_slot_fallback():
    async def connect(**_kwargs):
        raise TimeoutError("server timeout")

    model = DashboardSituationReadModel(_settings(), connect=connect)

    with pytest.raises(TimeoutError, match="server timeout"):
        await model.situation(day_of_week=5, step_index=95)


@pytest.mark.asyncio
async def test_situation_cache_evicts_oldest_slot_at_configured_limit():
    async def connect(**_kwargs):
        return _Connection()

    model = DashboardSituationReadModel(
        _settings(),
        connect=connect,
        cache_limit=2,
    )

    await model.situation(day_of_week=1, step_index=0)
    await model.situation(day_of_week=1, step_index=1)
    await model.situation(day_of_week=1, step_index=2)

    assert list(model._cache) == [
        ('20260501', 1, 1),
        ('20260501', 1, 2),
    ]
