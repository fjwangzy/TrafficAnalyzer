from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib.util
import json
from pathlib import Path

import pytest

from app.models.mission import TelemetrySourceRecord, VideoSourceRecord
from app.core.config import settings
from app.services.mission_orchestrator import MissionOrchestrator, SourceValidator
from utils_local.coordinates import wgs84_to_gcj02


@pytest.mark.parametrize("kind", ["srt", "file"])
def test_recording_position_uses_source_telemetry_without_a_detector_or_road_context(tmp_path, kind):
    path = tmp_path / ("telemetry.srt" if kind == "srt" else "telemetry.json")
    if kind == "srt":
        path.write_text("1\n00:00:01,000 --> 00:00:01,033\nFrameCnt: 1 2026-10-19 08:00:01.000\n[latitude: 36.7] [longitude: 117.0] [rel_alt: 130]\n")
    else:
        path.write_text(json.dumps([{"timestamp": 0, "longitude": 116, "latitude": 36},
                                    {"timestamp": 1, "longitude": 117, "latitude": 36.7}]))
    source = SimpleNamespace(mode="local", source_type=kind, location=str(path), config={"time_offset_sec": 1})
    result = SourceValidator([str(tmp_path)]).recording_position(source)
    lon, lat = wgs84_to_gcj02(117, 36.7)
    assert result["position_gcj02"] == pytest.approx({"longitude": lon, "latitude": lat})
    assert result["coordinate_system"] == "GCJ02"
    assert result["source_time_sec"] == 1


def test_recording_position_rejects_missing_outside_and_invalid_coordinates(tmp_path):
    validator = SourceValidator([str(tmp_path)])
    source = SimpleNamespace(mode="local", source_type="file", location=str(tmp_path / "missing.json"), config={})
    assert validator.recording_position(source) is None
    source.location = str(tmp_path.parent / "outside.json")
    assert validator.recording_position(source) is None
    path = tmp_path / "invalid.json"
    source.location = str(path)
    path.write_text(json.dumps([{"timestamp": 0, "longitude": 0, "latitude": 0}]))
    assert validator.recording_position(source) is None
    path.write_text(json.dumps([{"timestamp": 0, "longitude": 117, "latitude": 36.7}]))
    assert validator.recording_position(source) is not None
    path.write_text(json.dumps([{"timestamp": 0, "longitude": 117, "latitude": 36.7}, None]))
    assert validator.recording_position(source) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("degradation,enabled,expected", [(None, True, "valid"), ("telemetry_gap", True, "degraded"), (None, False, "invalid")])
async def test_source_list_recovers_stale_invalid_state_when_assets_arrive(tmp_path, degradation, enabled, expected):
    video = VideoSourceRecord(id="v", profile_id="p", drone_id="d", mode="local", source_type="mp4",
                              location=str(tmp_path / "video.mp4"), enabled=enabled, revision=1,
                              validation_status="invalid", validation_error_code="source_unreadable")
    telemetry = TelemetrySourceRecord(id="t", profile_id="p", drone_id="d", mode="local", source_type="srt",
                                      location=str(tmp_path / "video.srt"), enabled=enabled, revision=1,
                                      validation_status="invalid", validation_error_code="source_unreadable",
                                      config={"known_degradation": degradation} if degradation else {})

    class Session:
        commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, statement):
            if statement.column_descriptions[0]["entity"] is VideoSourceRecord:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [video]))
            return SimpleNamespace(scalar_one_or_none=lambda: telemetry)

    session = Session()
    orchestrator = MissionOrchestrator(lambda: session, None, None, source_validator=SourceValidator([str(tmp_path)]))
    assert (await orchestrator.list_sources())[0]["validation_status"] == "invalid"
    session.commit.assert_not_awaited()
    (tmp_path / "video.mp4").write_bytes(b"video")
    (tmp_path / "video.srt").write_text("telemetry")
    result = (await orchestrator.list_sources())[0]
    assert result["validation_status"] == expected
    assert result["enabled"] is enabled
    if enabled:
        session.commit.assert_awaited_once()
        assert result["validation_error_code"] == degradation
        assert result["validated_at"] is not None
    else:
        session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_deployment_seed_refreshes_existing_status_without_overwriting_site_sources(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("seed_sources", root / "deploy/intranet/seed_sources.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    catalog = json.loads((root / "deploy/intranet/test-sources.json").read_text())
    catalog["sources"] = catalog["sources"][:1]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(settings, "uav_local_asset_roots", [str(tmp_path)])
    video_path, telemetry_path = tmp_path / "site.mp4", tmp_path / "site.srt"
    video_path.write_bytes(b"video")
    telemetry_path.write_text("telemetry")
    video = SimpleNamespace(location=str(video_path), mode="local", validation_status="invalid", enabled=False)
    telemetry = SimpleNamespace(location=str(telemetry_path), mode="local", source_type="srt",
                                validation_status="invalid", config={"known_degradation": "site_gap"})
    session = SimpleNamespace(get=AsyncMock(return_value=object()), flush=AsyncMock(),
                              execute=AsyncMock(side_effect=[
                                  SimpleNamespace(scalar_one_or_none=lambda: video),
                                  SimpleNamespace(scalar_one_or_none=lambda: telemetry),
                              ]))
    result = await seed.seed_sources(session, path)
    assert result["inserted"] == 0
    assert video.validation_status == telemetry.validation_status == "degraded"
    assert video.validation_error_code == telemetry.validation_error_code == "site_gap"
    assert video.location == str(video_path) and not video.enabled
    assert telemetry.location == str(telemetry_path) and telemetry.config == {"known_degradation": "site_gap"}
