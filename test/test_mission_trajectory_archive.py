import pytest
import base64
import cv2
import numpy as np
import sys
import types
import uuid
from types import SimpleNamespace

from services.MissionTrajectoryArchive import MissionTrajectoryArchive
from nodes.KafkaProducerNode import KafkaProducerNode
from utils_local.replay_topics import build_replay_v2_topics


def test_archive_only_exposes_natural_eof_missions_and_keeps_real_points_aligned(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    archive.record_segment(
        mission_id="MSN-V2-1",
        source_profile_id="SRC-1",
        intersection_id="INT-1",
        segment={
            "track_id": 17,
            "termination_reason": "association_timeout",
            "trajectory_px": [[10, 20], [11, 20], [12, 20], [13, 20]],
            "trajectory_timestamps_sec": [100.0, 100.2, 100.4, 100.6],
            "trajectory_frame_nums": [1, 2, 3, 4],
            "trajectory_enu_m": [[0.0, 0.0], None, [0.4, 0.0], [0.6, 0.0]],
            "trajectory_gcj02": [[117.0, 36.0], None, [117.000004, 36.0], [117.000006, 36.0]],
            "point_quality_lineage": [{"tracking_quality": "verified"}] * 4,
        },
    )

    assert archive.load_mission("MSN-V2-1")["status"] == "incomplete"
    with pytest.raises(ValueError, match="natural_eof"):
        archive.seal_mission("MSN-V2-1", termination_reason="pipeline_failed")

    sealed = archive.seal_mission("MSN-V2-1", termination_reason="natural_eof")

    assert sealed["status"] == "sealed"
    assert sealed["source_point_count"] == 4
    journey = sealed["journeys"][0]
    assert journey["source_runtime_track_ids"] == ["17"]
    assert journey["retained_point_count"] == len(journey["points"])
    assert {point["source_timestamp_sec"] for point in journey["points"]} <= {
        100.0, 100.2, 100.4, 100.6
    }
    assert all(
        set(point) >= {"offset_ms", "frame_num", "pixel", "enu_m", "gcj02", "speed"}
        for point in journey["points"]
    )
    assert archive.load_mission("MSN-V2-1")["status"] == "sealed"


def test_replay_v2_producer_defers_completed_journeys_until_mission_seal(tmp_path):
    sent = []
    producer = KafkaProducerNode.__new__(KafkaProducerNode)
    producer.storage_profile = "replay_v2"
    producer.trajectory_archive = MissionTrajectoryArchive(tmp_path)
    producer.mission_id = "MSN-V2-2"
    producer.pipeline_id = "PIPE-V2-2"
    producer.run_id = "RUN-V2-2"
    producer.source_profile_id = "SRC-2"
    producer.intersection_id = "INT-2"
    producer.inter_id = "INT-2"
    producer.camera_id = 2
    producer.drone_id = "UAV-2"
    producer.road_context_status = "missing"
    producer.quality_status = "degraded"
    topics = build_replay_v2_topics("SRC-2")
    producer.track_complete_topic = topics.track_complete
    producer.mission_topic = topics.mission
    producer._enqueue = lambda topic, data, durable=False: sent.append((topic, data, durable))
    segment = {
        "track_id": 22,
        "termination_reason": "association_timeout",
        "trajectory_px": [[10, 20], [11, 20]],
        "trajectory_timestamps_sec": [5.0, 5.6],
        "trajectory_frame_nums": [1, 2],
        "trajectory_enu_m": [None, None],
        "trajectory_gcj02": [None, None],
        "point_quality_lineage": [{}, {}],
    }
    frame = SimpleNamespace(
        completed_tracks=[segment],
        timestamp=5.6,
        telemetry={},
        source_is_realtime=False,
    )

    assert producer.publish_completed_tracks(frame) == 0
    assert sent == []

    assert producer.seal_replay_mission(frame, termination_reason="natural_eof") == 1
    assert [topic for topic, _, _ in sent] == [topics.track_complete, topics.mission]
    assert sent[0][1]["data"]["source_runtime_track_ids"] == ["22"]
    assert sent[1][1]["data"]["status"] == "sealed"
    assert sent[1][1]["message_id"] == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "traffic-analyzer:uav-replay-v2-mission:MSN-V2-2:sealed",
        )
    )


def test_replay_v2_producer_publishes_running_mission_before_conflicts(tmp_path):
    sent = []
    producer = KafkaProducerNode.__new__(KafkaProducerNode)
    producer.storage_profile = "replay_v2"
    producer.trajectory_archive = MissionTrajectoryArchive(tmp_path)
    producer.mission_id = "MSN-RUNNING"
    producer.pipeline_id = "PIPE-RUNNING"
    producer.run_id = "RUN-RUNNING"
    producer.source_profile_id = "SRC-RUNNING"
    producer.intersection_id = "INT-RUNNING"
    producer.inter_id = "INT-RUNNING"
    producer.camera_id = 2
    producer.drone_id = "UAV-2"
    producer.road_context_status = "complete"
    producer.quality_status = "verified"
    producer.mission_topic = build_replay_v2_topics("SRC-RUNNING").mission
    producer._enqueue = lambda topic, data, durable=False: sent.append((topic, data, durable))
    frame = SimpleNamespace(timestamp=10.0, telemetry={}, source_is_realtime=False)
    manifest = producer.trajectory_archive.begin_mission(
        mission_id=producer.mission_id,
        source_profile_id=producer.source_profile_id,
        intersection_id=producer.intersection_id,
        source_timestamp_sec=frame.timestamp,
    )

    assert producer.publish_replay_mission_started(frame, manifest) == 1
    assert producer.publish_replay_mission_started(frame, manifest) == 0

    assert len(sent) == 1
    message = sent[0][1]
    assert sent[0][2] is True
    assert message["data"]["status"] == "running"
    assert message["data"]["source_profile_id"] == "SRC-RUNNING"
    assert message["message_id"] == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "traffic-analyzer:uav-replay-v2-mission:MSN-RUNNING:started",
        )
    )


def test_replay_v2_producer_publishes_incomplete_diagnostic_without_final_journeys(tmp_path):
    sent = []
    closed = []
    producer = KafkaProducerNode.__new__(KafkaProducerNode)
    producer.storage_profile = "replay_v2"
    producer.trajectory_archive = MissionTrajectoryArchive(tmp_path)
    producer.mission_id = "MSN-INCOMPLETE"
    producer.pipeline_id = "PIPE-INCOMPLETE"
    producer.run_id = "RUN-INCOMPLETE"
    producer.source_profile_id = "SRC-INCOMPLETE"
    producer.intersection_id = "INT-INCOMPLETE"
    producer.inter_id = "INT-INCOMPLETE"
    producer.camera_id = 2
    producer.drone_id = "UAV-2"
    producer.road_context_status = "missing"
    producer.quality_status = "degraded"
    producer.mission_topic = build_replay_v2_topics("SRC-INCOMPLETE").mission
    producer._enqueue = lambda topic, data, durable=False: sent.append((topic, data, durable))
    producer.publisher = SimpleNamespace(close=lambda: closed.append(True))
    frame = SimpleNamespace(timestamp=8.0, telemetry={}, source_is_realtime=False)
    producer._last_replay_frame = frame
    producer.trajectory_archive.begin_mission(
        mission_id=producer.mission_id,
        source_profile_id=producer.source_profile_id,
        intersection_id=producer.intersection_id,
        source_timestamp_sec=frame.timestamp,
    )

    assert producer.mark_replay_mission_incomplete(failure_reason="reader_process_died") == 1

    assert len(sent) == 1
    assert sent[0][1]["data"]["status"] == "incomplete"
    assert sent[0][1]["data"]["failure_reason"] == "reader_process_died"
    assert sent[0][1]["message_id"] == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "traffic-analyzer:uav-replay-v2-mission:MSN-INCOMPLETE:incomplete",
        )
    )
    assert producer.trajectory_archive.load_mission(producer.mission_id)["status"] == "incomplete"
    assert closed == [True]


def test_archive_only_merges_unique_motion_and_appearance_matches(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    base = {
        "termination_reason": "association_timeout",
        "point_quality_lineage": [{}, {}],
        "appearance_embedding": [1.0, 0.0, 0.0],
    }
    archive.record_segment(
        mission_id="MSN-MERGE",
        source_profile_id="SRC-1",
        intersection_id="INT-1",
        segment={
            **base,
            "track_id": 1,
            "trajectory_px": [[10, 20], [11, 20]],
            "trajectory_timestamps_sec": [0.0, 1.0],
            "trajectory_frame_nums": [1, 2],
            "trajectory_enu_m": [[0, 0], [1, 0]],
            "trajectory_gcj02": [[117, 36], [117.1, 36]],
        },
    )
    archive.record_segment(
        mission_id="MSN-MERGE",
        source_profile_id="SRC-1",
        intersection_id="INT-1",
        segment={
            **base,
            "track_id": 2,
            "trajectory_px": [[12, 20], [13, 20]],
            "trajectory_timestamps_sec": [1.5, 2.5],
            "trajectory_frame_nums": [3, 4],
            "trajectory_enu_m": [[1.4, 0], [2.4, 0]],
            "trajectory_gcj02": [[117.14, 36], [117.24, 36]],
        },
    )

    sealed = archive.seal_mission("MSN-MERGE", termination_reason="natural_eof")

    assert len(sealed["journeys"]) == 1
    assert sealed["journeys"][0]["source_runtime_track_ids"] == ["1", "2"]
    assert sealed["accuracy"]["reid_accuracy"] == "not_evaluated"
    assert sealed["journeys"][0]["reid_evidence"][0]["appearance_cosine"] == 1.0


def test_archive_derives_stopped_release_and_geometric_u_turn_from_full_world_points(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    timestamps = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    world = [[0, 0], [0.1, 0], [0.2, 0], [4.2, 0], [4.2, 4], [0.2, 4]]
    archive.record_segment(
        mission_id="MSN-BEHAVIOR",
        source_profile_id="SRC-1",
        intersection_id="INT-1",
        segment={
            "track_id": 9,
            "termination_reason": "natural_eof",
            "trajectory_px": [[10 + index, 20] for index in range(len(world))],
            "trajectory_timestamps_sec": timestamps,
            "trajectory_frame_nums": list(range(1, len(world) + 1)),
            "trajectory_enu_m": world,
            "trajectory_gcj02": [[117 + index / 10000, 36] for index in range(len(world))],
            "point_quality_lineage": [{} for _ in world],
        },
    )

    journey = archive.seal_mission("MSN-BEHAVIOR", termination_reason="natural_eof")["journeys"][0]

    assert "stopped" in {episode["kind"] for episode in journey["episodes"]}
    assert "releasing" in {episode["kind"] for episode in journey["episodes"]}
    assert "geometric_u_turn" in {maneuver["kind"] for maneuver in journey["maneuvers"]}


def test_geometric_u_turn_requires_three_metre_approach_and_departure_and_one_second_reverse_hold(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    cases = {
        "short_legs": (
            [0.0, 1.0, 2.0, 3.0],
            [[0, 0], [2, 0], [2, 2], [0, 2]],
        ),
        "short_reverse_hold": (
            [0.0, 1.0, 2.0, 2.2],
            [[0, 0], [4, 0], [4, 4], [0, 4]],
        ),
    }
    for track_id, (timestamps, world) in enumerate(cases.values(), start=1):
        archive.record_segment(
            mission_id="MSN-U-TURN-THRESHOLDS",
            source_profile_id="SRC-1",
            intersection_id="INT-1",
            segment={
                "track_id": track_id,
                "termination_reason": "natural_eof",
                "trajectory_px": [[10 + index, 20] for index in range(len(world))],
                "trajectory_timestamps_sec": timestamps,
                "trajectory_frame_nums": list(range(track_id * 10, track_id * 10 + len(world))),
                "trajectory_enu_m": world,
                "trajectory_gcj02": [[117 + index / 10000, 36] for index in range(len(world))],
                "point_quality_lineage": [{} for _ in world],
            },
        )

    sealed = archive.seal_mission(
        "MSN-U-TURN-THRESHOLDS", termination_reason="natural_eof"
    )

    assert all(
        "geometric_u_turn" not in {item["kind"] for item in journey["maneuvers"]}
        for journey in sealed["journeys"]
    )


def test_queue_is_not_inferred_from_lane_labels_without_road_analytics_trust(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    for track_id in (1, 2):
        archive.record_segment(
            mission_id="MSN-ROAD-UNTRUSTED",
            source_profile_id="SRC-1",
            intersection_id="INT-1",
            segment={
                "track_id": track_id,
                "termination_reason": "natural_eof",
                "matched_lane_key": "LANE-1",
                "matched_link_id": "LINK-1",
                "road_analytics_eligible": False,
                "trajectory_px": [[10 + track_id, 20]] * 4,
                "trajectory_timestamps_sec": [0.0, 1.0, 2.0, 3.0],
                "trajectory_frame_nums": [1, 2, 3, 4],
                "trajectory_enu_m": [[track_id * 0.1, 0]] * 4,
                "trajectory_gcj02": [[117.0, 36.0]] * 4,
                "point_quality_lineage": [{}] * 4,
            },
        )

    sealed = archive.seal_mission("MSN-ROAD-UNTRUSTED", termination_reason="natural_eof")

    assert all(
        "standing_queue" not in {episode["kind"] for episode in journey["episodes"]}
        for journey in sealed["journeys"]
    )


def test_road_trusted_overlapping_stops_form_queue_facts(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    for track_id in (1, 2):
        archive.record_segment(
            mission_id="MSN-ROAD-TRUSTED",
            source_profile_id="SRC-1",
            intersection_id="INT-1",
            segment={
                "track_id": track_id,
                "termination_reason": "natural_eof",
                "matched_lane_key": "LANE-1",
                "matched_link_id": "LINK-1",
                "road_analytics_eligible": True,
                "trajectory_px": [[10 + track_id, 20]] * 4,
                "trajectory_timestamps_sec": [0.0, 1.0, 2.0, 3.0],
                "trajectory_frame_nums": [1, 2, 3, 4],
                "trajectory_enu_m": [[track_id * 0.1, 0]] * 4,
                "trajectory_gcj02": [[117.0, 36.0]] * 4,
                "point_quality_lineage": [{}] * 4,
            },
        )

    sealed = archive.seal_mission("MSN-ROAD-TRUSTED", termination_reason="natural_eof")

    assert all(
        "standing_queue" in {episode["kind"] for episode in journey["episodes"]}
        for journey in sealed["journeys"]
    )


def test_archive_uses_existing_model_encoder_at_seal_and_removes_temporary_crops(tmp_path):
    ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    crop = base64.b64encode(encoded).decode("ascii")
    archive = MissionTrajectoryArchive(
        tmp_path,
        appearance_encoder=lambda values: [[1.0, 0.0] for _ in values],
    )
    for track_id, start, xs in ((1, 0.0, [0, 1]), (2, 1.5, [1.2, 2.2])):
        archive.record_segment(
            mission_id="MSN-ENCODE",
            source_profile_id="SRC-1",
            intersection_id="INT-1",
            segment={
                "track_id": track_id,
                "termination_reason": "association_timeout",
                "appearance_crop_jpeg": crop,
                "trajectory_px": [[x, 20] for x in xs],
                "trajectory_timestamps_sec": [start, start + 1],
                "trajectory_frame_nums": [track_id * 2 - 1, track_id * 2],
                "trajectory_enu_m": [[x, 0] for x in xs],
                "trajectory_gcj02": [[117 + x / 10000, 36] for x in xs],
                "point_quality_lineage": [{}, {}],
            },
        )

    sealed = archive.seal_mission("MSN-ENCODE", termination_reason="natural_eof")

    assert len(sealed["journeys"]) == 1
    segment_files = list((tmp_path / "MSN-ENCODE" / "segments").glob("*.json"))
    assert all("appearance_crop_jpeg" not in path.read_text() for path in segment_files)


def test_archive_marks_only_explicit_tracking_quality_gaps_as_replay_breaks(tmp_path):
    archive = MissionTrajectoryArchive(tmp_path)
    archive.record_segment(
        mission_id="MSN-GAP",
        source_profile_id="SRC-1",
        intersection_id="INT-1",
        segment={
            "track_id": 31,
            "termination_reason": "natural_eof",
            "trajectory_px": [[10 + index, 20] for index in range(5)],
            "trajectory_timestamps_sec": [0.0, 0.2, 0.4, 0.6, 0.8],
            "trajectory_frame_nums": [1, 2, 3, 4, 5],
            "trajectory_enu_m": [[0, 0], [0.2, 0], None, [0.6, 0], [0.8, 0]],
            "trajectory_gcj02": [[117, 36], [117.1, 36], None, [117.3, 36], [117.4, 36]],
            "point_quality_lineage": [
                {"tracking_quality": "verified", "road_context_status": "missing"},
                {"tracking_quality": "verified", "road_context_status": "missing"},
                {"tracking_quality": "gap", "road_context_status": "missing"},
                {"tracking_quality": "verified", "road_context_status": "missing"},
                {"tracking_quality": "verified", "road_context_status": "missing"},
            ],
        },
    )

    points = archive.seal_mission("MSN-GAP", termination_reason="natural_eof")["journeys"][0]["points"]

    boundaries = {point["frame_num"]: point["sampling_boundary"] for point in points}
    assert "quality_gap_start" in boundaries[3]
    assert "quality_gap_end" in boundaries[4]
    assert all(
        "gap" not in boundary
        for frame_num, values in boundaries.items()
        if frame_num not in {3, 4}
        for boundary in values
    )


def test_archive_batches_existing_model_appearance_encoding(tmp_path):
    ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    crop = base64.b64encode(encoded).decode("ascii")
    batch_sizes = []

    def encode(values):
        batch_sizes.append(len(values))
        return [[1.0, 0.0] for _ in values]

    archive = MissionTrajectoryArchive(tmp_path, appearance_encoder=encode)
    segments = [
        {"track_id": index, "appearance_crop_jpeg": crop}
        for index in range(65)
    ]

    archive._encode_appearance(segments)

    assert batch_sizes == [32, 32, 1]
    assert all(segment["appearance_embedding"] == [1.0, 0.0] for segment in segments)


def test_archive_forwards_isolated_mps_and_embedding_size_to_existing_model(
    tmp_path, monkeypatch
):
    ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    captured = {}

    class FakeTensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def float(self):
            return self

        def reshape(self, _value):
            return self

        def tolist(self):
            return [1.0, 0.0]

    class FakeModel:
        def embed(self, **kwargs):
            captured.update(kwargs)
            return [FakeTensor() for _ in kwargs["source"]]

    fake_ultralytics = types.ModuleType("ultralytics")
    fake_ultralytics.YOLO = lambda _path: FakeModel()
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)
    monkeypatch.setenv("REPLAY_V2_APPEARANCE_DEVICE", "mps")
    monkeypatch.setenv("REPLAY_V2_APPEARANCE_IMGSZ", "160")
    model_path = tmp_path / "existing.pt"
    model_path.touch()
    archive = MissionTrajectoryArchive(tmp_path / "spool", appearance_model_path=model_path)

    archive._encode_appearance(
        [
            {
                "track_id": 1,
                "appearance_crop_jpeg": base64.b64encode(encoded).decode("ascii"),
            }
        ]
    )

    assert captured["device"] == "mps"
    assert captured["imgsz"] == 160
