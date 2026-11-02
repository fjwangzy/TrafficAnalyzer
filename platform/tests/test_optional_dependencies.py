"""Optional production dependencies never change canonical data or invent a road version."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest

from app.core.deployment_diagnostics import DiagnosticError
from app.core.ycx_connection import active_road_version
from app.core.timeseries import configure_timescale
from app.services.dashboard_situation import DashboardSituationReadModel


@pytest.mark.asyncio
async def test_explicit_version_bypasses_missing_metadata_without_max_fallback():
    connection = SimpleNamespace(fetchval=AsyncMock(side_effect=asyncpg.UndefinedTableError("private-details")))
    assert await active_road_version(connection, SimpleNamespace(ycx_road_version="confirmed-v1")) == "confirmed-v1"
    assert await active_road_version(connection, SimpleNamespace(), "requested-v2") == "requested-v2"
    connection.fetchval.assert_not_called()
    with pytest.raises(DiagnosticError, match="YCX_VERSION_UNAVAILABLE"):
        await active_road_version(connection, SimpleNamespace())
    assert "MAX(" not in connection.fetchval.call_args.args[0]


def test_timescale_conversion_does_nothing_if_extension_absent():
    class Connection:
        def scalar(self, query): return False
        def execute(self, *args): raise AssertionError("No DDL without installed extension")
    assert configure_timescale(Connection(), replay_v2=True) is False


@pytest.mark.asyncio
async def test_optional_timescale_does_not_fail_ready_but_remains_visible(monkeypatch):
    from app import main
    from app.core.config import Settings
    monkeypatch.setattr(main, "settings", Settings(_env_file=None, db_timescale_required=False))
    state = main.app.state
    for name,value in {
        "db_available":True,
        "kafka_service":SimpleNamespace(_running=True, _consumer=object()),
        "metric_store":SimpleNamespace(capabilities=AsyncMock(return_value={"timescaledb":False})),
        "pipeline_manager":SimpleNamespace(get_active_count=lambda:0),
    }.items(): monkeypatch.setattr(state, name, value, raising=False)
    result = await main.readiness_check()
    assert result["services"]["timescaledb"] == "degraded"
    assert result["status"] == "ready"


@pytest.mark.asyncio
async def test_disabled_road_layer_never_opens_dependencies():
    model = DashboardSituationReadModel(SimpleNamespace(ycx_db_schema="road11", ycx_metrics_schema="xianchang", road_features_enabled=False))
    with pytest.raises(DiagnosticError, match="ROAD_FEATURES_DISABLED"):
        await model.situation(day_of_week=1, step_index=0)


def test_disabled_calibration_api_rejects_direct_calls_without_database(monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from app.main import require_road_features, settings
    from app.api.v1.calibration import router
    monkeypatch.setattr(settings, "road_features_enabled", False)
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(require_road_features)])
    with TestClient(app) as client:
        response = client.post("/calibration/road-context/import-ycx", json={"inter_id":"fixture"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ROAD_FEATURES_DISABLED"


def test_disabled_matching_ignores_even_a_stale_invalid_bundle(monkeypatch):
    from utils_local.runtime_map import load_runtime_map_bundle
    monkeypatch.setenv("ROAD_FEATURES_ENABLED", "false")
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", "invalid JSON must never be loaded")
    assert load_runtime_map_bundle() is None
