"""Regression: fixed-v2 track receipts must be written by every adapter.

``_add_ingest_receipt`` used to live only on the ``MetricStorePort`` Protocol,
which plain adapter classes do not inherit.  Every Kafka record then raised
``AttributeError`` inside ``persist()``, the consumer downgraded to "skip to
latest", and the console stayed empty with no data error visible.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.metric_store import (
    PostgresMetricStoreAdapter,
    record_ingest_receipt,
)
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    async def get(self, model, key):
        return self.existing

    def add(self, obj):
        self.added.append(obj)


def test_every_adapter_implements_ingest_receipt():
    for adapter in (PostgresMetricStoreAdapter, ReplayV2MetricStoreAdapter):
        assert hasattr(adapter, "_add_ingest_receipt"), adapter.__name__


def test_receipt_is_written_for_fixed_v2_track_complete_only():
    envelope = SimpleNamespace(payload={"a": 1})
    session = FakeSession()
    asyncio.run(
        record_ingest_receipt(
            session,
            envelope,
            {
                "transport_version": "uav-fixed/v2",
                "msg_type": "uav_track_complete",
                "message_id": "msg-1",
            },
        )
    )
    assert [row.message_id for row in session.added] == ["msg-1"]
    assert session.added[0].status == "pending"

    other = FakeSession()
    asyncio.run(
        record_ingest_receipt(
            other,
            envelope,
            {
                "transport_version": "uav-fixed/v2",
                "msg_type": "uav_stats",
                "message_id": "msg-2",
            },
        )
    )
    assert other.added == []

    legacy = FakeSession()
    asyncio.run(
        record_ingest_receipt(
            legacy,
            envelope,
            {
                "transport_version": "uav-fixed/v1",
                "msg_type": "uav_track_complete",
                "message_id": "msg-3",
            },
        )
    )
    assert legacy.added == []


def test_existing_receipt_is_marked_pending_again():
    existing = SimpleNamespace(status="dispatched")
    session = FakeSession(existing=existing)
    asyncio.run(
        record_ingest_receipt(
            session,
            SimpleNamespace(payload={}),
            {
                "transport_version": "uav-fixed/v2",
                "msg_type": "uav_track_complete",
                "message_id": "msg-4",
            },
        )
    )
    assert session.added == []
    assert existing.status == "pending"
