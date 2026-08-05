"""ReplayRepository seam for sealed Mission replay facts."""

from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Protocol

from sqlalchemy import and_, exists, func, or_, select, tuple_
from sqlalchemy.orm import aliased

from app.models.replay_v2 import (
    ReplayV2Episode,
    ReplayV2ConflictEvent,
    ReplayV2Maneuver,
    ReplayV2Mission,
    ReplayV2TrackEvent,
    ReplayV2TrackPoint,
)


_CARDINAL_LABELS = {"east": "东", "south": "南", "west": "西", "north": "北"}
_TURN_LABELS = {
    "left_turn": "左转",
    "right_turn": "右转",
    "straight": "直行",
    "u_turn": "掉头",
    "unknown": "未知方向",
}
_INFERRED_EXIT_BY_TURN = {
    "straight": {"east": "west", "west": "east", "north": "south", "south": "north"},
    "left_turn": {"east": "south", "west": "north", "north": "east", "south": "west"},
    "right_turn": {"east": "north", "west": "south", "north": "west", "south": "east"},
    "u_turn": {"east": "east", "west": "west", "north": "north", "south": "south"},
}


class ReplayRepository(Protocol):
    async def list_missions(self, intersection_id: str, *, include_incomplete: bool) -> list[dict]: ...

    async def replay(
        self,
        intersection_id: str,
        *,
        mission_id: str,
        cursor_ms: int,
        window_ms: int,
        max_points: int,
        page_after: str | None,
        track_id: str | None,
        behavior: str | None,
        vehicle_class: str | None,
        yolo_class_id: int | None,
        turn_behavior: str | None,
        movement_key: str | None,
    ) -> dict: ...


def _mission_summary(mission: dict) -> dict:
    journeys = mission.get("journeys") or []
    behavior_count = sum(
        len(journey.get("episodes") or []) + len(journey.get("maneuvers") or [])
        for journey in journeys
    )
    return {
        "mission_id": mission["id"],
        "source_profile_id": mission.get("source_profile_id"),
        "pipeline_id": mission.get("pipeline_id"),
        "run_id": mission.get("run_id"),
        "status": mission.get("status"),
        "started_at": mission.get("started_at"),
        "duration_ms": int(mission.get("duration_ms") or 0),
        "coordinate_coverage_ratio": float(mission.get("coordinate_coverage_ratio") or 0.0),
        "journey_count": int(mission.get("journey_count", len(journeys))),
        "behavior_count": int(mission.get("behavior_count", behavior_count)),
        "algorithm_versions": deepcopy(mission.get("algorithm_versions") or {}),
        "accuracy": deepcopy(mission.get("accuracy") or {}),
    }


def _journey_matches(
    journey: dict,
    *,
    track_id: str | None,
    behavior: str | None,
    vehicle_class: str | None,
    yolo_class_id: int | None,
    turn_behavior: str | None,
    movement_key: str | None,
) -> bool:
    return (
        (track_id is None or str(journey.get("track_id")) == str(track_id))
        and _behavior_matches(journey, behavior)
        and (vehicle_class is None or journey.get("vehicle_class") == vehicle_class)
        and (yolo_class_id is None or journey.get("yolo_class_id") == yolo_class_id)
        and (turn_behavior is None or journey.get("turn_behavior") == turn_behavior)
        and (movement_key is None or journey.get("movement_key") == movement_key)
    )


def _behavior_matches(journey: dict, behavior: str | None) -> bool:
    if behavior is None:
        return True
    return any(
        item.get("kind") == behavior
        for item in [*(journey.get("episodes") or []), *(journey.get("maneuvers") or [])]
    )


def _trajectory_cardinal(point: object) -> str | None:
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


def _physical_movement(journey: dict) -> tuple[str, str] | None:
    world_points = [
        point.get("enu_m")
        for point in journey.get("points") or []
        if point.get("enu_m") is not None
    ]
    if not world_points:
        return None
    approach = _trajectory_cardinal(world_points[0])
    observed_exit = _trajectory_cardinal(world_points[-1])
    if approach is None:
        return None
    if observed_exit is not None and observed_exit != approach:
        return approach, observed_exit
    turn = str(journey.get("turn_behavior") or "unknown")
    inferred_exit = _INFERRED_EXIT_BY_TURN.get(turn, {}).get(approach)
    return (approach, inferred_exit) if inferred_exit is not None else None


def _movement_label_from_key(key: str) -> str:
    parts = dict(
        part.split(":", 1)
        for part in key.split("|")
        if ":" in part
    )
    approach = parts.get("approach")
    exit_ = parts.get("exit")
    if approach in _CARDINAL_LABELS and exit_ in _CARDINAL_LABELS:
        return f"{_CARDINAL_LABELS[approach]}进口 → {_CARDINAL_LABELS[exit_]}出口"
    return key


def _journey_movement(journey: dict) -> tuple[str, str, str]:
    source_key = journey.get("movement_key")
    if source_key:
        key = str(source_key)
        return key, _movement_label_from_key(key), "road_context"
    physical = _physical_movement(journey)
    if physical is not None:
        approach, exit_ = physical
        key = f"approach:{approach}|exit:{exit_}"
        return key, _movement_label_from_key(key), "trajectory_quadrant_inferred"
    turn = str(journey.get("turn_behavior") or "unknown")
    return f"turn:{turn}", f"{_TURN_LABELS.get(turn, turn)}（进口未知）", "turn_behavior_fallback"


def _with_movement(journey: dict) -> dict:
    if journey.get("movement_label") and journey.get("movement_source"):
        return journey
    key, label, source = _journey_movement(journey)
    return {
        **journey,
        "movement_key": key,
        "movement_label": label,
        "movement_source": source,
    }


def _mission_analysis(mission: dict) -> dict:
    """Build the existing right-hand analysis semantics from one Mission only."""

    journeys = [_with_movement(journey) for journey in mission.get("journeys") or []]
    business = Counter(str(item.get("vehicle_class") or "unknown") for item in journeys)
    yolo = Counter(
        (item.get("yolo_class_id"), str(item.get("yolo_class_name") or "unknown"))
        for item in journeys
    )
    movement_groups: dict[str, list[dict]] = defaultdict(list)
    for journey in journeys:
        key = str(journey["movement_key"])
        movement_groups[key].append(journey)
    conflicts = deepcopy(mission.get("conflicts") or [])
    ranking = []
    for key, rows in movement_groups.items():
        speeds = [
            float(point["speed"]["ema_kmh"])
            for row in rows
            for point in (row.get("points") or [])[-1:]
            if point.get("speed", {}).get("ema_kmh") is not None
        ]
        ranking.append(
            {
                "movement_key": key,
                "movement_label": rows[0]["movement_label"],
                "movement_source": rows[0]["movement_source"],
                "vehicle_count": len(rows),
                "share": round(len(rows) / len(journeys), 4) if journeys else 0,
                "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
                "p85_speed_kmh": None,
                "conflict_count": sum(1 for item in conflicts if item.get("movement_key") == key),
            }
        )
    ranking.sort(
        key=lambda item: (
            0 if item["movement_source"] == "road_context" else
            1 if item["movement_source"] == "trajectory_quadrant_inferred" else 2,
            -item["vehicle_count"],
            item["movement_key"],
        )
    )
    return {
        "quality": {
            "status": "complete" if journeys else "empty",
            "total_tracks": len(journeys),
            "replayable_tracks": len(journeys),
            "spatial_coverage_ratio": float(mission.get("coordinate_coverage_ratio") or 0.0),
            "unattributed_conflicts": sum(1 for item in conflicts if not item.get("movement_key")),
            "truncated": False,
        },
        "movement_ranking": ranking,
        "class_summary": {
            "business": [
                {"class_name": name, "count": count}
                for name, count in sorted(business.items())
            ],
            "yolo": [
                {"class_id": class_id, "class_name": name, "count": count, "model_id": None}
                for (class_id, name), count in sorted(yolo.items(), key=lambda item: (str(item[0][0]), item[0][1]))
            ],
            "unknown_yolo_name_count": sum(
                count for (class_id, name), count in yolo.items() if name == "unknown"
            ),
        },
        "conflicts": conflicts,
    }


def _window_points(points: list[dict], start_ms: int, end_ms: int) -> list[dict]:
    anchor = None
    selected = []
    for index, source_point in enumerate(points):
        point = {**source_point, "point_seq": int(source_point.get("point_seq", index))}
        offset = int(point["offset_ms"])
        if offset <= start_ms:
            anchor = point
        if start_ms <= offset <= end_ms:
            selected.append(point)
    # An anchor exists only to connect into a window that the journey actually
    # overlaps.  Returning an anchor after the last point would pin every
    # departed vehicle at its exit location until Mission EOF.
    if selected and anchor is not None and selected[0]["offset_ms"] != anchor["offset_ms"]:
        selected.insert(0, anchor)
    return selected


def _encode_page_after(track_id: str, point_seq: int) -> str:
    payload = json.dumps([track_id, point_seq], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_page_after(value: str | None) -> tuple[str, int] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError
        return str(payload[0]), int(payload[1])
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("page_after is not a valid replay pagination anchor") from exc


def _point_record(point: ReplayV2TrackPoint) -> dict:
    return {
        "offset_ms": point.offset_ms,
        "point_seq": point.point_seq,
        "source_timestamp_sec": point.source_timestamp_sec,
        "frame_num": point.frame_num,
        "pixel": [point.pixel_x, point.pixel_y],
        "enu_m": (
            [point.enu_x_m, point.enu_y_m]
            if point.enu_x_m is not None and point.enu_y_m is not None
            else None
        ),
        "gcj02": (
            [point.longitude_gcj02, point.latitude_gcj02]
            if point.longitude_gcj02 is not None and point.latitude_gcj02 is not None
            else None
        ),
        "speed": {
            "instant_kmh": point.instant_speed_kmh,
            "ema_kmh": point.ema_speed_kmh,
            "enu_vector_mps": (
                [point.velocity_east_mps, point.velocity_north_mps]
                if point.velocity_east_mps is not None
                and point.velocity_north_mps is not None
                else None
            ),
            "quality": point.speed_quality,
        },
        "quality": point.point_quality,
        "sampling_boundary": point.sampling_boundary,
    }


def _behavior_record(row) -> dict:
    return {
        "kind": row.kind,
        "start_offset_ms": row.start_offset_ms,
        "end_offset_ms": row.end_offset_ms,
        "confidence": row.confidence,
        "quality_status": row.quality_status,
        "reason": row.reason,
        "evidence": row.evidence,
        "algorithm_version": row.algorithm_version,
    }


class InMemoryReplayRepository:
    """Executable contract adapter used by API and playback-clock tests."""

    def __init__(self, missions: list[dict] | None = None) -> None:
        self._missions = {mission["id"]: deepcopy(mission) for mission in missions or []}

    async def list_missions(self, intersection_id: str, *, include_incomplete: bool) -> list[dict]:
        rows = [
            _mission_summary(mission)
            for mission in self._missions.values()
            if mission.get("inter_id") == intersection_id
            and (include_incomplete or mission.get("status") == "sealed")
        ]
        return sorted(rows, key=lambda row: (row.get("started_at") or "", row["mission_id"]), reverse=True)

    async def replay(
        self,
        intersection_id: str,
        *,
        mission_id: str,
        cursor_ms: int,
        window_ms: int,
        max_points: int,
        page_after: str | None,
        track_id: str | None,
        behavior: str | None,
        vehicle_class: str | None = None,
        yolo_class_id: int | None = None,
        turn_behavior: str | None = None,
        movement_key: str | None = None,
    ) -> dict:
        mission = self._missions.get(mission_id)
        if mission is None or mission.get("inter_id") != intersection_id:
            raise LookupError("sealed replay Mission not found")
        if mission.get("status") != "sealed":
            raise LookupError("Mission is not sealed")
        duration_ms = int(mission.get("duration_ms") or 0)
        cursor_ms = min(max(cursor_ms, 0), duration_ms)
        start_ms = max(0, cursor_ms - max(window_ms, 0))
        end_ms = cursor_ms
        anchor_after = _decode_page_after(page_after)
        matching_journeys = [
            enriched
            for journey in mission.get("journeys") or []
            for enriched in [_with_movement(journey)]
            if _journey_matches(
                enriched,
                track_id=track_id,
                behavior=behavior,
                vehicle_class=vehicle_class,
                yolo_class_id=yolo_class_id,
                turn_behavior=turn_behavior,
                movement_key=movement_key,
            )
        ]
        flattened: list[tuple[str, int, dict, dict]] = []
        for journey in sorted(matching_journeys, key=lambda item: str(item.get("track_id"))):
            journey_track_id = str(journey.get("track_id"))
            points = _window_points(journey.get("points") or [], start_ms, end_ms)
            for point in points:
                key = (journey_track_id, int(point["point_seq"]))
                if anchor_after is None or key > anchor_after:
                    flattened.append((key[0], key[1], journey, point))
        page = flattened[:max_points]
        truncated = len(flattened) > len(page)
        tracks_by_id: dict[str, dict] = {}
        for journey_track_id, _point_seq, journey, point in page:
            row = tracks_by_id.setdefault(
                journey_track_id,
                {**deepcopy(journey), "points": []},
            )
            row["points"].append(deepcopy(point))
        tracks = list(tracks_by_id.values())
        next_page_after = (
            _encode_page_after(page[-1][0], page[-1][1]) if truncated and page else None
        )
        analysis = _mission_analysis({**mission, "journeys": matching_journeys})
        analysis["quality"].update(
            {
                "truncated": truncated,
                "returned_tracks": len(tracks),
            }
        )
        return {
            "schema_version": "uav.trajectory-replay/v1",
            "mission": _mission_summary(mission),
            "cursor": {
                "offset_ms": cursor_ms,
                "window_start_ms": start_ms,
                "window_end_ms": cursor_ms,
                "duration_ms": duration_ms,
            },
            "coordinate_mode": (
                "gcj02" if float(mission.get("coordinate_coverage_ratio") or 0.0) > 0 else "pixel"
            ),
            "tracks": tracks,
            "analysis": analysis,
            "conflicts": deepcopy(mission.get("conflicts") or []),
            "truncated": truncated,
            "next_cursor_ms": cursor_ms if truncated else None,
            "pagination": {
                "truncated": truncated,
                "next_page_after": next_page_after,
            },
        }


class PostgresReplayRepository:
    """PostgreSQL adapter for the ReplayRepository seam."""

    def __init__(self, session_maker) -> None:
        self._session_maker = session_maker

    async def list_missions(self, intersection_id: str, *, include_incomplete: bool) -> list[dict]:
        statement = select(ReplayV2Mission).where(ReplayV2Mission.inter_id == intersection_id)
        if not include_incomplete:
            statement = statement.where(ReplayV2Mission.status == "sealed")
        statement = statement.order_by(ReplayV2Mission.started_at.desc(), ReplayV2Mission.id.desc())
        async with self._session_maker() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [
            _mission_summary(
                {
                    "id": row.id,
                    "source_profile_id": row.source_profile_id,
                    "pipeline_id": row.pipeline_id,
                    "run_id": row.run_id,
                    "status": row.status,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "duration_ms": row.duration_ms,
                    "coordinate_coverage_ratio": row.coordinate_coverage_ratio,
                    "journey_count": row.journey_count,
                    "behavior_count": row.behavior_count,
                    "algorithm_versions": row.algorithm_versions,
                    "accuracy": row.accuracy,
                }
            )
            for row in rows
        ]

    async def replay(self, intersection_id: str, **kwargs) -> dict:
        mission_id = kwargs["mission_id"]
        anchor_after = _decode_page_after(kwargs.get("page_after"))
        async with self._session_maker() as session:
            mission = await session.scalar(
                select(ReplayV2Mission).where(
                    ReplayV2Mission.id == mission_id,
                    ReplayV2Mission.inter_id == intersection_id,
                )
            )
            if mission is None:
                raise LookupError("sealed replay Mission not found")
            if mission.status != "sealed":
                raise LookupError("Mission is not sealed")

            event_rows = (
                await session.execute(
                    select(ReplayV2TrackEvent)
                    .where(ReplayV2TrackEvent.mission_id == mission_id)
                    .order_by(ReplayV2TrackEvent.track_id)
                )
            ).scalars().all()
            episode_rows = (
                await session.execute(
                    select(ReplayV2Episode).where(ReplayV2Episode.mission_id == mission_id)
                )
            ).scalars().all()
            maneuver_rows = (
                await session.execute(
                    select(ReplayV2Maneuver).where(ReplayV2Maneuver.mission_id == mission_id)
                )
            ).scalars().all()
            conflict_rows = (
                await session.execute(
                    select(ReplayV2ConflictEvent)
                    .where(ReplayV2ConflictEvent.mission_id == mission_id)
                    .order_by(ReplayV2ConflictEvent.offset_ms, ReplayV2ConflictEvent.id)
                )
            ).scalars().all()

            point_bounds = (
                select(
                    ReplayV2TrackPoint.track_id.label("track_id"),
                    func.min(ReplayV2TrackPoint.point_seq).label("first_seq"),
                    func.max(ReplayV2TrackPoint.point_seq).label("last_seq"),
                    func.min(ReplayV2TrackPoint.point_seq)
                    .filter(
                        ReplayV2TrackPoint.enu_x_m.is_not(None),
                        ReplayV2TrackPoint.enu_y_m.is_not(None),
                    )
                    .label("first_world_seq"),
                    func.max(ReplayV2TrackPoint.point_seq)
                    .filter(
                        ReplayV2TrackPoint.enu_x_m.is_not(None),
                        ReplayV2TrackPoint.enu_y_m.is_not(None),
                    )
                    .label("last_world_seq"),
                )
                .where(ReplayV2TrackPoint.mission_id == mission_id)
                .group_by(ReplayV2TrackPoint.track_id)
                .subquery()
            )
            boundary_rows = (
                await session.execute(
                    select(ReplayV2TrackPoint)
                    .join(
                        point_bounds,
                        and_(
                            ReplayV2TrackPoint.track_id == point_bounds.c.track_id,
                            or_(
                                ReplayV2TrackPoint.point_seq == point_bounds.c.first_seq,
                                ReplayV2TrackPoint.point_seq == point_bounds.c.last_seq,
                                ReplayV2TrackPoint.point_seq == point_bounds.c.first_world_seq,
                                ReplayV2TrackPoint.point_seq == point_bounds.c.last_world_seq,
                            ),
                        ),
                    )
                    .where(ReplayV2TrackPoint.mission_id == mission_id)
                    .order_by(ReplayV2TrackPoint.track_id, ReplayV2TrackPoint.point_seq)
                )
            ).scalars().all()

        episodes_by_track: dict[str, list[dict]] = defaultdict(list)
        maneuvers_by_track: dict[str, list[dict]] = defaultdict(list)
        boundary_points_by_track: dict[str, list[dict]] = defaultdict(list)
        for row in episode_rows:
            episodes_by_track[row.track_id].append(_behavior_record(row))
        for row in maneuver_rows:
            maneuvers_by_track[row.track_id].append(_behavior_record(row))
        for row in boundary_rows:
            boundary_points_by_track[row.track_id].append(_point_record(row))

        journeys = [
            _with_movement(
                {
                    "track_id": event.track_id,
                    "source_runtime_track_ids": event.source_runtime_track_ids,
                    "source_point_count": event.source_point_count,
                    "retained_point_count": event.retained_point_count,
                    "sampling": event.sampling,
                    "vehicle_class": event.vehicle_class,
                    "yolo_class_id": event.yolo_class_id,
                    "yolo_class_name": event.yolo_class_name,
                    "turn_behavior": event.turn_behavior,
                    "movement_key": event.movement_key,
                    "matched_lane_key": event.matched_lane_key,
                    "matched_link_id": event.matched_link_id,
                    "termination_reason": event.termination_reason,
                    "episodes": episodes_by_track[event.track_id],
                    "maneuvers": maneuvers_by_track[event.track_id],
                    "points": boundary_points_by_track[event.track_id],
                }
            )
            for event in event_rows
        ]
        matching_journeys = [
            journey
            for journey in journeys
            if _journey_matches(
                journey,
                track_id=kwargs.get("track_id"),
                behavior=kwargs.get("behavior"),
                vehicle_class=kwargs.get("vehicle_class"),
                yolo_class_id=kwargs.get("yolo_class_id"),
                turn_behavior=kwargs.get("turn_behavior"),
                movement_key=kwargs.get("movement_key"),
            )
        ]
        matching_by_track = {
            str(journey["track_id"]): journey for journey in matching_journeys
        }

        duration_ms = int(mission.duration_ms or 0)
        cursor_ms = min(max(int(kwargs["cursor_ms"]), 0), duration_ms)
        start_ms = max(0, cursor_ms - max(int(kwargs["window_ms"]), 0))
        max_points = int(kwargs["max_points"])
        page_rows = []
        if matching_by_track:
            window_point = aliased(ReplayV2TrackPoint)
            anchor_point = aliased(ReplayV2TrackPoint)
            window_exists = exists(
                select(1).where(
                    window_point.mission_id == mission_id,
                    window_point.track_id == ReplayV2TrackPoint.track_id,
                    window_point.offset_ms >= start_ms,
                    window_point.offset_ms <= cursor_ms,
                )
            ).correlate(ReplayV2TrackPoint)
            anchor_seq = (
                select(func.max(anchor_point.point_seq))
                .where(
                    anchor_point.mission_id == mission_id,
                    anchor_point.track_id == ReplayV2TrackPoint.track_id,
                    anchor_point.offset_ms <= start_ms,
                )
                .correlate(ReplayV2TrackPoint)
                .scalar_subquery()
            )
            point_statement = select(ReplayV2TrackPoint).where(
                ReplayV2TrackPoint.mission_id == mission_id,
                ReplayV2TrackPoint.track_id.in_(matching_by_track),
                or_(
                    and_(
                        ReplayV2TrackPoint.offset_ms >= start_ms,
                        ReplayV2TrackPoint.offset_ms <= cursor_ms,
                    ),
                    and_(
                        ReplayV2TrackPoint.point_seq == anchor_seq,
                        window_exists,
                    ),
                ),
            )
            if anchor_after is not None:
                point_statement = point_statement.where(
                    tuple_(ReplayV2TrackPoint.track_id, ReplayV2TrackPoint.point_seq)
                    > tuple_(anchor_after[0], anchor_after[1])
                )
            point_statement = point_statement.order_by(
                ReplayV2TrackPoint.track_id,
                ReplayV2TrackPoint.point_seq,
            ).limit(max_points + 1)
            async with self._session_maker() as session:
                page_rows = (await session.execute(point_statement)).scalars().all()

        truncated = len(page_rows) > max_points
        page_rows = page_rows[:max_points]
        tracks_by_id: dict[str, dict] = {}
        for point in page_rows:
            journey = matching_by_track[str(point.track_id)]
            row = tracks_by_id.setdefault(
                str(point.track_id),
                {**deepcopy(journey), "points": []},
            )
            row["points"].append(_point_record(point))
        tracks = list(tracks_by_id.values())
        next_page_after = (
            _encode_page_after(str(page_rows[-1].track_id), int(page_rows[-1].point_seq))
            if truncated and page_rows
            else None
        )
        conflicts = [
            {
                "id": row.id,
                "offset_ms": row.offset_ms,
                "severity": row.severity,
                "prediction_type": row.prediction_type,
                "ttc_sec": row.ttc_sec,
                "pet_sec": row.pet_sec,
                "evidence": row.evidence,
            }
            for row in conflict_rows
        ]
        mission_document = {
            "id": mission.id,
            "inter_id": mission.inter_id,
            "source_profile_id": mission.source_profile_id,
            "pipeline_id": mission.pipeline_id,
            "run_id": mission.run_id,
            "status": mission.status,
            "started_at": mission.started_at.isoformat() if mission.started_at else None,
            "duration_ms": duration_ms,
            "coordinate_coverage_ratio": mission.coordinate_coverage_ratio,
            "journey_count": mission.journey_count,
            "behavior_count": mission.behavior_count,
            "algorithm_versions": mission.algorithm_versions,
            "accuracy": mission.accuracy,
            "journeys": matching_journeys,
            "conflicts": conflicts,
        }
        analysis = _mission_analysis(mission_document)
        analysis["quality"].update(
            {"truncated": truncated, "returned_tracks": len(tracks)}
        )
        return {
            "schema_version": "uav.trajectory-replay/v1",
            "mission": _mission_summary(mission_document),
            "cursor": {
                "offset_ms": cursor_ms,
                "window_start_ms": start_ms,
                "window_end_ms": cursor_ms,
                "duration_ms": duration_ms,
            },
            "coordinate_mode": (
                "gcj02" if float(mission.coordinate_coverage_ratio or 0.0) > 0 else "pixel"
            ),
            "tracks": tracks,
            "analysis": analysis,
            "conflicts": conflicts,
            "truncated": truncated,
            "next_cursor_ms": cursor_ms if truncated else None,
            "pagination": {
                "truncated": truncated,
                "next_page_after": next_page_after,
            },
        }
