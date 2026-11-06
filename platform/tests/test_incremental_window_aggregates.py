from datetime import UTC, datetime, timedelta
from app.services.replay_v2_aggregates import build_mission_aggregates
from utils_local.trajectory_sampling import full_sequence_summary

BASE = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
MISSION = {"id": "M1", "inter_id": "I1", "source_profile_id": "S1", "started_at": BASE}


def journey(track, start, speeds):
    points = [
        {"offset_ms": start + i * 1000, "enu_m": [i, 0], "speed": {"ema_kmh": v}}
        for i, v in enumerate(speeds)
    ]
    return {
        "track_id": track,
        "started_offset_ms": start,
        "source_point_count": len(points),
        "sampling": {
            "algorithm_version": "event-faithful/v2",
            "full_sequence_summary": full_sequence_summary(points, BASE.isoformat()),
        },
        "points": [],
        "episodes": [{"kind": "stopped", "start_offset_ms": start}],
        "maneuvers": [],
        "matched_link_id": "L1",
    }


def test_incremental_pages_equal_existing_full_sequence_aggregate():
    from app.services.incremental_window_aggregates import WindowAccumulator

    rows = [journey("a", 1000, [10.0, 20.0, 30.0]), journey("b", 5000, [40.0, 50.0])]
    expected = build_mission_aggregates(
        mission=MISSION,
        journeys=rows,
        samples=[],
        calc_version="replay-v2-aggregate/v2",
        profile_version="test",
    )
    accumulator = WindowAccumulator(MISSION, BASE)
    for row in rows:
        accumulator.add(row)
    actual = accumulator.facts()
    for grain in ("intersection", "link", "lane", "turn"):
        assert actual[grain] == expected[grain]


def test_linked_fragments_have_one_entry_but_preserve_all_speed_samples():
    from app.services.incremental_window_aggregates import WindowAccumulator

    first = journey("a", 1000, [10.0, 20.0])
    second = journey("b", 5000, [30.0, 40.0])
    accumulator = WindowAccumulator(MISSION, BASE)
    accumulator.add(first)
    accumulator.add(second, root=first)
    row = accumulator.facts()["intersection"][0]
    assert row["vehicle_count"] == 1
    assert row["stopped_count"] == 1
    assert row["avg_speed_kmh"] == 25
    assert row["p85_speed_kmh"] == 40


def test_late_fragment_in_next_window_does_not_count_a_second_vehicle_entry():
    from app.services.incremental_window_aggregates import WindowAccumulator

    first = journey("a", 299000, [10.0])
    second = journey("b", 300500, [30.0, 40.0])
    accumulator = WindowAccumulator(MISSION, BASE + timedelta(minutes=5))
    accumulator.add(second, root=first)
    row = accumulator.facts()["intersection"][0]
    assert row["vehicle_count"] == 0
    assert row["avg_speed_kmh"] == 35
    assert row["p85_speed_kmh"] == 40
