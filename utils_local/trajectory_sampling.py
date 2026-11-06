"""Event-faithful geometry compaction and exact full-sequence speed summaries.

Only geometry is compacted. Online facts and frozen full-sequence statistics are
never derived from the retained geometry. No geographic projection happens here.
"""

from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import math

VERSION = "event-faithful/v2"
DEFAULTS = dict(
    enu_error_m=0.2,
    pixel_error_px=2.0,
    moving_interval_sec=0.5,
    stopped_interval_sec=2.0,
    event_before_sec=5.0,
    event_after_sec=5.0,
    source_gap_sec=0.5,
    heading_change_deg=10.0,
)


def policy_from_config(config):
    unknown = set(config) - set(DEFAULTS) - {"enabled"}
    if unknown:
        raise ValueError(
            "unknown history sampling settings: " + ",".join(sorted(unknown))
        )
    values = dict(DEFAULTS)
    values.update({k: float(v) for k, v in config.items() if k in DEFAULTS})
    if any(not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError("sampling limits must be finite and positive")
    return values


def semantic_quality(point):
    quality = point.get("quality") or {}
    return {
        k: v
        for k, v in quality.items()
        if k not in {"timestamp_sec", "frame_num", "source_drop_count"}
    }


def _window_start(value):
    return value.replace(minute=value.minute // 5 * 5, second=0, microsecond=0)


def full_sequence_summary(points, time_basis):
    basis = datetime.fromisoformat(time_basis.replace("Z", "+00:00"))
    if basis.tzinfo is None:
        raise ValueError("full-sequence time basis must have timezone")
    windows = defaultdict(Counter)
    for point in points:
        speed = (point.get("speed") or {}).get("ema_kmh")
        if speed is None:
            continue
        speed = float(speed)
        if not math.isfinite(speed) or speed < 0:
            raise ValueError("invalid frozen speed")
        when = basis + timedelta(milliseconds=int(point["offset_ms"]))
        windows[_window_start(when).astimezone(timezone.utc).isoformat()][
            round(speed * 1000)
        ] += 1
    return {
        "version": "full-sequence/v1",
        "time_basis": basis.isoformat(),
        "source_point_count": len(points),
        "speed_sample_count": sum(sum(h.values()) for h in windows.values()),
        "world_point_count": sum(p.get("enu_m") is not None for p in points),
        "windows": [
            {
                "window_start": key,
                "count": sum(hist.values()),
                "sum_milli": sum(k * n for k, n in hist.items()),
                "histogram": [[k, n] for k, n in sorted(hist.items())],
            }
            for key, hist in sorted(windows.items())
        ],
    }


def validate_summary(sampling, *, time_basis=None, source_count=None):
    if sampling.get("algorithm_version") != VERSION:
        raise ValueError("not a v2 sampling record")
    summary = sampling.get("full_sequence_summary")
    if not isinstance(summary, dict) or summary.get("version") != "full-sequence/v1":
        raise ValueError("v2 sampling requires full-sequence summary")
    basis = datetime.fromisoformat(
        str(summary.get("time_basis", "")).replace("Z", "+00:00")
    )
    if basis.tzinfo is None:
        raise ValueError("invalid summary time basis")
    if time_basis is not None and basis != time_basis:
        raise ValueError("summary time basis does not match sealed Mission")
    count = summary.get("source_point_count")
    world = summary.get("world_point_count")
    if (
        type(count) is not int
        or count < 1
        or type(world) is not int
        or not 0 <= world <= count
    ):
        raise ValueError("invalid summary point counts")
    if source_count is not None and count != int(source_count):
        raise ValueError("summary source point count mismatch")
    seen = set()
    speed_count = 0
    for window in summary.get("windows", []):
        stamp = datetime.fromisoformat(window["window_start"])
        if stamp.tzinfo is None or stamp != _window_start(stamp) or stamp in seen:
            raise ValueError("invalid/duplicate five minute window")
        seen.add(stamp)
        histogram = window["histogram"]
        if any(
            type(k) is not int or k < 0 or type(n) is not int or n < 1
            for k, n in histogram
        ):
            raise ValueError("invalid exact speed histogram")
        if len({k for k, n in histogram}) != len(histogram):
            raise ValueError("duplicate speed histogram bins")
        if (
            sum(n for k, n in histogram) != window["count"]
            or sum(k * n for k, n in histogram) != window["sum_milli"]
        ):
            raise ValueError("speed histogram totals mismatch")
        speed_count += window["count"]
    if (
        type(summary.get("speed_sample_count")) is not int
        or summary["speed_sample_count"] != speed_count
    ):
        raise ValueError("speed summary sample count mismatch")
    if speed_count > world:
        raise ValueError("speed summary exceeds world-coordinate observations")
    return summary


def public_sampling(sampling):
    return {k: v for k, v in (sampling or {}).items() if k != "full_sequence_summary"}


def _distance_error(points, left, right, index, key, tolerance):
    a, b, value = (points[k].get(key) for k in (left, right, index))
    if a is None or b is None or value is None:
        return 0.0 if a is None and b is None and value is None else math.inf
    interval = (
        points[right]["source_timestamp_sec"] - points[left]["source_timestamp_sec"]
    )
    weight = (
        points[index]["source_timestamp_sec"] - points[left]["source_timestamp_sec"]
    ) / interval
    source_error = math.dist(value, [a[c] + weight * (b[c] - a[c]) for c in (0, 1)])
    milliseconds = points[right]["offset_ms"] - points[left]["offset_ms"]
    if milliseconds <= 0:
        return math.inf
    canonical_weight = (
        points[index]["offset_ms"] - points[left]["offset_ms"]
    ) / milliseconds
    canonical_error = math.dist(
        value, [a[c] + canonical_weight * (b[c] - a[c]) for c in (0, 1)]
    )
    return max(source_error, canonical_error) / tolerance


def retain_indices(points, *, policy=None, episodes=(), maneuvers=(), event_windows=()):
    limits = policy_from_config(policy or {})
    if len(points) <= 2:
        return list(range(len(points)))
    times = [float(p["source_timestamp_sec"]) for p in points]
    if any(not math.isfinite(t) for t in times) or any(
        b <= a for a, b in zip(times, times[1:])
    ):
        raise ValueError("sampling source time must be strictly increasing")
    for p in points:
        for key in ("pixel", "enu_m", "gcj02"):
            value = p.get(key)
            if value is not None and (
                len(value) != 2 or not all(math.isfinite(float(v)) for v in value)
            ):
                raise ValueError("invalid point geometry")
    anchors = {0, len(points) - 1}
    windows = list(event_windows)
    direction = None
    last = 0
    for i in range(1, len(points)):
        speed = (points[i].get("speed") or {}).get("ema_kmh")
        if speed is not None and speed <= 2:
            direction = None
            last = i
            continue
        key = (
            "enu_m"
            if points[last].get("enu_m") is not None
            and points[i].get("enu_m") is not None
            else "pixel"
        )
        a, b = points[last].get(key), points[i].get(key)
        if (
            a is None
            or b is None
            or math.dist(a, b) < (0.05 if key == "enu_m" else 1.0)
        ):
            continue
        heading = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if direction is None:
            direction = heading
        elif (
            abs((heading - direction + 180) % 360 - 180) >= limits["heading_change_deg"]
        ):
            windows.append(
                (
                    times[i] - limits["event_before_sec"],
                    times[i] + limits["event_after_sec"],
                )
            )
            direction = heading
        last = i
    mission_start = times[0] - points[0]["offset_ms"] / 1000
    for event in [*episodes, *maneuvers]:
        start = mission_start + event["start_offset_ms"] / 1000
        end = mission_start + event["end_offset_ms"] / 1000
        if event.get("kind") in {
            "stopped",
            "standing_queue",
            "inferred_red_signal_queue",
        }:
            # Preserve transitions, not a thirty minute parking interval at full rate.
            windows += [
                (start - limits["event_before_sec"], start + limits["event_after_sec"]),
                (end - limits["event_before_sec"], end + limits["event_after_sec"]),
            ]
        else:
            windows.append(
                (start - limits["event_before_sec"], end + limits["event_after_sec"])
            )
    merged = []
    for start, end in sorted(windows):
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("invalid event sampling interval")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    window_index = 0
    for i, point in enumerate(points):
        while window_index < len(merged) and merged[window_index][1] < times[i]:
            window_index += 1
        if (
            window_index < len(merged)
            and merged[window_index][0] <= times[i] <= merged[window_index][1]
        ):
            anchors.add(i)
            point["sampling_boundary"].append("event_dense")
        if i:
            previous = points[i - 1]
            if semantic_quality(point) != semantic_quality(previous):
                anchors.update((i - 1, i))
                point["sampling_boundary"].append("quality_boundary")
            if (point.get("enu_m") is None) != (previous.get("enu_m") is None):
                anchors.update((i - 1, i))
                point["sampling_boundary"].append("world_coordinate_boundary")
            quality = point.get("quality") or {}
            stride = quality.get("source_frame_stride")
            frame_gap = stride is not None and int(point["frame_num"]) - int(
                previous["frame_num"]
            ) > int(stride)
            dropped = int(quality.get("source_drop_count") or 0) > 0
            if (
                frame_gap
                or dropped
                or times[i] - times[i - 1] > limits["source_gap_sec"] + 1e-9
            ):
                anchors.update((i - 1, i))
                point["sampling_boundary"].append("source_gap")
    # Sparse parked heartbeats require a confirmed full-sequence stopped
    # episode. Valid but slow crawling alone is still ordinary movement.
    stopped_windows = sorted(
        (event["start_offset_ms"], event["end_offset_ms"])
        for event in episodes
        if event.get("kind") == "stopped"
    )
    stopped_index = 0
    # Insert heartbeat anchors before simplifying, so each error scan is bounded
    # by at most 0.5/2 seconds of observations in ordinary intervals.
    last = 0
    for i in range(1, len(points)):
        speed = (points[last].get("speed") or {}).get("ema_kmh")
        while (
            stopped_index < len(stopped_windows)
            and stopped_windows[stopped_index][1] < points[last]["offset_ms"]
        ):
            stopped_index += 1
        confirmed_stopped = (
            stopped_index < len(stopped_windows)
            and stopped_windows[stopped_index][0]
            <= points[last]["offset_ms"]
            <= stopped_windows[stopped_index][1]
        )
        stopped = (
            confirmed_stopped
            and speed is not None
            and speed <= 2
            and points[last].get("enu_m") is not None
        )
        interval = (
            limits["stopped_interval_sec"] if stopped else limits["moving_interval_sec"]
        )
        if times[i] - times[last] > interval + 1e-9:
            if i - 1 > last:
                anchors.add(i - 1)
                last = i - 1
            else:
                anchors.add(i)
                last = i
        if i in anchors:
            last = i
    selected = set(anchors)
    ordered = sorted(anchors)
    stack = list(zip(ordered, ordered[1:]))
    while stack:
        left, right = stack.pop()
        if right - left <= 1:
            continue
        worst, split = 1.0, None
        for i in range(left + 1, right):
            error = max(
                _distance_error(
                    points, left, right, i, "pixel", limits["pixel_error_px"]
                ),
                _distance_error(points, left, right, i, "enu_m", limits["enu_error_m"]),
            )
            if error > worst + 1e-10:
                worst, split = error, i
        if split is not None:
            selected.add(split)
            stack.extend(((left, split), (split, right)))
    return sorted(selected)


def compact_journey(journey, *, time_basis, policy=None, event_windows=()):
    points = journey["points"]
    summary = full_sequence_summary(points, time_basis)
    enabled = (policy or {}).get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("sampling enabled must be a boolean")
    indices = (
        retain_indices(
            points,
            policy=policy,
            episodes=journey["episodes"],
            maneuvers=journey["maneuvers"],
            event_windows=event_windows,
        )
        if enabled
        else list(range(len(points)))
    )
    kept = [points[i] for i in indices]
    journey["points"] = kept
    journey["retained_point_count"] = len(kept)
    journey["sampling"] = {
        "algorithm_version": VERSION,
        "geometry_compacted": enabled,
        **policy_from_config(policy or {}),
        "full_sequence_summary": summary,
    }
    validate_summary(journey["sampling"], source_count=journey["source_point_count"])
    return journey
