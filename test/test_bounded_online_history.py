import hashlib
import pickle
from queue import Queue
import numpy as np
import pytest
from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from services.PipelineEgress import EgressClient, DeltaTracks


def test_acknowledged_prefix_can_be_evicted_without_losing_a_single_archived_point(
    tmp_path,
):
    disk = DeltaTracks(tmp_path)
    acks = Queue()

    class Sink:
        def put(self, p, timeout):
            role, seq, digest, raw = p
            assert hashlib.sha256(raw).hexdigest() == digest
            kind, data = pickle.loads(raw)
            if kind == "points_batch":
                for row in data:
                    disk.append(row)
            elif kind == "close":
                disk.finish(data)
            acks.put(seq)

    client = EgressClient(
        "tracker", Sink(), acks, bounded_history=True, history_tail_points=64
    )
    track = TrackElement(1, 0)
    for i in range(2000):
        for key, value in {
            "trajectory_points": (i, i + 1),
            "ground_contact_points_px": (i, i + 2),
            "trajectory_timestamps_sec": i * 0.1,
            "trajectory_frame_nums": i,
            "trajectory_enu_m": (i * 0.01, 0),
            "trajectory_gcj02": None,
            "point_quality_lineage": {},
        }.items():
            getattr(track, key).append(value)
        frame = FrameElement("fixture", None, i * 0.1, i, {})
        frame.active_tracks = frame.buffer_tracks = {1: track}
        client.frame(frame)
        assert len(track.trajectory_points) <= 64
    base = track.trajectory_history_start
    assert base == 1936
    row = {
        "track_id": 1,
        "trajectory_history_start": base,
        "trajectory_px": track.ground_contact_points_px,
        "trajectory_bbox_center_px": track.trajectory_points,
        "trajectory_timestamps_sec": track.trajectory_timestamps_sec,
        "trajectory_frame_nums": track.trajectory_frame_nums,
        "trajectory_enu_m": track.trajectory_enu_m,
        "trajectory_gcj02": track.trajectory_gcj02,
        "point_quality_lineage": track.point_quality_lineage,
    }
    client.closed([row])
    complete = disk.closed["1"]
    assert len(complete["trajectory_px"]) == 2000
    assert complete["trajectory_px"][0] == [0, 2]
    assert complete["trajectory_px"][-1] == [1999, 2001]
    assert complete["trajectory_timestamps_sec"] == [i * 0.1 for i in range(2000)]
    disk.disk.close()


@pytest.mark.parametrize("missing", [False, True])
def test_real_online_tracking_speed_direction_and_completed_records_are_equivalent(missing):
    import json
    from test_ground_trajectory_tracker import (
        BaseTrack,
        _TrackingPipeline,
        _config,
        _multi_frame,
        TrackerInfoUpdateNode,
    )
    from nodes.SpeedEstimationNode import SpeedEstimationNode
    from nodes.DirectionFlowNode import DirectionFlowNode
    from nodes.TrajectoryNode import TrajectoryNode
    from nodes.ConflictDetectionNode import ConflictDetectionNode

    def replay(bounded):
        BaseTrack._count = 0
        config = _config()
        config["pipeline"] = {"egress_enabled": True}
        tracker = _TrackingPipeline(config)
        info = TrackerInfoUpdateNode(config)
        speed = SpeedEstimationNode(config)
        direction = DirectionFlowNode(config)
        trajectory = TrajectoryNode(config)
        conflict = ConflictDetectionNode(config)
        disk = DeltaTracks()
        acks = Queue()

        class Sink:
            def put(self, p, timeout):
                role, seq, digest, body = p
                kind, data = pickle.loads(body)
                if kind == "points_batch":
                    for row in data:
                        disk.append(row)
                if kind == "close":
                    disk.finish(data)
                acks.put(seq)

        client = EgressClient(
            "tracker", Sink(), acks, bounded_history=bounded, history_tail_points=64
        )
        observations = []
        for i in range(900):
            x = 20 + min(i, 450) * 0.01
            y = 20 + max(0, i - 500) * 0.01
            frame = _multi_frame(
                i * 0.1, [] if missing and 300 <= i < 304 else [[x, y, x + 20, y + 20]], np.diag([0.1, 0.1, 1.0])
            )
            frame.homography_matrix = np.diag([0.1, 0.1, 1.0])
            frame.drone_displacement_m = np.zeros(2)
            frame = tracker.process(frame)
            frame = info.process(frame)
            frame = speed.process(frame)
            frame = direction.process(frame)
            frame = trajectory.process(frame)
            frame = conflict.process(frame)
            records = {
                str(k): {
                    field: getattr(t, field)
                    for field in (
                        "speed_kmh",
                        "avg_speed_kmh",
                        "max_speed_kmh",
                        "direction_class",
                        "vehicle_class",
                        "heading_angle",
                        "velocity_ms",
                    )
                }
                for k, t in frame.active_tracks.items()
            }
            if missing and i == 299:
                before_lost = set(records)
                assert before_lost
                if bounded:
                    assert all(t.trajectory_history_start > 128 for t in frame.active_tracks.values())
            if missing and i == 310:
                assert set(records) == before_lost, "short loss must reactivate the same mature identities"
            observations.append(
                json.dumps(
                    {
                        "tracks": records,
                        "direction": frame.direction_stats,
                        "conflicts": frame.conflict_events,
                    },
                    sort_keys=True,
                    default=lambda v: (
                        v.tolist() if isinstance(v, np.ndarray) else v.item()
                    ),
                )
            )
            client.frame(frame)
        end = tracker.flush("natural_eof")
        frame = info.flush(
            timestamp=89.9,
            reason="natural_eof",
            terminated_track_ids=end["terminated_track_ids"],
        )
        frame = trajectory.process(frame)
        client.closed(frame.completed_tracks)
        completed = json.dumps(
            disk.closed,
            sort_keys=True,
            default=lambda v: v.tolist() if isinstance(v, np.ndarray) else v.item(),
        )
        disk.disk.close()
        return observations, completed

    baseline = replay(False)
    candidate = replay(True)
    assert candidate[0] == baseline[0]
    assert candidate[1] == baseline[1]
