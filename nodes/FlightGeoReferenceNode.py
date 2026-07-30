"""Resolve frame-level map context without participating in target association."""

from __future__ import annotations

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.flight_motion import FlightMotionClassifier
from utils_local.homography import (
    is_valid_homography,
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
        """Build the current frame's absolute ENU projection from video/SRT only."""
        H = getattr(frame_element, "homography_matrix", None)
        displacement = getattr(frame_element, "drone_displacement_m", None)
        if not is_valid_homography(H) or displacement is None:
            return None, False
        result = _translation(float(displacement[0]), float(displacement[1])) @ np.asarray(
            H, dtype=np.float64
        )
        return (
            result / result[2, 2] if abs(result[2, 2]) > 1e-12 else result,
            True,
        )

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
        projection, current_frame_matrix_valid = self._absolute_projection(frame_element)
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
        geo_reasons = list(phase.reasons)
        runtime_map = bool(getattr(frame_element, "runtime_map_bundle", None))
        if projection is None:
            geo_reasons.append("pixel_to_world_projection_unavailable")
        if not current_frame_matrix_valid:
            geo_reasons.append("current_frame_matrix_invalid")
        if not phase.formal_pose_eligible:
            geo_reasons.append("flight_pose_not_eligible")
        if phase.phase not in {"hover_verified", "cruise_nadir"}:
            geo_reasons.append("flight_phase_not_verified")
        if self._require_visual and visual.get("status") not in {"verified", "bootstrap"}:
            visual.setdefault("reasons", []).append("visual_warp_not_verified")
        detection_diagnostics = (
            getattr(frame_element, "detection_diagnostics", None) or {}
        )

        geo_blocking = {
            "pixel_to_world_projection_unavailable",
            "current_frame_matrix_invalid",
            "flight_pose_not_eligible",
            "flight_phase_not_verified",
        }
        geo_reasons = list(dict.fromkeys(geo_reasons))
        geo_eligible = not any(reason in geo_blocking for reason in geo_reasons)
        road_reasons = [] if runtime_map else ["lane_verified_map_required"]
        if not geo_eligible:
            road_reasons.append("world_position_unavailable")
        road_reasons = list(dict.fromkeys(road_reasons))
        road_eligible = bool(geo_eligible and runtime_map)
        # Keep the legacy aggregate as the complete road-analysis capability;
        # image trajectory lifecycle no longer consumes this value.
        formal = road_eligible
        frame_element.pixel_to_world_enu = projection
        frame_element.pose_motion_warp = pose_warp
        frame_element.geo_analytics_eligible = geo_eligible
        frame_element.road_analytics_eligible = road_eligible
        frame_element.tcc_analytics_eligible = geo_eligible
        frame_element.formal_analytics_eligible = formal
        frame_element.geo_reference_quality = {
            "status": "verified" if formal else "degraded",
            "geo_status": "verified" if geo_eligible else "degraded",
            "road_status": "verified" if road_eligible else "missing" if not runtime_map else "degraded",
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
            "current_frame_matrix": {
                "status": "verified" if current_frame_matrix_valid else "unavailable"
            },
            "capabilities": {
                "geo_analytics_eligible": geo_eligible,
                "road_analytics_eligible": road_eligible,
                "tcc_analytics_eligible": geo_eligible,
                "formal_analytics_eligible": formal,
            },
            "geo_reasons": geo_reasons,
            "road_reasons": road_reasons,
            "tcc_reasons": geo_reasons,
            "reasons": list(dict.fromkeys([*geo_reasons, *road_reasons])),
        }

        self._previous_projection = projection.copy() if projection is not None else None
        return frame_element
