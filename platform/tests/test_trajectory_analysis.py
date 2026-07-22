from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services.metric_store import PostgresMetricStoreAdapter
from app.services.trajectory_analysis import build_trajectory_analysis


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _track(
    *,
    row_id: str,
    track_id: str,
    mission_id: str,
    started_at: str,
    ended_at: str,
    start_road_id: str | None,
    exit_road_id: str | None,
    vehicle_class: str,
    yolo_class_id: int | None,
    yolo_class_name: str | None,
    trajectory: list[list[float]],
    offsets: list[float],
):
    return SimpleNamespace(
        id=row_id,
        track_id=track_id,
        mission_id=mission_id,
        pipeline_id=f"pipe-{mission_id}",
        source_profile_id="SRC-1",
        inter_id="INT-1",
        road_data_version="road-v1",
        road_context_status="matched",
        quality_status="verified",
        time_quality="verified",
        started_at=_dt(started_at),
        ended_at=_dt(ended_at),
        vehicle_class=vehicle_class,
        yolo_class_id=yolo_class_id,
        yolo_class_name=yolo_class_name,
        yolo_model_id="yolo11s.pt@abc123",
        class_mapping_version="visdrone-business/v1",
        turn_behavior="straight",
        start_road_id=start_road_id,
        exit_road_id=exit_road_id,
        avg_speed_kmh=31.5,
        max_speed_kmh=42.0,
        trajectory_enu_m=trajectory,
        trajectory_gcj02=[[117.0 + point[0] / 100000, 36.7 + point[1] / 100000] for point in trajectory],
        anchor_gcj02=[117.0, 36.7],
        map_version_id="CMV-TEST",
        payload={
            "data": {
                "trajectory_enu_m": trajectory,
                "trajectory_time_offsets_sec": offsets,
            }
        },
    )


def _conflict(*, event_id: str, mission_id: str, occurred_at: str, motor_id: str, non_motor_id: str):
    return SimpleNamespace(
        id=event_id,
        mission_id=mission_id,
        pipeline_id=f"pipe-{mission_id}",
        source_profile_id="SRC-1",
        occurred_at=_dt(occurred_at),
        motor_id=motor_id,
        non_motor_id=non_motor_id,
        severity="warning",
        ttc_sec=1.2,
        pet_sec=0.4,
        conflict_scene="crossing",
        prediction_type="path_intersection",
        risk_score=0.7,
        evidence=["hard_ttc_or_pet"],
        payload={"data": {"message": "candidate"}},
    )


def test_builds_ranked_movements_time_buckets_and_raw_yolo_summary():
    tracks = [
        _track(
            row_id="row-a", track_id="7", mission_id="M1",
            started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
            start_road_id="1", exit_road_id="2", vehicle_class="motor",
            yolo_class_id=3, yolo_class_name="car",
            trajectory=[[0, 0], [10, 0], [20, 0]], offsets=[0, 10, 20],
        ),
        _track(
            row_id="row-b", track_id="8", mission_id="M1",
            started_at="2026-07-21T08:00:10Z", ended_at="2026-07-21T08:00:30Z",
            start_road_id="1", exit_road_id="3", vehicle_class="motor",
            yolo_class_id=6, yolo_class_name="bus",
            trajectory=[[0, 2], [10, 2], [20, 2]], offsets=[0, 10, 20],
        ),
    ]
    conflicts = [
        _conflict(event_id="c1", mission_id="M1", occurred_at="2026-07-21T08:00:15Z", motor_id="7", non_motor_id="8"),
        # Same track id in another mission must not be joined to M1.
        _conflict(event_id="c2", mission_id="M2", occurred_at="2026-07-21T08:00:16Z", motor_id="7", non_motor_id="99"),
    ]

    result = build_trajectory_analysis(
        intersection_id="INT-1",
        tracks=tracks,
        conflicts=conflicts,
        start_at=_dt("2026-07-21T08:00:00Z"),
        end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:09Z"),
        slice_end_at=_dt("2026-07-21T08:00:21Z"),
        bucket_sec=10,
        movement_key="entry:1|exit:2",
        track_limit=20,
    )

    assert [item["movement_key"] for item in result["movement_ranking"]] == [
        "entry:1|exit:2", "entry:1|exit:3",
    ]
    assert [item["conflict_count"] for item in result["movement_ranking"]] == [1, 1]
    assert [item["active_tracks"] for item in result["timeline"]] == [1, 1, 1]
    assert result["quality"]["total_tracks"] == 1
    assert result["class_summary"]["business"] == [{"class_name": "motor", "count": 1}]
    assert result["class_summary"]["yolo"][0]["class_name"] == "car"
    assert result["class_summary"]["unknown_yolo_name_count"] == 0
    assert [track["track_id"] for track in result["slice_tracks"]] == ["7"]
    assert result["slice_tracks"][0]["trajectory_enu_m"] == [[10, 0], [20, 0]]
    assert result["slice_tracks"][0]["trajectory_gcj02"] == [
        [117.0001, 36.7],
        [117.0002, 36.7],
    ]
    assert result["quality"]["unattributed_conflicts"] == 1


def test_slice_limit_is_explicit_and_never_hides_total_track_count():
    tracks = [
        _track(
            row_id=f"row-{track_id}", track_id=str(track_id), mission_id="M1",
            started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
            start_road_id="1", exit_road_id="2", vehicle_class="motor",
            yolo_class_id=3, yolo_class_name="car",
            trajectory=[[0, track_id], [10, track_id]], offsets=[0, 10],
        )
        for track_id in range(3)
    ]

    result = build_trajectory_analysis(
        intersection_id="INT-1",
        tracks=tracks,
        conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"),
        end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"),
        slice_end_at=_dt("2026-07-21T08:00:20Z"),
        bucket_sec=10,
        movement_key=None,
        track_limit=2,
    )

    assert result["quality"]["total_tracks"] == 3
    assert result["quality"]["returned_tracks"] == 2
    assert result["quality"]["truncated"] is True
    assert len(result["slice_tracks"]) == 2


def test_unmatched_road_context_uses_explicit_trajectory_quadrant_fallback():
    track = _track(
        row_id="row-west-east", track_id="42", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id=None, exit_road_id=None, vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[-20, 1], [0, 0], [24, -2]], offsets=[0, 10, 20],
    )

    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[track], conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:00:20Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    movement = result["movement_ranking"][0]
    assert movement["movement_key"] == "approach:west|exit:east"
    assert movement["movement_label"] == "西进口 → 东出口"
    assert movement["movement_source"] == "trajectory_quadrant_inferred"
    assert result["slice_tracks"][0]["movement_source"] == "trajectory_quadrant_inferred"


def test_ranking_prioritizes_complete_flows_over_high_volume_unknown_turns():
    unknown_road_tracks = [
        _track(
            row_id=f"row-unknown-{index}", track_id=str(index), mission_id="M1",
            started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
            start_road_id="2", exit_road_id=None, vehicle_class="motor",
            yolo_class_id=3, yolo_class_name="car",
            trajectory=[[0, 0], [10, 0]], offsets=[0, 10],
        )
        for index in range(5)
    ]
    for track in unknown_road_tracks:
        track.turn_behavior = "unknown"
    inferred_track = _track(
        row_id="row-inferred", track_id="99", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id=None, exit_road_id=None, vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[-20, 1], [20, -1]], offsets=[0, 20],
    )

    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[*unknown_road_tracks, inferred_track], conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:00:20Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    assert result["movement_ranking"][0]["movement_key"] == "approach:west|exit:east"
    assert result["movement_ranking"][1]["movement_key"] == "entry:2|turn:unknown"


def test_duplicate_completed_track_is_counted_once_within_the_same_lineage():
    original = _track(
        row_id="row-original", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [10, 0]], offsets=[0, 10],
    )
    duplicate = _track(
        row_id="row-duplicate", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:21Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [11, 0]], offsets=[0, 11],
    )
    same_track_id_other_mission = _track(
        row_id="row-other-mission", track_id="7", mission_id="M2",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:22Z",
        start_road_id="1", exit_road_id="3", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [12, 0]], offsets=[0, 12],
    )
    same_mission_other_pipeline = _track(
        row_id="row-other-pipeline", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:23Z",
        start_road_id="4", exit_road_id="5", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [13, 0]], offsets=[0, 13],
    )
    same_mission_other_pipeline.pipeline_id = "pipe-M1-retry"
    same_lineage_other_source = _track(
        row_id="row-other-source", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:24Z",
        start_road_id="6", exit_road_id="7", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [14, 0]], offsets=[0, 14],
    )
    same_lineage_other_source.source_profile_id = "SRC-2"

    result = build_trajectory_analysis(
        intersection_id="INT-1",
        tracks=[
            original,
            duplicate,
            same_track_id_other_mission,
            same_mission_other_pipeline,
            same_lineage_other_source,
        ],
        conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:00:25Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    assert result["quality"]["total_tracks"] == 4
    assert result["quality"]["duplicate_tracks_omitted"] == 1
    assert sum(item["vehicle_count"] for item in result["movement_ranking"]) == 4
    assert {(track["source_profile_id"], track["pipeline_id"]) for track in result["slice_tracks"]} == {
        ("SRC-1", "pipe-M1"),
        ("SRC-2", "pipe-M1"),
        ("SRC-1", "pipe-M1-retry"),
        ("SRC-1", "pipe-M2"),
    }


def test_time_slice_extends_to_adjacent_point_when_only_one_sample_is_inside():
    track = _track(
        row_id="row-sparse", track_id="9", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [10, 0], [20, 0]], offsets=[0, 10, 20],
    )
    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[track], conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:09Z"), slice_end_at=_dt("2026-07-21T08:00:11Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    assert result["slice_tracks"][0]["trajectory_enu_m"] == [[0, 0], [10, 0]]


def test_sampled_slice_preserves_endpoints_turn_and_conflict_nearby_point():
    trajectory = [[index, 0] for index in range(50)] + [[49, index - 49] for index in range(50, 100)]
    track = _track(
        row_id="row-turn", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:01:40Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=trajectory, offsets=list(range(100)),
    )
    conflict = _conflict(
        event_id="c-turn", mission_id="M1", occurred_at="2026-07-21T08:00:50Z",
        motor_id="7", non_motor_id="99",
    )

    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[track], conflicts=[conflict],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:01:40Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:01:40Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    sliced = result["slice_tracks"][0]
    assert len(sliced["trajectory_enu_m"]) == 60
    assert sliced["trajectory_enu_m"][0] == trajectory[0]
    assert sliced["trajectory_enu_m"][-1] == trajectory[-1]
    assert trajectory[49] in sliced["trajectory_enu_m"]
    assert trajectory[50] in sliced["trajectory_enu_m"]
    assert sliced["trajectory_sampled"] is True
    assert sliced["trajectory_original_point_count"] == 100


def test_slice_end_is_exclusive_for_conflict_evidence():
    track = _track(
        row_id="row-boundary", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [10, 0], [20, 0]], offsets=[0, 10, 20],
    )
    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[track], conflicts=[_conflict(
            event_id="c-boundary", mission_id="M1", occurred_at="2026-07-21T08:00:10Z",
            motor_id="7", non_motor_id="99",
        )],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:20Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:00:10Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    assert result["conflicts"] == []


def test_map_slice_omits_non_replayable_tracks_without_hiding_window_total():
    track = _track(
        row_id="row-no-anchor", track_id="10", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [10, 0]], offsets=[0, 10],
    )
    track.anchor_gcj02 = None
    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[track], conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:00Z"), slice_end_at=_dt("2026-07-21T08:00:20Z"),
        bucket_sec=10, movement_key=None, track_limit=20,
    )

    assert result["quality"]["total_tracks"] == 1
    assert result["quality"]["returned_tracks"] == 0
    assert result["quality"]["slice_non_replayable_omitted"] == 1
    assert result["slice_tracks"] == []


def test_class_filter_is_applied_after_lineage_deduplication():
    older_bus = _track(
        row_id="row-older", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:20Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=6, yolo_class_name="bus",
        trajectory=[[0, 0], [10, 0]], offsets=[0, 10],
    )
    latest_car = _track(
        row_id="row-latest", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:21Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [11, 0]], offsets=[0, 11],
    )

    common = {
        "intersection_id": "INT-1", "tracks": [older_bus, latest_car], "conflicts": [],
        "start_at": _dt("2026-07-21T08:00:00Z"), "end_at": _dt("2026-07-21T08:00:30Z"),
        "slice_start_at": _dt("2026-07-21T08:00:00Z"),
        "slice_end_at": _dt("2026-07-21T08:00:25Z"),
        "bucket_sec": 10, "movement_key": None, "track_limit": 20,
    }
    car_result = build_trajectory_analysis(**common, yolo_class_id=3)
    bus_result = build_trajectory_analysis(**common, yolo_class_id=6)

    assert car_result["quality"]["total_tracks"] == 1
    assert car_result["quality"]["duplicate_tracks_omitted"] == 1
    assert car_result["class_summary"]["yolo"][0]["count"] == 1
    assert bus_result["quality"]["total_tracks"] == 0


def test_default_slice_follows_latest_replayable_track_in_selected_movement():
    older_selected = _track(
        row_id="row-selected", track_id="7", mission_id="M1",
        started_at="2026-07-21T08:00:00Z", ended_at="2026-07-21T08:00:12Z",
        start_road_id="1", exit_road_id="2", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [12, 0]], offsets=[0, 12],
    )
    latest_other = _track(
        row_id="row-other", track_id="8", mission_id="M1",
        started_at="2026-07-21T08:00:20Z", ended_at="2026-07-21T08:00:29Z",
        start_road_id="1", exit_road_id="3", vehicle_class="motor",
        yolo_class_id=3, yolo_class_name="car",
        trajectory=[[0, 0], [9, 0]], offsets=[0, 9],
    )

    result = build_trajectory_analysis(
        intersection_id="INT-1", tracks=[older_selected, latest_other], conflicts=[],
        start_at=_dt("2026-07-21T08:00:00Z"), end_at=_dt("2026-07-21T08:00:30Z"),
        slice_start_at=_dt("2026-07-21T08:00:20Z"),
        slice_end_at=_dt("2026-07-21T08:00:30Z"),
        bucket_sec=10, movement_key="entry:1|exit:2", track_limit=20,
        prefer_latest_active_slice=True,
    )

    assert result["query"]["slice_start_at"] == "2026-07-21T08:00:10+00:00"
    assert [track["track_id"] for track in result["slice_tracks"]] == ["7"]
    assert [item["active_tracks"] for item in result["timeline"]] == [1, 1, 0]


@pytest.mark.asyncio
async def test_postgres_analysis_bounds_source_and_time_before_canonical_class_filtering():
    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return []

    statements = []
    store = PostgresMetricStoreAdapter(None)

    async def execute(statement):
        statements.append(statement)
        return _Rows()

    store._execute = execute
    await store.query_trajectory_analysis(
        "INT-1",
        start_at=_dt("2026-07-21T08:00:00Z"),
        end_at=_dt("2026-07-21T08:30:00Z"),
        slice_start_at=_dt("2026-07-21T08:10:00Z"),
        slice_end_at=_dt("2026-07-21T08:10:10Z"),
        source_profile_id="SRC-1",
        vehicle_class="motor",
        yolo_class_id=3,
    )

    track_sql = str(statements[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    conflict_sql = str(statements[1].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "uav_track_events.source_profile_id = 'SRC-1'" in track_sql
    assert "uav_track_events.vehicle_class = 'motor'" not in track_sql
    assert "uav_track_events.yolo_class_id = 3" not in track_sql
    assert "coalesce(uav_track_events.started_at, uav_track_events.ended_at)" in track_sql
    assert "uav_conflict_events.source_profile_id = 'SRC-1'" in conflict_sql
    assert "uav_conflict_events.occurred_at <=" in conflict_sql


@pytest.mark.asyncio
async def test_latest_30_minute_period_is_anchored_to_latest_filtered_track():
    latest_at = _dt("2026-07-21T08:30:00Z")

    class _Latest:
        def scalar_one_or_none(self):
            return latest_at

    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return []

    statements = []
    store = PostgresMetricStoreAdapter(None)

    async def execute(statement):
        statements.append(statement)
        return _Latest() if len(statements) == 1 else _Rows()

    store._execute = execute
    result = await store.query_trajectory_analysis(
        "INT-1", period="latest30m", source_profile_id="SRC-1",
    )

    track_sql = str(statements[1].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "uav_track_events.source_profile_id = 'SRC-1'" in track_sql
    assert "uav_track_events.ended_at >= '2026-07-21 08:00:00+00:00'" in track_sql
    assert result["query"]["start_at"] == "2026-07-21T08:00:00+00:00"
    assert result["query"]["end_at"] == "2026-07-21T08:30:00+00:00"
