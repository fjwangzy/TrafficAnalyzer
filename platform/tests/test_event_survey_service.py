from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.core.config import settings
from app.models.mission import TelemetrySourceRecord
from app.models.survey import (
    AuditLog,
    EvidenceItem,
    SurveyCaptureBatch,
    SurveyFrame,
    SurveyTask,
)
from app.services.survey_service import SurveyService


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, evidence, telemetry_source):
        self.objects = {(EvidenceItem, evidence.id): evidence}
        self.telemetry_source = telemetry_source
        self.added = []

    async def get(self, model, identifier):
        return self.objects.get((model, identifier))

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity in {AuditLog, SurveyTask}:
            return _Result(None)
        if entity is TelemetrySourceRecord:
            return _Result(self.telemetry_source)
        raise AssertionError(f"unexpected query for {entity}")

    def add(self, value):
        self.added.append(value)
        identifier = getattr(value, "id", None)
        if identifier:
            self.objects[(type(value), identifier)] = value

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_event_survey_reuses_original_frame_and_prepares_metric_measurement(
    tmp_path, monkeypatch
):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    telemetry_path = source_root / "event.srt"
    telemetry_path.write_text(
        "1\n00:00:10,000 --> 00:00:10,040\nframe\n"
        "latitude: 36.70 longitude: 117.02 rel_alt: 100 "
        "gb_yaw: 0 gb_pitch: -90 gb_roll: 0 dzoom_ratio: 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "survey_asset_roots", [str(source_root)])
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path / "managed"))

    image = np.zeros((60, 100, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    storage = SurveyService(SimpleNamespace()).storage
    stored = storage.ingest_bytes(encoded.tobytes())
    original = EvidenceItem(
        id="EVI-EVENT-ORIGINAL",
        package_id="EVP-EVENT",
        task_id=None,
        kind="conflict_original_frame",
        storage_backend="managed",
        storage_key=stored.storage_key,
        sha256=stored.sha256,
        media_type="image/jpeg",
        size_bytes=stored.size_bytes,
        item_metadata={"width": 100, "height": 60, "frame_timestamp_sec": 10.0},
    )
    telemetry_source = SimpleNamespace(
        profile_id="SRC-1",
        location="event.srt",
        mode="local",
        enabled=True,
        source_type="srt",
        config={
            "time_offset_sec": 0,
            "sync_tolerance_sec": 0.5,
            "source_manifest": {"video_fps": 30.0},
        },
        validation_status="valid",
    )
    session = _Session(original, telemetry_source)
    service = SurveyService(session)

    result = await service.create_from_event(
        {
            "id": "EVT-1",
            "title": "真实机非冲突",
            "event_type": "conflict",
            "inter_id": "INT-1",
            "road_data_version": "ROAD-1",
            "source_profile_id": "SRC-1",
            "mission_id": "MSN-1",
            "pipeline_id": "PIPE-1",
            "evidence_refs": [
                {"id": original.id, "kind": "conflict_original_frame"}
            ],
        },
        actor_id=7,
        actor_name="admin",
        role="admin",
        request_id="event-survey-EVT-1",
    )

    assert result["task"]["status"] == "measuring"
    assert result["task"]["external_task_id"] == "EVT-1"
    assert result["task"]["selected_batch_id"] == result["batch"]["id"]
    assert result["frame"]["has_metric_transform"] is True
    assert result["frame"]["frame_number"] == 300
    assert result["frame"]["task_id"] == result["task"]["id"]
    assert result["batch"]["source_profile_id"] == "SRC-1"

    linked_original = next(
        item
        for item in session.added
        if isinstance(item, EvidenceItem)
        and item.kind == "event_original_frame"
    )
    frame = next(item for item in session.added if isinstance(item, SurveyFrame))
    assert linked_original.derived_from_id == original.id
    assert linked_original.sha256 == original.sha256
    assert frame.image_evidence_id == linked_original.id
    assert frame.bev_evidence_id != linked_original.id
    assert any(
        isinstance(item, SurveyCaptureBatch) and item.status == "selected"
        for item in session.added
    )
    assert any(
        isinstance(item, AuditLog) and item.action == "survey.task.created_from_event"
        for item in session.added
    )
