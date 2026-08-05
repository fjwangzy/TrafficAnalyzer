from app.core.config import Settings
from fastapi.testclient import TestClient


def test_replay_v2_runtime_profile_forces_shadow_consumer_and_disables_control_writers():
    settings = Settings(
        app_runtime_profile="replay_v2",
        kafka_consumer_group="unsafe-shared-group",
        kafka_topics_pattern="uav_.*",
        lane_annotation_auto_tasks_enabled=True,
    )

    assert settings.kafka_consumer_group == "uav-platform-replay-v2"
    assert settings.kafka_topics_pattern == (
        r"^uav_replay_v2_(?:statistics|track_complete|conflicts|telemetry|mission)_"
        r"[A-Za-z0-9._-]+$"
    )
    assert settings.control_plane_writes_enabled is False
    assert settings.lane_annotation_auto_tasks_enabled is False


def test_replay_v2_runtime_rejects_control_plane_mutations_but_keeps_auth(monkeypatch):
    from app.main import app, settings

    monkeypatch.setattr(settings, "app_runtime_profile", "replay_v2")
    client = TestClient(app)

    blocked = client.post("/api/v1/missions/not-present/stop", json={"reason": "test"})
    auth = client.post("/api/v1/auth/login", json={})

    assert blocked.status_code == 405
    assert blocked.json()["runtime_profile"] == "replay_v2"
    assert auth.status_code != 405
