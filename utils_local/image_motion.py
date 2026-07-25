"""Image-only camera-motion estimation for motion-compensated tracking.

This module deliberately has no telemetry, map, homography, ENU or GCJ-02
dependency.  Its output is therefore safe to use as the canonical ByteTrack
camera warp without allowing geographic-reference noise to change identities.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageMotionObservation:
    timestamp_sec: float
    frame_num: int
    frame_bgr: np.ndarray | None
    detected_xyxy: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class ImageMotionSnapshot:
    status: str
    previous_to_current_pixel_warp: np.ndarray | None
    feature_count: int
    inlier_ratio: float | None = None
    reprojection_p95_px: float | None = None
    reasons: tuple[str, ...] = ()

    @property
    def usable_for_tracking(self) -> bool:
        return self.status == "verified" and self.previous_to_current_pixel_warp is not None

    def quality_dict(self) -> dict:
        return {
            "status": self.status,
            "feature_count": self.feature_count,
            "inlier_ratio": self.inlier_ratio,
            "reprojection_p95_px": self.reprojection_p95_px,
            "reasons": list(self.reasons),
            "source": "background_lk_ransac",
        }


class ImageMotionEstimator:
    """Estimate previous-frame to current-frame pixel motion from background."""

    def __init__(
        self,
        *,
        visual_max_width: int = 960,
        min_background_points: int = 40,
        min_inlier_ratio: float = 0.5,
        max_reprojection_p95_px: float = 3.0,
        max_frame_gap_sec: float = 0.5,
        forward_backward_max_error_px: float = 1.5,
    ) -> None:
        self._max_width = max(int(visual_max_width), 160)
        self._min_features = max(int(min_background_points), 4)
        self._min_inlier_ratio = float(min_inlier_ratio)
        self._max_reprojection_p95 = float(max_reprojection_p95_px)
        self._max_frame_gap_sec = float(max_frame_gap_sec)
        self._forward_backward_max_error = float(forward_backward_max_error_px)
        self._previous_gray: np.ndarray | None = None
        self._previous_scale = 1.0
        self._previous_boxes: tuple[tuple[float, float, float, float], ...] = ()
        self._previous_timestamp: float | None = None

    @staticmethod
    def _gray(frame: np.ndarray, max_width: int) -> tuple[np.ndarray, float]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.shape[1] <= max_width:
            return gray, 1.0
        scale = max_width / gray.shape[1]
        resized = cv2.resize(
            gray,
            (max_width, max(1, int(round(gray.shape[0] * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, scale

    @staticmethod
    def _feature_mask(
        shape: tuple[int, int],
        boxes: tuple[tuple[float, float, float, float], ...],
        scale: float,
    ) -> np.ndarray:
        mask = np.full(shape, 255, dtype=np.uint8)
        for box in boxes:
            if len(box) < 4:
                continue
            x1, y1, x2, y2 = (float(value) * scale for value in box[:4])
            pad_x = max((x2 - x1) * 0.25, 3.0)
            pad_y = max((y2 - y1) * 0.25, 3.0)
            cv2.rectangle(
                mask,
                (max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))),
                (
                    min(shape[1] - 1, int(x2 + pad_x)),
                    min(shape[0] - 1, int(y2 + pad_y)),
                ),
                0,
                thickness=-1,
            )
        return mask

    @staticmethod
    def _points_outside_boxes(
        points: np.ndarray,
        boxes: tuple[tuple[float, float, float, float], ...],
        scale: float,
    ) -> np.ndarray:
        keep = np.ones(len(points), dtype=bool)
        for box in boxes:
            if len(box) < 4:
                continue
            x1, y1, x2, y2 = (float(value) * scale for value in box[:4])
            pad_x = max((x2 - x1) * 0.25, 3.0)
            pad_y = max((y2 - y1) * 0.25, 3.0)
            keep &= ~(
                (points[:, 0] >= x1 - pad_x)
                & (points[:, 0] <= x2 + pad_x)
                & (points[:, 1] >= y1 - pad_y)
                & (points[:, 1] <= y2 + pad_y)
            )
        return keep

    def _remember(
        self,
        gray: np.ndarray,
        scale: float,
        boxes: tuple[tuple[float, float, float, float], ...],
        timestamp: float,
    ) -> None:
        self._previous_gray = gray
        self._previous_scale = scale
        self._previous_boxes = boxes
        self._previous_timestamp = timestamp

    def observe(self, observation: ImageMotionObservation) -> ImageMotionSnapshot:
        timestamp = float(observation.timestamp_sec)
        frame = observation.frame_bgr
        boxes = tuple(tuple(float(value) for value in box[:4]) for box in observation.detected_xyxy)
        if frame is None:
            return ImageMotionSnapshot(
                "unavailable", None, 0, reasons=("frame_unavailable",)
            )

        current_gray, current_scale = self._gray(frame, self._max_width)
        if self._previous_gray is None:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot("bootstrap", None, 0)

        if self._previous_timestamp is not None:
            delta = timestamp - self._previous_timestamp
            if delta <= 0.0 or delta > self._max_frame_gap_sec:
                reason = "source_time_reversal" if delta <= 0.0 else "source_time_gap"
                self._remember(current_gray, current_scale, boxes, timestamp)
                return ImageMotionSnapshot("unavailable", None, 0, reasons=(reason,))
        if self._previous_gray.shape != current_gray.shape:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable", None, 0, reasons=("frame_shape_changed",)
            )

        mask = self._feature_mask(
            self._previous_gray.shape,
            self._previous_boxes,
            self._previous_scale,
        )
        previous_points = cv2.goodFeaturesToTrack(
            self._previous_gray,
            maxCorners=500,
            qualityLevel=0.01,
            minDistance=8,
            mask=mask,
        )
        if previous_points is None or len(previous_points) < self._min_features:
            count = 0 if previous_points is None else len(previous_points)
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable",
                None,
                count,
                reasons=("insufficient_background_features",),
            )

        current_points, forward_status, _ = cv2.calcOpticalFlowPyrLK(
            self._previous_gray,
            current_gray,
            previous_points,
            None,
        )
        if current_points is None or forward_status is None:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable", None, 0, reasons=("optical_flow_failed",)
            )
        backward_points, backward_status, _ = cv2.calcOpticalFlowPyrLK(
            current_gray,
            self._previous_gray,
            current_points,
            None,
        )
        if backward_points is None or backward_status is None:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable", None, 0, reasons=("backward_flow_failed",)
            )

        source_all = previous_points.reshape(-1, 2)
        target_all = current_points.reshape(-1, 2)
        backward_all = backward_points.reshape(-1, 2)
        valid = (forward_status.reshape(-1) == 1) & (backward_status.reshape(-1) == 1)
        valid &= np.linalg.norm(backward_all - source_all, axis=1) <= self._forward_backward_max_error
        valid &= self._points_outside_boxes(target_all, boxes, current_scale)
        source = source_all[valid]
        target = target_all[valid]
        feature_count = len(source)
        if feature_count < self._min_features:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable",
                None,
                feature_count,
                reasons=("insufficient_tracked_background_features",),
            )

        affine, inliers = cv2.estimateAffinePartial2D(
            source,
            target,
            method=cv2.RANSAC,
            ransacReprojThreshold=self._max_reprojection_p95,
        )
        if affine is None or inliers is None:
            self._remember(current_gray, current_scale, boxes, timestamp)
            return ImageMotionSnapshot(
                "unavailable",
                None,
                feature_count,
                reasons=("visual_transform_failed",),
            )

        inlier_mask = inliers.reshape(-1).astype(bool)
        inlier_ratio = float(np.mean(inlier_mask))
        small_warp = np.vstack([affine, [0.0, 0.0, 1.0]])
        source_h = np.column_stack([source, np.ones(feature_count)])
        predicted = (small_warp @ source_h.T).T
        errors = np.linalg.norm(predicted[:, :2] - target, axis=1)
        reprojection_p95 = float(np.percentile(errors[inlier_mask], 95))
        scale_previous = np.diag(
            [self._previous_scale, self._previous_scale, 1.0]
        )
        scale_current_inverse = np.diag(
            [1.0 / current_scale, 1.0 / current_scale, 1.0]
        )
        full_warp = scale_current_inverse @ small_warp @ scale_previous
        if abs(full_warp[2, 2]) > 1e-12:
            full_warp = full_warp / full_warp[2, 2]

        verified = (
            np.isfinite(full_warp).all()
            and inlier_ratio >= self._min_inlier_ratio
            and reprojection_p95 <= self._max_reprojection_p95
        )
        self._remember(current_gray, current_scale, boxes, timestamp)
        return ImageMotionSnapshot(
            "verified" if verified else "degraded",
            full_warp if verified else None,
            feature_count,
            round(inlier_ratio, 4),
            round(reprojection_p95, 3),
            () if verified else ("visual_motion_quality_gate_failed",),
        )
