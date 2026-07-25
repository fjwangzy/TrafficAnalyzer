"""Resolve frame-level map context without participating in target association."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon, shape

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.flight_motion import FlightMotionClassifier
from utils_local.homography import (
    compute_homography_from_telemetry,
    is_valid_homography,
    pixel_to_world,
)
from utils_local.utils import profile_time


def _translation(east_m: float, north_m: float) -> np.ndarray:
    return np.array(
        [[1.0, 0.0, east_m], [0.0, 1.0, north_m], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


class FlightGeoReferenceNode:
    """Own flight phase, absolute frame projection and camera-motion quality."""

    def __init__(self, config: dict) -> None:
        motion = config.get("flight_motion", {})
        self._classifier = FlightMotionClassifier(
            hover_speed_mps=motion.get(
                "hover_enter_speed_mps", motion.get("hover_speed_mps", 1.0)
            ),
            hover_confirm_sec=motion.get("hover_confirm_sec", 15.0),
            cruise_max_speed_mps=motion.get(
                "max_cruise_speed_mps", motion.get("cruise_max_speed_mps", 12.0)
            ),
            min_agl_m=motion.get("min_agl_m", 60.0),
            max_agl_m=motion.get("max_agl_m", 150.0),
            max_nadir_deviation_deg=motion.get("max_nadir_deviation_deg", 10.0),
            max_roll_deg=motion.get("max_roll_deg", 5.0),
            max_vertical_speed_mps=motion.get("max_vertical_speed_mps", 2.0),
            max_yaw_rate_dps=motion.get("max_yaw_rate_dps", 15.0),
            max_zoom_drift_ratio=motion.get("max_zoom_drift_ratio", 0.02),
            speed_consistency_mps=motion.get("speed_consistency_mps", 3.0),
            speed_inconsistency_confirm_sec=motion.get(
                "speed_inconsistency_confirm_sec", 1.0
            ),
            hover_exit_speed_mps=motion.get("hover_exit_speed_mps", 1.5),
            hover_max_radius_p95_m=motion.get("hover_max_radius_p95_m", 5.0),
            hover_exit_radius_m=motion.get("hover_exit_radius_m", 8.0),
            hover_exit_confirm_sec=motion.get("hover_exit_confirm_sec", 2.0),
        )
        quality = config.get("geo_reference", {})
        self._tracking_profile = config.get("tracking_profile", "hover_cruise_v1")
        self._require_visual = bool(quality.get("require_visual_validation", True))
        self._max_pose_visual_p95 = float(
            quality.get(
                "max_pose_visual_residual_p95_px",
                quality.get("pose_visual_max_residual_p95_px", 5.0),
            )
        )
        self._previous_projection: np.ndarray | None = None
        self._flight_segment_index = 0
        self._previous_phase: str | None = None

    def _absolute_projection(
        self, frame_element: FrameElement
    ) -> tuple[np.ndarray | None, bool]:
        H = getattr(frame_element, "homography_matrix", None)
        displacement = getattr(frame_element, "drone_displacement_m", None)
        if not is_valid_homography(H) or displacement is None:
            return None, False

        registration = getattr(frame_element, "runtime_visual_registration", None) or {}
        pose = registration.get("registration_pose") or {}
        camera = registration.get("camera_calibration") or {}
        reference_local = pose.get("telemetry_homography_pixel_to_local_enu")
        intrinsics = camera.get("camera_intrinsics") or camera.get("intrinsics")
        telemetry = getattr(frame_element, "telemetry", None)
        if reference_local is not None and intrinsics and telemetry and frame_element.frame is not None:
            reference_local = np.asarray(reference_local, dtype=np.float64)
            current_local = compute_homography_from_telemetry(
                telemetry,
                intrinsics,
                (frame_element.frame.shape[1], frame_element.frame.shape[0]),
            )
            if is_valid_homography(reference_local) and is_valid_homography(current_local):
                try:
                    correction = np.asarray(H, dtype=np.float64) @ np.linalg.inv(reference_local)
                    result = (
                        _translation(float(displacement[0]), float(displacement[1]))
                        @ correction
                        @ current_local
                    )
                    result = result / result[2, 2] if abs(result[2, 2]) > 1e-12 else result
                    return result, True
                except np.linalg.LinAlgError:
                    pass

        result = _translation(float(displacement[0]), float(displacement[1])) @ np.asarray(
            H, dtype=np.float64
        )
        return (
            result / result[2, 2] if abs(result[2, 2]) > 1e-12 else result,
            False,
        )

    @staticmethod
    def _map_coverage(
        frame_element: FrameElement, projection: np.ndarray | None
    ) -> dict:
        registration = getattr(frame_element, "runtime_visual_registration", None) or {}
        raw = registration.get("map_coverage_enu_m") or {}
        if not raw:
            return {"status": "unavailable", "coverage_ratio": None}
        try:
            coverage = shape(raw)
            height, width = frame_element.frame.shape[:2]
            frame_world = pixel_to_world(
                np.asarray(
                    [[0.0, 0.0], [width - 1.0, 0.0], [width - 1.0, height - 1.0], [0.0, height - 1.0]],
                    dtype=np.float64,
                ),
                projection,
            )
            footprint = Polygon(frame_world)
            ratio = (
                float(footprint.intersection(coverage).area / footprint.area)
                if footprint.is_valid and footprint.area > 1e-9
                else 0.0
            )
            return {
                "status": "verified" if ratio > 0 else "outside",
                "coverage_ratio": round(ratio, 6),
                "geometry_enu_m": raw,
            }
        except (TypeError, ValueError):
            return {"status": "unavailable", "coverage_ratio": None}

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        phase = self._classifier.observe(getattr(frame_element, "telemetry", None))
        frame_element.flight_phase = phase.phase
        if phase.phase != self._previous_phase:
            self._flight_segment_index += 1
            self._previous_phase = phase.phase
        frame_element.flight_segment_id = f"runtime-flight-{self._flight_segment_index:04d}"
        frame_element.is_hovering = phase.phase == "hover_verified"
        if frame_element.telemetry is not None and phase.horizontal_speed_mps is not None:
            telemetry = dict(frame_element.telemetry)
            telemetry["horizontal_speed"] = phase.horizontal_speed_mps
            telemetry["speed_source"] = phase.speed_source
            frame_element.telemetry = telemetry
        projection, pose_lineage_valid = self._absolute_projection(frame_element)
        pose_warp = None
        if projection is not None and self._previous_projection is not None:
            try:
                pose_warp = np.linalg.inv(projection) @ self._previous_projection
                if abs(pose_warp[2, 2]) > 1e-12:
                    pose_warp = pose_warp / pose_warp[2, 2]
            except np.linalg.LinAlgError:
                pose_warp = None

        visual = dict(
            getattr(frame_element, "visual_motion_quality", None)
            or {
                "status": "unavailable",
                "feature_count": 0,
                "reasons": ["visual_motion_not_resolved"],
            }
        )
        visual_warp = getattr(frame_element, "camera_motion_warp", None)
        if visual.get("status") == "verified":
            if not is_valid_homography(visual_warp):
                visual["status"] = "degraded"
                visual.setdefault("reasons", []).append(
                    "verified_visual_motion_missing_warp"
                )
            elif pose_warp is not None and frame_element.frame is not None:
                height, width = frame_element.frame.shape[:2]
                sample_x = np.linspace(0.0, max(width - 1.0, 0.0), 5)
                sample_y = np.linspace(0.0, max(height - 1.0, 0.0), 5)
                sample_points = np.asarray(
                    [[x, y, 1.0] for y in sample_y for x in sample_x],
                    dtype=np.float64,
                )
                visual_points = (np.asarray(visual_warp) @ sample_points.T).T
                pose_points = (pose_warp @ sample_points.T).T
                valid = (
                    np.abs(visual_points[:, 2]) > 1e-9
                ) & (np.abs(pose_points[:, 2]) > 1e-9)
                if np.any(valid):
                    visual_xy = visual_points[valid, :2] / visual_points[valid, 2:3]
                    pose_xy = pose_points[valid, :2] / pose_points[valid, 2:3]
                    residual = float(
                        np.percentile(np.linalg.norm(visual_xy - pose_xy, axis=1), 95)
                    )
                    visual["pose_visual_residual_p95_px"] = round(residual, 3)
                    if residual > self._max_pose_visual_p95:
                        visual["status"] = "degraded"
                        visual.setdefault("reasons", []).append(
                            "pose_visual_residual_exceeded"
                        )
        reasons = list(phase.reasons)
        runtime_map = (
            getattr(frame_element, "calibration_mode", None) == "runtime_map"
            and bool(getattr(frame_element, "map_version_id", None))
        )
        if not runtime_map:
            reasons.append("lane_verified_map_required")
        if projection is None:
            reasons.append("pixel_to_map_projection_unavailable")
        if self._tracking_profile == "hover_cruise_v1" and not pose_lineage_valid:
            reasons.append("registration_pose_lineage_required")
        if not phase.formal_pose_eligible:
            reasons.append("flight_pose_not_eligible")
        if phase.phase not in {"hover_verified", "cruise_nadir"}:
            reasons.append("flight_phase_not_verified")
        if self._require_visual and visual.get("status") not in {"verified", "bootstrap"}:
            reasons.append("visual_warp_not_verified")
        detection_diagnostics = (
            getattr(frame_element, "detection_diagnostics", None) or {}
        )
        if int(detection_diagnostics.get("invalid_geometry_count") or 0) > 0:
            reasons.append("invalid_detector_geometry")

        map_coverage = self._map_coverage(frame_element, projection) if projection is not None and frame_element.frame is not None else {"status": "unavailable", "coverage_ratio": None}
        if self._tracking_profile == "hover_cruise_v1" and map_coverage["status"] != "verified":
            reasons.append("map_coverage_not_verified")

        blocking = {
            "lane_verified_map_required",
            "pixel_to_map_projection_unavailable",
            "flight_pose_not_eligible",
            "visual_warp_not_verified",
            "flight_phase_not_verified",
            "registration_pose_lineage_required",
            "map_coverage_not_verified",
            "invalid_detector_geometry",
        }
        formal = not any(reason in blocking for reason in reasons)
        frame_element.pixel_to_map_enu = projection
        frame_element.pose_motion_warp = pose_warp
        frame_element.formal_analytics_eligible = formal
        frame_element.geo_reference_quality = {
            "status": "verified" if formal else "degraded",
            "flight_phase": phase.phase,
            "speed_source": phase.speed_source,
            "horizontal_speed_mps": phase.horizontal_speed_mps,
            "gps_coverage": phase.gps_coverage,
            "position_radius_p95_m": phase.position_radius_p95_m,
            "telemetry": {
                "status": "verified" if phase.formal_pose_eligible else "degraded",
                "reasons": list(phase.reasons),
            },
            "visual_warp": visual,
            "detection_geometry": detection_diagnostics,
            "registration_pose_lineage": {
                "status": "verified" if pose_lineage_valid else "unavailable"
            },
            "map_coverage": map_coverage,
            "reasons": list(dict.fromkeys(reasons)),
        }

        self._previous_projection = projection.copy() if projection is not None else None
        return frame_element
