from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.survey import AiEvent
from app.services.event_center import EventCenter


AGGREGATE_ID = "EVT-8da17afcda8e2f0cdc1db1bebb982ef6"
INTERSECTION_ID = "011wwe0z19700001"
OCCURRED_AT = datetime(2026, 8, 9, 13, 55, 20, 699481, tzinfo=UTC)
CHILD_IDS = ["child-46", "child-47", "child-48", "child-49"]


def _aggregate():
    return SimpleNamespace(
        id=AGGREGATE_ID,
        event_type="multiple_conflicts",
        occurred_at=OCCURRED_AT,
        created_at=OCCURRED_AT,
        inter_id=INTERSECTION_ID,
        road_data_version=None,
        quality_status="unverified",
        review_status="confirmed",
        review_revision=2,
        review_reason=None,
        reviewed_at=None,
        delivery_status="not_queued",
        payload={
            "title": "冲突事件频发 (4次/分钟)",
            "status": "open",
            "severity": "P2",
            "evidence_refs": [],
        },
    )


def _inbox(event_id, received_at):
    return SimpleNamespace(
        msg_type="uav_conflict",
        received_at=received_at,
        fact_refs=[f"uav_replay_v2_conflict_events:{event_id}"],
    )


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, model, key):
        if model is AiEvent and key == AGGREGATE_ID:
            return _aggregate()
        return None

    async def execute(self, statement):
        sql = str(statement)
        if "uav_replay_v2_message_inbox" in sql:
            return _Result([
                _inbox("outside-window", OCCURRED_AT - timedelta(seconds=61)),
                *[
                    _inbox(event_id, OCCURRED_AT - timedelta(seconds=40 - index * 10))
                    for index, event_id in enumerate(CHILD_IDS)
                ],
            ])
        if "uav_replay_v2_conflict_events" in sql:
            return _Result([
                SimpleNamespace(id=event_id, inter_id=INTERSECTION_ID)
                for event_id in CHILD_IDS
            ])
        if "uav_evidence_items" in sql and "uav_evidence_packages" in sql:
            return _Result([
                (
                    SimpleNamespace(
                        id=f"evidence-{event_id}",
                        kind="conflict_detector_frame",
                        sha256=(str(index) * 64),
                    ),
                    event_id,
                )
                for index, event_id in enumerate(CHILD_IDS, start=1)
            ])
        if "uav_track_events" in sql:
            return _Result([])
        raise AssertionError(f"unexpected EventCenter query: {sql}")


@pytest.mark.asyncio
async def test_multiple_conflicts_projects_exact_window_child_images():
    center = EventCenter(lambda: _Session(), materialize_on_list=False)

    event = await center.get_event(AGGREGATE_ID)

    assert event["related_event_ids"] == CHILD_IDS
    assert event["payload"]["related_event_ids"] == CHILD_IDS
    assert [item["related_event_id"] for item in event["evidence_refs"]] == CHILD_IDS
    assert [item["id"] for item in event["evidence_refs"]] == [
        f"evidence-{event_id}" for event_id in CHILD_IDS
    ]


class _ConflictSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _model, _key):
        return None

    async def execute(self, statement):
        sql = str(statement)
        if "uav_conflict_events" in sql:
            return _Result([
                SimpleNamespace(
                    id="conflict-1",
                    payload={"data": {"motor_id": 11, "non_motor_id": 22}},
                    severity="critical",
                    occurred_at=OCCURRED_AT,
                    inter_id=INTERSECTION_ID,
                    road_data_version=None,
                    quality_status="verified",
                    mission_id="mission-1",
                    pipeline_id="pipeline-1",
                    source_profile_id="source-1",
                )
            ])
        if "uav_conflict_reviews" in sql:
            return _Result([])
        if "uav_track_events" in sql:
            track_ids = ("33",) if "NOT IN" in sql else ("11", "22")
            return _Result([
                SimpleNamespace(
                    id=f"track-row-{track_id}",
                    track_id=track_id,
                    payload={"data": {"track_id": int(track_id)}},
                    mission_id="mission-1",
                    pipeline_id="pipeline-1",
                    source_profile_id="source-1",
                    ended_at=OCCURRED_AT,
                )
                for track_id in track_ids
            ])
        raise AssertionError(f"unexpected EventCenter query: {sql}")


class _RejectedConflictSession(_ConflictSession):
    async def execute(self, statement):
        sql = str(statement)
        if "uav_conflict_reviews" in sql:
            return _Result([
                SimpleNamespace(
                    event_id="conflict-1",
                    review_status="rejected",
                    revision=2,
                    review_reason="同向近平行车辆不构成共同冲突区",
                    reviewed_at=OCCURRED_AT,
                )
            ])
        return await super().execute(statement)


class _ConfirmedConflictSession(_ConflictSession):
    async def execute(self, statement):
        sql = str(statement)
        if "uav_conflict_reviews" in sql:
            return _Result([
                SimpleNamespace(
                    event_id="conflict-1",
                    review_status="confirmed",
                    revision=2,
                    review_reason="逐帧确认双方进入共同冲突区",
                    reviewed_at=OCCURRED_AT,
                )
            ])
        return await super().execute(statement)


@pytest.mark.asyncio
async def test_conflict_detail_separates_exact_participants_from_context_tracks():
    center = EventCenter(lambda: _ConflictSession(), materialize_on_list=False)

    event = await center.get_event("conflict-1")

    assert event["title"] == "待复核冲突候选"
    assert "真实" not in event["title"]
    assert [track["track_id"] for track in event["related_tracks"]] == [11, 22]
    assert [track["track_id"] for track in event["context_tracks"]] == [33]


@pytest.mark.asyncio
async def test_rejected_conflict_is_not_presented_as_a_real_event():
    center = EventCenter(lambda: _RejectedConflictSession(), materialize_on_list=False)

    event = await center.get_event("conflict-1")

    assert event["review_status"] == "rejected"
    assert event["title"] == "已驳回冲突候选"
    assert "真实" not in event["title"]


@pytest.mark.asyncio
async def test_only_confirmed_conflict_is_presented_as_confirmed():
    center = EventCenter(lambda: _ConfirmedConflictSession(), materialize_on_list=False)

    event = await center.get_event("conflict-1")

    assert event["review_status"] == "confirmed"
    assert event["title"] == "已确认机非冲突"
