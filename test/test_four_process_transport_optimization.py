"""Exercise the actual four-worker handoff, including its durable packet boundary."""

import pickle
from queue import Queue
import numpy as np
import pytest
from services.PipelineEgress import EgressClient, apply_facts_delta
from native_trajectory_pickle_fixture import make


def handoff(source):
    acknowledgements = Queue()
    packets = []

    class Sink:
        def put(self, packet, timeout):
            packets.append(pickle.loads(packet[3]))
            acknowledgements.put(packet[1])

    client = EgressClient("tracker", Sink(), acknowledgements)
    client.offsets = {
        str(k): len(t.trajectory_points) - 1 for k, t in source.active_tracks.items()
    }
    rendered = pickle.loads(pickle.dumps(client.frame(source)))
    # The client may send an incremental facts packet; rebuild the same object the
    # egress writer would commit so every assertion below tests the real contract.
    static_cache: dict = {}
    decoded = []
    for kind, data in packets:
        if kind == "frame_delta":
            decoded.append(("frame", apply_facts_delta(data, static_cache)))
        else:
            decoded.append((kind, data))
    return rendered, decoded


def test_four_worker_display_excludes_archive_geometry_but_facts_keep_it():
    source = make(False, 250, 500)
    source.frame = None
    source.association_trajectories = [
        {
            "association_id": k,
            "trajectory_display_px": t.trajectory_points,
            "trajectory_enu_m": t.trajectory_enu_m,
            "point_quality_lineage": t.point_quality_lineage,
        }
        for k, t in source.active_tracks.items()
    ]
    rendered, packets = handoff(source)
    assert len(pickle.dumps(rendered)) < 400000
    assert all(
        "trajectory_enu_m" not in vars(t)["_values"]
        for t in rendered.active_tracks.values()
    )
    assert all(
        set(row)
        <= {"track_id", "association_id", "trajectory_px", "trajectory_display_px"}
        for row in rendered.association_trajectories
    )
    facts = next(data for kind, data in packets if kind == "frame")
    assert len(facts.active_tracks) == 250
    assert all(
        view.trajectory_point_count == 500 for view in facts.active_tracks.values()
    )
    assert (
        sum(
            len(row["arrays"]["trajectory_px"])
            for kind, data in packets
            if kind == "points_batch"
            for row in data
        )
        == 250
    )
    source.active_tracks[0].trajectory_points[-1] = (99999, 99999)
    assert rendered.active_tracks[0].trajectory_points[-1] != (99999, 99999)
    assert (
        facts.active_tracks[0].geo_reference_quality
        == source.active_tracks[0].geo_reference_quality
    )


def logical(value):
    if isinstance(value, dict):
        return {k: logical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [logical(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "__dict__"):
        return logical(vars(value))
    return value


def test_four_worker_archive_facts_match_previous_contract_and_are_detached():
    from services.PipelineEgress import freeze_frame

    source = make(False, 3, 60)
    source.conflict_events = [{"motor_id": 0, "non_motor_id": 1, "ttc_sec": 1.3}]
    source.enforcement_clues = [{"track_id": 0, "kind": "truck"}]
    source.info = {"cars_amount": 3, "roads_activity": {"R": 1}}
    source.shm_name = "owned-test"
    source.shm_shape = (20, 20, 3)
    source.shm_dtype = "uint8"
    source.annotation_snapshot_requested = True
    source.fact_wall_time = 100.0
    source.pipeline_fps = 1.4
    source.candidate_trajectories = [
        {
            "association_id": 3,
            "trajectory_px": [(1.0, 2.0)] * 60,
            "trajectory_enu_m": [(3.0, 4.0)] * 60,
            "point_quality_lineage": [{"quality": "good"}] * 60,
            "state": "candidate",
        }
    ]
    source.association_trajectories = [
        {
            "association_id": 0,
            "trajectory_display_px": [(1.0, 2.0)] * 60,
            "trajectory_enu_m": [(3.0, 4.0)] * 60,
            "tracking_quality": "verified",
        }
    ]
    expected = freeze_frame(source, 0)
    expected.candidate_trajectories = freeze_frame(source).candidate_trajectories
    expected.egress_frame_seq = 1
    expected.egress_closed_ids = []
    rendered, packets = handoff(source)
    facts = next(data for kind, data in packets if kind == "frame")
    # ``render_snapshot`` is the display view for the image owner; the incremental
    # facts packet omits it (the egress writer never reads it) and the egress
    # writer rebuilds tracks from the delta blocks instead.
    assert facts.render_snapshot is None
    assert logical(vars(facts) | {"render_snapshot": None}) == logical(
        vars(expected) | {"render_snapshot": None}
    )
    rendered.conflict_events[0]["ttc_sec"] = 9
    rendered.info["roads_activity"]["R"] = 9
    source.enforcement_clues[0]["kind"] = "changed"
    assert facts.conflict_events[0]["ttc_sec"] == 1.3
    assert source.conflict_events[0]["ttc_sec"] == 1.3
    assert facts.info["roads_activity"]["R"] == 1
    assert facts.enforcement_clues[0]["kind"] == "truck"
    assert rendered.shm_name == source.shm_name
    assert rendered.annotation_snapshot_requested
    assert all(len(t.trajectory_points) == 60 for t in source.active_tracks.values())


@pytest.mark.parametrize("candidate", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.parametrize("visual_history", [False, True])
def test_four_worker_pixels_match_authoritative_tracks(
    monkeypatch, candidate, conflict, visual_history
):
    from test import test_three_process_render_transport as reference

    monkeypatch.setattr(
        reference, "freeze_display_frame", lambda frame: handoff(frame)[0]
    )
    reference.test_snapshot_render_matches_full_history_pixels(
        candidate, conflict, visual_history
    )


def test_same_version_fallback_keeps_archive_facts_identical():
    from services.PipelineEgress import freeze_frame

    source = make(False, 3, 60)
    acks = Queue()
    packets = []

    class Sink:
        def put(self, packet, timeout):
            packets.append(pickle.loads(packet[3]))
            acks.put(packet[1])

    client = EgressClient("tracker", Sink(), acks, optimized_views=False)
    client.offsets = {str(k): 60 for k in source.active_tracks}
    display = client.frame(source)
    assert logical(display.active_tracks) == logical(freeze_frame(source).active_tracks)
    old_facts = next(data for kind, data in packets if kind == "frame")
    _, new_packets = handoff(source)
    new_facts = next(data for kind, data in new_packets if kind == "frame")
    # Both paths must agree on every archive fact; the delta packet intentionally
    # omits the display-only render_snapshot.
    assert logical(vars(new_facts) | {"render_snapshot": None}) == logical(
        vars(old_facts) | {"render_snapshot": None}
    )


def test_four_worker_keeps_speed_road_labels_and_exact_evidence(monkeypatch, tmp_path):
    from test.test_show_node_class_colors import ShowNodeClassColorsTest
    from nodes.EgressEvidenceNode import EgressEvidenceNode

    source = make(False, 2, 60)
    for key, track in source.active_tracks.items():
        track.trajectory_points = [(100.0 + key * 100, 100.0)] * 60
        track.start_road = 1
        track.avg_speed_kmh = 36.75
    source.id_list = [0, 1]
    source.tracked_xyxy = [[80, 70, 120, 100], [180, 70, 220, 100]]
    source.tracked_cls = ["car", "motor"]
    source.tracked_conf = [0.9, 0.9]
    source.trajectory_output_eligible = True
    source.trajectory_association_ids = [0, 1]
    source.mature_trajectory_association_ids = [0, 1]
    source.track_id_by_association = {0: 0, 1: 1}
    source.conflict_events = [
        {"motor_id": 0, "non_motor_id": 1, "ttc_sec": 1.5, "severity": "critical"}
    ]
    rendered, _ = handoff(source)
    image = np.zeros((240, 320, 3), np.uint8)
    source.frame = image.copy()
    rendered.frame = image.copy()
    before = ShowNodeClassColorsTest._make_node().process(source).frame_result.copy()
    after = ShowNodeClassColorsTest._make_node().process(rendered).frame_result.copy()
    assert np.count_nonzero(before) > 0
    np.testing.assert_array_equal(before, after)
    monkeypatch.setenv("SURVEY_STORAGE_DIR", str(tmp_path))
    sent = []

    class Client:
        def send(self, kind, data):
            sent.append(data)

    cfg = {
        "pipeline": {"send_info_kafka": True},
        "video_saver_node": {"conflict_jpeg_quality": 95},
    }
    source.egress_frame_seq = rendered.egress_frame_seq = 1
    EgressEvidenceNode(cfg, Client()).process(source)
    EgressEvidenceNode(cfg, Client()).process(rendered)
    assert sent[0] == sent[1]
    assert sent[0]["ok"] and len(sent[0]["tcc"]) == 2
