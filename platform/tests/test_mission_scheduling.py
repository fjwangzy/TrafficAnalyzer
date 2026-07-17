from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from app.models.mission import TelemetrySourceRecord, VideoSourceRecord
from app.services.mission_orchestrator import SourceValidator, schedule_occurrences


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
