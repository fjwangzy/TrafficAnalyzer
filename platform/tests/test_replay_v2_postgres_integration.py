"""Explicit local-road9 integration for Replay V2 aggregate convergence."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, text

from app.core.database import async_session_maker, init_replay_v2_db
from app.models.replay_v2 import (
    ReplayV2Episode,
    ReplayV2ConflictEvent,
    ReplayV2InterEvaluation5MinMM,
    ReplayV2IntersectionMetric5Min,
    ReplayV2LaneMetric5Min,
    ReplayV2LinkMetric5Min,
    ReplayV2Maneuver,
    ReplayV2MessageInbox,
    ReplayV2Mission,
    ReplayV2TrackEvent,
    ReplayV2TrackPoint,
    ReplayV2TrafficMetricSample,
    ReplayV2TurnMetric5Min,
)
from app.services.metric_store import MessageEnvelope
from app.services.replay_repository import PostgresReplayRepository
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires explicit local road9 PostgreSQL/TimescaleDB integration",
)


async def _canonical_snapshot() -> tuple:
    async with async_session_maker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT version_num FROM uav_alembic_version LIMIT 1),
                      (SELECT COUNT(*) FROM uav_message_inbox),
                      (SELECT COUNT(*) FROM uav_track_events),
                      (SELECT COUNT(*) FROM uav_track_points),
                      (SELECT COUNT(*) FROM uav_telemetry_metrics),
                      (SELECT COUNT(*) FROM uav_traffic_metrics),
                      (SELECT COUNT(*) FROM uav_conflict_events)
                    """
                )
            )
        ).one()
    return tuple(row)


def _envelope(msg_type: str, message_id: str, data: dict, marker: str) -> dict:
    now = datetime(2026, 8, 5, 8, 4, tzinfo=UTC).isoformat()
    return {
        "message_id": message_id,
        "msg_type": msg_type,
        "schema_version": f"{msg_type}/replay-v2",
        "occurred_at": now,
        "produced_at": now,
        "source_system": "uav_traffic_analyzer_ai",
        "inter_id": f"INT-{marker}",
        "intersection_id": f"INT-{marker}",
        "quality_status": "verified",
        "data": data,
    }


@pytest.mark.asyncio
async def test_sealed_mission_transactionally_converges_all_dws_grains_without_canonical_writes():
    assert await init_replay_v2_db()
    marker = uuid.uuid4().hex[:10]
    mission_id = f"MSN-RV2-PG-{marker}"
    source_id = f"SRC-PG-{marker}"
    inter_id = f"INT-{marker}"
    topic_suffix = source_id
    store = ReplayV2MetricStoreAdapter(async_session_maker)
    canonical_before = await _canonical_snapshot()

    stats = _envelope(
        "uav_stats",
        f"stats-{marker}",
        {
            "mission_id": mission_id,
            "source_profile_id": source_id,
            "cars": 1,
            "avg_speed_kmh": 15.0,
            "coverage_ratio": 0.8,
            "active_trajectories": [
                {
                    "track_id": "RT-1",
                    "trajectory_px": [[10.0, 20.0]],
                    "trajectory_gcj02": [[117.0, 36.0]],
                }
            ],
            "candidate_trajectories": [],
        },
        marker,
    )
    conflict = _envelope(
        "uav_conflict",
        f"conflict-{marker}",
        {
            "mission_id": mission_id,
            "source_profile_id": source_id,
            "offset_ms": 10_000,
            "severity": "warning",
            "prediction_type": "crossing",
            "ttc_sec": 3.2,
        },
        marker,
    )
    track = _envelope(
        "uav_track_complete",
        f"track-{marker}",
        {
            "mission_id": mission_id,
            "source_profile_id": source_id,
            "pipeline_id": f"pipe-{marker}",
            "track_id": "J-1",
            "source_runtime_track_ids": ["RT-1"],
            "matched_link_id": "LINK-1",
            "matched_lane_key": "LANE-1",
            "movement_key": "N-S",
            "source_point_count": 2,
            "retained_point_count": 2,
            "sampling": {"algorithm_version": "event-faithful/v1"},
            "termination_reason": "natural_eof",
            "points": [
                {
                    "offset_ms": 0,
                    "source_timestamp_sec": 0.0,
                    "frame_num": 1,
                    "pixel": [10.0, 20.0],
                    "enu_m": [0.0, 0.0],
                    "gcj02": [117.0, 36.0],
                    "speed": {"instant_kmh": 10.0, "ema_kmh": 10.0, "quality": "verified"},
                    "quality": {"status": "verified"},
                    "sampling_boundary": ["journey_start"],
                },
                {
                    "offset_ms": 60_000,
                    "source_timestamp_sec": 60.0,
                    "frame_num": 2,
                    "pixel": [20.0, 20.0],
                    "enu_m": [100.0, 0.0],
                    "gcj02": [117.001, 36.0],
                    "speed": {"instant_kmh": 20.0, "ema_kmh": 20.0, "quality": "verified"},
                    "quality": {"status": "verified"},
                    "sampling_boundary": ["journey_end"],
                },
            ],
            "episodes": [
                {"kind": "stopped", "start_offset_ms": 10_000, "end_offset_ms": 30_000},
                {"kind": "releasing", "start_offset_ms": 30_000, "end_offset_ms": 40_000},
            ],
            "maneuvers": [],
        },
        marker,
    )
    mission = _envelope(
        "uav_replay_mission",
        f"mission-{marker}",
        {
            "mission_id": mission_id,
            "source_profile_id": source_id,
            "pipeline_id": f"pipe-{marker}",
            "status": "sealed",
            "duration_sec": 120.0,
            "journey_count": 1,
            "behavior_count": 2,
            "coordinate_coverage_ratio": 1.0,
            "algorithm_versions": {"aggregate": "replay-v2-aggregate/v1"},
            "accuracy": {"idf1": "not_evaluated"},
        },
        marker,
    )
    incomplete_mission = _envelope(
        "uav_replay_mission",
        f"mission-incomplete-{marker}",
        {
            "mission_id": mission_id,
            "source_profile_id": source_id,
            "status": "incomplete",
            "duration_sec": 30.0,
            "journey_count": 0,
            "behavior_count": 0,
            "failure_reason": "reader_process_died",
            "accuracy": {"idf1": "not_evaluated"},
        },
        marker,
    )

    try:
        await store.persist(
            MessageEnvelope(
                incomplete_mission,
                f"uav_replay_v2_mission_{topic_suffix}",
                0,
                0,
            )
        )
        await store.persist(
            MessageEnvelope(stats, f"uav_replay_v2_statistics_{topic_suffix}", 0, 0)
        )
        await store.persist(
            MessageEnvelope(track, f"uav_replay_v2_track_complete_{topic_suffix}", 0, 0)
        )
        await store.persist(
            MessageEnvelope(conflict, f"uav_replay_v2_conflicts_{topic_suffix}", 0, 0)
        )
        await store.persist(
            MessageEnvelope(mission, f"uav_replay_v2_mission_{topic_suffix}", 0, 1)
        )

        traffic_rows = await store.query_traffic(
            inter_id,
            "all",
            grain_type="intersection",
            source_profile_id=source_id,
            pipeline_id=f"pipe-{marker}",
        )
        other_pipeline_rows = await store.query_traffic(
            inter_id,
            "all",
            grain_type="intersection",
            source_profile_id=source_id,
            pipeline_id=f"pipe-other-{marker}",
        )
        conflict_rows = await store.query_conflicts(
            inter_id,
            "all",
            10,
            source_profile_id=source_id,
            pipeline_id=f"pipe-{marker}",
        )
        replay = await PostgresReplayRepository(async_session_maker).replay(
            inter_id,
            mission_id=mission_id,
            cursor_ms=120_000,
            window_ms=120_000,
            max_points=100,
            page_after=None,
            track_id=None,
            behavior=None,
            vehicle_class=None,
            yolo_class_id=None,
            turn_behavior=None,
            movement_key=None,
        )

        async with async_session_maker() as session:
            counts = []
            for model in (
                ReplayV2IntersectionMetric5Min,
                ReplayV2LinkMetric5Min,
                ReplayV2LaneMetric5Min,
                ReplayV2TurnMetric5Min,
                ReplayV2InterEvaluation5MinMM,
            ):
                counts.append(
                    await session.scalar(
                        select(func.count()).select_from(model).where(
                            model.source_profile_id == source_id
                        )
                    )
                )
            intersection = await session.scalar(
                select(ReplayV2IntersectionMetric5Min).where(
                    ReplayV2IntersectionMetric5Min.mission_id == mission_id
                )
            )

        assert counts == [1, 1, 1, 1, 1]
        assert intersection.vehicle_count == 1
        assert intersection.avg_speed_kmh == 15.0
        assert intersection.stopped_count == 1
        assert intersection.release_count == 1
        assert traffic_rows[0]["total_vehicles"] == 1
        assert traffic_rows[0]["pipeline_id"] == f"pipe-{marker}"
        assert other_pipeline_rows == []
        assert conflict_rows[0]["prediction_type"] == "crossing"
        assert replay["mission"]["mission_id"] == mission_id
        assert [track["track_id"] for track in replay["tracks"]] == ["J-1"]
        assert replay["cursor"] == {
            "offset_ms": 120_000,
            "window_start_ms": 0,
            "window_end_ms": 120_000,
            "duration_ms": 120_000,
        }
        assert await _canonical_snapshot() == canonical_before
    finally:
        async with async_session_maker() as session:
            for model in (
                ReplayV2InterEvaluation5MinMM,
                ReplayV2TurnMetric5Min,
                ReplayV2LaneMetric5Min,
                ReplayV2LinkMetric5Min,
                ReplayV2IntersectionMetric5Min,
            ):
                await session.execute(delete(model).where(model.source_profile_id == source_id))
            for model in (ReplayV2Episode, ReplayV2Maneuver, ReplayV2TrackPoint, ReplayV2TrackEvent):
                await session.execute(delete(model).where(model.mission_id == mission_id))
            await session.execute(
                delete(ReplayV2ConflictEvent).where(
                    ReplayV2ConflictEvent.mission_id == mission_id
                )
            )
            await session.execute(
                delete(ReplayV2TrafficMetricSample).where(
                    ReplayV2TrafficMetricSample.mission_id == mission_id
                )
            )
            await session.execute(delete(ReplayV2Mission).where(ReplayV2Mission.id == mission_id))
            await session.execute(
                delete(ReplayV2MessageInbox).where(
                    ReplayV2MessageInbox.message_id.in_(
                        [
                            f"stats-{marker}",
                            f"track-{marker}",
                            f"conflict-{marker}",
                            f"mission-{marker}",
                        ]
                        + [f"mission-incomplete-{marker}"]
                    )
                )
            )
            await session.commit()
