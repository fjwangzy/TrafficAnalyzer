"""Equivalence and size guards for the incremental egress facts packet.

``EgressClient`` used to pickle every track's full metadata on every frame.  The
delta payload sends frame metadata plus only dynamic per-track fields, and
re-sends a track's static block only when it changes.  These tests drive the real
``freeze_egress_views`` output through ``facts_delta_payload`` /
``apply_facts_delta`` and require the rebuilt facts to match the full snapshot
field by field.
"""

from __future__ import annotations

import pickle
import statistics

import pytest

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from services.PipelineEgress import (
    _DELTA_DROP_FIELDS,
    _DYNAMIC_TRACK_FIELDS,
    apply_facts_delta,
    facts_delta_payload,
    freeze_egress_views,
)


def _track(track_id: int, frame_num: int, *, speed: float = 10.0, road: int = 2) -> TrackElement:
    track = TrackElement(id=track_id, timestamp_first=1.0, start_road=road)
    track.timestamp_last = 1.0 + frame_num * 0.1
    track.avg_speed_kmh = speed
    track.max_speed_kmh = speed + 5.0
    track.vehicle_class = "motor"
    track.yolo_class_id = 3
    track.yolo_class_name = "car"
    track.yolo_model_id = "yolo11s-visdrone.pt@abc"
    track.class_mapping_version = "visdrone-1"
    track.trajectory_history_start = 0
    track.trajectory_points = [[float(frame_num + i), 100.0] for i in range(30)]
    track.ground_contact_points_px = [[float(frame_num + i), 110.0] for i in range(30)]
    track.trajectory_timestamps_sec = [1.0 + i * 0.1 for i in range(30)]
    track.trajectory_frame_nums = list(range(30))
    track.trajectory_enu_m = [[float(i), 2.0] for i in range(30)]
    track.trajectory_gcj02 = [[117.0 + i * 1e-6, 36.6] for i in range(30)]
    track.point_quality_lineage = [
        {"timestamp_sec": 1.0 + i * 0.1, "frame_num": i, "flight_phase": "cruise"}
        for i in range(30)
    ]
    track.current_bbox_xyxy = [1.0 + frame_num, 2.0, 11.0 + frame_num, 22.0]
    track.current_position_enu_m = [float(frame_num), 2.0]
    track.velocity_ms = [1.0, 0.1]
    return track


def _frame(track_ids, frame_num: int, *, mature=None) -> FrameElement:
    frame = FrameElement(
        source="test",
        frame=None,
        timestamp=1.0 + frame_num * 0.1,
        frame_num=frame_num,
        roads_info={},
    )
    tracks = {tid: _track(tid, frame_num, speed=10.0 + tid % 5) for tid in track_ids}
    frame.active_tracks = tracks
    frame.buffer_tracks = tracks
    frame.mature_tracks = (
        None if mature is None else {key: tracks[key] for key in mature if key in tracks}
    )
    frame.info = {"cars_amount": len(tracks)}
    frame.id_list = list(track_ids)
    frame.detected_xyxy = [[1.0, 2.0], [3.0, 4.0]]
    return frame


def _facts(frame: FrameElement):
    snapshot, facts = freeze_egress_views(frame)
    facts.egress_frame_seq = int(frame.frame_num)
    facts.egress_closed_ids = []
    return snapshot, facts


def _assert_same_facts(original, rebuilt, *, dropped=frozenset()):
    ignored = {"active_tracks", "buffer_tracks", "mature_tracks"} | set(dropped)
    expected = {
        name: value for name, value in vars(original).items() if name not in ignored
    }
    actual = {
        name: value for name, value in vars(rebuilt).items() if name not in ignored
    }
    assert actual == expected
    for name in dropped:
        assert getattr(rebuilt, name, None) is None
    original_tracks = original.active_tracks or {}
    rebuilt_tracks = rebuilt.active_tracks or {}
    assert set(rebuilt_tracks) == set(original_tracks)
    for key, view in original_tracks.items():
        assert dict(rebuilt_tracks[key]._values) == dict(view._values), key
    if original.mature_tracks is None:
        assert rebuilt.mature_tracks is None
    else:
        assert set(rebuilt.mature_tracks) == set(original.mature_tracks)
        for key, view in original.mature_tracks.items():
            assert dict(rebuilt.mature_tracks[key]._values) == dict(view._values)


def test_delta_round_trip_matches_full_snapshot_every_frame():
    cache: dict = {}
    for frame_num in range(1, 13):
        ids = [1, 2, 3] if frame_num < 8 else [1, 2, 3, 4]
        _, facts = _facts(_frame(ids, frame_num, mature=[1, 2]))
        payload = facts_delta_payload(facts, cache)
        rebuilt = apply_facts_delta(payload, cache)
        _assert_same_facts(facts, rebuilt, dropped=_DELTA_DROP_FIELDS)


def test_static_block_is_sent_only_on_change():
    cache: dict = {}
    _, facts = _facts(_frame([1, 2], 1))
    first = facts_delta_payload(facts, cache)
    assert set(first["static"]) == {1, 2}
    second = facts_delta_payload(_facts(_frame([1, 2], 2))[1], cache)
    assert second["static"] == {}
    assert set(second["dynamic"]) == {1, 2}

    changed = _track(1, 3)
    changed.vehicle_class = "non_motor"
    changed.yolo_class_name = "bicycle"
    frame = _frame([1, 2], 3)
    frame.active_tracks[1] = changed
    frame.buffer_tracks = frame.active_tracks
    third = facts_delta_payload(_facts(frame)[1], cache)
    assert set(third["static"]) == {1}
    assert third["static"][1]["vehicle_class"] == "non_motor"


def test_speed_and_heading_churn_do_not_resend_static_blocks():
    cache: dict = {}
    facts_delta_payload(_facts(_frame([1], 1))[1], cache)
    frame = _frame([1], 2)
    track = frame.active_tracks[1]
    track.avg_speed_kmh = 33.5
    track.speed_kmh = 31.0
    track.heading_angle = 91.5
    track.current_observation_timestamp_sec = 2.2
    track.timestamp_last = 2.2
    payload = facts_delta_payload(_facts(frame)[1], cache)
    assert payload["static"] == {}
    dynamic = payload["dynamic"][1]
    assert dynamic["avg_speed_kmh"] == 33.5
    assert dynamic["heading_angle"] == 91.5
    rebuilt = apply_facts_delta(payload, cache)
    assert dict(rebuilt.active_tracks[1]._values) == dict(
        _facts(frame)[1].active_tracks[1]._values
    )


def test_absent_tracks_are_pruned_and_unknown_tracks_raise():
    cache: dict = {}
    facts_delta_payload(_facts(_frame([1, 2, 3], 1))[1], cache)
    assert set(cache) == {1, 2, 3}
    third = facts_delta_payload(_facts(_frame([1, 2], 2))[1], cache)
    assert set(third["present"]) == {1, 2}
    rebuilt = apply_facts_delta(third, cache)
    assert set(rebuilt.active_tracks) == {1, 2}
    assert set(cache) == {1, 2}

    with pytest.raises(ValueError):
        apply_facts_delta(
            {
                "frame_seq": 9,
                "meta": {},
                "present": [42],
                "mature": None,
                "static": {},
                "dynamic": {42: {}},
            },
            {},
        )


def test_dynamic_fields_are_always_sent_and_static_ones_are_not():
    cache: dict = {}
    _, facts = _facts(_frame([1], 1))
    payload = facts_delta_payload(facts, cache)
    static_names = set(payload["static"][1])
    dynamic_names = set(payload["dynamic"][1])
    assert dynamic_names <= set(_DYNAMIC_TRACK_FIELDS)
    assert static_names.isdisjoint(dynamic_names)
    assert "avg_speed_kmh" in dynamic_names
    assert "vehicle_class" in static_names
    # Every field the archive view carries is covered exactly once.
    values = set(dict(facts.active_tracks[1]._values))
    assert values == static_names | dynamic_names


def test_steady_state_payload_is_materially_smaller_than_full_snapshot():
    cache: dict = {}
    ids = list(range(1, 201))
    _, facts = _facts(_frame(ids, 1, mature=ids[:100]))
    facts_delta_payload(facts, cache)
    _, facts = _facts(_frame(ids, 2, mature=ids[:100]))
    payload = facts_delta_payload(facts, cache)
    delta_bytes = len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    full_bytes = len(pickle.dumps(facts, protocol=pickle.HIGHEST_PROTOCOL))
    assert delta_bytes < full_bytes * 0.5, (delta_bytes, full_bytes)

    # Reporting only: keep the observed ratio visible in the test log.
    ratios = [delta_bytes / full_bytes]
    print(
        f"facts delta {delta_bytes} B vs full {full_bytes} B "
        f"({1 - statistics.median(ratios):.0%} smaller) at {len(ids)} tracks"
    )


def test_independent_sender_receiver_caches_survive_wire_and_reactivation():
    """Caches never share objects across the actual pickle boundary."""
    sender, receiver = {}, {}
    for number, identities in enumerate(([1, 2], [1], [], [1, 2], [2]), 1):
        _, facts = _facts(_frame(identities, number))
        wire = pickle.dumps(facts_delta_payload(facts, sender))
        rebuilt = apply_facts_delta(pickle.loads(wire), receiver)
        _assert_same_facts(facts, rebuilt, dropped=_DELTA_DROP_FIELDS)
        assert set(sender) == set(receiver) == set(identities)
        for key in identities:
            assert sender[key] is not receiver[key]
