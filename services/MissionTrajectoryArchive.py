"""Durable mission archive for event-faithful historical trajectory replay.

The interface deliberately has three operations: record a terminated runtime
segment, seal a mission at natural EOF, and load the resulting manifest.  The
online tracker remains unaware of replay sampling and historical identities.
"""

from __future__ import annotations

import hashlib
import base64
import json
import math
import os
from pathlib import Path
from typing import Any, Callable


ARCHIVE_SCHEMA_VERSION = "uav.trajectory-archive/v2"
SAMPLING_VERSION = "event-faithful/v1"
SPEED_VERSION = "enu-linear-regression-15-ema5/v1"
BEHAVIOR_VERSION = "trajectory-behavior/v1"


def _json_default(value: Any):
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    temporary.replace(path)


def _segment_id(segment: dict) -> str:
    raw = "|".join(
        str(segment.get(key) or "")
        for key in ("track_id", "timestamp_first", "timestamp_last", "termination_reason")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _validate_segment(segment: dict) -> int:
    arrays = {
        "trajectory_px": segment.get("trajectory_px") or [],
        "trajectory_timestamps_sec": segment.get("trajectory_timestamps_sec") or [],
        "trajectory_frame_nums": segment.get("trajectory_frame_nums") or [],
        "trajectory_enu_m": segment.get("trajectory_enu_m") or [],
        "trajectory_gcj02": segment.get("trajectory_gcj02") or [],
        "point_quality_lineage": segment.get("point_quality_lineage") or [],
    }
    count = len(arrays["trajectory_px"])
    if count == 0:
        raise ValueError("segment contains no trajectory points")
    mismatched = [name for name, values in arrays.items() if len(values) != count]
    if mismatched:
        raise ValueError(f"trajectory point arrays are not aligned: {', '.join(mismatched)}")
    timestamps = [float(value) for value in arrays["trajectory_timestamps_sec"]]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("trajectory timestamps must be strictly increasing")
    return count


def _linear_velocity(points: list[dict], end: int) -> tuple[float, float] | None:
    window = [point for point in points[max(0, end - 14):end + 1] if point["enu_m"] is not None]
    if len(window) < 2:
        return None
    times = [point["source_timestamp_sec"] for point in window]
    mean_t = sum(times) / len(times)
    denominator = sum((value - mean_t) ** 2 for value in times)
    if denominator <= 1e-9:
        return None
    mean_x = sum(point["enu_m"][0] for point in window) / len(window)
    mean_y = sum(point["enu_m"][1] for point in window) / len(window)
    vx = sum((point["source_timestamp_sec"] - mean_t) * (point["enu_m"][0] - mean_x) for point in window) / denominator
    vy = sum((point["source_timestamp_sec"] - mean_t) * (point["enu_m"][1] - mean_y) for point in window) / denominator
    return vx, vy


def _freeze_speeds(points: list[dict]) -> None:
    ema: float | None = None
    alpha = 2.0 / 6.0
    for index, point in enumerate(points):
        velocity = _linear_velocity(points, index)
        if velocity is None:
            point["speed"] = {
                "instant_kmh": None,
                "ema_kmh": None,
                "enu_vector_mps": None,
                "quality": "world_coordinates_unavailable",
                "algorithm_version": SPEED_VERSION,
            }
            continue
        instant = math.hypot(*velocity) * 3.6
        ema = instant if ema is None else alpha * instant + (1.0 - alpha) * ema
        point["speed"] = {
            "instant_kmh": round(instant, 3),
            "ema_kmh": round(ema, 3),
            "enu_vector_mps": [round(velocity[0], 4), round(velocity[1], 4)],
            "quality": "reconstructed_from_full_sequence",
            "algorithm_version": SPEED_VERSION,
        }


def _heading(a: list[float], b: list[float]) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _heading_delta(a: float, b: float) -> float:
    return abs((b - a + 180.0) % 360.0 - 180.0)


def _has_tracking_quality_gap(quality: object) -> bool:
    """Recognize only image/trajectory quality gaps, never road/geo degradation."""

    if not isinstance(quality, dict):
        return False
    gap_values = {"gap", "lost", "invalid", "unavailable", "missing"}
    for key in ("tracking_quality", "trajectory_quality", "association_quality", "data_quality"):
        value = quality.get(key)
        if value is not None and str(value).strip().lower() in gap_values:
            return True
    return False


def _annotate_sampling_boundaries(points: list[dict]) -> None:
    previous_gap = False
    previous_world_available: bool | None = None
    for point in points:
        current_gap = _has_tracking_quality_gap(point.get("quality"))
        world_available = point.get("enu_m") is not None
        if current_gap and not previous_gap:
            point["sampling_boundary"].append("quality_gap_start")
        elif previous_gap and not current_gap:
            point["sampling_boundary"].append("quality_gap_end")
        if previous_world_available is not None and world_available != previous_world_available:
            point["sampling_boundary"].append("world_coordinate_boundary")
        previous_gap = current_gap
        previous_world_available = world_available


def _retain_indices(points: list[dict]) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))
    retained = [0]
    last_heading: float | None = None
    for index in range(1, len(points) - 1):
        previous = points[retained[-1]]
        current = points[index]
        elapsed = current["source_timestamp_sec"] - previous["source_timestamp_sec"]
        coordinate_boundary = (previous["enu_m"] is None) != (current["enu_m"] is None)
        quality_boundary = previous["quality"] != current["quality"]
        displacement = 0.0
        heading_change = 0.0
        if previous["enu_m"] is not None and current["enu_m"] is not None:
            displacement = math.dist(previous["enu_m"], current["enu_m"])
            heading = _heading(previous["enu_m"], current["enu_m"])
            if last_heading is not None:
                heading_change = _heading_delta(last_heading, heading)
            last_heading = heading
        stopped = (current["speed"].get("ema_kmh") or 0.0) <= 2.0
        heartbeat = 2.0 if stopped else 0.5
        if elapsed >= heartbeat or displacement >= 0.5 or heading_change >= 10.0 or coordinate_boundary or quality_boundary:
            retained.append(index)
    if retained[-1] != len(points) - 1:
        retained.append(len(points) - 1)
    return retained


def _world_run(points: list[dict]) -> list[dict]:
    """Return the longest contiguous world-coordinate run.

    Behavior facts may not bridge a coordinate-quality gap.  Choosing one
    contiguous run also makes the geometric maneuver result deterministic
    when a mission temporarily loses projection quality.
    """

    runs: list[list[dict]] = []
    current: list[dict] = []
    for point in points:
        if point["enu_m"] is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(point)
    if current:
        runs.append(current)
    return max(runs, key=len, default=[])


def _derive_episodes(points: list[dict]) -> list[dict]:
    """Derive conservative stopped/release episodes from the full sequence."""

    episodes: list[dict] = []
    stopped_start: int | None = None
    for index, point in enumerate(points):
        if point["enu_m"] is None:
            stopped_start = None
            continue
        timestamp = point["source_timestamp_sec"]
        window_start = index
        while (
            window_start > 0
            and points[window_start - 1]["enu_m"] is not None
            and timestamp - points[window_start - 1]["source_timestamp_sec"] <= 2.0
        ):
            window_start -= 1
        window = points[window_start:index + 1]
        enough_history = (
            len(window) >= 2
            and window[-1]["source_timestamp_sec"] - window[0]["source_timestamp_sec"] >= 2.0
        )
        displacement = (
            math.dist(window[0]["enu_m"], window[-1]["enu_m"])
            if enough_history
            else math.inf
        )
        ema_kmh = point["speed"].get("ema_kmh")
        is_stopped = enough_history and displacement <= 1.5 and (ema_kmh is None or ema_kmh <= 2.0)
        if is_stopped and stopped_start is None:
            stopped_start = window_start
            continue
        instant_kmh = point["speed"].get("instant_kmh")
        release_detected = (
            not is_stopped
            and (
                (ema_kmh is not None and ema_kmh >= 5.0)
                or (instant_kmh is not None and instant_kmh >= 5.0)
            )
        )
        if stopped_start is not None and release_detected:
            stopped_end = max(stopped_start, index - 1)
            episodes.append(
                {
                    "kind": "stopped",
                    "start_offset_ms": points[stopped_start]["offset_ms"],
                    "end_offset_ms": points[stopped_end]["offset_ms"],
                    "confidence": 1.0,
                    "evidence": {
                        "enter_max_displacement_m": 1.5,
                        "enter_window_sec": 2.0,
                        "exit_ema_speed_kmh": 5.0,
                    },
                    "algorithm_version": BEHAVIOR_VERSION,
                }
            )
            release_end = min(len(points) - 1, index + 1)
            episodes.append(
                {
                    "kind": "releasing",
                    "start_offset_ms": point["offset_ms"],
                    "end_offset_ms": points[release_end]["offset_ms"],
                    "confidence": 1.0,
                    "evidence": {"instant_speed_kmh": instant_kmh, "ema_speed_kmh": ema_kmh},
                    "algorithm_version": BEHAVIOR_VERSION,
                }
            )
            stopped_start = None
    if stopped_start is not None:
        episodes.append(
            {
                "kind": "stopped",
                "start_offset_ms": points[stopped_start]["offset_ms"],
                "end_offset_ms": points[-1]["offset_ms"],
                "confidence": 1.0,
                "evidence": {"enter_max_displacement_m": 1.5, "enter_window_sec": 2.0},
                "algorithm_version": BEHAVIOR_VERSION,
            }
        )
    return episodes


def _derive_maneuvers(points: list[dict]) -> list[dict]:
    """Detect high-confidence geometric U-turns without inferring road intent."""

    run = _world_run(points)
    if len(run) < 4:
        return []
    total_world = sum(point["enu_m"] is not None for point in points)
    if total_world / len(points) < 0.8:
        return []
    if any(_has_tracking_quality_gap(point.get("quality")) for point in run):
        return []
    segments = [
        {
            "index": index,
            "distance_m": math.dist(left["enu_m"], right["enu_m"]),
            "heading_deg": _heading(left["enu_m"], right["enu_m"]),
        }
        for index, (left, right) in enumerate(zip(run, run[1:]))
        if math.dist(left["enu_m"], right["enu_m"]) >= 0.05
    ]
    if len(segments) < 3:
        return []
    headings = [segment["heading_deg"] for segment in segments]
    cumulative_turn = sum(_heading_delta(left, right) for left, right in zip(headings, headings[1:]))
    net_turn = _heading_delta(headings[0], headings[-1])
    turn_start = next(
        (index for index, value in enumerate(headings) if _heading_delta(headings[0], value) >= 45.0),
        None,
    )
    reverse_start = next(
        (index for index, value in enumerate(headings) if _heading_delta(headings[0], value) >= 135.0),
        None,
    )
    if turn_start is None or reverse_start is None:
        return []
    approach_distance = sum(segment["distance_m"] for segment in segments[:turn_start])
    departure_distance = sum(segment["distance_m"] for segment in segments[reverse_start:])
    reverse_point_index = int(segments[reverse_start]["index"])
    reverse_hold_sec = (
        run[-1]["source_timestamp_sec"]
        - run[reverse_point_index]["source_timestamp_sec"]
    )
    path_length = sum(segment["distance_m"] for segment in segments)
    start_end = math.dist(run[0]["enu_m"], run[-1]["enu_m"])
    if (
        cumulative_turn < 135.0
        or net_turn < 135.0
        or approach_distance < 3.0
        or departure_distance < 3.0
        or reverse_hold_sec < 1.0
        or path_length < 6.0
        or start_end > path_length * 0.75
    ):
        return []
    return [
        {
            "kind": "geometric_u_turn",
            "start_offset_ms": run[0]["offset_ms"],
            "end_offset_ms": run[-1]["offset_ms"],
            "confidence": 1.0,
            "evidence": {
                "cumulative_heading_change_deg": round(cumulative_turn, 3),
                "net_heading_change_deg": round(net_turn, 3),
                "approach_distance_m": round(approach_distance, 3),
                "departure_distance_m": round(departure_distance, 3),
                "reverse_hold_sec": round(reverse_hold_sec, 3),
                "path_length_m": round(path_length, 3),
                "start_end_distance_m": round(start_end, 3),
                "world_coordinate_ratio": round(total_world / len(points), 6),
            },
            "algorithm_version": BEHAVIOR_VERSION,
        }
    ]


def _journey_from_segment(segment: dict, mission_start: float) -> dict:
    count = _validate_segment(segment)
    points = []
    for index in range(count):
        timestamp = float(segment["trajectory_timestamps_sec"][index])
        points.append(
            {
                "offset_ms": round((timestamp - mission_start) * 1000),
                "source_timestamp_sec": timestamp,
                "frame_num": int(segment["trajectory_frame_nums"][index]),
                "pixel": [float(value) for value in segment["trajectory_px"][index]],
                "enu_m": (
                    [float(value) for value in segment["trajectory_enu_m"][index]]
                    if segment["trajectory_enu_m"][index] is not None
                    else None
                ),
                "gcj02": (
                    [float(value) for value in segment["trajectory_gcj02"][index]]
                    if segment["trajectory_gcj02"][index] is not None
                    else None
                ),
                "quality": segment["point_quality_lineage"][index],
                "sampling_boundary": [],
            }
        )
    _freeze_speeds(points)
    episodes = _derive_episodes(points)
    maneuvers = _derive_maneuvers(points)
    _annotate_sampling_boundaries(points)
    indices = _retain_indices(points)
    retained = [points[index] for index in indices]
    retained[0]["sampling_boundary"].append("journey_start")
    retained[-1]["sampling_boundary"].append("journey_end")
    runtime_id = str(segment.get("track_id"))
    return {
        "track_id": runtime_id,
        "source_runtime_track_ids": [runtime_id],
        "source_point_count": count,
        "retained_point_count": len(retained),
        "sampling": {
            "algorithm_version": SAMPLING_VERSION,
            "moving_max_interval_ms": 500,
            "stopped_max_interval_ms": 2000,
            "max_deviation_m": 0.5,
            "max_heading_change_deg": 10.0,
        },
        "vehicle_class": segment.get("vehicle_class"),
        "yolo_class_id": segment.get("yolo_class_id"),
        "yolo_class_name": segment.get("yolo_class_name"),
        "turn_behavior": segment.get("turn_behavior"),
        "movement_key": segment.get("movement_key"),
        "matched_lane_key": segment.get("matched_lane_key"),
        "matched_link_id": segment.get("matched_link_id"),
        "road_analytics_eligible": bool(segment.get("road_analytics_eligible")),
        "road_match_quality": segment.get("road_match_quality"),
        "termination_reason": segment.get("termination_reason"),
        "episodes": episodes,
        "maneuvers": maneuvers,
        "points": retained,
    }


def _cosine(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator <= 1e-12:
        return None
    return sum(a * b for a, b in zip(left, right)) / denominator


def _merge_candidate(left: dict, right: dict) -> dict | None:
    gap = float(right["trajectory_timestamps_sec"][0]) - float(left["trajectory_timestamps_sec"][-1])
    if gap <= 0 or gap > 2.0:
        return None
    appearance = _cosine(left.get("appearance_embedding"), right.get("appearance_embedding"))
    if appearance is None or appearance < 0.90:
        return None
    left_world = left["trajectory_enu_m"][-1]
    right_world = right["trajectory_enu_m"][0]
    if left_world is not None and right_world is not None:
        motion_distance = math.dist(left_world, right_world)
        motion_space = "enu_m"
        if motion_distance > 5.0:
            return None
    else:
        motion_distance = math.dist(left["trajectory_px"][-1], right["trajectory_px"][0])
        motion_space = "pixel"
        if motion_distance > 50.0:
            return None
    return {
        "predecessor_runtime_track_id": str(left.get("track_id")),
        "successor_runtime_track_id": str(right.get("track_id")),
        "temporal_gap_sec": round(gap, 3),
        "motion_distance": round(motion_distance, 3),
        "motion_space": motion_space,
        "appearance_cosine": round(appearance, 6),
        "score": appearance - motion_distance * 0.001,
        "algorithm_version": "conservative-motion-appearance/v1",
    }


def _combine_segments(group: list[dict]) -> dict:
    first = group[0]
    combined = {
        key: first.get(key)
        for key in (
            "vehicle_class", "yolo_class_id", "yolo_class_name", "termination_reason",
            "tracking_quality", "quality_status", "turn_behavior", "movement_key",
            "matched_lane_key", "matched_link_id", "road_match_quality",
        )
    }
    runtime_ids = [str(segment.get("track_id")) for segment in group]
    combined["track_id"] = (
        runtime_ids[0]
        if len(runtime_ids) == 1
        else f"journey-{hashlib.sha256('|'.join(runtime_ids).encode()).hexdigest()[:16]}"
    )
    combined["road_analytics_eligible"] = all(
        bool(segment.get("road_analytics_eligible")) for segment in group
    )
    for key in (
        "trajectory_px", "trajectory_timestamps_sec", "trajectory_frame_nums",
        "trajectory_enu_m", "trajectory_gcj02", "point_quality_lineage",
    ):
        combined[key] = [value for segment in group for value in segment[key]]
    combined["source_runtime_track_ids"] = runtime_ids
    return combined


def _merge_segments(segments: list[dict], mission_start: float) -> list[dict]:
    ordered = sorted(segments, key=lambda item: float(item["trajectory_timestamps_sec"][0]))
    candidates = []
    for left_index, left in enumerate(ordered):
        for right_index in range(left_index + 1, len(ordered)):
            evidence = _merge_candidate(left, ordered[right_index])
            if evidence is not None:
                candidates.append((left_index, right_index, evidence))
    candidates_by_left: dict[int, list[tuple[int, int, dict]]] = {}
    candidates_by_right: dict[int, list[tuple[int, int, dict]]] = {}
    for candidate in candidates:
        candidates_by_left.setdefault(candidate[0], []).append(candidate)
        candidates_by_right.setdefault(candidate[1], []).append(candidate)
    for rows in (*candidates_by_left.values(), *candidates_by_right.values()):
        rows.sort(key=lambda item: item[2]["score"], reverse=True)
    accepted = []
    for candidate in candidates:
        left_index, right_index, evidence = candidate
        same_left = candidates_by_left[left_index]
        same_right = candidates_by_right[right_index]
        if same_left[0] is not candidate or same_right[0] is not candidate:
            continue
        left_margin = math.inf if len(same_left) == 1 else evidence["score"] - same_left[1][2]["score"]
        right_margin = math.inf if len(same_right) == 1 else evidence["score"] - same_right[1][2]["score"]
        if left_margin >= 0.05 and right_margin >= 0.05:
            accepted.append(candidate)
    successor = {left: (right, evidence) for left, right, evidence in accepted}
    predecessors = {right for _, right, _ in accepted}
    groups = []
    consumed = set()
    for index in range(len(ordered)):
        if index in predecessors or index in consumed:
            continue
        group_indices = [index]
        evidence_rows = []
        while group_indices[-1] in successor:
            next_index, evidence = successor[group_indices[-1]]
            if next_index in group_indices:
                break
            group_indices.append(next_index)
            evidence_rows.append({key: value for key, value in evidence.items() if key != "score"})
        consumed.update(group_indices)
        combined = _combine_segments([ordered[item] for item in group_indices])
        journey = _journey_from_segment(combined, mission_start)
        journey["track_id"] = combined["track_id"]
        journey["source_runtime_track_ids"] = combined["source_runtime_track_ids"]
        journey["reid_evidence"] = evidence_rows
        groups.append(journey)
    for index in range(len(ordered)):
        if index not in consumed:
            combined = _combine_segments([ordered[index]])
            journey = _journey_from_segment(combined, mission_start)
            journey["source_runtime_track_ids"] = combined["source_runtime_track_ids"]
            journey["reid_evidence"] = []
            groups.append(journey)
    return groups


def _derive_road_queues(journeys: list[dict]) -> None:
    """Enrich only road-trusted, overlapping stopped journeys as a queue."""

    groups: dict[tuple[str, str], list[dict]] = {}
    for journey in journeys:
        if journey.get("road_analytics_eligible") is not True:
            continue
        lane = journey.get("matched_lane_key")
        link = journey.get("matched_link_id")
        if lane and link:
            groups.setdefault((str(lane), str(link)), []).append(journey)
    for (lane, link), candidates in groups.items():
        if len(candidates) < 2:
            continue
        stopped = [
            (journey, episode)
            for journey in candidates
            for episode in journey["episodes"]
            if episode["kind"] == "stopped"
        ]
        if len(stopped) < 2:
            continue
        overlap_start = max(episode["start_offset_ms"] for _, episode in stopped)
        overlap_end = min(episode["end_offset_ms"] for _, episode in stopped)
        if overlap_end < overlap_start:
            continue
        for journey, _ in stopped:
            journey["episodes"].append(
                {
                    "kind": "standing_queue",
                    "start_offset_ms": overlap_start,
                    "end_offset_ms": overlap_end,
                    "confidence": 1.0,
                    "evidence": {
                        "matched_lane_key": lane,
                        "matched_link_id": link,
                        "overlapping_stopped_journeys": len({item[0]["track_id"] for item in stopped}),
                    },
                    "algorithm_version": BEHAVIOR_VERSION,
                }
            )
            releasing = next(
                (episode for episode in journey["episodes"] if episode["kind"] == "releasing"),
                None,
            )
            if releasing is not None and releasing["start_offset_ms"] >= overlap_start:
                journey["episodes"].append(
                    {
                        **releasing,
                        "kind": "queue_release",
                        "evidence": {**releasing["evidence"], "matched_lane_key": lane},
                    }
                )


class MissionTrajectoryArchive:
    """Filesystem-backed archive; Postgres ingestion consumes its sealed result."""

    def __init__(
        self,
        spool_root: str | os.PathLike[str],
        *,
        appearance_model_path: str | os.PathLike[str] | None = None,
        appearance_encoder: Callable[[list[Any]], list[list[float]]] | None = None,
    ) -> None:
        self.spool_root = Path(spool_root).expanduser().resolve()
        self.appearance_model_path = (
            Path(appearance_model_path).expanduser().resolve()
            if appearance_model_path
            else None
        )
        self.appearance_encoder = appearance_encoder

    def _encode_appearance(self, segments: list[dict]) -> None:
        selected = [segment for segment in segments if segment.get("appearance_crop_jpeg")]
        if not selected:
            return
        try:
            import cv2
            import numpy as np

            encoder = self.appearance_encoder
            if encoder is None:
                if self.appearance_model_path is None or not self.appearance_model_path.is_file():
                    return
                from ultralytics import YOLO

                model = YOLO(str(self.appearance_model_path))

                def encoder(values):
                    embed_options = {"source": values, "verbose": False}
                    appearance_device = os.environ.get("REPLAY_V2_APPEARANCE_DEVICE")
                    if appearance_device:
                        embed_options["device"] = appearance_device
                    appearance_imgsz = os.environ.get("REPLAY_V2_APPEARANCE_IMGSZ")
                    if appearance_imgsz:
                        embed_options["imgsz"] = int(appearance_imgsz)
                    outputs = model.embed(**embed_options)
                    return [
                        output.detach().cpu().float().reshape(-1).tolist()
                        for output in outputs
                    ]

            batch_size = max(int(os.environ.get("REPLAY_V2_APPEARANCE_BATCH_SIZE", "32")), 1)
            for start in range(0, len(selected), batch_size):
                batch = selected[start:start + batch_size]
                crops = [
                    cv2.imdecode(
                        np.frombuffer(
                            base64.b64decode(segment["appearance_crop_jpeg"]),
                            dtype=np.uint8,
                        ),
                        cv2.IMREAD_COLOR,
                    )
                    for segment in batch
                ]
                if any(crop is None for crop in crops):
                    continue
                embeddings = encoder(crops)
                if len(embeddings) != len(batch):
                    continue
                for segment, embedding in zip(batch, embeddings):
                    values = [float(value) for value in embedding]
                    norm = math.sqrt(sum(value * value for value in values))
                    if norm > 1e-12:
                        segment["appearance_embedding"] = [
                            round(value / norm, 8) for value in values
                        ]
        except Exception:
            # Appearance evidence is optional and fail-closed: motion alone must
            # never merge two runtime segments.
            return

    def _mission_dir(self, mission_id: str) -> Path:
        if not mission_id or any(part in mission_id for part in ("/", "\\", "..")):
            raise ValueError("mission_id contains unsupported path characters")
        return self.spool_root / mission_id

    def begin_mission(
        self,
        *,
        mission_id: str,
        source_profile_id: str,
        intersection_id: str,
        source_timestamp_sec: float | None = None,
    ) -> dict:
        mission_dir = self._mission_dir(mission_id)
        manifest_path = mission_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "mission_id": mission_id,
                "source_profile_id": source_profile_id,
                "intersection_id": intersection_id,
                "status": "incomplete",
                "segments": [],
                "recorded_segment_count": 0,
                "recorded_point_count": 0,
            }
        if source_timestamp_sec is not None:
            timestamp = float(source_timestamp_sec)
            manifest["observed_start_source_sec"] = min(
                timestamp, float(manifest.get("observed_start_source_sec", timestamp))
            )
            manifest["observed_end_source_sec"] = max(
                timestamp, float(manifest.get("observed_end_source_sec", timestamp))
            )
        _atomic_json(manifest_path, manifest)
        return manifest

    def mark_incomplete(self, mission_id: str, *, failure_reason: str) -> dict:
        mission_dir = self._mission_dir(mission_id)
        manifest_path = mission_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"mission archive not found: {mission_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "sealed":
            manifest["status"] = "incomplete"
            manifest["failure_reason"] = failure_reason
            _atomic_json(manifest_path, manifest)
        return manifest

    def record_segment(
        self,
        *,
        mission_id: str,
        source_profile_id: str,
        intersection_id: str,
        segment: dict,
    ) -> dict:
        point_count = _validate_segment(segment)
        mission_dir = self._mission_dir(mission_id)
        segment_id = _segment_id(segment)
        _atomic_json(mission_dir / "segments" / f"{segment_id}.json", segment)
        manifest_path = mission_dir / "manifest.json"
        manifest = self.begin_mission(
            mission_id=mission_id,
            source_profile_id=source_profile_id,
            intersection_id=intersection_id,
            source_timestamp_sec=float(segment["trajectory_timestamps_sec"][0]),
        )
        if manifest.get("status") == "sealed":
            raise ValueError("sealed mission cannot accept more segments")
        if segment_id not in manifest["segments"]:
            manifest["segments"].append(segment_id)
        manifest["recorded_segment_count"] = len(manifest["segments"])
        manifest["recorded_point_count"] = sum(
            _validate_segment(json.loads((mission_dir / "segments" / f"{item}.json").read_text(encoding="utf-8")))
            for item in manifest["segments"]
        )
        _atomic_json(manifest_path, manifest)
        return {"segment_id": segment_id, "point_count": point_count, "status": "incomplete"}

    def seal_mission(self, mission_id: str, *, termination_reason: str) -> dict:
        if termination_reason != "natural_eof":
            raise ValueError("mission can only be sealed after natural_eof")
        mission_dir = self._mission_dir(mission_id)
        manifest_path = mission_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"mission archive not found: {mission_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sealed_path = mission_dir / "sealed.json"
        if manifest.get("status") == "sealed" and sealed_path.exists():
            return json.loads(sealed_path.read_text(encoding="utf-8"))
        segments = [
            json.loads((mission_dir / "segments" / f"{segment_id}.json").read_text(encoding="utf-8"))
            for segment_id in manifest["segments"]
        ]
        self._encode_appearance(segments)
        mission_start = min(
            [float(segment["trajectory_timestamps_sec"][0]) for segment in segments]
            or [float(manifest.get("observed_start_source_sec", 0.0))]
        )
        mission_end = max(
            [float(segment["trajectory_timestamps_sec"][-1]) for segment in segments]
            or [float(manifest.get("observed_end_source_sec", mission_start))]
        )
        journeys = _merge_segments(segments, mission_start) if segments else []
        _derive_road_queues(journeys)
        total_points = sum(journey["source_point_count"] for journey in journeys)
        world_points = sum(
            point["enu_m"] is not None
            for journey in journeys
            for point in journey["points"]
        )
        retained_points = sum(len(journey["points"]) for journey in journeys)
        sealed = {
            **{key: value for key, value in manifest.items() if key != "segments"},
            "status": "sealed",
            "termination_reason": termination_reason,
            "started_at_source_sec": mission_start,
            "ended_at_source_sec": mission_end,
            "duration_sec": round(mission_end - mission_start, 3),
            "source_point_count": total_points,
            "retained_point_count": retained_points,
            "coordinate_coverage_ratio": round(world_points / retained_points, 6) if retained_points else 0.0,
            "journey_count": len(journeys),
            "behavior_count": sum(
                len(journey["episodes"]) + len(journey["maneuvers"])
                for journey in journeys
            ),
            "algorithm_versions": {
                "sampling": SAMPLING_VERSION,
                "speed": SPEED_VERSION,
                "behavior": BEHAVIOR_VERSION,
                "reid": "conservative-motion-appearance/v1",
            },
            "accuracy": {
                key: "not_evaluated"
                for key in ("idf1", "hota", "id_switch", "position_rmse", "speed_mae", "reid_accuracy")
            },
            "journeys": journeys,
        }
        _atomic_json(sealed_path, sealed)
        for segment_id, segment in zip(manifest["segments"], segments):
            if segment.pop("appearance_crop_jpeg", None) is not None:
                _atomic_json(mission_dir / "segments" / f"{segment_id}.json", segment)
        manifest["status"] = "sealed"
        manifest["sealed_artifact"] = "sealed.json"
        _atomic_json(manifest_path, manifest)
        return sealed

    def load_mission(self, mission_id: str) -> dict:
        mission_dir = self._mission_dir(mission_id)
        manifest_path = mission_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"mission archive not found: {mission_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") == "sealed" and (mission_dir / "sealed.json").exists():
            return json.loads((mission_dir / "sealed.json").read_text(encoding="utf-8"))
        return manifest
