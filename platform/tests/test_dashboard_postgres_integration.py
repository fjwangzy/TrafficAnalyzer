"""Run with RUN_PG_INTEGRATION=1 against a disposable/local road9 database."""

import os
import uuid

import pytest
from sqlalchemy import delete

from app.core.database import async_session_maker
from app.models.mission import RoadContextSnapshot
from app.services.dashboard_read_model import DashboardReadModel

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires an explicitly selected local PostgreSQL/TimescaleDB database",
)


@pytest.mark.asyncio
async def test_dashboard_reads_verified_coordinates_and_never_invents_kpis():
    marker = uuid.uuid4().hex[:10]
    inter_id = f"INT-I5-{marker}"
    snapshot_id = f"ROADCTX-I5-{marker}"
    async with async_session_maker() as session:
        session.add(RoadContextSnapshot(
            id=snapshot_id,
            inter_id=inter_id,
            road_data_version=f"ROAD-I5-{marker}",
            source="integration_fixture",
            checksum="c" * 64,
            coordinate_reference={"display": "GCJ02", "status": "verified"},
            payload={"intersection": {"name": "I5 集成路口", "center_lat": 36.7, "center_lon": 117.0}},
            quality_status="verified",
        ))
        await session.commit()
    try:
        read_model = DashboardReadModel(async_session_maker)
        intersections = await read_model.intersections()
        row = next(item for item in intersections["items"] if item["inter_id"] == inter_id)
        assert row["map_eligible"] is True
        assert row["lat"] == 36.7
        assert row["lon"] == 117.0
        assert row["risk"] == "unknown"
        filtered = await read_model.intersections(
            quality="unverified", bbox=(116.9, 36.6, 117.1, 36.8), query=marker, limit=1
        )
        assert filtered["project_total"] >= 1
        assert filtered["total"] == 1
        assert filtered["items"][0]["inter_id"] == inter_id
        assert filtered["has_more"] is False
        overview = await read_model.overview()
        assert overview["coverage_ratio"] is None
        assert next(item for item in overview["kpis"] if item["id"] == "monitoring_coverage")["value"] is None
    finally:
        async with async_session_maker() as session:
            await session.execute(delete(RoadContextSnapshot).where(RoadContextSnapshot.id == snapshot_id))
            await session.commit()
