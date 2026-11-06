"""Exercise actual publication before EOF, identity recovery and bounded disk state."""

from types import SimpleNamespace
import pytest
from nodes.KafkaProducerNode import KafkaProducerNode
from services.MissionTrajectoryArchive import MissionTrajectoryArchive
from services.PipelineEgress import DeltaTracks, POINT_FIELDS
from utils_local.replay_topics import build_replay_v2_topics


def producer(tmp_path):
    p = KafkaProducerNode.__new__(KafkaProducerNode)
    for k, v in dict(
        storage_profile="replay_v2",
        mission_id="M1",
        source_profile_id="S1",
        pipeline_id="P1",
        run_id="R1",
        intersection_id="I1",
        inter_id="I1",
        camera_id=1,
        drone_id="D1",
        quality_status="degraded",
        road_context_status="missing",
    ).items():
        setattr(p, k, v)
    p.trajectory_archive = MissionTrajectoryArchive(
        tmp_path, sampling_policy={"enabled": True}
    )
    p.track_complete_topic = "uav_track_complete"
    p.mission_topic = "uav_missions"
    p.sent = []
    p._enqueue = lambda topic, payload, **kwargs: p.sent.append((topic, payload))
    p.trajectory_archive.begin_mission(
        mission_id="M1",
        source_profile_id="S1",
        intersection_id="I1",
        source_timestamp_sec=0,
    )
    return p


def segment():
    return dict(
        track_id="7",
        termination_reason="association_timeout",
        trajectory_px=[[0, 0], [1, 1], [2, 2]],
        trajectory_timestamps_sec=[0, 0.5, 1],
        trajectory_frame_nums=[1, 2, 3],
        trajectory_enu_m=[None] * 3,
        trajectory_gcj02=[None] * 3,
        point_quality_lineage=[{}] * 3,
    )


def test_departure_is_published_without_eof_and_retries_are_byte_identical(tmp_path):
    p = producer(tmp_path)
    f = SimpleNamespace(timestamp=1, completed_tracks=[segment()], telemetry={})
    assert p.publish_completed_tracks(f) == 1
    first = p.sent[0]
    assert first[0] == "uav_track_complete"
    assert first[1]["data"]["sampling"]["full_sequence_summary"]
    assert not (tmp_path / "M1/sealed.json").exists()
    p.publish_completed_tracks(f)
    assert p.sent[1] == first
    assert p.seal_replay_mission(f, termination_reason="natural_eof") == 1
    assert (
        len([m for t, m in p.sent if t == "uav_track_complete"]) == 2
    )  # retries, not EOF duplication


def test_topics_do_not_grow_with_sources():
    assert build_replay_v2_topics("S1") == build_replay_v2_topics("S2")


def test_full_arrays_and_completed_identities_are_disk_backed(tmp_path):
    d = DeltaTracks(tmp_path)
    arrays = {k: [0] for k in POINT_FIELDS}
    for k in (
        "trajectory_px",
        "trajectory_bbox_center_px",
        "trajectory_enu_m",
        "trajectory_gcj02",
    ):
        arrays[k] = [[0, 0]]
    arrays["trajectory_timestamps_sec"] = [1]
    for i in range(1000):
        key = str(i)
        d.append(dict(track_id=key, start=0, arrays=arrays))
        assert not isinstance(d.rows[key]["trajectory_px"], list)
        d.finish(dict(track_id=key, point_count=1, metadata={"track_id": key}))
        d.closed.pop(key)
    assert not d.rows and not d.closed
    assert not isinstance(d.completed_ids, set)
    assert len(d.completed_ids) == 1000
    with pytest.raises(ValueError, match="closed"):
        d.append(dict(track_id="0", start=0, arrays=arrays))
    d.disk.close()


def test_source_clock_does_not_drift_with_slow_processing(tmp_path):
    p = producer(tmp_path)
    p._replay_source_start_sec = 0
    first = p._canonical_envelope(
        "uav_stats", {}, SimpleNamespace(timestamp=0, telemetry={})
    )
    # Changing capture metadata or wall time after source origin must not redefine T+.
    last = p._canonical_envelope(
        "uav_stats",
        {},
        SimpleNamespace(
            timestamp=10, telemetry={"recorded_at": "2099-01-01T00:00:00+00:00"}
        ),
    )
    from datetime import datetime

    assert (
        datetime.fromisoformat(last["occurred_at"])
        - datetime.fromisoformat(first["occurred_at"])
    ).total_seconds() == 10


def test_incremental_summary_remains_v2_when_geometry_compaction_is_disabled(tmp_path):
    p = producer(tmp_path / "initial")
    p.trajectory_archive = MissionTrajectoryArchive(tmp_path / "uncompacted")
    p.trajectory_archive.begin_mission(
        mission_id="M1",
        source_profile_id="S1",
        intersection_id="I1",
        source_timestamp_sec=0,
    )
    p.publish_completed_tracks(
        SimpleNamespace(timestamp=1, completed_tracks=[segment()], telemetry={})
    )
    data = p.sent[0][1]["data"]
    assert data["sampling"]["algorithm_version"] == "event-faithful/v2"
    assert data["sampling"]["geometry_compacted"] is False
    assert len(data["points"]) == data["source_point_count"] == 3


def test_three_worker_replay_does_not_presample_before_freezing_summary(monkeypatch):
    from nodes.TrajectoryNode import TrajectoryNode
    from elements.FrameElement import FrameElement

    monkeypatch.setenv("TRAJECTORY_STORAGE_PROFILE", "replay_v2")
    monkeypatch.setenv("HISTORY_SAMPLING_ENABLED", "false")
    node = TrajectoryNode({"pipeline": {"egress_enabled": False}})
    frame = FrameElement("fixture", None, 20, 200, {})
    frame.completed_tracks = [
        {
            "turn_behavior": "straight",
            "trajectory_px": [[i, i] for i in range(200)],
            "trajectory_timestamps_sec": [i / 10 for i in range(200)],
        }
    ]
    node.process(frame)
    assert len(frame.completed_tracks[0]["trajectory_px"]) == 200
