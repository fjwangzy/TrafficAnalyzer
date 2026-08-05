"""Build narrow five-minute Replay V2 facts from one sealed Mission.

The module's interface accepts Mission-relative journeys plus second samples and
returns database-ready facts.  Absolute window alignment, behavior counting,
speed statistics, road-grain fan-out, and typical-slot semantics stay hidden
behind this seam.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Any


def _window_start(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 5) * 5, second=0, microsecond=0)


def _at_offset(started_at: datetime, offset_ms: int | float | None) -> datetime:
    return started_at + timedelta(milliseconds=float(offset_ms or 0))


def _p85(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(len(ordered) * 0.85) - 1, 0)]


def _rounded_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _empty_bucket() -> dict[str, Any]:
    return {
        "track_ids": set(),
        "speeds": [],
        "coverage": [],
        "stopped": set(),
        "queues": set(),
        "releases": set(),
        "u_turns": set(),
        "inferred_queues": set(),
    }


def _fact_row(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "vehicle_count": len(bucket["track_ids"]),
        "avg_speed_kmh": _rounded_mean(bucket["speeds"]),
        "p85_speed_kmh": _p85(bucket["speeds"]),
        "stopped_count": len(bucket["stopped"]),
        "queue_count": len(bucket["queues"]),
        "release_count": len(bucket["releases"]),
        "geometric_u_turn_count": len(bucket["u_turns"]),
        "inferred_red_signal_queue_count": len(bucket["inferred_queues"]),
        "coverage_ratio": _rounded_mean(bucket["coverage"]),
    }


def _record_episode(bucket: dict[str, Any], track_id: str, kind: object) -> None:
    if kind == "stopped":
        bucket["stopped"].add(track_id)
    elif kind == "standing_queue":
        bucket["queues"].add(track_id)
    elif kind in {"releasing", "queue_release"}:
        bucket["releases"].add((track_id, kind))
    elif kind == "inferred_red_signal_queue":
        bucket["inferred_queues"].add(track_id)


def build_mission_aggregates(
    *,
    mission: dict[str, Any],
    journeys: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    calc_version: str,
    profile_version: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic actual facts and a separate typical matrix."""

    started_at = mission["started_at"]
    if not isinstance(started_at, datetime) or started_at.tzinfo is None:
        raise ValueError("sealed Mission started_at must be timezone-aware")

    buckets: dict[datetime, dict[str, Any]] = defaultdict(_empty_bucket)
    road_buckets: dict[str, dict[tuple[datetime, str], dict[str, Any]]] = {
        "link": defaultdict(_empty_bucket),
        "lane": defaultdict(_empty_bucket),
        "turn": defaultdict(_empty_bucket),
    }

    for sample in samples:
        sampled_at = sample.get("sampled_at")
        if isinstance(sampled_at, datetime):
            coverage = sample.get("coverage_ratio")
            if coverage is not None:
                buckets[_window_start(sampled_at)]["coverage"].append(float(coverage))

    for journey in journeys:
        track_id = str(journey["track_id"])
        track_window = _window_start(
            _at_offset(started_at, journey.get("started_offset_ms"))
        )
        buckets[track_window]["track_ids"].add(track_id)
        dimensions = {
            "link": journey.get("matched_link_id"),
            "lane": journey.get("matched_lane_key"),
            "turn": journey.get("movement_key") or (
                f"turn_behavior:{journey['turn_behavior']}"
                if journey.get("turn_behavior")
                else None
            ),
        }
        for grain, value in dimensions.items():
            if value:
                road_buckets[grain][(track_window, str(value))]["track_ids"].add(track_id)
        for point in journey.get("points") or []:
            speed = (point.get("speed") or {}).get("ema_kmh")
            if speed is not None:
                point_window = _window_start(_at_offset(started_at, point.get("offset_ms")))
                buckets[point_window]["speeds"].append(float(speed))
                for grain, value in dimensions.items():
                    if value:
                        road_buckets[grain][(point_window, str(value))]["speeds"].append(
                            float(speed)
                        )
        for behavior in journey.get("episodes") or []:
            behavior_window = _window_start(
                _at_offset(started_at, behavior.get("start_offset_ms"))
            )
            bucket = buckets[behavior_window]
            kind = behavior.get("kind")
            _record_episode(bucket, track_id, kind)
            for grain, value in dimensions.items():
                if value:
                    _record_episode(
                        road_buckets[grain][(behavior_window, str(value))], track_id, kind
                    )
        for maneuver in journey.get("maneuvers") or []:
            if maneuver.get("kind") == "geometric_u_turn":
                maneuver_window = _window_start(
                    _at_offset(started_at, maneuver.get("start_offset_ms"))
                )
                buckets[maneuver_window]["u_turns"].add(track_id)
                for grain, value in dimensions.items():
                    if value:
                        road_buckets[grain][(maneuver_window, str(value))]["u_turns"].add(
                            track_id
                        )

    intersection = []
    for window, bucket in sorted(buckets.items()):
        intersection.append(
            {
                "window_start": window,
                "window_end": window + timedelta(minutes=5),
                "inter_id": mission["inter_id"],
                "source_profile_id": mission["source_profile_id"],
                "mission_id": mission["id"],
                "calc_version": calc_version,
                **_fact_row(bucket),
            }
        )

    dimension_names = {"link": "link_id", "lane": "lane_id", "turn": "movement_key"}
    road_rows: dict[str, list[dict[str, Any]]] = {"link": [], "lane": [], "turn": []}
    for grain, grain_buckets in road_buckets.items():
        for (window, dimension), bucket in sorted(grain_buckets.items()):
            road_rows[grain].append(
                {
                    "window_start": window,
                    "window_end": window + timedelta(minutes=5),
                    "inter_id": mission["inter_id"],
                    "source_profile_id": mission["source_profile_id"],
                    "mission_id": mission["id"],
                    "calc_version": calc_version,
                    dimension_names[grain]: dimension,
                    **_fact_row(bucket),
                }
            )

    typical = [
        {
            "inter_id": row["inter_id"],
            "source_profile_id": row["source_profile_id"],
            "day_of_week": row["window_start"].weekday(),
            "step_index": row["window_start"].hour * 12 + row["window_start"].minute // 5,
            "profile_version": profile_version,
            "sample_days": 1,
            "vehicle_count": float(row["vehicle_count"]),
            "avg_speed_kmh": row["avg_speed_kmh"],
            "saturation": None,
            "saturation_reason": "lane_capacity_unavailable",
            "quality_status": "estimated",
        }
        for row in intersection
    ]
    return {
        "intersection": intersection,
        "link": road_rows["link"],
        "lane": road_rows["lane"],
        "turn": road_rows["turn"],
        "typical": typical,
    }
