from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings


def test_replay_v2_runtime_profile_uses_v2_topics_with_full_control_plane():
    settings = Settings(
        app_runtime_profile="replay_v2",
        kafka_consumer_group="unsafe-shared-group",
        kafka_topics_pattern="uav_.*",
        lane_annotation_auto_tasks_enabled=True,
    )

    assert settings.kafka_consumer_group == "uav-platform-replay-v2"
    assert settings.kafka_topics_pattern == (
        r"^(?:uav_statistics|uav_track_complete|uav_conflicts|uav_telemetry|uav_missions|uav_track_relations|uav_enforcement_clues|uav_system_metrics)$"
    )
    assert settings.control_plane_writes_enabled is True
    assert settings.lane_annotation_auto_tasks_enabled is True


def test_replay_v2_runtime_keeps_mission_control_reads_and_writes_available(monkeypatch):
    from app.main import app, settings
    from app.middleware import auth as auth_middleware
    from app.services.auth_service import create_access_token

    class MissionOrchestrator:
        async def list_drones(self):
            return [{"id": "UAV-REPLAY-V2"}]

        async def stop_mission(self, mission_id, reason):
            return {"id": mission_id, "status": "cancelled", "reason": reason}

    async def active_user(_payload):
        return True

    monkeypatch.setattr(settings, "app_runtime_profile", "replay_v2")
    monkeypatch.setattr(auth_middleware, "_is_active_user", active_user)
    monkeypatch.setattr(
        app.state, "mission_orchestrator", MissionOrchestrator(), raising=False
    )
    client = TestClient(app)
    token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})

    read_response = client.get(
        "/api/v1/drones", headers={"Authorization": f"Bearer {token}"}
    )
    write_response = client.post(
        "/api/v1/missions/MSN-REPLAY-V2/stop",
        json={"reason": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert read_response.status_code == 200
    assert [item["id"] for item in read_response.json()] == ["UAV-REPLAY-V2"]
    assert write_response.status_code == 200
    assert write_response.json()["status"] == "cancelled"


def test_replay_v2_pipeline_children_use_v2_storage_profile(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.pipeline_manager import PipelineManager

    monkeypatch.setattr(settings, "app_runtime_profile", "replay_v2")
    manager = PipelineManager(project_root=tmp_path)

    assert manager._executor._extra_env["TRAJECTORY_STORAGE_PROFILE"] == "replay_v2"
    assert manager._topic_for_runtime(None, 10, "SRC-REPLAY-V2") == (
        "uav_statistics"
    )


@pytest.mark.asyncio
async def test_replay_readiness_detects_missing_repository_without_changing_live_readiness(monkeypatch):
    from app.main import app, readiness_check, settings

    for key, value in {
        "db_available": True,
        "kafka_service": SimpleNamespace(_running=True, _consumer=object()),
        "metric_store": SimpleNamespace(capabilities=AsyncMock(return_value={"timescaledb": True})),
        "pipeline_manager": SimpleNamespace(get_active_count=lambda: 0),
        "replay_repository": None,
    }.items():
        monkeypatch.setattr(app.state, key, value, raising=False)
    monkeypatch.setattr(settings, "app_runtime_profile", "replay_v2")
    missing = await readiness_check()
    assert missing["status"] == "degraded"
    assert missing["runtime_profile"] == "replay_v2"
    assert missing["services"]["trajectory_replay"] == "not_configured"

    monkeypatch.setattr(app.state, "replay_repository", object())
    assert (await readiness_check())["status"] == "ready"
    monkeypatch.setattr(app.state, "replay_repository", None)
    monkeypatch.setattr(settings, "app_runtime_profile", "live")
    assert (await readiness_check())["status"] == "ready"
