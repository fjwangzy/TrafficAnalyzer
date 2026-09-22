"""Trajectory-only lane-change shape detection.

The detector deliberately knows nothing about lanes or maps.  It recognises a
stable-forward, lateral-shift, stable-forward shape in one compensated track.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def _unit(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-6 else None


def _heading_difference_deg(left: np.ndarray, right: np.ndarray) -> float:
    cosine = float(np.clip(np.dot(left, right), -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def detect_lane_change(
    observations: Iterable[tuple[float, float, float]],
    *,
    min_lateral_displacement: float,
    stable_window_sec: float = 2.0,
    min_lateral_speed: float = 0.2,
    max_heading_change_deg: float = 20.0,
) -> dict | None:
    """Return one completed lateral-shift fact, or ``None``.

    ``observations`` are ``(x, y, source_time_sec)`` in one fixed reference
    frame.  Callers choose ENU or a motion-compensated pixel coordinate system.
    """
    rows = sorted((float(x), float(y), float(t)) for x, y, t in observations)
    if len(rows) < 7 or any(b[2] <= a[2] for a, b in zip(rows, rows[1:])):
        return None
    points = np.asarray([(x, y) for x, y, _ in rows], dtype=float)
    times = np.asarray([t for _, _, t in rows], dtype=float)
    first_end = int(np.searchsorted(times, times[0] + stable_window_sec, side="right"))
    last_start = int(np.searchsorted(times, times[-1] - stable_window_sec, side="left"))
    if first_end < 2 or last_start >= len(rows) - 2:
        return None

    forward = _unit(points[first_end - 1] - points[0])
    final_forward = _unit(points[-1] - points[last_start])
    if forward is None or final_forward is None:
        return None
    if _heading_difference_deg(forward, final_forward) > max_heading_change_deg:
        return None

    left_normal = np.asarray([-forward[1], forward[0]])
    lateral = (points - points[0]) @ left_normal
    net_lateral = float(np.median(lateral[last_start:]) - np.median(lateral[:first_end]))
    if abs(net_lateral) < min_lateral_displacement:
        return None

    lateral_speed = np.diff(lateral) / np.diff(times)
    peak_index = int(np.argmax(np.abs(lateral_speed)))
    if abs(float(lateral_speed[peak_index])) < min_lateral_speed:
        return None
    tail_speed = float(np.median(lateral_speed[last_start:]))
    if abs(tail_speed) >= min_lateral_speed:
        return None

    start_threshold = abs(net_lateral) * 0.15
    start_index = next((index for index, value in enumerate(lateral) if abs(value) >= start_threshold), None)
    if start_index is None or start_index >= last_start:
        return None
    if float((points[-1] - points[0]) @ forward) <= 0:
        return None

    return {
        "start_time_sec": round(float(times[start_index]), 3),
        "peak_time_sec": round(float(times[peak_index + 1]), 3),
        "end_time_sec": round(float(times[-1]), 3),
        "direction": "left" if net_lateral > 0 else "right",
        "lateral_displacement": round(net_lateral, 3),
        "peak_lateral_speed": round(float(lateral_speed[peak_index]), 3),
        "heading_change_deg": round(_heading_difference_deg(forward, final_forward), 3),
    }
