"""Emit completed trajectory-only lane-change facts without lane geometry."""

from __future__ import annotations

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.lane_change import detect_lane_change
from utils_local.track_lifecycle import mature_tracks_of
from utils_local.utils import profile_time


class LaneChangeDetectionNode:
    """A small pipeline adapter over the trajectory-shape detector."""

    def __init__(self, config: dict) -> None:
        cfg = config.get("lane_change_detection", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.stable_window_sec = float(cfg.get("stable_window_sec", 2.0))
        self.min_lateral_speed_mps = float(cfg.get("min_lateral_speed_mps", 0.2))
        self.min_lateral_displacement_m = float(cfg.get("min_lateral_displacement_m", 2.0))
        self.min_lateral_displacement_px = float(cfg.get("min_lateral_displacement_px", 12.0))
        self.max_heading_change_deg = float(cfg.get("max_heading_change_deg", 20.0))
        self._emitted_end_by_track: dict[int, float] = {}

    def _observations(self, track, frame_element: FrameElement):
        enu = list(getattr(track, "position_history_enu_m", None) or [])
        if len(enu) >= 7:
            return enu, "trajectory_only_enu", self.min_lateral_displacement_m, self.min_lateral_speed_mps
        pixels = list(getattr(track, "position_history", None) or [])
        if len(pixels) >= 7 and bool(getattr(frame_element, "is_hovering", False)):
            return pixels, "trajectory_only_hover_pixels", self.min_lateral_displacement_px, self.min_lateral_speed_mps
        return None

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        frame_element.lane_change_events = []
        if not self.enabled:
            return frame_element
        for track_id, track in mature_tracks_of(frame_element).items():
            candidate = self._observations(track, frame_element)
            if candidate is None:
                continue
            observations, basis, min_displacement, min_speed = candidate
            last_end = self._emitted_end_by_track.get(int(track_id))
            if last_end is not None:
                observations = [point for point in observations if float(point[2]) > last_end]
            fact = detect_lane_change(
                observations,
                min_lateral_displacement=min_displacement,
                stable_window_sec=self.stable_window_sec,
                min_lateral_speed=min_speed,
                max_heading_change_deg=self.max_heading_change_deg,
            )
            if fact is None:
                continue
            fact.update({
                "event_id": f"lane-change:{track_id}:{int(fact['start_time_sec'] * 1000)}",
                "track_id": track_id,
                "inference_basis": basis,
                "quality_status": "unverified",
            })
            self._emitted_end_by_track[int(track_id)] = fact["end_time_sec"]
            frame_element.lane_change_events.append(fact)
        return frame_element
