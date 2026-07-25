"""Validated YOLO detection boundary shared by new and rollback pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import torch


@dataclass(frozen=True)
class ValidatedDetections:
    xyxy: list[list[float]]
    confidences: list[float]
    class_ids: list[int]
    class_names: list[str]
    diagnostics: dict[str, Any]


def configure_safe_mps_box_clipping(device, *, ops_module=None) -> bool:
    """Force Ultralytics away from sliced in-place clamp on Apple MPS.

    Older PyTorch MPS runtimes can silently corrupt sliced ``clamp_`` results.
    Ultralytics exposes its platform branch through ``NOT_MACOS14``; setting it
    false selects the equivalent out-of-place assignment path.
    """

    if torch.device(device).type != "mps":
        return False
    if ops_module is None:
        from ultralytics.utils import ops as ops_module

    if not hasattr(ops_module, "NOT_MACOS14"):
        return False
    ops_module.NOT_MACOS14 = False
    return True


def _as_numpy(value) -> np.ndarray:
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _class_name(class_names: Mapping[int, str] | Sequence[str], class_id: int) -> str:
    try:
        return str(class_names[class_id])
    except (IndexError, KeyError, TypeError):
        return str(class_id)


def extract_valid_detections(
    boxes,
    *,
    class_names: Mapping[int, str] | Sequence[str],
    frame_shape: Sequence[int],
) -> ValidatedDetections:
    """Clip and validate model boxes while preserving field alignment.

    Invalid geometry is discarded as one aligned row. It is never repaired into
    an invented object and therefore cannot contaminate association state.
    """

    xyxy = _as_numpy(boxes.xyxy)
    confidences = _as_numpy(boxes.conf).reshape(-1)
    class_ids = _as_numpy(boxes.cls).reshape(-1)
    raw_count = int(len(xyxy)) if xyxy.ndim > 0 else 0
    reasons: dict[str, int] = {}

    def reject(reason: str, count: int = 1) -> None:
        reasons[reason] = reasons.get(reason, 0) + count

    if (
        xyxy.ndim != 2
        or xyxy.shape[1:] != (4,)
        or len(confidences) != raw_count
        or len(class_ids) != raw_count
    ):
        reject("unaligned_model_output", max(raw_count, 1))
        return ValidatedDetections(
            xyxy=[],
            confidences=[],
            class_ids=[],
            class_names=[],
            diagnostics={
                "raw_detection_count": raw_count,
                "valid_detection_count": 0,
                "invalid_geometry_count": max(raw_count, 1),
                "invalid_geometry_reasons": reasons,
            },
        )

    height, width = int(frame_shape[0]), int(frame_shape[1])
    valid_xyxy: list[list[float]] = []
    valid_confidences: list[float] = []
    valid_class_ids: list[int] = []
    valid_class_names: list[str] = []
    for raw_box, raw_confidence, raw_class_id in zip(
        xyxy, confidences, class_ids, strict=True
    ):
        row = np.asarray(
            [*raw_box.tolist(), raw_confidence, raw_class_id], dtype=np.float64
        )
        if not np.isfinite(row).all():
            reject("non_finite")
            continue
        clipped = np.asarray(raw_box, dtype=np.float64).copy()
        clipped[[0, 2]] = np.clip(clipped[[0, 2]], 0.0, float(width))
        clipped[[1, 3]] = np.clip(clipped[[1, 3]], 0.0, float(height))
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            reject("non_positive_extent")
            continue
        class_id = int(raw_class_id)
        valid_xyxy.append([float(value) for value in clipped])
        valid_confidences.append(float(raw_confidence))
        valid_class_ids.append(class_id)
        valid_class_names.append(_class_name(class_names, class_id))

    invalid_count = raw_count - len(valid_xyxy)
    return ValidatedDetections(
        xyxy=valid_xyxy,
        confidences=valid_confidences,
        class_ids=valid_class_ids,
        class_names=valid_class_names,
        diagnostics={
            "raw_detection_count": raw_count,
            "valid_detection_count": len(valid_xyxy),
            "invalid_geometry_count": invalid_count,
            "invalid_geometry_reasons": reasons,
        },
    )
