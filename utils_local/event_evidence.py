"""Persist synchronized visual evidence from an actual TCC output frame.

This module never draws boxes, labels, trajectories, or conflict markers.  The
detector image must already be the exact ``ShowNode`` output that would be
written by ``VideoSaverNode``.  Files use the Platform-managed content-addressed
layout so events only carry portable descriptors.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import cv2
import numpy as np


CONFLICT_EVIDENCE_KINDS = (
    "conflict_original_frame",
    "conflict_detector_frame",
)

def _encode(
    frame: np.ndarray, max_width: int | None, jpeg_quality: int
) -> tuple[bytes, int, int]:
    height, width = frame.shape[:2]
    output = frame
    if max_width is not None and width > max_width:
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
        raise ValueError("failed to encode conflict evidence frame")
    out_height, out_width = output.shape[:2]
    return buffer.tobytes(), out_width, out_height


def _store_jpeg(
    storage_root: str | Path,
    kind: str,
    content: bytes,
    width: int,
    height: int,
) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    storage_key = f"objects/{digest[:2]}/{digest}"
    root = Path(storage_root).expanduser().resolve()
    destination = root / storage_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_name(
            f".{digest}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_bytes(content)
            os.replace(temporary, destination)
            destination.chmod(0o440)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "kind": kind,
        "storage_backend": "managed",
        "storage_key": storage_key,
        "sha256": digest,
        "size_bytes": len(content),
        "media_type": "image/jpeg",
        "width": width,
        "height": height,
    }


def save_conflict_evidence_files(
    frame_element,
    _event: dict | None = None,
    *,
    storage_root: str | Path,
    max_width: int | None = None,
    jpeg_quality: int = 95,
) -> list[dict]:
    """Save the raw frame and exact detector output without drawing either one."""
    original_frame = getattr(frame_element, "frame", None)
    detector_frame = getattr(frame_element, "frame_result", None)
    if original_frame is None or detector_frame is None:
        return []
    rendered = (
        np.asarray(original_frame),
        np.asarray(detector_frame),
    )
    result = []
    for kind, image in zip(CONFLICT_EVIDENCE_KINDS, rendered):
        content, width, height = _encode(
            image,
            max(1, int(max_width)) if max_width is not None else None,
            int(jpeg_quality),
        )
        result.append(_store_jpeg(storage_root, kind, content, width, height))
    return result
