from types import SimpleNamespace

import pytest

from app.api.v1.trajectories import get_replay_missions, get_trajectory_replay
from app.services.replay_repository import InMemoryReplayRepository


def _request(repository):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(replay_repository=repository)),
        state=SimpleNamespace(user={"role": "admin"}),
    )


@pytest.mark.asyncio
async def test_replay_api_lists_only_sealed_missions_and_returns_real_point_clock():
    repository = InMemoryReplayRepository(
        [
            {
                "id": "MSN-SEALED",
                "inter_id": "INT-1",
                "source_profile_id": "SRC-1",
                "status": "sealed",
                "duration_ms": 1200,
                "coordinate_coverage_ratio": 0.5,
                "algorithm_versions": {"sampling": "event-faithful/v1"},
                "accuracy": {"idf1": "not_evaluated"},
                "journeys": [
                    {
                        "track_id": "J-1",
                        "source_runtime_track_ids": ["17"],
                        "source_point_count": 4,
                        "retained_point_count": 4,
                        "sampling": {"algorithm_version": "event-faithful/v1"},
                        "episodes": [{"kind": "stopped", "start_offset_ms": 600, "end_offset_ms": 1000}],
                        "maneuvers": [],
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [10, 20], "enu_m": None, "gcj02": None, "speed": {}, "quality": {}, "sampling_boundary": []},
                            {"offset_ms": 400, "frame_num": 2, "pixel": [11, 20], "enu_m": None, "gcj02": None, "speed": {}, "quality": {}, "sampling_boundary": []},
                            {"offset_ms": 800, "frame_num": 3, "pixel": [12, 20], "enu_m": [1, 2], "gcj02": [117, 36], "speed": {}, "quality": {}, "sampling_boundary": ["coordinate_validity"]},
                            {"offset_ms": 1200, "frame_num": 4, "pixel": [13, 20], "enu_m": [2, 2], "gcj02": [117.1, 36], "speed": {}, "quality": {}, "sampling_boundary": ["journey_end"]},
                        ],
                    }
                ],
            },
            {"id": "MSN-INCOMPLETE", "inter_id": "INT-1", "status": "incomplete", "journeys": []},
        ]
    )

    missions = await get_replay_missions("INT-1", _request(repository), False)
    assert [mission["mission_id"] for mission in missions["items"]] == ["MSN-SEALED"]

    replay = await get_trajectory_replay(
        "INT-1",
        _request(repository),
        mission_id="MSN-SEALED",
        cursor_sec=0.6,
        window_sec=0.5,
        max_points=100,
        track_id=None,
        behavior=None,
        page_after=None,
    )
    assert replay["schema_version"] == "uav.trajectory-replay/v1"
    assert replay["mission"]["duration_ms"] == 1200
    assert replay["cursor"]["offset_ms"] == 600
    assert replay["cursor"]["window_start_ms"] == 100
    assert replay["tracks"][0]["points"][0]["offset_ms"] == 0  # deterministic anchor
    assert [point["offset_ms"] for point in replay["tracks"][0]["points"]] == [0, 400]
    assert replay["tracks"][0]["points"][1]["enu_m"] is None


@pytest.mark.asyncio
async def test_replay_analysis_restores_physical_entry_and_exit_directions_from_journey_geometry():
    repository = InMemoryReplayRepository(
        [
            {
                "id": "MSN-DIRECTIONS",
                "inter_id": "INT-1",
                "status": "sealed",
                "duration_ms": 2_000,
                "coordinate_coverage_ratio": 1.0,
                "journeys": [
                    {
                        "track_id": "J-EW",
                        "turn_behavior": "straight",
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [0, 0], "enu_m": [12, 1], "speed": {"ema_kmh": 30}},
                            {"offset_ms": 1_000, "frame_num": 2, "pixel": [1, 0], "enu_m": [-10, 0], "speed": {"ema_kmh": 32}},
                        ],
                    },
                    {
                        "track_id": "J-NW",
                        "turn_behavior": "right_turn",
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [0, 0], "enu_m": [0, 15], "speed": {"ema_kmh": 18}},
                            {"offset_ms": 1_000, "frame_num": 2, "pixel": [0, 1], "enu_m": [0, 8], "speed": {"ema_kmh": 20}},
                        ],
                    },
                    {
                        "track_id": "J-FALLBACK",
                        "turn_behavior": "straight",
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [0, 0], "enu_m": None, "speed": {"ema_kmh": 10}},
                        ],
                    },
                ],
            }
        ]
    )

    replay = await repository.replay(
        "INT-1",
        mission_id="MSN-DIRECTIONS",
        cursor_ms=1_000,
        window_ms=1_000,
        max_points=100,
        page_after=None,
        track_id=None,
        behavior=None,
        vehicle_class=None,
        yolo_class_id=None,
        turn_behavior=None,
        movement_key=None,
    )

    ranking = {item["movement_key"]: item for item in replay["analysis"]["movement_ranking"]}
    assert ranking["approach:east|exit:west"]["movement_label"] == "东进口 → 西出口"
    assert ranking["approach:north|exit:west"]["movement_label"] == "北进口 → 西出口"
    assert ranking["approach:north|exit:west"]["movement_source"] == "trajectory_quadrant_inferred"
    assert ranking["turn:straight"]["movement_label"] == "直行（进口未知）"
    assert {track["movement_label"] for track in replay["tracks"]} == {
        "东进口 → 西出口",
        "北进口 → 西出口",
        "直行（进口未知）",
    }

    focused = await repository.replay(
        "INT-1",
        mission_id="MSN-DIRECTIONS",
        cursor_ms=1_000,
        window_ms=1_000,
        max_points=100,
        page_after=None,
        track_id=None,
        behavior=None,
        vehicle_class=None,
        yolo_class_id=None,
        turn_behavior=None,
        movement_key="approach:north|exit:west",
    )
    assert [track["track_id"] for track in focused["tracks"]] == ["J-NW"]


@pytest.mark.asyncio
async def test_replay_api_page_anchor_continues_without_duplicate_points():
    repository = InMemoryReplayRepository(
        [
            {
                "id": "MSN-PAGED",
                "inter_id": "INT-1",
                "source_profile_id": "SRC-1",
                "status": "sealed",
                "duration_ms": 2_000,
                "journeys": [
                    {
                        "track_id": "J-1",
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [0, 0]},
                            {"offset_ms": 1_000, "frame_num": 2, "pixel": [1, 0]},
                            {"offset_ms": 2_000, "frame_num": 3, "pixel": [2, 0]},
                        ],
                    }
                ],
            }
        ]
    )

    first = await get_trajectory_replay(
        "INT-1",
        _request(repository),
        mission_id="MSN-PAGED",
        cursor_sec=2.0,
        window_sec=2.0,
        max_points=2,
        track_id=None,
        behavior=None,
        page_after=None,
    )
    second = await get_trajectory_replay(
        "INT-1",
        _request(repository),
        mission_id="MSN-PAGED",
        cursor_sec=2.0,
        window_sec=2.0,
        max_points=2,
        track_id=None,
        behavior=None,
        page_after=first["pagination"]["next_page_after"],
    )

    assert [point["point_seq"] for point in first["tracks"][0]["points"]] == [0, 1]
    assert [point["point_seq"] for point in second["tracks"][0]["points"]] == [2]
    assert first["pagination"]["truncated"] is True
    assert first["analysis"]["quality"]["truncated"] is True
    assert first["analysis"]["quality"]["returned_tracks"] == 1
    assert second["pagination"] == {"truncated": False, "next_page_after": None}


@pytest.mark.asyncio
async def test_incomplete_missions_are_available_only_to_admin_diagnostics():
    repository = InMemoryReplayRepository(
        [{"id": "MSN-INCOMPLETE", "inter_id": "INT-1", "status": "incomplete"}]
    )
    analyst_request = _request(repository)
    analyst_request.state.user = {"role": "analyst"}

    with pytest.raises(Exception) as caught:
        await get_replay_missions("INT-1", analyst_request, True)

    assert caught.value.status_code == 403
    admin = await get_replay_missions("INT-1", _request(repository), True)
    assert admin["items"][0]["status"] == "incomplete"


@pytest.mark.asyncio
async def test_replay_does_not_hold_a_departed_vehicle_after_its_journey_ended():
    repository = InMemoryReplayRepository(
        [
            {
                "id": "MSN-LIFETIME",
                "inter_id": "INT-1",
                "status": "sealed",
                "duration_ms": 20_000,
                "journeys": [
                    {
                        "track_id": "J-DEPARTED",
                        "points": [
                            {"offset_ms": 0, "frame_num": 1, "pixel": [0, 0]},
                            {"offset_ms": 1_000, "frame_num": 2, "pixel": [1, 0]},
                        ],
                    }
                ],
            }
        ]
    )

    replay = await get_trajectory_replay(
        "INT-1",
        _request(repository),
        mission_id="MSN-LIFETIME",
        cursor_sec=10.0,
        window_sec=5.0,
        max_points=100,
        track_id=None,
        behavior=None,
        page_after=None,
    )

    assert replay["tracks"] == []
