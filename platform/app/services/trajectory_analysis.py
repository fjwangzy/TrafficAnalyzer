"""Pure aggregation for bounded historical trajectory analysis."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from math import ceil
from typing import Any

TURN_LABELS = {
    "left_turn": "左转",
    "right_turn": "右转",
    "straight": "直行",
    "u_turn": "掉头",
    "unknown": "未知方向",
}
CARDINAL_LABELS = {
    "east": "东",
    "south": "南",
    "west": "西",
    "north": "北",
}


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _payload_data(row: Any) -> dict[str, Any]:
    payload = _value(row, "payload")
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _trajectory_cardinal(point: Any) -> str | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        easting, northing = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if max(abs(easting), abs(northing)) < 1.0:
        return None
    if abs(easting) >= abs(northing):
        return "east" if easting >= 0 else "west"
    return "north" if northing >= 0 else "south"


def _trajectory_movement(row: Any) -> tuple[str, str] | None:
    points = _value(row, "trajectory_enu_m") or _payload_data(row).get("trajectory_enu_m") or []
    if not isinstance(points, list) or len(points) < 2:
        return None
    approach = _trajectory_cardinal(points[0])
    exit_ = _trajectory_cardinal(points[-1])
    if approach and exit_ and approach != exit_:
        return approach, exit_
    return None


def _movement_key(row: Any) -> str:
    start = _value(row, "start_road_id")
    exit_ = _value(row, "exit_road_id")
    turn = _value(row, "turn_behavior")
    if start is not None and exit_ is not None:
        return f"entry:{start}|exit:{exit_}"
    if start is not None and turn:
        return f"entry:{start}|turn:{turn}"
    trajectory_movement = _trajectory_movement(row)
    if trajectory_movement:
        approach, exit_ = trajectory_movement
        return f"approach:{approach}|exit:{exit_}"
    if turn:
        return f"turn:{turn}"
    return "unmapped"


def _movement_label(row: Any) -> str:
    start = _value(row, "start_road_id")
    exit_ = _value(row, "exit_road_id")
    turn = str(_value(row, "turn_behavior") or "unknown")
    if start is not None and exit_ is not None:
        return f"道路 {start} → 道路 {exit_}"
    if start is not None:
        return f"道路 {start} → {TURN_LABELS.get(turn, turn)}"
    trajectory_movement = _trajectory_movement(row)
    if trajectory_movement:
        approach, exit_ = trajectory_movement
        return f"{CARDINAL_LABELS[approach]}进口 → {CARDINAL_LABELS[exit_]}出口"
    if turn:
        return f"{TURN_LABELS.get(turn, turn)}（进口未知）"
    return "未匹配流向"


def _movement_source(row: Any) -> str:
    if _value(row, "start_road_id") is not None:
        return "road_context"
    if _trajectory_movement(row):
        return "trajectory_quadrant_inferred"
    if _value(row, "turn_behavior"):
        return "turn_behavior_fallback"
    return "unmapped"


def _lineage_key(row: Any) -> tuple[str, str] | None:
    source_profile_id = _value(row, "source_profile_id")
    mission_id = _value(row, "mission_id")
    pipeline_id = _value(row, "pipeline_id")
    lineage = []
    if source_profile_id:
        lineage.append(("source", str(source_profile_id)))
    if mission_id:
        lineage.append(("mission", str(mission_id)))
    if pipeline_id:
        lineage.append(("pipeline", str(pipeline_id)))
    if mission_id or pipeline_id:
        return "+".join(name for name, _ in lineage), "|".join(value for _, value in lineage)
    return None


def _track_identity(row: Any) -> tuple[Any, ...]:
    lineage = _lineage_key(row)
    track_id = _value(row, "track_id")
    row_id = _value(row, "id")
    if lineage and track_id is not None:
        return "track", lineage, str(track_id)
    if row_id is not None:
        return "row", str(row_id)
    return "object", id(row)


def _deduplicate_tracks(tracks: list[Any]) -> tuple[list[Any], int]:
    """Keep one completion fact per lineage-scoped track identity."""
    unique: dict[tuple[Any, ...], Any] = {}
    for row in tracks:
        row_id = _value(row, "id")
        identity = _track_identity(row)
        previous = unique.get(identity)
        if previous is None or (
            _value(row, "ended_at"), str(row_id or "")
        ) > (
            _value(previous, "ended_at"), str(_value(previous, "id") or "")
        ):
            unique[identity] = row
    return list(unique.values()), len(tracks) - len(unique)


def _matches_track_filters(
    row: Any,
    *,
    vehicle_class: str | None,
    yolo_class_id: int | None,
    yolo_class_name: str | None,
    turn_behavior: str | None,
    quality_status: str | None,
) -> bool:
    return all((
        vehicle_class is None or _value(row, "vehicle_class") == vehicle_class,
        yolo_class_id is None or _value(row, "yolo_class_id") == yolo_class_id,
        yolo_class_name is None or _value(row, "yolo_class_name") == yolo_class_name,
        turn_behavior is None or _value(row, "turn_behavior") == turn_behavior,
        quality_status is None or _value(row, "quality_status") == quality_status,
    ))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 2)


def _turn_scores(points: list[Any]) -> list[tuple[float, int]]:
    scores: list[tuple[float, int]] = []
    for index in range(1, len(points) - 1):
        try:
            before = (float(points[index][0]) - float(points[index - 1][0]), float(points[index][1]) - float(points[index - 1][1]))
            after = (float(points[index + 1][0]) - float(points[index][0]), float(points[index + 1][1]) - float(points[index][1]))
        except (TypeError, ValueError, IndexError):
            continue
        before_norm = (before[0] ** 2 + before[1] ** 2) ** 0.5
        after_norm = (after[0] ** 2 + after[1] ** 2) ** 0.5
        if before_norm == 0 or after_norm == 0:
            continue
        cosine = max(-1.0, min(1.0, (before[0] * after[0] + before[1] * after[1]) / (before_norm * after_norm)))
        score = 1.0 - cosine
        if score > 0.01:
            scores.append((score, index))
    return sorted(scores, reverse=True)


def _downsample_indexes(
    points: list[Any], maximum: int = 60, priority_indexes: Iterable[int] = (),
) -> list[int]:
    if len(points) <= maximum:
        return list(range(len(points)))
    last = len(points) - 1
    indexes = {0, last}
    indexes.update(index for index in priority_indexes if 0 <= index <= last)
    for _, index in _turn_scores(points):
        if len(indexes) >= maximum:
            break
        indexes.add(index)
    if len(indexes) < maximum:
        evenly_spaced = [round(index * last / (maximum - 1)) for index in range(maximum)]
        for index in evenly_spaced:
            if len(indexes) >= maximum:
                break
            indexes.add(index)
    if len(indexes) < maximum:
        for index in range(1, last):
            if len(indexes) >= maximum:
                break
            indexes.add(index)
    if len(indexes) > maximum:
        priority = sorted({index for index in priority_indexes if 0 < index < last})
        protected = {0, last, *priority[:max(0, maximum - 2)]}
        ordered_optional = [index for index in sorted(indexes) if index not in protected]
        indexes = set(protected)
        indexes.update(ordered_optional[:max(0, maximum - len(indexes))])
    return sorted(indexes)


def _downsample(points: list[Any], maximum: int = 60, priority_indexes: Iterable[int] = ()) -> list[Any]:
    return [points[index] for index in _downsample_indexes(points, maximum, priority_indexes)]


def _slice_trajectory(
    row: Any,
    slice_start_at: datetime,
    slice_end_at: datetime,
    conflict_times: Iterable[datetime] = (),
) -> tuple[list[Any], bool, int, list[int]]:
    data = _payload_data(row)
    points = _value(row, "trajectory_enu_m") or data.get("trajectory_enu_m") or []
    if not isinstance(points, list):
        return [], False, 0, []
    offsets = data.get("trajectory_time_offsets_sec") or []
    started_at = _value(row, "started_at")
    if not started_at or not isinstance(offsets, list) or len(offsets) != len(points):
        selected_indexes = _downsample_indexes(points)
        return [points[index] for index in selected_indexes], len(points) > 60, len(points), selected_indexes
    point_times = []
    for offset in offsets:
        try:
            occurred_at = started_at + timedelta(seconds=float(offset))
        except (TypeError, ValueError):
            selected_indexes = _downsample_indexes(points)
            return [points[index] for index in selected_indexes], len(points) > 60, len(points), selected_indexes
        point_times.append(occurred_at)
    indexes = [
        index for index, occurred_at in enumerate(point_times)
        if slice_start_at <= occurred_at < slice_end_at
    ]
    if len(indexes) == 1 and len(points) >= 2:
        index = indexes[0]
        indexes = [index - 1, index] if index > 0 else [index, index + 1]
    elif not indexes and len(points) >= 2:
        midpoint = slice_start_at + (slice_end_at - slice_start_at) / 2
        nearest = min(range(len(point_times)), key=lambda index: abs(point_times[index] - midpoint))
        indexes = [nearest - 1, nearest] if nearest > 0 else [nearest, nearest + 1]
    sliced_points = [points[index] for index in indexes]
    priority_indexes = []
    for conflict_time in conflict_times:
        if not (slice_start_at <= conflict_time < slice_end_at) or not indexes:
            continue
        nearest_global = min(indexes, key=lambda index: abs(point_times[index] - conflict_time))
        priority_indexes.append(indexes.index(nearest_global))
    local_indexes = _downsample_indexes(sliced_points, priority_indexes=priority_indexes)
    selected_indexes = [indexes[index] for index in local_indexes]
    return (
        [points[index] for index in selected_indexes],
        len(sliced_points) > 60,
        len(sliced_points),
        selected_indexes,
    )


def _serialize_track(
    row: Any,
    slice_start_at: datetime,
    slice_end_at: datetime,
    conflict_times: Iterable[datetime] = (),
) -> dict[str, Any]:
    trajectory, sampled, original_point_count, selected_indexes = _slice_trajectory(
        row, slice_start_at, slice_end_at, conflict_times,
    )
    trajectory_gcj02 = _value(row, "trajectory_gcj02") or []
    if not isinstance(trajectory_gcj02, list):
        trajectory_gcj02 = []
    if selected_indexes and all(index < len(trajectory_gcj02) for index in selected_indexes):
        trajectory_gcj02 = [trajectory_gcj02[index] for index in selected_indexes]
    else:
        trajectory_gcj02 = _downsample(trajectory_gcj02)
    return {
        "id": _value(row, "id"),
        "track_id": str(_value(row, "track_id")),
        "mission_id": _value(row, "mission_id"),
        "pipeline_id": _value(row, "pipeline_id"),
        "source_profile_id": _value(row, "source_profile_id"),
        "inter_id": _value(row, "inter_id"),
        "road_data_version": _value(row, "road_data_version"),
        "road_context_status": _value(row, "road_context_status"),
        "quality_status": _value(row, "quality_status"),
        "time_quality": _value(row, "time_quality"),
        "vehicle_class": _value(row, "vehicle_class"),
        "yolo_class_id": _value(row, "yolo_class_id"),
        "yolo_class_name": _value(row, "yolo_class_name"),
        "yolo_model_id": _value(row, "yolo_model_id"),
        "class_mapping_version": _value(row, "class_mapping_version"),
        "turn_behavior": _value(row, "turn_behavior"),
        "movement_key": _movement_key(row),
        "movement_label": _movement_label(row),
        "movement_source": _movement_source(row),
        "started_at": _value(row, "started_at").isoformat() if _value(row, "started_at") else None,
        "ended_at": _value(row, "ended_at").isoformat() if _value(row, "ended_at") else None,
        "avg_speed_kmh": _value(row, "avg_speed_kmh"),
        "max_speed_kmh": _value(row, "max_speed_kmh"),
        "anchor_gcj02": _value(row, "anchor_gcj02"),
        "trajectory_enu_m": trajectory,
        "trajectory_gcj02": trajectory_gcj02,
        "map_version_id": _value(row, "map_version_id"),
        "matched_lane_key": _value(row, "matched_lane_key"),
        "map_match_confidence": _value(row, "map_match_confidence"),
        "trajectory_sampled": sampled,
        "trajectory_original_point_count": original_point_count,
    }


def _serialize_conflict(row: Any, attributed_movements: Iterable[str]) -> dict[str, Any]:
    return {
        "id": _value(row, "id"),
        "occurred_at": _value(row, "occurred_at").isoformat(),
        "mission_id": _value(row, "mission_id"),
        "pipeline_id": _value(row, "pipeline_id"),
        "source_profile_id": _value(row, "source_profile_id"),
        "motor_id": _value(row, "motor_id"),
        "non_motor_id": _value(row, "non_motor_id"),
        "severity": _value(row, "severity"),
        "ttc_sec": _value(row, "ttc_sec"),
        "pet_sec": _value(row, "pet_sec"),
        "conflict_scene": _value(row, "conflict_scene"),
        "prediction_type": _value(row, "prediction_type"),
        "risk_score": _value(row, "risk_score"),
        "evidence": _value(row, "evidence"),
        "attributed_movements": sorted(attributed_movements),
    }


def _is_replayable(row: Any) -> bool:
    trajectory = _value(row, "trajectory_gcj02") or []
    return (
        isinstance(trajectory, list)
        and len(trajectory) >= 2
        and bool(_value(row, "anchor_gcj02"))
    )


def build_trajectory_analysis(
    *,
    intersection_id: str,
    tracks: list[Any],
    conflicts: list[Any],
    start_at: datetime,
    end_at: datetime,
    slice_start_at: datetime,
    slice_end_at: datetime,
    bucket_sec: int,
    movement_key: str | None,
    track_limit: int,
    vehicle_class: str | None = None,
    yolo_class_id: int | None = None,
    yolo_class_name: str | None = None,
    turn_behavior: str | None = None,
    quality_status: str | None = None,
    prefer_latest_active_slice: bool = False,
) -> dict[str, Any]:
    """Build one consistent analytical view without joining on bare track ids."""
    raw_tracks = tracks
    tracks, _ = _deduplicate_tracks(raw_tracks)
    tracks = [
        row for row in tracks
        if _matches_track_filters(
            row,
            vehicle_class=vehicle_class,
            yolo_class_id=yolo_class_id,
            yolo_class_name=yolo_class_name,
            turn_behavior=turn_behavior,
            quality_status=quality_status,
        )
    ]
    movement_counts = Counter(_movement_key(row) for row in tracks)
    labels = {_movement_key(row): _movement_label(row) for row in tracks}
    movement_sources = {_movement_key(row): _movement_source(row) for row in tracks}
    speeds: dict[str, list[float]] = defaultdict(list)
    track_lookup: dict[tuple[tuple[str, str], str], Any] = {}
    for row in tracks:
        key = _movement_key(row)
        speed = _value(row, "avg_speed_kmh")
        if speed is not None:
            speeds[key].append(float(speed))
        lineage = _lineage_key(row)
        if lineage:
            track_lookup[(lineage, str(_value(row, "track_id")))] = row

    movement_conflicts: dict[str, set[str]] = defaultdict(set)
    attributed_by_conflict: dict[str, set[str]] = {}
    conflict_times_by_track: dict[tuple[tuple[str, str], str], list[datetime]] = defaultdict(list)
    unattributed_conflicts = 0
    for conflict in conflicts:
        lineage = _lineage_key(conflict)
        attributed: set[str] = set()
        if lineage:
            for track_id in {_value(conflict, "motor_id"), _value(conflict, "non_motor_id")}:
                if track_id is None:
                    continue
                track = track_lookup.get((lineage, str(track_id)))
                if track is not None:
                    attributed.add(_movement_key(track))
                    conflict_times_by_track[(lineage, str(track_id))].append(_value(conflict, "occurred_at"))
        conflict_id = str(_value(conflict, "id"))
        attributed_by_conflict[conflict_id] = attributed
        if not attributed:
            unattributed_conflicts += 1
        for key in attributed:
            movement_conflicts[key].add(conflict_id)

    ranking = []
    for key, count in movement_counts.items():
        values = speeds.get(key, [])
        ranking.append({
            "movement_key": key,
            "movement_label": labels.get(key, key),
            "movement_source": movement_sources.get(key, "unmapped"),
            "vehicle_count": count,
            "share": round(count / len(tracks), 4) if tracks else 0,
            "avg_speed_kmh": round(sum(values) / len(values), 2) if values else None,
            "p85_speed_kmh": _percentile(values, 0.85),
            "conflict_count": len(movement_conflicts.get(key, set())),
            "selected": key == movement_key,
        })
    def ranking_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        key = item["movement_key"]
        source = item["movement_source"]
        if source == "road_context" and "|exit:" in key:
            priority = 0
        elif source == "trajectory_quadrant_inferred":
            priority = 1
        elif source == "road_context" and not key.endswith("|turn:unknown"):
            priority = 2
        elif source == "turn_behavior_fallback" and key != "turn:unknown":
            priority = 3
        else:
            priority = 4
        return priority, -item["vehicle_count"], -item["conflict_count"], item["movement_key"]

    ranking.sort(key=ranking_key)

    focused = [row for row in tracks if movement_key is None or _movement_key(row) == movement_key]
    focused_identities = {_track_identity(row) for row in focused}
    duplicate_tracks_omitted = (
        sum(_track_identity(row) in focused_identities for row in raw_tracks) - len(focused)
    )
    replayable = sum(_is_replayable(row) for row in focused)

    if prefer_latest_active_slice:
        replayable_focused = [row for row in focused if _is_replayable(row)]
        if replayable_focused:
            slice_anchor = max(_value(row, "ended_at") for row in replayable_focused)
            bucket_count = max(1, ceil((end_at - start_at).total_seconds() / bucket_sec))
            bucket_index = min(
                bucket_count - 1,
                max(0, int((slice_anchor - start_at).total_seconds() // bucket_sec)),
            )
            slice_start_at = start_at + timedelta(seconds=bucket_index * bucket_sec)
            slice_end_at = min(end_at, slice_start_at + timedelta(seconds=bucket_sec))

    timeline = []
    cursor = start_at
    while cursor < end_at:
        bucket_end = min(cursor + timedelta(seconds=bucket_sec), end_at)
        active = sum(
            1 for row in focused
            if (_value(row, "started_at") or _value(row, "ended_at")) < bucket_end
            and _value(row, "ended_at") >= cursor
        )
        conflict_count = sum(
            1 for row in conflicts if cursor <= _value(row, "occurred_at") < bucket_end
        )
        timeline.append({
            "start_at": cursor.isoformat(),
            "end_at": bucket_end.isoformat(),
            "active_tracks": active,
            "conflict_count": conflict_count,
        })
        cursor = bucket_end

    business_counts = Counter(str(_value(row, "vehicle_class") or "unknown") for row in focused)
    yolo_counts = Counter(
        (
            _value(row, "yolo_class_id"),
            _value(row, "yolo_class_name"),
            _value(row, "yolo_model_id"),
        )
        for row in focused
    )
    class_summary = {
        "business": [
            {"class_name": name, "count": count}
            for name, count in sorted(business_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "yolo": [
            {"class_id": class_id, "class_name": name, "model_id": model_id, "count": count}
            for (class_id, name, model_id), count in sorted(
                yolo_counts.items(), key=lambda item: (-item[1], str(item[0][0]), str(item[0][1]))
            )
        ],
        "unknown_yolo_name_count": sum(
            count for (_, name, _), count in yolo_counts.items() if not name
        ),
    }

    slice_candidates = [
        row for row in focused
        if _is_replayable(row)
        if (_value(row, "started_at") or _value(row, "ended_at")) <= slice_end_at
        and _value(row, "ended_at") >= slice_start_at
    ]
    overlapping_count = sum(
        1 for row in focused
        if (_value(row, "started_at") or _value(row, "ended_at")) <= slice_end_at
        and _value(row, "ended_at") >= slice_start_at
    )
    slice_candidates.sort(key=lambda row: (_value(row, "ended_at"), str(_value(row, "track_id"))), reverse=True)
    slice_tracks = [
        _serialize_track(
            row,
            slice_start_at,
            slice_end_at,
            conflict_times_by_track.get((_lineage_key(row), str(_value(row, "track_id"))), []),
        )
        for row in slice_candidates[:track_limit]
    ]
    slice_conflicts = []
    for row in conflicts:
        occurred_at = _value(row, "occurred_at")
        attributed = attributed_by_conflict[str(_value(row, "id"))]
        if not (slice_start_at <= occurred_at < slice_end_at):
            continue
        if movement_key is not None and movement_key not in attributed:
            continue
        slice_conflicts.append(_serialize_conflict(row, attributed))

    return {
        "query": {
            "intersection_id": intersection_id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "slice_start_at": slice_start_at.isoformat(),
            "slice_end_at": slice_end_at.isoformat(),
            "bucket_sec": bucket_sec,
            "movement_key": movement_key,
        },
        "quality": {
            "total_tracks": len(focused),
            "duplicate_tracks_omitted": duplicate_tracks_omitted,
            "replayable_tracks": replayable,
            "returned_tracks": len(slice_tracks),
            "truncated": len(slice_candidates) > track_limit,
            "slice_non_replayable_omitted": overlapping_count - len(slice_candidates),
            "unattributed_conflicts": unattributed_conflicts,
            "spatial_coverage_ratio": round(replayable / len(focused), 4) if focused else 0,
            "status": "empty" if not focused else ("complete" if replayable == len(focused) else "degraded"),
        },
        "timeline": timeline,
        "movement_ranking": ranking,
        "class_summary": class_summary,
        "slice_tracks": slice_tracks,
        "conflicts": slice_conflicts,
    }
