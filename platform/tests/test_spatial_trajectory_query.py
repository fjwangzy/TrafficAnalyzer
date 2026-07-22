from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services.metric_store import PostgresMetricStoreAdapter


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _RowsResult(_EmptyResult):
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_spatial_ready_track_query_filters_before_applying_the_limit():
    store = PostgresMetricStoreAdapter(None)
    captured = []

    async def execute(statement):
        captured.append(statement)
        return _EmptyResult()

    store._execute = execute

    await store.query_tracks(
        "INT_camera_1",
        "all",
        500,
        spatial_ready=True,
        min_gcj02_points=6,
    )

    sql = str(captured[0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
    where_sql, limit_sql = sql.split(" ORDER BY ", maxsplit=1)
    assert "json_array_length(uav_track_events.trajectory_gcj02) >= 6" in where_sql
    assert "uav_track_events.anchor_gcj02 IS NOT NULL" in where_sql
    assert "LIMIT" in limit_sql


@pytest.mark.asyncio
async def test_track_query_uses_typed_gcj02_and_map_lineage_as_public_authority():
    store = PostgresMetricStoreAdapter(None)
    now = datetime.now(UTC)
    row = SimpleNamespace(
        payload={"data": {"coordinate_system": "WGS84", "map_version_id": "stale"}},
        id="track-event-1",
        mission_id="mission-1",
        pipeline_id="pipeline-1",
        source_profile_id="source-1",
        inter_id="intersection-1",
        anchor_gcj02=[117.0, 36.0],
        trajectory_enu_m=[[1.0, 2.0], [3.0, 4.0]],
        trajectory_gcj02=[[117.0, 36.0], [117.0001, 36.0001]],
        map_version_id="map-verified-1",
        matched_lane_key="local:lane-1",
        source_lane_id="geomhash-lane-1",
        matched_link_id="geomhash-link-1",
        movement_key="12",
        map_match_confidence=0.91,
        map_match_quality="verified",
        road_data_version="road-1",
        road_context_status="verified",
        quality_status="verified",
        time_quality="verified",
        started_at=now,
        ended_at=now,
    )

    async def execute(_statement):
        return _RowsResult([row])

    store._execute = execute
    tracks = await store.query_tracks("intersection-1", "all", 1)

    assert tracks[0]["coordinate_system"] == "GCJ02"
    assert tracks[0]["map_version_id"] == "map-verified-1"
    assert tracks[0]["trajectory_gcj02"] == row.trajectory_gcj02
    assert tracks[0]["trajectory_enu_m"] == row.trajectory_enu_m
    assert tracks[0]["matched_lane_key"] == "local:lane-1"
