"""Real ORM transactions without external services; no mocked persistence assertions."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.replay_v2 import (
    ReplayV2Episode,
    ReplayV2IngestReceipt,
    ReplayV2Maneuver,
    ReplayV2MessageInbox,
    ReplayV2Mission,
    ReplayV2TrackEvent,
    ReplayV2TrackPoint,
)
from app.services.metric_store import MessageEnvelope, MessageIdentityConflict
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter


class AsyncSession:
    def __init__(self, engine):
        self.sync = Session(engine)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.sync.close()

    @asynccontextmanager
    async def begin(self):
        with self.sync.begin():
            yield self

    async def get(self, *args, **kwargs):
        return self.sync.get(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self.sync.scalar(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        return self.sync.execute(*args, **kwargs)

    async def flush(self):
        self.sync.flush()

    def get_bind(self):
        return self.sync.get_bind()

    def add(self, *args):
        self.sync.add(*args)


@pytest.mark.asyncio
async def test_track_before_mission_commits_points_inbox_and_receipt_atomically():
    engine = create_engine("sqlite://")
    for model in (
        ReplayV2Mission,
        ReplayV2TrackEvent,
        ReplayV2TrackPoint,
        ReplayV2Episode,
        ReplayV2Maneuver,
        ReplayV2MessageInbox,
        ReplayV2IngestReceipt,
    ):
        model.__table__.create(engine)
    store = ReplayV2MetricStoreAdapter(lambda: AsyncSession(engine))
    point = {
        "offset_ms": 1000,
        "source_timestamp_sec": 1,
        "frame_num": 1,
        "pixel": [1, 2],
        "enu_m": None,
        "gcj02": None,
    }
    payload = {
        "message_id": "m1",
        "msg_type": "uav_track_complete",
        "source_system": "uav_traffic_analyzer_ai",
        "inter_id": "I1",
        "produced_at": datetime.now(UTC).isoformat(),
        "data": {
            "mission_id": "M1",
            "source_profile_id": "S1",
            "track_id": "T1",
            "points": [point],
        },
    }
    envelope = MessageEnvelope(topic="uav_track_complete", partition=0, offset=1, payload=payload)
    result = await store.persist(envelope)
    assert not result.duplicate
    with Session(engine) as db:
        assert db.get(ReplayV2Mission, "M1").status == "running"
        assert db.scalar(select(ReplayV2TrackPoint)).offset_ms == 1000
        assert db.get(ReplayV2IngestReceipt, "m1").status == "pending"
    assert (await store.persist(envelope)).duplicate
    payload["data"]["points"][0]["pixel"] = [99, 99]
    with pytest.raises(MessageIdentityConflict):
        await store.persist(envelope)
    engine.dispose()


@pytest.mark.asyncio
async def test_oversize_chunks_remain_invisible_until_complete_and_survive_duplicates():
    from app.models.replay_v2 import ReplayV2TrackChunk
    from utils_local.track_message_codec import transport_messages
    import random

    engine = create_engine("sqlite://")
    for model in (
        ReplayV2Mission,
        ReplayV2TrackEvent,
        ReplayV2TrackPoint,
        ReplayV2Episode,
        ReplayV2Maneuver,
        ReplayV2MessageInbox,
        ReplayV2IngestReceipt,
        ReplayV2TrackChunk,
    ):
        model.__table__.create(engine)
    store = ReplayV2MetricStoreAdapter(lambda: AsyncSession(engine))
    rng = random.Random(19)
    payload = {
        "message_id": "chunk-m1",
        "msg_type": "uav_track_complete",
        "source_system": "uav_traffic_analyzer_ai",
        "inter_id": "I1",
        "produced_at": datetime.now(UTC).isoformat(),
        "storage_profile": "replay_v2",
        "transport_version": "uav-fixed/v2",
        "deployment_id": "test",
        "data": {
            "mission_id": "M1",
            "source_profile_id": "S1",
            "track_id": "T1",
            "points": [
                {
                    "offset_ms": i * 100,
                    "source_timestamp_sec": i / 10,
                    "frame_num": i,
                    "pixel": [rng.random(), rng.random()],
                    "enu_m": None,
                    "gcj02": None,
                }
                for i in range(100)
            ],
            "sampling": {"algorithm_version": "event-faithful/v1"},
        },
    }
    # Force the exact fallback branch using a v2 compression-budget error.
    # A large non-v2 record is also split at the common transport boundary.
    chunks = transport_messages(payload, budget=1000, chunk_bytes=400)
    assert len(chunks) > 1
    for i, chunk in enumerate(reversed(chunks)):
        envelope = MessageEnvelope(chunk, "uav_track_complete", 0, i)
        await store.persist(envelope)
        assert (await store.persist(envelope)).duplicate
        with Session(engine) as db:
            events = db.scalars(select(ReplayV2TrackEvent)).all()
            assert len(events) == (1 if i == len(chunks) - 1 else 0)
    engine.dispose()
