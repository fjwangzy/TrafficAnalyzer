from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models.replay_v2 import (
    ReplayV2Mission,
    ReplayV2IntersectionMetric5Min,
    ReplayV2DirtyWindow,
    ReplayV2TrackRelation,
)
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter
from app.services.metric_store import MessageEnvelope
from app.services.incremental_replay_jobs import IncrementalReplayJobs
from utils_local.trajectory_sampling import full_sequence_summary
from test_incremental_ingest_transaction import AsyncSession

BASE = datetime(2026, 11, 4, tzinfo=UTC)


def setup():
    engine = create_engine("sqlite://")
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("uav_replay_v2_"):
            table.create(engine)
    sessions = lambda: AsyncSession(engine)
    return (
        engine,
        ReplayV2MetricStoreAdapter(sessions),
        IncrementalReplayJobs(sessions, page_size=1),
    )


def envelope(kind, message_id, data, offset=0):
    topics = {
        "uav_track_complete": "uav_track_complete",
        "uav_replay_mission": "uav_missions",
        "uav_track_relation": "uav_track_relations",
    }
    payload = {
        "message_id": message_id,
        "msg_type": kind,
        "source_system": "uav_traffic_analyzer_ai",
        "inter_id": "I1",
        "produced_at": (BASE + timedelta(seconds=10)).isoformat(),
        "occurred_at": (BASE + timedelta(seconds=10)).isoformat(),
        "data": {"mission_id": "M1", "source_profile_id": "S1", **data},
    }
    return MessageEnvelope(payload, topics[kind], 0, offset)


def track(key, start, speeds):
    points = [
        {
            "offset_ms": start + i * 1000,
            "source_timestamp_sec": (start + i * 1000) / 1000,
            "frame_num": i,
            "pixel": [i, 0],
            "enu_m": [i, 0],
            "gcj02": None,
            "speed": {"ema_kmh": v},
        }
        for i, v in enumerate(speeds)
    ]
    return {
        "track_id": key,
        "archive_schema_version": "incremental/v1",
        "points": points,
        "source_point_count": len(points),
        "retained_point_count": len(points),
        "sampling": {
            "algorithm_version": "event-faithful/v2",
            "full_sequence_summary": full_sequence_summary(points, BASE.isoformat()),
        },
    }


@pytest.mark.asyncio
async def test_running_window_jobs_use_paged_summaries_and_relation_recounts_once():
    engine, store, jobs = setup()
    await store.persist(envelope("uav_track_complete", "a", track("a", 1000, [10, 20])))
    await store.persist(envelope("uav_track_complete", "b", track("b", 2500, [30, 40])))
    with Session(engine) as db:
        assert db.scalar(select(ReplayV2DirtyWindow)).dirty == 1
        assert db.scalar(select(ReplayV2IntersectionMetric5Min)) is None
    await jobs.process_pending()
    with Session(engine) as db:
        metric = db.scalar(select(ReplayV2IntersectionMetric5Min))
        assert (
            metric.vehicle_count == 2 and metric.avg_speed_kmh == 25 and metric.p85_speed_kmh == 40
        )
        assert db.get(ReplayV2Mission, "M1").status == "running"
    evidence = {
        "temporal_gap_sec": 0.5,
        "appearance_cosine": 1,
        "motion_space": "enu_m",
        "motion_distance": 0.1,
    }
    await store.persist(
        envelope(
            "uav_track_relation",
            "relation",
            {"predecessor_id": "a", "successor_id": "b", "evidence": evidence},
        )
    )
    await jobs.process_pending()
    await jobs.process_pending()
    with Session(engine) as db:
        metric = db.scalar(select(ReplayV2IntersectionMetric5Min))
        assert (
            metric.vehicle_count == 1 and metric.avg_speed_kmh == 25 and metric.p85_speed_kmh == 40
        )
        assert db.get(ReplayV2TrackRelation, "relation").state == "applied"
    engine.dispose()


@pytest.mark.asyncio
async def test_eof_waits_for_dirty_windows_and_does_not_rescan_sparse_geometry():
    engine, store, jobs = setup()
    await store.persist(envelope("uav_track_complete", "a", track("a", 1000, [10, 20])))
    await store.persist(
        envelope(
            "uav_replay_mission",
            "end",
            {
                "status": "sealed",
                "duration_sec": 10,
                "journey_count": 1,
                "algorithm_versions": {"archive": "incremental/v1"},
                "source_point_count": 2,
                "retained_point_count": 2,
            },
        )
    )
    with Session(engine) as db:
        assert db.get(ReplayV2Mission, "M1").status == "finalizing"
    await jobs.process_pending()
    with Session(engine) as db:
        assert db.get(ReplayV2Mission, "M1").status == "sealed"
    engine.dispose()


@pytest.mark.asyncio
async def test_final_manifest_hash_mismatch_never_marks_mission_sealed():
    import hashlib

    engine, store, jobs = setup()
    data = track("a", 1000, [10, 20])
    data["segment_digest"] = hashlib.sha256(b"source-a").hexdigest()
    await store.persist(envelope("uav_track_complete", "a", data))
    await store.persist(
        envelope(
            "uav_replay_mission",
            "end",
            {
                "status": "sealed",
                "duration_sec": 10,
                "journey_count": 1,
                "algorithm_versions": {"archive": "incremental/v1"},
                "source_point_count": 2,
                "retained_point_count": 2,
                "segment_manifest_hash": "0" * 64,
                "expected_relation_count": 0,
            },
        )
    )
    await jobs.process_pending()
    with Session(engine) as db:
        mission = db.get(ReplayV2Mission, "M1")
        assert (
            mission.status == "finalizing"
            and mission.failure_reason == "incremental_manifest_hash_mismatch"
        )
    engine.dispose()


@pytest.mark.asyncio
async def test_final_manifest_hash_and_summary_counts_converge():
    import hashlib
    from utils_local.trajectory_manifest import manifest_hash

    engine, store, jobs = setup()
    digest = hashlib.sha256(b"source-a").hexdigest()
    data = track("a", 1000, [10, 20])
    data["segment_digest"] = digest
    await store.persist(envelope("uav_track_complete", "a", data))
    await store.persist(
        envelope(
            "uav_replay_mission",
            "end",
            {
                "status": "sealed",
                "duration_sec": 10,
                "journey_count": 1,
                "algorithm_versions": {"archive": "incremental/v1"},
                "source_point_count": 2,
                "retained_point_count": 2,
                "segment_manifest_hash": manifest_hash([("a", digest)]),
                "expected_relation_count": 0,
            },
        )
    )
    await jobs.process_pending()
    with Session(engine) as db:
        assert db.get(ReplayV2Mission, "M1").status == "sealed"
    engine.dispose()


@pytest.mark.asyncio
async def test_typical_slot_is_refreshed_after_seal_without_including_running_missions():
    from app.models.replay_v2 import ReplayV2InterEvaluation5MinMM

    engine, store, jobs = setup()
    await store.persist(envelope("uav_track_complete", "a", track("a", 1000, [10, 20])))
    await jobs.process_pending()
    with Session(engine) as db:
        assert db.scalar(select(ReplayV2InterEvaluation5MinMM)) is None
    await store.persist(
        envelope(
            "uav_replay_mission",
            "end",
            {
                "status": "sealed",
                "duration_sec": 10,
                "journey_count": 1,
                "algorithm_versions": {"archive": "incremental/v1"},
                "source_point_count": 2,
                "retained_point_count": 2,
            },
        )
    )
    await jobs.process_pending()
    await jobs.process_pending()
    with Session(engine) as db:
        row = db.scalar(select(ReplayV2InterEvaluation5MinMM))
        assert (
            row is not None
            and row.vehicle_count == 1
            and row.avg_speed_kmh == 15
            and row.sample_days == 1
        )
    engine.dispose()
