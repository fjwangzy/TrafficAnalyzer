import pytest
from sqlalchemy.dialects import postgresql

from app.services.metric_store import PostgresMetricStoreAdapter


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


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
        min_world_points=6,
    )

    sql = str(captured[0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
    where_sql, limit_sql = sql.split(" ORDER BY ", maxsplit=1)
    assert "json_array_length(uav_track_events.trajectory_world_m) >= 6" in where_sql
    assert "uav_track_events.world_anchor_lat_lon IS NOT NULL" in where_sql
    assert "LIMIT" in limit_sql
