"""Match tracked ground-contact points to one immutable lane-verified map."""

from __future__ import annotations

import math

from shapely.geometry import Point, shape

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.coordinates import gcj02_to_enu
from utils_local.runtime_map import (
    load_runtime_map_bundle,
)
from utils_local.track_lifecycle import (
    active_tracks_of,
    mature_track_for_association,
    mature_tracks_of,
)
from utils_local.utils import profile_time


class RoadMapMatchingNode:
    def __init__(self, config: dict) -> None:
        cfg = config.get("road_map_matching", {})
        self.max_lateral_distance_m = float(cfg.get("max_lateral_distance_m", 2.5))
        self.bundle = load_runtime_map_bundle(config)
        self._lanes: list[tuple[dict, object, float | None, dict]] = []
        self._lane_transitions: dict[str, set[str]] = {}
        if self.bundle:
            topology = self.bundle.get("topology") or {}
            lane_properties = topology.get("lane_properties") or {}
            self._lane_transitions = {
                str(key): {str(value) for value in values}
                for key, values in (topology.get("lane_transitions") or {}).items()
                if isinstance(values, list)
            }
            link_headings = self._link_headings(topology)
            for lane in self.bundle.get("lanes") or []:
                geometry = lane.get("geometry_enu_m")
                if geometry:
                    properties = lane_properties.get(lane.get("local_lane_id"), {})
                    heading = properties.get("heading_deg")
                    if heading is None:
                        heading = link_headings.get(lane.get("link_id"))
                    self._lanes.append((lane, shape(geometry), heading, properties))

    def _link_headings(self, topology: dict) -> dict[str, float]:
        geometries = (self.bundle.get("geometry_enu_m") or {}).get("links") or {}
        inter_id = self.bundle.get("inter_id")
        result: dict[str, float] = {}
        for link in topology.get("links") or []:
            link_id = link.get("link_id")
            geometry = geometries.get(link_id) or {}
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) < 2:
                continue
            # YCX Link geometry follows f_inter_id -> t_inter_id.  Both inbound
            # and outbound lanes therefore use the coordinate order as travel heading.
            start, end = coordinates[-2], coordinates[-1]
            if link.get("f_inter_id") == inter_id:
                start, end = coordinates[0], coordinates[1]
            dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
            if math.hypot(dx, dy) > 1e-6:
                result[str(link_id)] = math.degrees(math.atan2(dy, dx)) % 360
        return result

    @property
    def ready(self) -> bool:
        return bool(self.bundle and self.bundle.get("anchor_gcj02") and self._lanes)

    @staticmethod
    def _clear_road_fields(track, quality: str) -> None:
        track.current_lane = None
        track.matched_lane_key = None
        track.source_lane_id = None
        track.matched_link_id = None
        track.map_version_id = None
        track.map_match_confidence = None
        track.road_match_quality = quality

    @staticmethod
    def _heading_similarity(left: float, right: float) -> float:
        delta = abs((left - right + 180) % 360 - 180)
        return max(-1.0, math.cos(math.radians(delta)))

    def _match(
        self,
        point: Point,
        previous_lane: str | None,
        vehicle_heading: float | None,
    ) -> tuple[dict, dict, float] | None:
        candidates: list[tuple[float, dict, dict]] = []
        for lane, polygon, lane_heading, properties in self._lanes:
            distance = float(polygon.distance(point))
            if distance <= self.max_lateral_distance_m:
                continuity_bonus = 0.35 if lane["local_lane_id"] == previous_lane else 0.0
                inside_bonus = 1.0 if polygon.covers(point) else 0.0
                heading_bonus = 0.0
                if vehicle_heading is not None and lane_heading is not None:
                    heading_bonus = 0.45 * self._heading_similarity(vehicle_heading, float(lane_heading))
                transition_penalty = 0.0
                allowed = self._lane_transitions.get(previous_lane or "")
                if allowed and lane["local_lane_id"] not in allowed and lane["local_lane_id"] != previous_lane:
                    transition_penalty = 0.8
                score = (
                    inside_bonus + continuity_bonus + math.exp(-distance)
                    + heading_bonus - transition_penalty
                )
                candidates.append((score, lane, properties))
        if not candidates:
            return None
        score, lane, properties = max(candidates, key=lambda item: item[0])
        confidence = max(0.0, min(1.0, score / 2.8))
        return lane, properties, confidence

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        if not self.ready:
            status = (
                "degraded"
                if self.bundle is not None
                else "missing"
            )
            frame_element.road_analytics_eligible = False
            frame_element.formal_analytics_eligible = False
            frame_element.road_context_status = status
            frame_element.info["map_matching"] = {
                "map_version_id": (
                    self.bundle.get("map_version_id") if self.bundle else None
                ),
                "map_status": status,
                "matched_tracks": 0,
                "total_tracks": len(mature_tracks_of(frame_element)),
            }
            for track in active_tracks_of(frame_element).values():
                self._clear_road_fields(track, status)
            return frame_element
        frame_element.runtime_map_bundle = self.bundle
        frame_element.map_version_id = self.bundle["map_version_id"]
        frame_element.road_context_status = "complete"
        if not getattr(frame_element, "geo_analytics_eligible", False):
            frame_element.road_analytics_eligible = False
            frame_element.formal_analytics_eligible = False
            frame_element.info["map_matching"] = {
                "map_version_id": self.bundle["map_version_id"],
                "map_status": "quality_gate_blocked",
                "matched_tracks": 0,
                "total_tracks": 0,
            }
            for track in active_tracks_of(frame_element).values():
                self._clear_road_fields(track, "quality_gate_blocked")
            return frame_element
        frame_element.road_analytics_eligible = True
        frame_element.formal_analytics_eligible = True
        matched = 0
        map_anchor = self.bundle["anchor_gcj02"]
        for index, track_id in enumerate(frame_element.id_list or []):
            if index >= len(frame_element.tracked_xyxy or []):
                continue
            track = mature_track_for_association(frame_element, track_id)
            if track is None:
                continue
            self._clear_road_fields(track, "unmatched")
            gcj_history = [
                point for point in (getattr(track, "trajectory_gcj02", None) or [])
                if point is not None
            ]
            if not gcj_history:
                continue
            easting, northing = gcj02_to_enu(
                float(gcj_history[-1][0]), float(gcj_history[-1][1]), map_anchor
            )
            previous_position = None
            if len(gcj_history) >= 2:
                previous_position = gcj02_to_enu(
                    float(gcj_history[-2][0]), float(gcj_history[-2][1]), map_anchor
                )
            vehicle_heading = None
            if previous_position:
                dx = easting - float(previous_position[0])
                dy = northing - float(previous_position[1])
                if math.hypot(dx, dy) >= 0.2:
                    vehicle_heading = math.degrees(math.atan2(dy, dx)) % 360
            result = self._match(
                Point(easting, northing), track.matched_lane_key, vehicle_heading
            )
            if result is None:
                continue
            lane, _properties, confidence = result
            track.current_lane = lane["local_lane_id"]
            track.matched_lane_key = lane["local_lane_id"]
            track.source_lane_id = lane.get("source_lane_id")
            track.matched_link_id = lane.get("link_id")
            track.map_version_id = self.bundle["map_version_id"]
            track.map_match_confidence = round(confidence, 4)
            track.road_match_quality = "verified"
            track.lane_history.append((track.matched_lane_key, frame_element.timestamp))
            matched += 1
        frame_element.lane_source = "channelized_map"
        frame_element.info["map_matching"] = {
            "map_version_id": self.bundle["map_version_id"],
            "map_status": "lane_verified",
            "matched_tracks": matched,
            "total_tracks": len(mature_tracks_of(frame_element)),
        }
        return frame_element
