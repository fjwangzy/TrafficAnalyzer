"""Exercise the real three-worker tracker -> display handoff with long histories."""

import copy
import pickle

import numpy as np
import pytest

import main_optimized
from elements.VideoEndBreakElement import VideoEndBreakElement
from services.PipelineEgress import freeze_display_frame
from test.test_pipeline_egress import frame
from test import test_show_node_class_colors as show_tests


@pytest.mark.parametrize("send_kafka", [True, False])
def test_three_worker_handoff_is_bounded_and_keeps_full_analysis(monkeypatch, send_kafka):
    sources = [frame(60), frame(3000)]
    for f in sources:
        f.frame = None
        f.association_trajectories = [{
            "association_id": 1,
            "trajectory_display_px": f.active_tracks[1].trajectory_points,
            "trajectory_enu_m": f.active_tracks[1].trajectory_enu_m,
            "point_quality_lineage": f.active_tracks[1].point_quality_lineage,
        }]
        f.pending_tcc_envelopes = [{"data": {"event_id": "tcc"}}]
        f.pending_enforcement_envelopes = [{"data": {"event_id": "clue"}}]
    sentinel = VideoEndBreakElement("fixture", 301.0)
    incoming = iter([*sources, sentinel])
    received = []
    analysis_lengths = []

    class Node:
        last_flush_result = None

        def __init__(self, config):
            pass

        def process(self, f):
            return f

        def flush(self, **kwargs):
            return None

        def seal_replay_mission(self, *args, **kwargs):
            pass

    class Producer(Node):
        def process(self, f):
            if not isinstance(f, VideoEndBreakElement):
                analysis_lengths.append(len(f.active_tracks[1].trajectory_points))
            return f

    for name in vars(main_optimized).copy():
        if name.endswith("Node") and name not in {"ShowNode"}:
            monkeypatch.setattr(main_optimized, name, Node)
    monkeypatch.setattr(main_optimized, "KafkaProducerNode", Producer)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)

    class Input:
        def get(self, timeout):
            return next(incoming)

    class Output:
        def put(self, value):
            # Serialize at the actual handoff seam, as Queue's feeder does.
            received.append(pickle.dumps(value))

    main_optimized.proc_tracker_update_and_calc(
        Input(), Output(),
        {"tracking_profile": "hover_cruise_v1", "pipeline": {"send_info_kafka": send_kafka}},
        reader_pid=123,
    )
    assert len(received[1]) < len(received[0]) * 1.15
    assert len(received[1]) < 20000
    for source, payload in zip(sources, received):
        restored = pickle.loads(payload)
        assert len(restored.active_tracks[1].trajectory_points) == 30
        assert "trajectory_enu_m" not in restored.association_trajectories[0]
        assert len(restored.association_trajectories[0]["trajectory_display_px"]) == 30
        assert list(restored.pending_tcc_envelopes) == source.pending_tcc_envelopes
        assert list(restored.pending_enforcement_envelopes) == source.pending_enforcement_envelopes
    assert [len(f.active_tracks[1].trajectory_points) for f in sources] == [60, 3000]
    assert analysis_lengths == ([60, 3000] if send_kafka else [])
    assert isinstance(pickle.loads(received[-1]), VideoEndBreakElement)


@pytest.mark.parametrize("candidate", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.parametrize("visual_history", [False, True])
def test_snapshot_render_matches_full_history_pixels(candidate, conflict, visual_history):
    source = frame(3000)
    track = source.active_tracks[1]
    track.trajectory_points = [(100.0 + (i % 30) * 2, 100.0) for i in range(3000)]
    track.trajectory_output_eligible = not candidate
    source.mature_tracks = {} if candidate else source.active_tracks
    source.tracked_xyxy = [[140, 70, 180, 100]]
    source.id_list = [1]
    source.tracked_cls = ["car"]
    source.tracked_conf = [0.9]
    source.candidate_trajectories = ([{"track_id": 1, "trajectory_px": track.trajectory_points}]
                                     if candidate else [])
    if conflict:
        other = copy.deepcopy(track)
        other.id = 2
        other.trajectory_points = [(220.0, 100.0)] * 3000
        source.active_tracks[2] = other
        source.id_list.append(2)
        source.tracked_xyxy.append([200, 70, 240, 100])
        source.tracked_cls.append("motor")
        source.tracked_conf.append(0.9)
        source.conflict_events = [{"motor_id": 1, "non_motor_id": 2,
                                   "severity": "critical", "ttc_sec": 1.6}]
    if visual_history:
        source.association_trajectories = [
            {"association_id": key, "trajectory_display_px": value.trajectory_points,
             "trajectory_enu_m": value.trajectory_enu_m}
            for key, value in source.active_tracks.items()
        ]
    frozen = pickle.loads(pickle.dumps(freeze_display_frame(source)))
    original = copy.deepcopy(source)
    original.frame = np.zeros((240, 320, 3), np.uint8)
    frozen.frame = original.frame.copy()
    before = show_tests.ShowNodeClassColorsTest._make_node().process(original).frame_result
    after = show_tests.ShowNodeClassColorsTest._make_node().process(frozen).frame_result
    np.testing.assert_array_equal(after, before)
