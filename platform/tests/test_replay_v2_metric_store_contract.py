from unittest.mock import Mock

import pytest

from app.models.survey import EvidenceItem, EvidencePackage
from app.services.metric_store import MetricContractError
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter
from app.services.survey_storage import ContentAddressedStore


class _EmptyRows:
    def all(self):
        return []


class _CapturingSession:
    def __init__(self, statements):
        self.statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyRows()


@pytest.mark.parametrize("fact_method", ["_add_conflict", "_add_telemetry"])
def test_replay_timed_facts_reject_missing_source_offset(fact_method):
    adapter = ReplayV2MetricStoreAdapter(Mock())
    value = {
        "message_id": "msg-no-offset",
        "intersection_id": "INT-XQH",
        "produced_at": None,
        "quality_status": "unverified",
    }

    with pytest.raises(MetricContractError, match="offset_ms"):
        getattr(adapter, fact_method)(Mock(), value, {"mission_id": "MSN-XQH"})


def test_replay_conflict_retains_track_pair_and_path_intersection_distance():
    adapter = ReplayV2MetricStoreAdapter(Mock())
    session = Mock()
    value = {
        "message_id": "msg-xqh-tcc",
        "intersection_id": "INT-XQH",
        "produced_at": None,
        "quality_status": "unverified",
    }

    adapter._add_conflict(session, value, {
        "mission_id": "MSN-XQH",
        "offset_ms": 15_816,
        "motor_id": 88,
        "non_motor_id": 725,
        "distance_m": 0.0,
        "prediction_type": "path_intersection",
        "conflict_scene": "suspected_right_turn_mv_nmv",
    })

    fact = session.add.call_args.args[0]
    assert fact.motor_track_id == "88"
    assert fact.non_motor_track_id == "725"
    assert fact.distance_m == 0.0
    assert fact.conflict_scene == "suspected_right_turn_mv_nmv"


def test_replay_conflict_registers_managed_detector_evidence(tmp_path):
    stored = ContentAddressedStore(str(tmp_path)).ingest_bytes(b"detector-jpeg")
    adapter = ReplayV2MetricStoreAdapter(
        Mock(), evidence_storage_root=str(tmp_path)
    )
    session = Mock()
    value = {
        "message_id": "msg-xqh-tcc-evidence",
        "intersection_id": "INT-XQH",
        "produced_at": None,
        "quality_status": "unverified",
        "source_time_raw": {"frame_timestamp_sec": 15.816},
    }

    references = adapter._add_conflict(session, value, {
        "mission_id": "MSN-XQH",
        "offset_ms": 15_816,
        "motor_id": 88,
        "non_motor_id": 725,
        "distance_m": 0.0,
        "prediction_type": "path_intersection",
        "evidence_files": [{
            "kind": "conflict_detector_frame",
            "storage_backend": "managed",
            "storage_key": stored.storage_key,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "media_type": "image/jpeg",
            "width": 3840,
            "height": 2160,
        }],
    })

    added = [call.args[0] for call in session.add.call_args_list]
    package = next(item for item in added if isinstance(item, EvidencePackage))
    evidence = next(item for item in added if isinstance(item, EvidenceItem))
    conflict = next(item for item in added if item.__class__.__name__ == "ReplayV2ConflictEvent")
    assert package.owner_type == "replay_v2_conflict"
    assert package.owner_id == conflict.id
    assert evidence.kind == "conflict_detector_frame"
    assert evidence.sha256 == stored.sha256
    assert evidence.item_metadata["frame_timestamp_sec"] == pytest.approx(15.816)
    assert evidence.item_metadata["mission_offset_ms"] == 15_816
    assert references == [
        f"uav_replay_v2_conflict_events:{conflict.id}",
        f"uav_evidence_items:{evidence.id}",
    ]


@pytest.mark.asyncio
async def test_replay_traffic_query_accepts_and_filters_pipeline_id():
    statements = []
    adapter = ReplayV2MetricStoreAdapter(lambda: _CapturingSession(statements))

    assert await adapter.query_traffic(
        "INT-XQH",
        "all",
        source_profile_id="SRC-XQH",
        pipeline_id="pipe-xqh",
    ) == []

    sql = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "uav_replay_v2_missions.pipeline_id = 'pipe-xqh'" in sql
