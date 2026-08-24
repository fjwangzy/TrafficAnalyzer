"""Shared flight-phase classification for ingestion and runtime analysis."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from utils_local.coordinates import gcj02_to_enu, normalize_telemetry_position


@dataclass(frozen=True)
class FlightPhaseSnapshot:
    phase: str
    horizontal_speed_mps: float | None
    speed_source: str | None
    formal_pose_eligible: bool
    reasons: tuple[str, ...] = ()
    gps_coverage: float | None = None
    position_radius_p95_m: float | None = None
    heading_deg: float | None = None


class FlightMotionClassifier:
    """Classify a telemetry stream with the same rules offline and at runtime."""

    def __init__(
        self,
        *,
        hover_speed_mps: float = 1.0,
        hover_confirm_sec: float = 15.0,
        cruise_max_speed_mps: float = 12.0,
        min_agl_m: float = 60.0,
        max_agl_m: float = 150.0,
        max_nadir_deviation_deg: float = 10.0,
        max_roll_deg: float = 5.0,
        allow_roll_with_visual_validation: bool = False,
        max_roll_visual_validation_deg: float = 15.0,
        max_vertical_speed_mps: float = 2.0,
        max_yaw_rate_dps: float = 15.0,
        max_zoom_drift_ratio: float = 0.02,
        speed_consistency_mps: float = 3.0,
        speed_inconsistency_confirm_sec: float = 1.0,
        hover_exit_speed_mps: float = 1.5,
        hover_max_radius_p95_m: float = 5.0,
        hover_exit_radius_m: float = 8.0,
        hover_exit_confirm_sec: float = 2.0,
    ) -> None:
        self.hover_speed_mps = float(hover_speed_mps)
        self.hover_confirm_sec = float(hover_confirm_sec)
        self.cruise_max_speed_mps = float(cruise_max_speed_mps)
        self.min_agl_m = float(min_agl_m)
        self.max_agl_m = float(max_agl_m)
        self.max_nadir_deviation_deg = float(max_nadir_deviation_deg)
        self.max_roll_deg = float(max_roll_deg)
        self.allow_roll_with_visual_validation = bool(allow_roll_with_visual_validation)
        self.max_roll_visual_validation_deg = float(max_roll_visual_validation_deg)
        self.max_vertical_speed_mps = float(max_vertical_speed_mps)
        self.max_yaw_rate_dps = float(max_yaw_rate_dps)
        self.max_zoom_drift_ratio = float(max_zoom_drift_ratio)
        self.speed_consistency_mps = float(speed_consistency_mps)
        self.speed_inconsistency_confirm_sec = float(
            speed_inconsistency_confirm_sec
        )
        self.hover_exit_speed_mps = float(hover_exit_speed_mps)
        self.hover_max_radius_p95_m = float(hover_max_radius_p95_m)
        self.hover_exit_radius_m = float(hover_exit_radius_m)
        self.hover_exit_confirm_sec = float(hover_exit_confirm_sec)

        self._last_timestamp: float | None = None
        self._last_position_gcj02: tuple[float, float] | None = None
        self._last_yaw_deg: float | None = None
        self._reference_zoom: float | None = None
        self._hover_started_at: float | None = None
        self._hover_exit_started_at: float | None = None
        self._was_hover_verified = False
        self._motion_window: list[tuple[float, tuple[float, float]]] = []
        self._hover_window: list[tuple[float, tuple[float, float] | None, float | None]] = []
        self._speed_inconsistent_started_at: float | None = None

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        position = (len(ordered) - 1) * percentile
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return float(ordered[lower])
        return float(
            ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        )

    @staticmethod
    def _angle_delta(current: float, previous: float) -> float:
        return (current - previous + 180.0) % 360.0 - 180.0

    def observe(self, telemetry: dict | None) -> FlightPhaseSnapshot:
        telemetry = normalize_telemetry_position(telemetry)
        if not telemetry:
            self._hover_started_at = None
            self._was_hover_verified = False
            self._speed_inconsistent_started_at = None
            return FlightPhaseSnapshot(
                "telemetry_unavailable", None, None, False, ("telemetry_unavailable",)
            )

        timestamp = float(telemetry.get("timestamp", 0.0) or 0.0)
        position = telemetry.get("position_gcj02") or {}
        lon = position.get("longitude")
        lat = position.get("latitude")
        current_position = (
            (float(lon), float(lat))
            if lon is not None and lat is not None
            else None
        )
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            reported_raw = telemetry.get("horizontal_speed")
            reported_speed = (
                abs(float(reported_raw)) if reported_raw is not None else None
            )
            return FlightPhaseSnapshot(
                phase="unsupported_pose",
                horizontal_speed_mps=reported_speed,
                speed_source="reported" if reported_speed is not None else None,
                formal_pose_eligible=False,
                reasons=("telemetry_time_reversal",),
            )

        derived_speed: float | None = None
        derived_heading: float | None = None
        yaw_rate: float | None = None
        if self._last_timestamp is not None and timestamp > self._last_timestamp:
            dt = timestamp - self._last_timestamp
            if current_position is not None and self._motion_window:
                candidates = [
                    item for item in self._motion_window
                    if 0 < timestamp - item[0] <= 1.5
                ]
                previous_time, previous_position = (
                    min(candidates, key=lambda item: abs((timestamp - item[0]) - 1.0))
                    if candidates
                    else self._motion_window[-1]
                )
                east, north = gcj02_to_enu(
                    current_position[0], current_position[1], previous_position
                )
                motion_dt = timestamp - previous_time
                if motion_dt > 0:
                    derived_speed = math.hypot(east, north) / motion_dt
                    if derived_speed > 1e-6:
                        derived_heading = math.degrees(math.atan2(east, north)) % 360.0
            yaw = float(telemetry.get("gimbal_yaw", 0.0) or 0.0)
            if self._last_yaw_deg is not None:
                yaw_rate = abs(self._angle_delta(yaw, self._last_yaw_deg)) / dt

        reported_raw = telemetry.get("horizontal_speed")
        reported_speed = (
            abs(float(reported_raw)) if reported_raw is not None else None
        )
        reasons: list[str] = []
        speed_disagreement = (
            derived_speed is not None
            and reported_speed is not None
            and abs(reported_speed - derived_speed) > self.speed_consistency_mps
        )
        if derived_speed is not None and (reported_speed is None or speed_disagreement):
            speed = derived_speed
            speed_source = "derived"
            if speed_disagreement and self._speed_inconsistent_started_at is None:
                self._speed_inconsistent_started_at = timestamp
            if (
                speed_disagreement
                and self._speed_inconsistent_started_at is not None
                and timestamp - self._speed_inconsistent_started_at
                >= self.speed_inconsistency_confirm_sec
            ):
                reasons.append("telemetry_speed_inconsistent")
        elif reported_speed is not None:
            speed = reported_speed
            speed_source = "reported"
        else:
            speed = derived_speed
            speed_source = "derived" if derived_speed is not None else None
        if not speed_disagreement:
            self._speed_inconsistent_started_at = None

        self._hover_window.append((timestamp, current_position, speed))
        self._hover_window = [
            item for item in self._hover_window
            if item[0] >= timestamp - self.hover_confirm_sec
        ]
        gps_coverage = (
            sum(item[1] is not None for item in self._hover_window) / len(self._hover_window)
            if self._hover_window
            else 0.0
        )
        valid_positions = [item[1] for item in self._hover_window if item[1] is not None]
        position_radius_p95 = None
        if valid_positions:
            center = (
                median(position[0] for position in valid_positions),
                median(position[1] for position in valid_positions),
            )
            radii = [
                math.hypot(*gcj02_to_enu(position[0], position[1], center))
                for position in valid_positions
            ]
            position_radius_p95 = self._percentile(radii, 0.95)
        hover_speed_p95 = self._percentile(
            [item[2] for item in self._hover_window if item[2] is not None], 0.95
        )

        agl = float(telemetry.get("altitude_agl", 0.0) or 0.0)
        pitch = float(telemetry.get("gimbal_pitch", -90.0) or -90.0)
        roll = abs(float(telemetry.get("gimbal_roll", 0.0) or 0.0))
        vertical_speed = abs(float(telemetry.get("vertical_speed", 0.0) or 0.0))
        zoom = float(telemetry.get("zoom_factor", 1.0) or 1.0)
        if self._reference_zoom is None and zoom > 0:
            self._reference_zoom = zoom
        zoom_drift = (
            abs(zoom / self._reference_zoom - 1.0)
            if self._reference_zoom and zoom > 0
            else 0.0
        )

        if current_position is None:
            reasons.append("gps_unavailable")
        if not self.min_agl_m <= agl <= self.max_agl_m:
            reasons.append("agl_out_of_range")
        if telemetry.get("altitude_agl_source") == "unavailable":
            reasons.append("agl_source_unverified")
        if telemetry.get("camera_lens_verified") is False:
            reasons.append("camera_lens_unverified")
        if abs(pitch + 90.0) > self.max_nadir_deviation_deg:
            reasons.append("gimbal_pitch_out_of_range")
        roll_requires_visual_validation = False
        if roll > self.max_roll_deg:
            if (
                self.allow_roll_with_visual_validation
                and roll <= self.max_roll_visual_validation_deg
            ):
                roll_requires_visual_validation = True
            else:
                reasons.append("gimbal_roll_out_of_range")
        if vertical_speed > self.max_vertical_speed_mps:
            reasons.append("vertical_speed_out_of_range")
        if yaw_rate is not None and yaw_rate > self.max_yaw_rate_dps:
            reasons.append("gimbal_yaw_rate_out_of_range")
        if zoom_drift > self.max_zoom_drift_ratio:
            reasons.append("zoom_drift_out_of_range")
        if speed is not None and speed > self.cruise_max_speed_mps:
            reasons.append("horizontal_speed_out_of_range")

        pose_reasons = list(reasons)
        if roll_requires_visual_validation:
            reasons.append("gimbal_roll_visual_validation_required")
        eligible = not pose_reasons
        leaving_hover = self._was_hover_verified and (
            (speed is not None and speed > self.hover_exit_speed_mps)
            or (position_radius_p95 is not None and position_radius_p95 > self.hover_exit_radius_m)
            or pitch > -78.0
        )
        if leaving_hover:
            if self._hover_exit_started_at is None:
                self._hover_exit_started_at = timestamp
            if timestamp - self._hover_exit_started_at < self.hover_exit_confirm_sec:
                phase = "transition"
                eligible = False
                reasons.append("hover_exit_transition")
            else:
                self._was_hover_verified = False
                self._hover_exit_started_at = None
                self._hover_started_at = None
                if pose_reasons:
                    phase = "unsupported_pose"
                elif speed is not None and speed > self.hover_speed_mps:
                    phase = "cruise_nadir"
                else:
                    phase = "hover_candidate"
        elif not eligible:
            phase = "unsupported_pose"
            self._hover_started_at = None
            self._was_hover_verified = False
            self._hover_exit_started_at = None
        elif speed is None or speed <= self.hover_speed_mps:
            if self._hover_started_at is None:
                self._hover_started_at = timestamp
            stable_hover = (
                timestamp - self._hover_started_at >= self.hover_confirm_sec
                and gps_coverage >= 0.9
                and (position_radius_p95 or 0.0) <= self.hover_max_radius_p95_m
                and (hover_speed_p95 is None or hover_speed_p95 <= self.hover_speed_mps)
            )
            phase = "hover_verified" if stable_hover else "hover_candidate"
            self._was_hover_verified = stable_hover
            self._hover_exit_started_at = None
        else:
            phase = "cruise_nadir"
            self._hover_started_at = None
            self._was_hover_verified = False
            self._hover_exit_started_at = None

        self._last_timestamp = timestamp
        self._last_position_gcj02 = current_position
        self._last_yaw_deg = float(telemetry.get("gimbal_yaw", 0.0) or 0.0)
        if current_position is not None:
            self._motion_window.append((timestamp, current_position))
            self._motion_window = [
                item for item in self._motion_window if item[0] >= timestamp - 1.5
            ]

        return FlightPhaseSnapshot(
            phase=phase,
            horizontal_speed_mps=speed,
            speed_source=speed_source,
            formal_pose_eligible=eligible,
            reasons=tuple(reasons),
            gps_coverage=round(gps_coverage, 6),
            position_radius_p95_m=(
                round(position_radius_p95, 3) if position_radius_p95 is not None else None
            ),
            heading_deg=derived_heading,
        )
