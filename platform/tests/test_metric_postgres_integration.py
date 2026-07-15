"""Run with RUN_PG_INTEGRATION=1 against a disposable/local road9 database."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker
from app.models.metrics import (
    ConflictEvent,
    ConflictReview,
    SystemMetric,
    TelemetryMetric,
    TrackEvent,
    TrackPoint,
    TrafficMetric,
)
from app.models.mission import MessageDeadLetter, MessageInbox
from app.services.metric_store import (
    MessageEnvelope,
    MessageIdentityConflict,
    PostgresMetricStoreAdapter,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires an explicitly selected local PostgreSQL/TimescaleDB database",
)


def canonical(msg_type: str, message_id: str, data: dict, **headers) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "message_id": message_id,
        "msg_type": msg_type,
        "schema_version": f"{msg_type}/v1",
        "occurred_at": now,
        "produced_at": now,
        "source_system": "uav_traffic_analyzer_ai",
        "camera_id": "id_i3",
        "drone_id": "drone_i3",
        "intersection_id": "INT-I3",
        "inter_id": "INT-I3",
        "road_data_version": "ROAD-I3",
        "road_context_status": "ok",
        "source_time_semantics": "event_time",
        "time_quality": "verified",
        "quality_status": "verified",
        "data": data,
        **headers,
    }


@pytest.mark.asyncio
async def test_transactional_inbox_facts_queries_and_identity_conflict():
    marker = uuid.uuid4().hex[:10]
    store = PostgresMetricStoreAdapter(async_session_maker)
    messages = [
        ("uav_statistics_i3", canonical("uav_stats", f"stats-{marker}", {
            "cars": 4, "total_vehicles": 4, "avg_speed_kmh": 18.5,
            "lanes": [{"lane_id": "L-1", "vehicle_count": 2, "flow_veh_per_min": 6.0}],
        })),
        ("uav_track_complete_i3", canonical("uav_track_complete", f"track-{marker}", {
            "track_id": 7, "vehicle_class": "motor", "turn_behavior": "straight",
            "trajectory_px": [[1, 2], [3, 4]],
            "trajectory_world_m": [[0.1, 0.2], [0.3, 0.4]],
        })),
        ("uav_conflicts_i3", canonical("uav_conflict", f"conflict-{marker}", {
            "motor_id": 7, "non_motor_id": 8, "severity": "warning",
            "prediction_type": "path_intersection", "ttc_sec": 2.1, "pet_sec": 0.4,
            "distance_m": 0.0, "evidence": ["path_intersection"],
        })),
        ("uav_telemetry_i3", canonical("uav_telemetry", f"telemetry-{marker}", {
            "drone_id": "drone_i3", "latitude": 36.7, "longitude": 117.0,
            "altitude_m": 120.0, "battery_pct": 75,
        })),
        ("uav_system_metrics", canonical("uav_system_metrics", f"system-{marker}", {
            "instance_id": "pipeline-i3",
            "metrics": [{"metric_name": "fps", "metric_value": 14.5, "unit": "fps"}],
        })),
    ]

    try:
        results = []
        for offset, (topic, payload) in enumerate(messages):
            results.append(await store.persist(MessageEnvelope(payload, topic, 0, offset)))
        duplicate = await store.persist(MessageEnvelope(messages[0][1], messages[0][0], 0, 99))

        assert all(not result.duplicate for result in results)
        assert duplicate.duplicate
        assert len(duplicate.fact_references) == 2  # intersection + one lane

        conflicting = {**messages[0][1], "data": {"cars": 999}}
        with pytest.raises(MessageIdentityConflict):
            await store.persist(MessageEnvelope(conflicting, messages[0][0], 0, 100))
        dead_letter_id = await store.quarantine(
            MessageEnvelope(conflicting, messages[0][0], 0, 100),
            MessageIdentityConflict("integration identity conflict"),
        )

        traffic = await store.query_traffic("INT-I3", "1h")
        tracks = await store.query_tracks("INT-I3", "1h", 20)
        conflicts = await store.query_conflicts("INT-I3", "1h", 20)
        system = await store.query_system_metrics("1h", ["fps"])
        assert len(traffic) == 2
        assert tracks[0]["track_id"] == 7
        assert conflicts[0]["prediction_type"] == "path_intersection"
        reviewed = await store.review_conflict(
            "INT-I3", conflicts[0]["id"], "confirmed", conflicts[0]["review_revision"], None,
            "integration verification",
        )
        assert reviewed["review_status"] == "confirmed"
        assert reviewed["review_revision"] == 2
        with pytest.raises(MessageIdentityConflict):
            await store.review_conflict("INT-I3", conflicts[0]["id"], "rejected", 1, None)
        assert system[-1]["fps"] == 14.5

        async with async_session_maker() as session:
            inbox_count = await session.scalar(select(func.count()).select_from(MessageInbox).where(
                MessageInbox.message_id.like(f"%-{marker}")
            ))
            point_count = await session.scalar(select(func.count()).select_from(TrackPoint).where(
                TrackPoint.source_message_id == f"track-{marker}"
            ))
            dead_letter = await session.get(MessageDeadLetter, dead_letter_id)
        assert inbox_count == 5
        assert point_count == 2
        assert dead_letter is not None
        assert dead_letter.reason_code == "MessageIdentityConflict"
        async with async_session_maker() as session:
            session.add(ConflictReview(
                event_id=f"missing-{marker}",
                event_occurred_at=datetime.now(UTC),
                inter_id="INT-I3",
                review_status="confirmed",
                revision=2,
            ))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        async with async_session_maker() as session:
            await session.execute(delete(MessageDeadLetter).where(
                MessageDeadLetter.message_id.like(f"%-{marker}")
            ))
            await session.execute(delete(ConflictReview).where(ConflictReview.event_id.in_(
                select(ConflictEvent.id).where(ConflictEvent.source_message_id.like(f"%-{marker}"))
            )))
            for model in (TrackPoint, TrackEvent, TrafficMetric, ConflictEvent, TelemetryMetric, SystemMetric):
                await session.execute(delete(model).where(model.source_message_id.like(f"%-{marker}")))
            await session.execute(delete(MessageInbox).where(MessageInbox.message_id.like(f"%-{marker}")))
            await session.commit()
