from copy import deepcopy
from datetime import datetime, timezone
import math
import pytest
from utils_local.trajectory_sampling import (
    retain_indices,
    compact_journey,
    validate_summary,
    VERSION,
)
from services.MissionTrajectoryArchive import MissionTrajectoryArchive
from app.services.replay_v2_aggregates import build_mission_aggregates


def points(count=100, *, stationary=False):
    return [
        {
            "source_timestamp_sec": i / 10,
            "offset_ms": i * 100,
            "frame_num": i,
            "pixel": [i * 0.2, math.sin(i * 0.1) * 10]
            if not stationary
            else [2.0, 3.0],
            "enu_m": [i * 0.01, math.sin(i * 0.1) * 0.5]
            if not stationary
            else [0.0, 0.0],
            "gcj02": [117.0, 36.0],
            "sampling_boundary": [],
            "quality": {
                "tracking_quality": "verified",
                "geo_reference_quality": "verified",
                "timestamp_sec": i / 10,
                "frame_num": i,
            },
            "speed": {"ema_kmh": 0.0 if stationary else float(i % 30)},
        }
        for i in range(count)
    ]


def test_timestamps_and_frame_numbers_do_not_disable_static_sampling():
    values = points(21, stationary=True)
    # This slice is in the middle of a longer, already confirmed parked episode.
    episode = {"kind": "stopped", "start_offset_ms": -10000, "end_offset_ms": 20000}
    assert retain_indices(values, episodes=[episode]) == [0, 20]


def test_each_omitted_point_respects_same_source_time_error_bounds():
    values = points(1000)
    retained = retain_indices(values, policy={"heading_change_deg": 180})
    assert len(retained) < len(values) / 2
    for a, b in zip(retained, retained[1:]):
        for i in range(a + 1, b):
            ratio = (
                values[i]["source_timestamp_sec"] - values[a]["source_timestamp_sec"]
            ) / (values[b]["source_timestamp_sec"] - values[a]["source_timestamp_sec"])
            for key, limit in [("pixel", 2.0), ("enu_m", 0.2)]:
                interpolated = [
                    values[a][key][c] + ratio * (values[b][key][c] - values[a][key][c])
                    for c in (0, 1)
                ]
                assert math.dist(values[i][key], interpolated) <= limit + 1e-9


def test_events_quality_and_real_gaps_are_preserved():
    values = points(200)
    values[60]["quality"]["tracking_quality"] = "lost"
    values[61]["quality"]["tracking_quality"] = "verified"
    for i in range(100, 200):
        values[i]["source_timestamp_sec"] += 2
    retained = retain_indices(values, event_windows=[(2.0, 3.0)])
    assert set(range(20, 31)) <= set(retained)
    assert {59, 60, 61, 99, 100} <= set(retained)
    assert "source_gap" in values[100]["sampling_boundary"]


def test_unknown_speed_uses_moving_heartbeat_and_pixel_mode():
    values = points(50, stationary=True)
    for p in values:
        p["speed"]["ema_kmh"] = None
        p["enu_m"] = None
    retained = retain_indices(values)
    assert all(
        values[b]["source_timestamp_sec"] - values[a]["source_timestamp_sec"]
        <= 0.5 + 1e-9
        for a, b in zip(retained, retained[1:])
    )


def test_full_sequence_aggregates_do_not_change_after_geometry_sampling():
    values = points(1000, stationary=True)
    for i, p in enumerate(values):
        p["speed"]["ema_kmh"] = 0.0 if i < 800 else 40.0
    journey = {
        "track_id": "1",
        "started_offset_ms": 0,
        "source_point_count": len(values),
        "points": deepcopy(values),
        "episodes": [],
        "maneuvers": [],
    }
    basis = datetime(2026, 11, 3, 12, 4, 50, tzinfo=timezone.utc)
    mission = {
        "id": "M",
        "inter_id": "I",
        "source_profile_id": "S",
        "started_at": basis,
    }
    before = build_mission_aggregates(
        mission=mission,
        journeys=[journey],
        samples=[],
        calc_version="full",
        profile_version="full",
    )
    sampled = compact_journey(deepcopy(journey), time_basis=basis.isoformat())
    assert len(sampled["points"]) < len(values) / 2
    after = build_mission_aggregates(
        mission=mission,
        journeys=[sampled],
        samples=[],
        calc_version="full",
        profile_version="full",
    )
    assert before == after
    for p in sampled["points"]:
        original = values[p["frame_num"]]
        assert p["speed"] == original["speed"]


def test_missing_or_corrupt_full_summary_is_not_recomputed_from_sparse_points():
    with pytest.raises(ValueError, match="requires"):
        validate_summary({"algorithm_version": VERSION})
    journey = {
        "points": points(30),
        "source_point_count": 30,
        "episodes": [],
        "maneuvers": [],
    }
    sampled = compact_journey(journey, time_basis="2026-11-03T12:00:00+00:00")
    sampled["sampling"]["full_sequence_summary"]["windows"][0]["count"] += 1
    with pytest.raises(ValueError, match="totals"):
        validate_summary(sampled["sampling"])


def test_archive_v2_requires_fixed_time_basis_and_keeps_raw_until_explicit_cleanup(
    tmp_path,
):
    archive = MissionTrajectoryArchive(tmp_path, sampling_policy={})
    values = points(500, stationary=True)
    segment = {
        "track_id": 1,
        "termination_reason": "natural_eof",
        "trajectory_px": [p["pixel"] for p in values],
        "trajectory_timestamps_sec": [p["source_timestamp_sec"] for p in values],
        "trajectory_frame_nums": [p["frame_num"] for p in values],
        "trajectory_enu_m": [p["enu_m"] for p in values],
        "trajectory_gcj02": [p["gcj02"] for p in values],
        "point_quality_lineage": [p["quality"] for p in values],
    }
    archive.record_segment(
        mission_id="M", source_profile_id="S", intersection_id="I", segment=segment
    )
    with pytest.raises(ValueError, match="time basis"):
        archive.seal_mission("M", termination_reason="natural_eof")
    sealed = archive.seal_mission(
        "M", termination_reason="natural_eof", ended_at="2026-11-03T12:00:50+00:00"
    )
    assert sealed["source_point_count"] == 500
    assert sealed["retained_point_count"] < 250
    assert sealed["coordinate_coverage_ratio"] == 1.0
    assert list((tmp_path / "M/segments").glob("*.json"))
    assert archive.seal_mission("M", termination_reason="natural_eof") == sealed
    archive.cleanup_full_segments("M")
    assert not list((tmp_path / "M/segments").glob("*.json"))
    assert archive.load_mission("M") == sealed


def test_gradual_turn_is_retained_densely_even_when_each_step_heading_is_small():
    values = points(100)
    for i, p in enumerate(values):
        angle = i * 0.015
        p["enu_m"] = [10 * math.cos(angle), 10 * math.sin(angle)]
        p["pixel"] = [v * 10 for v in p["enu_m"]]
        p["speed"]["ema_kmh"] = 10.0
    selected = retain_indices(values)
    assert set(range(20, 80)) <= set(selected)


def test_dense_v2_geometry_transport_is_bounded_deterministic_and_lossless():
    from utils_local.track_message_codec import pack_track_message, unpack_track_message

    message = {
        "msg_type": "uav_track_complete",
        "data": {
            "mission_id": "M",
            "track_id": "1",
            "retained_point_count": 5000,
            "sampling": {"algorithm_version": VERSION},
            "points": [
                {
                    "offset_ms": i * 100,
                    "pixel": [i * 0.1, i * 0.2],
                    "quality": {
                        "tracking_quality": "verified",
                        "frame_num": i,
                        "flight_segment_id": "S",
                    },
                }
                for i in range(5000)
            ],
        },
    }
    packed = pack_track_message(message, trigger_bytes=1000)
    assert "points_blob" in packed["data"] and "points" not in packed["data"]
    assert packed == pack_track_message(message, trigger_bytes=1000)
    assert unpack_track_message(packed) == message
    corrupt = deepcopy(packed)
    corrupt["data"]["points_blob"]["decoded_bytes"] = 10
    with pytest.raises(ValueError):
        unpack_track_message(corrupt)


def test_v2_does_not_freeze_valid_speed_on_missing_world_observations():
    from services.MissionTrajectoryArchive import _journey_from_segment

    values = points(20)
    values[10]["enu_m"] = None
    segment = {
        "track_id": 1,
        "termination_reason": "natural_eof",
        "trajectory_px": [p["pixel"] for p in values],
        "trajectory_timestamps_sec": [p["source_timestamp_sec"] for p in values],
        "trajectory_frame_nums": [p["frame_num"] for p in values],
        "trajectory_enu_m": [p["enu_m"] for p in values],
        "trajectory_gcj02": [p["gcj02"] for p in values],
        "point_quality_lineage": [p["quality"] for p in values],
    }
    journey = _journey_from_segment(segment, 0.0, full_sequence=True)
    assert journey["points"][10]["speed"]["ema_kmh"] is None
    assert journey["points"][10]["speed"]["quality"] == "world_coordinates_unavailable"


def test_short_observation_gap_is_not_hidden_by_maximum_time_interval():
    values = points(21, stationary=True)
    for i, p in enumerate(values):
        p["quality"]["source_frame_stride"] = 1
        p["quality"]["source_drop_count"] = 0
        if i >= 11:
            p["frame_num"] += 1
    retained = retain_indices(values)
    assert 10 in retained and 11 in retained
    assert "source_gap" in values[11]["sampling_boundary"]


def test_public_millisecond_clock_also_respects_pixel_error_bound():
    values = points(3)
    for p, t, ms in zip(values, [0.0, 0.0006, 0.0016], [0, 1, 2]):
        p["source_timestamp_sec"] = t
        p["offset_ms"] = ms
        p["pixel"] = [t * 12000, 0.0]
        p["enu_m"] = [t * 10, 0.0]
        p["speed"]["ema_kmh"] = 10.0
    assert retain_indices(values) == [0, 1, 2]


def test_disabling_geometry_compaction_keeps_v2_full_sequence_statistics():
    values = points(100, stationary=True)
    journey = {
        "track_id": "1",
        "points": deepcopy(values),
        "source_point_count": 100,
        "episodes": [],
        "maneuvers": [],
    }
    result = compact_journey(
        journey, time_basis="2026-11-03T12:00:00+00:00", policy={"enabled": False}
    )
    assert len(result["points"]) == 100
    assert result["sampling"]["algorithm_version"] == VERSION
    assert result["sampling"]["geometry_compacted"] is False
    validate_summary(result["sampling"], source_count=100)


def test_old_raw_archives_cannot_be_cleaned_by_enabling_a_new_policy(tmp_path):
    old = MissionTrajectoryArchive(tmp_path)
    values = points(5, stationary=True)
    segment = {
        "track_id": 1,
        "termination_reason": "natural_eof",
        "trajectory_px": [p["pixel"] for p in values],
        "trajectory_timestamps_sec": [p["source_timestamp_sec"] for p in values],
        "trajectory_frame_nums": [p["frame_num"] for p in values],
        "trajectory_enu_m": [p["enu_m"] for p in values],
        "trajectory_gcj02": [p["gcj02"] for p in values],
        "point_quality_lineage": [p["quality"] for p in values],
    }
    old.record_segment(
        mission_id="M", source_profile_id="S", intersection_id="I", segment=segment
    )
    old.seal_mission("M", termination_reason="natural_eof")
    new = MissionTrajectoryArchive(tmp_path, sampling_policy={})
    with pytest.raises(ValueError, match="never legacy"):
        new.cleanup_full_segments("M")
    assert list((tmp_path / "M/segments").glob("*.json"))
    with pytest.raises(ValueError, match="immutable"):
        new.begin_mission(mission_id="M", source_profile_id="S", intersection_id="I")


def test_four_process_sampling_off_keeps_full_fact_archive(monkeypatch, tmp_path):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module("nodes.KafkaProducerNode")
    monkeypatch.setenv("TRAJECTORY_STORAGE_PROFILE", "replay_v2")
    monkeypatch.setenv("MISSION_ID", "M")
    monkeypatch.setenv("SOURCE_PROFILE_ID", "S")
    monkeypatch.setenv("TRAJECTORY_ARCHIVE_SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(module, "KafkaProducer", lambda **kwargs: None)
    monkeypatch.setattr("utils_local.kafka_topic_preflight.check_fixed_topics", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        module, "ReliableKafkaPublisher", lambda *args, **kwargs: SimpleNamespace()
    )
    config = {
        "pipeline": {"egress_enabled": True},
        "history_sampling": {"enabled": False},
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "kafka_producer_node": {
            "bootstrap_servers": "unused",
            "camera_id": 1,
            "how_often_sec": 1,
        },
    }
    node = module.KafkaProducerNode(config)
    assert node.trajectory_archive.sampling_policy is not None
    assert node.trajectory_archive.sampling_policy["enabled"] is False


def test_slow_crawling_without_confirmed_stop_keeps_moving_heartbeat():
    values = points(100)
    for i, point in enumerate(values):
        point["pixel"] = [i * 0.4, 0.0]
        point["enu_m"] = [i * 0.04, 0.0]
        point["speed"]["ema_kmh"] = 1.44
    retained = retain_indices(values)
    assert all(
        values[b]["source_timestamp_sec"] - values[a]["source_timestamp_sec"]
        <= 0.5 + 1e-9
        for a, b in zip(retained, retained[1:])
    )
