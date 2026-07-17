from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.models.metrics import TelemetryMetric, TrafficMetric
from app.services.dashboard_read_model import DashboardReadModel


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingSession:
    def __init__(self):
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()

    async def scalar(self, statement):
        self.statements.append(statement)
        return 0


@pytest.mark.asyncio
async def test_dashboard_latest_metric_queries_reduce_rows_in_postgres_before_materializing():
    session = _CapturingSession()
    service = DashboardReadModel(lambda: session)

    await service._facts(datetime(2026, 7, 17, tzinfo=UTC))

    by_entity = {
        statement.column_descriptions[0].get("entity"): statement
        for statement in session.statements
        if getattr(statement, "column_descriptions", None)
        and statement.column_descriptions[0].get("entity") in {TrafficMetric, TelemetryMetric}
    }
    metric_sql = str(by_entity[TrafficMetric].compile(dialect=postgresql.dialect()))
    telemetry_sql = str(by_entity[TelemetryMetric].compile(dialect=postgresql.dialect()))

    assert "DISTINCT ON (uav_traffic_metrics.inter_id)" in metric_sql
    assert "LIMIT" not in metric_sql
    assert "DISTINCT ON (uav_telemetry_metrics.drone_id)" in telemetry_sql
    assert "LIMIT" not in telemetry_sql
