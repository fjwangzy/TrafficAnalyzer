"""Build the synchronized visual evidence bundle for a conflict event.

The detector publishes evidence before ``ShowNode`` runs.  This module keeps
that ordering intact and renders independent copies of the same source frame,
so evidence generation never mutates the shared-memory frame consumed by the
preview and video workers.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import cv2
import numpy as np


CONFLICT_EVIDENCE_KINDS = (
    "conflict_original_frame",
    "conflict_detector_frame",
    "conflict_trajectory_reconstruction",
)


def _clip_point(point: Any, width: int, height: int) -> tuple[int, int] | None:
    if not isinstance(point, (list, tuple, np.ndarray)) or len(point) < 2:
        return None
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if not np.isfinite([x, y]).all():
        return None
    return (
        max(0, min(width - 1, int(round(x)))),
        max(0, min(height - 1, int(round(y)))),
    )


def _clip_box(box: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(box, (list, tuple, np.ndarray)) or len(box) != 4:
        return None
    try:
        values = [float(value) for value in box]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(values).all():
        return None
    x1, y1 = _clip_point(values[:2], width, height) or (0, 0)
    x2, y2 = _clip_point(values[2:], width, height) or (0, 0)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _track_color(track_id: Any, motor_id: Any, non_motor_id: Any) -> tuple[int, int, int]:
    if str(track_id) == str(motor_id):
        return 0, 82, 255
    if str(track_id) == str(non_motor_id):
        return 0, 210, 255
    seed = int.from_bytes(
        hashlib.sha256(str(track_id).encode("utf-8")).digest()[:4],
        byteorder="big",
    )
    return 90 + seed % 120, 100 + (seed // 7) % 120, 120 + (seed // 17) % 120


def _draw_detector_frame(frame: np.ndarray, frame_element, event: dict) -> np.ndarray:
    output = frame.copy()
    height, width = output.shape[:2]
    boxes = list(getattr(frame_element, "tracked_xyxy", None) or [])
    track_ids = list(getattr(frame_element, "id_list", None) or [])
    classes = list(getattr(frame_element, "tracked_cls", None) or [])
    if not boxes:
        boxes = list(getattr(frame_element, "detected_xyxy", None) or [])
        classes = list(getattr(frame_element, "detected_cls", None) or [])
        track_ids = list(range(len(boxes)))

    motor_id = event.get("motor_id")
    non_motor_id = event.get("non_motor_id")
    thickness = max(1, round(min(width, height) / 360))
    font_scale = max(0.35, min(width, height) / 900)
    for index, raw_box in enumerate(boxes):
        box = _clip_box(raw_box, width, height)
        if box is None:
            continue
        track_id = track_ids[index] if index < len(track_ids) else index
        class_name = classes[index] if index < len(classes) else "object"
        color = _track_color(track_id, motor_id, non_motor_id)
        cv2.rectangle(output, box[:2], box[2:], color, thickness + 1)
        label = f"#{track_id} {class_name}"
        cv2.putText(
            output,
            label,
            (box[0], max(11, box[1] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
    return output


def _draw_trajectory_frame(frame: np.ndarray, frame_element, event: dict) -> np.ndarray:
    output = frame.copy()
    height, width = output.shape[:2]
    overlay = np.zeros_like(output)
    overlay[:] = (8, 13, 21)
    output = cv2.addWeighted(output, 0.68, overlay, 0.32, 0)
    motor_id = event.get("motor_id")
    non_motor_id = event.get("non_motor_id")
    conflict_ids = {str(value) for value in (motor_id, non_motor_id) if value is not None}
    endpoints: dict[str, tuple[int, int]] = {}
    buffer_tracks = getattr(frame_element, "buffer_tracks", None) or {}

    for track_id, track in buffer_tracks.items():
        points = [
            clipped
            for point in (getattr(track, "trajectory_points", None) or [])[-90:]
            if (clipped := _clip_point(point, width, height)) is not None
        ]
        if not points:
            continue
        color = _track_color(track_id, motor_id, non_motor_id)
        highlighted = str(track_id) in conflict_ids
        if len(points) >= 2:
            cv2.polylines(
                output,
                [np.asarray(points, dtype=np.int32)],
                False,
                color,
                4 if highlighted else 2,
                cv2.LINE_AA,
            )
        endpoint = points[-1]
        endpoints[str(track_id)] = endpoint
        cv2.circle(output, endpoint, 6 if highlighted else 3, color, -1, cv2.LINE_AA)
        cv2.putText(
            output,
            f"#{track_id}",
            (endpoint[0] + 5, max(12, endpoint[1] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.35, min(width, height) / 900),
            color,
            1,
            cv2.LINE_AA,
        )

    motor_point = endpoints.get(str(motor_id))
    non_motor_point = endpoints.get(str(non_motor_id))
    if motor_point and non_motor_point:
        cv2.line(output, motor_point, non_motor_point, (40, 40, 255), 2, cv2.LINE_AA)
        midpoint = (
            (motor_point[0] + non_motor_point[0]) // 2,
            (motor_point[1] + non_motor_point[1]) // 2,
        )
        cv2.circle(output, midpoint, 7, (40, 40, 255), 2, cv2.LINE_AA)

    cv2.putText(
        output,
        "SAME-TIME TRAJECTORY RECONSTRUCTION",
        (12, max(18, round(height * 0.04))),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.35, min(width, height) / 1000),
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    return output


def _encode(kind: str, frame: np.ndarray, max_width: int, jpeg_quality: int) -> dict:
    height, width = frame.shape[:2]
    output = frame
    if width > max_width:
        scale = max_width / width
        output = cv2.resize(
            frame,
            (max_width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(
        ".jpg",
        output,
        [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
    )
    if not ok:
        raise ValueError(f"failed to encode {kind}")
    out_height, out_width = output.shape[:2]
    return {
        "kind": kind,
        "jpeg_base64": base64.b64encode(buffer).decode("ascii"),
        "width": out_width,
        "height": out_height,
    }


def build_conflict_evidence_images(
    frame_element,
    event: dict,
    *,
    max_width: int = 960,
    jpeg_quality: int = 75,
) -> list[dict]:
    """Return original, detector and trajectory images from one source frame."""
    frame = getattr(frame_element, "frame", None)
    if frame is None:
        return []
    original = np.asarray(frame).copy()
    rendered = (
        original,
        _draw_detector_frame(original, frame_element, event),
        _draw_trajectory_frame(original, frame_element, event),
    )
    return [
        _encode(kind, image, max(1, int(max_width)), int(jpeg_quality))
        for kind, image in zip(CONFLICT_EVIDENCE_KINDS, rendered)
    ]
