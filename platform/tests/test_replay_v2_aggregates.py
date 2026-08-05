from datetime import UTC, datetime

from app.services.replay_v2_aggregates import build_mission_aggregates


def test_sealed_mission_builds_actual_five_minute_facts_and_a_separate_typical_slot():
    result = build_mission_aggregates(
        mission={
            "id": "MSN-1",
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "started_at": datetime(2026, 8, 5, 8, 2, tzinfo=UTC),
        },
        journeys=[
            {
                "track_id": "J-1",
                "started_offset_ms": 60_000,
                "points": [
                    {"offset_ms": 60_000, "speed": {"ema_kmh": 12.0}},
                    {"offset_ms": 120_000, "speed": {"ema_kmh": 18.0}},
                ],
                "episodes": [
                    {"kind": "stopped", "start_offset_ms": 70_000},
                    {"kind": "releasing", "start_offset_ms": 100_000},
                    {"kind": "standing_queue", "start_offset_ms": 70_000},
                    {"kind": "queue_release", "start_offset_ms": 100_000},
                ],
                "maneuvers": [
                    {"kind": "geometric_u_turn", "start_offset_ms": 110_000},
                ],
            },
        ],
        samples=[
            {"sampled_at": datetime(2026, 8, 5, 8, 3, tzinfo=UTC), "coverage_ratio": 0.8},
            {"sampled_at": datetime(2026, 8, 5, 8, 4, tzinfo=UTC), "coverage_ratio": 1.0},
        ],
        calc_version="replay-v2-aggregate/v1",
        profile_version="replay-v2-typical/v1",
    )

    assert result["intersection"] == [
        {
            "window_start": datetime(2026, 8, 5, 8, 0, tzinfo=UTC),
            "window_end": datetime(2026, 8, 5, 8, 5, tzinfo=UTC),
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "mission_id": "MSN-1",
            "calc_version": "replay-v2-aggregate/v1",
            "vehicle_count": 1,
            "avg_speed_kmh": 15.0,
            "p85_speed_kmh": 18.0,
            "stopped_count": 1,
            "queue_count": 1,
            "release_count": 2,
            "geometric_u_turn_count": 1,
            "inferred_red_signal_queue_count": 0,
            "coverage_ratio": 0.9,
        }
    ]
    assert result["typical"] == [
        {
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "day_of_week": 2,
            "step_index": 96,
            "profile_version": "replay-v2-typical/v1",
            "sample_days": 1,
            "vehicle_count": 1.0,
            "avg_speed_kmh": 15.0,
            "saturation": None,
            "saturation_reason": "lane_capacity_unavailable",
            "quality_status": "estimated",
        }
    ]


def test_road_grains_are_narrow_independent_facts_instead_of_copied_stats_payloads():
    result = build_mission_aggregates(
        mission={
            "id": "MSN-ROAD",
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "started_at": datetime(2026, 8, 5, 8, 0, tzinfo=UTC),
        },
        journeys=[
            {
                "track_id": "J-1",
                "started_offset_ms": 1_000,
                "matched_link_id": "LINK-A",
                "matched_lane_key": "LANE-1",
                "movement_key": "N-S",
                "points": [{"offset_ms": 1_000, "speed": {"ema_kmh": 20.0}}],
                "episodes": [
                    {"kind": "stopped", "start_offset_ms": 1_000},
                    {"kind": "queue_release", "start_offset_ms": 1_500},
                ],
                "maneuvers": [
                    {"kind": "geometric_u_turn", "start_offset_ms": 1_800},
                ],
            },
            {
                "track_id": "J-2",
                "started_offset_ms": 2_000,
                "matched_link_id": "LINK-A",
                "matched_lane_key": "LANE-2",
                "movement_key": "N-S",
                "points": [{"offset_ms": 2_000, "speed": {"ema_kmh": 10.0}}],
                "episodes": [],
                "maneuvers": [],
            },
        ],
        samples=[],
        calc_version="replay-v2-aggregate/v1",
        profile_version="replay-v2-typical/v1",
    )

    assert [(row["link_id"], row["vehicle_count"], row["avg_speed_kmh"]) for row in result["link"]] == [
        ("LINK-A", 2, 15.0),
    ]
    assert result["link"][0]["stopped_count"] == 1
    assert result["link"][0]["release_count"] == 1
    assert result["link"][0]["geometric_u_turn_count"] == 1
    assert [(row["lane_id"], row["vehicle_count"]) for row in result["lane"]] == [
        ("LANE-1", 1),
        ("LANE-2", 1),
    ]
    assert [(row["movement_key"], row["vehicle_count"]) for row in result["turn"]] == [
        ("N-S", 2),
    ]


def test_turn_grain_falls_back_to_frozen_turn_behavior_when_movement_is_unavailable():
    result = build_mission_aggregates(
        mission={
            "id": "MSN-TURN",
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "started_at": datetime(2026, 8, 5, 8, 0, tzinfo=UTC),
        },
        journeys=[
            {
                "track_id": "J-1",
                "started_offset_ms": 1_000,
                "movement_key": None,
                "turn_behavior": "left_turn",
                "points": [{"offset_ms": 1_000, "speed": {"ema_kmh": 12.0}}],
            }
        ],
        samples=[],
        calc_version="replay-v2-aggregate/v1",
        profile_version="replay-v2-typical/v1",
    )

    assert [(row["movement_key"], row["vehicle_count"]) for row in result["turn"]] == [
        ("turn_behavior:left_turn", 1),
    ]
