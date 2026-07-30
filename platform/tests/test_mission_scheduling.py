import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.mission import TelemetrySourceRecord, VideoSourceRecord
from app.schemas.mission import MissionCreate
from app.services.mission_orchestrator import (
    MissionOrchestrator,
    SourceValidator,
    _runtime_missing_grace_expired,
    resolve_tracking_profile,
    schedule_occurrences,
)


def test_once_schedule_preserves_exact_utc_window():
    result = schedule_occurrences(
        {
            "type": "once",
            "start_at": "2026-07-15T08:00:00+08:00",
            "end_at": "2026-07-15T09:00:00+08:00",
        },
        "Asia/Shanghai",
        datetime(2026, 7, 14, tzinfo=UTC),
        datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert result[0].start_at == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert result[0].end_at == datetime(2026, 7, 15, 1, 0, tzinfo=UTC)


def test_weekly_schedule_supports_cross_midnight_and_exceptions():
    result = schedule_occurrences(
        {
            "type": "weekly", "weekdays": [2], "local_start": "23:30:00",
            "local_end": "00:20:00", "effective_from": "2026-07-01",
            "effective_to": None, "exceptions": ["2026-07-22"],
        },
        "Asia/Shanghai",
        datetime(2026, 7, 14, tzinfo=UTC),
        datetime(2026, 7, 30, tzinfo=UTC),
    )
    assert len(result) == 2
    assert all(item.end_at - item.start_at == timedelta(minutes=50) for item in result)


def test_recent_pipeline_runtime_miss_is_not_terminal_until_grace_expires():
    started_at = datetime(2026, 7, 22, 3, 23, 59, tzinfo=UTC)
    mission = SimpleNamespace(
        actual_start_at=started_at,
        scheduled_start_at=started_at - timedelta(seconds=3),
    )

    assert not _runtime_missing_grace_expired(
        mission,
        started_at + timedelta(seconds=3),
        grace_sec=15,
    )
    assert _runtime_missing_grace_expired(
        mission,
        started_at + timedelta(seconds=15),
        grace_sec=15,
    )


def test_manual_mission_accepts_an_explicit_runtime_map_version():
    body = MissionCreate(
        name="runtime map mission",
        drone_id="drone-1",
        source_profile_id="source-1",
        inter_id="INT-1",
        map_version_id="CMV-READY",
        scheduled_end_at=datetime(2026, 7, 25, 12, tzinfo=UTC),
    )

    assert body.map_version_id == "CMV-READY"


def test_tracking_profile_defaults_to_cruise_without_registration_or_map():
    assert resolve_tracking_profile(None) == (
        "hover_cruise_v1",
        "default_hover_cruise",
    )
    assert resolve_tracking_profile("hover_only_legacy") == (
        "hover_only_legacy",
        "explicit_request",
    )


@pytest.mark.asyncio
async def test_mission_pipeline_reports_four_runtime_capabilities_independently():
    runtime_quality = {
        "capabilities": {
            "trajectory": True,
            "geo": True,
            "road": False,
            "tcc": True,
        },
        "capability_reasons": {
            "trajectory": [],
            "geo": [],
            "road": ["lane_verified_map_required"],
            "tcc": [],
        },
    }
    pipeline = SimpleNamespace(
        id="pipe-1",
        desired_status="running",
        observed_status="running",
        topic_name="uav_statistics_1",
        camera_id=1,
        video_port=8101,
        error_message=None,
        flight_phase="cruise_nadir",
        tracking_quality="verified",
        formal_analytics_eligible=False,
        runtime_quality=runtime_quality,
    )
    mission = SimpleNamespace(
        id="mission-1",
        name="mission",
        flight_plan_id=None,
        parent_mission_id=None,
        retry_index=0,
        trigger_type="manual",
        drone_id="drone-1",
        inter_id="INT-1",
        road_data_version="unverified",
        scheduled_start_at=None,
        scheduled_end_at=None,
        actual_start_at=None,
        actual_end_at=None,
        status="running",
        reason_code=None,
        error_message=None,
        pipeline_id=pipeline.id,
        context_snapshot={
            "tracking_profile": "hover_cruise_v1",
            "tracking_profile_selection_reason": "default_hover_cruise",
        },
        created_at=None,
        updated_at=None,
    )

    class Session:
        async def get(self, _model, record_id):
            return pipeline if record_id == pipeline.id else None

    orchestrator = object.__new__(MissionOrchestrator)
    orchestrator._pipeline = SimpleNamespace(get=lambda _pipeline_id: None)

    result = await orchestrator._mission_dict(Session(), mission)

    assert result["pipeline"]["capabilities"] == runtime_quality["capabilities"]
    assert (
        result["pipeline"]["capability_reasons"]
        == runtime_quality["capability_reasons"]
    )
    assert result["pipeline"]["formal_analytics_eligible"] is False


def test_local_source_validation_enforces_allowlist_and_pair_types(tmp_path):
    video_path = tmp_path / "sample.mp4"
    telemetry_path = tmp_path / "sample.srt"
    video_path.write_bytes(b"video")
    telemetry_path.write_text("1\n00:00:00,000 --> 00:00:00,033\nGPS", encoding="utf-8")
    validator = SourceValidator([str(tmp_path)])
    video = VideoSourceRecord(
        id="v", profile_id="p", drone_id="d", mode="local", source_type="mp4",
        location=str(video_path), validation_status="unknown",
    )
    telemetry = TelemetrySourceRecord(
        id="t", profile_id="p", drone_id="d", mode="local", source_type="srt",
        location=str(telemetry_path), validation_status="unknown",
    )
    assert validator.validate(video, telemetry) == ("valid", None)

    video.location = str(Path(tmp_path).parent / "outside.mp4")
    assert validator.validate(video, telemetry)[0] == "invalid"


def test_local_dji_json_txt_source_is_validated_by_content(tmp_path):
    video_path = tmp_path / "sample.mp4"
    telemetry_path = tmp_path / "sample.txt"
    video_path.write_bytes(b"video")
    telemetry_path.write_text(json.dumps({
        "data": [{
            "time": "2026-06-25 08:00:00.000",
            "value": json.dumps({"latitude": 36.7, "longitude": 117.0}),
        }]
    }), encoding="utf-8")
    validator = SourceValidator([str(tmp_path)])
    video = VideoSourceRecord(
        id="v-json", profile_id="p-json", drone_id="d", mode="local", source_type="mp4",
        location=str(video_path), validation_status="unknown",
    )
    telemetry = TelemetrySourceRecord(
        id="t-json", profile_id="p-json", drone_id="d", mode="local", source_type="file",
        location=str(telemetry_path), validation_status="unknown", config={},
    )
    assert validator.validate(video, telemetry) == ("valid", None)

    telemetry_path.write_text('{"data": []}', encoding="utf-8")
    status, code = validator.validate(video, telemetry)
    assert status == "invalid"
    assert code == "telemetry_json_empty"


def test_local_dji_json_extension_and_invalid_json_are_handled(tmp_path):
    video_path = tmp_path / "sample.mp4"
    telemetry_path = tmp_path / "sample.json"
    video_path.write_bytes(b"video")
    telemetry_path.write_text(json.dumps({
        "data": [{
            "timestamp": 1782345600.0,
            "latitude": 36.7,
            "longitude": 117.0,
        }]
    }), encoding="utf-8")
    validator = SourceValidator([str(tmp_path)])
    video = VideoSourceRecord(
        id="v-json-extension", profile_id="p-json-extension", drone_id="d", mode="local",
        source_type="mp4", location=str(video_path), validation_status="unknown",
    )
    telemetry = TelemetrySourceRecord(
        id="t-json-extension", profile_id="p-json-extension", drone_id="d", mode="local",
        source_type="file", location=str(telemetry_path), validation_status="unknown", config={},
    )

    assert validator.validate(video, telemetry) == ("valid", None)

    telemetry_path.write_text("{not valid JSON", encoding="utf-8")
    assert validator.validate(video, telemetry) == ("invalid", "telemetry_json_invalid")


def test_local_source_outside_allowlist_reports_stable_error_code(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    video_path = outside / "sample.mp4"
    telemetry_path = allowed / "sample.txt"
    video_path.write_bytes(b"video")
    telemetry_path.write_text(json.dumps({
        "data": [{"timestamp": 1782345600.0}]
    }), encoding="utf-8")
    validator = SourceValidator([str(allowed)])
    video = VideoSourceRecord(
        id="v-outside", profile_id="p-outside", drone_id="d", mode="local",
        source_type="mp4", location=str(video_path), validation_status="unknown",
    )
    telemetry = TelemetrySourceRecord(
        id="t-outside", profile_id="p-outside", drone_id="d", mode="local",
        source_type="file", location=str(telemetry_path), validation_status="unknown", config={},
    )

    assert validator.validate(video, telemetry) == ("invalid", "source_outside_allowlist")


@pytest.mark.asyncio
async def test_manual_mission_runtime_params_allow_detection_without_road_context():
    video = VideoSourceRecord(
        id="video-1", profile_id="source-1", drone_id="drone-1", mode="local",
        source_type="mp4", location="test_videos/demo.mp4", validation_status="valid",
    )
    telemetry = TelemetrySourceRecord(
        id="telemetry-1", profile_id="source-1", drone_id="drone-1", mode="local",
        source_type="srt", location="test_videos/demo.srt", validation_status="valid", config={},
    )

    class Session:
        async def get(self, model, record_id):
            return video if model is VideoSourceRecord and record_id == video.id else telemetry

        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    class RoadContextMustNotBeUsed:
        async def get(self, *_args):
            raise AssertionError("unbound missions must not resolve road context")

    orchestrator = object.__new__(MissionOrchestrator)
    orchestrator._road_context = RoadContextMustNotBeUsed()
    mission = SimpleNamespace(
        id="mission-1", drone_id="drone-1", inter_id="INT-1",
        road_data_version="unverified", video_source_id=video.id,
        telemetry_source_id=telemetry.id, context_snapshot={"quality_status": "unverified"},
    )

    params = await orchestrator._runtime_params(Session(), mission)

    assert params["runtime_map_bundle"] is None
    assert params["road_context_status"] == "missing"
    assert params["quality_status"] == "degraded"
    assert params["video_src"] == "test_videos/demo.mp4"
