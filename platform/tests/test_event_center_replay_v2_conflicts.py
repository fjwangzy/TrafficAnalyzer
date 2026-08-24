from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.event_center import EventCenter


EVENT_ID = "d1bfae25da343b0d5e32c61ffe85a09f5892180d"
MISSION_ID = "MSN-AE785FD3C417"
PIPELINE_ID = "pipe-d6e82e41"
SOURCE_ID = "SRC-INTER-XQH-0403-PM"
INTERSECTION_ID = "011wwe0z19700001"


def _replay_conflict():
    return SimpleNamespace(
        id=EVENT_ID,
        mission_id=MISSION_ID,
        inter_id=INTERSECTION_ID,
        offset_ms=15_816,
        severity="warning",
        prediction_type="path_intersection",
        motor_track_id="88",
        non_motor_track_id="725",
        distance_m=0.0,
        conflict_scene="general_crossing",
        ttc_sec=2.25,
        pet_sec=0.18,
        evidence=["hard_pet", "hard_deceleration"],
    )


def _replay_mission():
    return SimpleNamespace(
        id=MISSION_ID,
        inter_id=INTERSECTION_ID,
        source_profile_id=SOURCE_ID,
        pipeline_id=PIPELINE_ID,
        started_at=datetime(2026, 4, 3, 6, 29, 30, 21_000, tzinfo=UTC),
        created_at=datetime(2026, 8, 9, 14, 0, 0, tzinfo=UTC),
        algorithm_versions={},
    )


def _detector_evidence():
    return SimpleNamespace(
        id="evi-xqh-detector",
        kind="conflict_detector_frame",
        sha256="a1a58957492a461039abb18935e726d9d0f628c965bc1f24837500391a36aecc",
    )


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _PairResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, *, include_replay=True):
        self.include_replay = include_replay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _model, _key):
        return None

    async def execute(self, statement):
        sql = str(statement)
        if "uav_evidence_items" in sql and "uav_evidence_packages" in sql:
            return _PairResult([(_detector_evidence(), EVENT_ID)])
        if "uav_replay_v2_conflict_events" in sql:
            rows = [(_replay_conflict(), _replay_mission())] if self.include_replay else []
            return _PairResult(rows)
        if "uav_ai_events" in sql or "uav_conflict_events" in sql or "uav_conflict_reviews" in sql:
            return _ScalarResult([])
        raise AssertionError(f"unexpected EventCenter query: {sql}")


def _assert_xqh_event(event):
    assert event["id"] == EVENT_ID
    assert event["source_kind"] == "replay_v2_conflict"
    assert event["fact_table"] == "uav_replay_v2_conflict_events"
    assert event["inter_id"] == INTERSECTION_ID
    assert event["mission_id"] == MISSION_ID
    assert event["pipeline_id"] == PIPELINE_ID
    assert event["source_profile_id"] == SOURCE_ID
    assert event["title"] == "只读冲突候选 · 轨迹 88 与 725"
    assert event["occurred_at"] == "2026-04-03T06:29:45.837000+00:00"
    assert event["review_supported"] is False
    assert event["evidence_refs"] == [{
        "id": "evi-xqh-detector",
        "kind": "conflict_detector_frame",
        "url": "/api/v1/survey-evidence/evi-xqh-detector/content",
        "sha256": "a1a58957492a461039abb18935e726d9d0f628c965bc1f24837500391a36aecc",
    }]
    payload = event["payload"]
    assert payload["offset_ms"] == 15_816
    assert payload["prediction_type"] == "path_intersection"
    assert payload["motor_id"] == "88"
    assert payload["non_motor_id"] == "725"
    assert payload["distance_m"] == pytest.approx(0.0)
    assert payload["conflict_scene"] == "general_crossing"
    assert payload["ttc_sec"] == pytest.approx(2.25)
    assert payload["pet_sec"] == pytest.approx(0.18)
    assert payload["evidence"] == ["hard_pet", "hard_deceleration"]
    assert payload["time_quality"] == "verified"
    assert payload["evidence_status"] == "complete"


@pytest.mark.asyncio
async def test_event_center_lists_replay_v2_conflict_with_xqh_lineage():
    center = EventCenter(lambda: _Session(), materialize_on_list=False)

    events = await center.list_events(
        event_type="conflict",
        inter_id=INTERSECTION_ID,
        source_profile_id=SOURCE_ID,
        mission_id=MISSION_ID,
        limit=150,
    )

    assert len(events) == 1
    _assert_xqh_event(events[0])


@pytest.mark.asyncio
async def test_event_center_gets_replay_v2_conflict_detail_by_id():
    center = EventCenter(lambda: _Session(), materialize_on_list=False)

    event = await center.get_event(EVENT_ID)

    _assert_xqh_event(event)
    assert event["related_tracks"] == []


def test_historical_detector_replay_is_explicitly_labeled_reconstructed():
    conflict = _replay_conflict()
    conflict.prediction_type = "historical_detector_output"
    conflict.motor_track_id = "6342"
    conflict.non_motor_track_id = "5713"
    conflict.ttc_sec = 1.6
    conflict.pet_sec = None
    mission = _replay_mission()
    mission.algorithm_versions = {
        "detector_commit": "41fb6e6",
        "source_time_semantics": "reconstructed",
        "reproduction_match": {
            "same_frame_pixels_le_5_pct": 99.437,
            "replay_track_ids": ["6239", "5620"],
        },
    }

    event = EventCenter._replay_conflict_dict(
        conflict, mission, [{"id": "historical-frame", "kind": "conflict_detector_frame"}]
    )

    assert event["title"] == "历史检测口径复现 · 冲突候选 · 轨迹 6342 与 5713"
    assert event["quality_status"] == "historical_reconstructed"
    assert event["payload"]["time_quality"] == "reconstructed"
    assert event["payload"]["historical_replay"] is True
    assert event["payload"]["algorithm_versions"]["detector_commit"] == "41fb6e6"
