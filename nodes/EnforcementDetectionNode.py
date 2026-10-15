"""Evaluate frozen ENU candidate rules against mature video tracks."""

from __future__ import annotations

import json
import math
import os

from shapely.geometry import Point, shape

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.track_lifecycle import mature_tracks_of
from utils_local.utils import profile_time


class EnforcementDetectionNode:
    """Create technical facts only; legal disposition stays outside the pipeline."""

    def __init__(self, config: dict) -> None:
        cfg = dict(config.get("enforcement_detection", {}))
        raw_snapshot = os.environ.get("ENFORCEMENT_RUNTIME_SNAPSHOT_JSON")
        if raw_snapshot:
            snapshot = json.loads(raw_snapshot)
            cfg["zones"] = snapshot.get("zones", [])
            cfg["rules"] = snapshot.get("rules", [])
        self.enabled = bool(cfg.get("enabled", True))
        self._zones = {}
        for zone in cfg.get("zones", []):
            geometry = zone.get("geometry_enu_m") or zone.get("geometry")
            if geometry and zone.get("id"):
                self._zones[str(zone["id"])] = (dict(zone), shape(geometry))
        self._rules = [dict(rule) for rule in cfg.get("rules", []) if rule.get("id")]
        self._entered_at: dict[tuple[int, str], float] = {}
        self._emitted: set[tuple[int, str, float]] = set()
        self._max_observation_gap = float(config.get("tracking_node", {}).get("max_frame_gap_sec", 0.5))
        self._last_timestamp: float | None = None

    @staticmethod
    def _vehicle_class(track) -> str:
        name = str(getattr(track, "yolo_class_name", "") or "").strip().lower()
        if not name or name.isdecimal() or name in {"unknown", "none", "nan"}:
            return "unknown"
        if name == "truck":
            return "truck"
        return "non_truck"

    def _fact(self, rule: dict, zone: dict, track, track_id: int, vehicle_class: str, timestamp: float, facts: dict) -> dict:
        result = {
            "source_event_id": f"enforcement:{rule['clue_type']}:{rule['id']}:{track_id}:{int(timestamp * 1000)}",
            "track_id": str(track_id),
            "vehicle_class": vehicle_class,
            "clue_type": rule["clue_type"],
            "zone_id": zone["id"],
            "zone_version": zone.get("version"),
            "rule_id": rule["id"],
            "rule_version": rule.get("version"),
            "class_confidence": getattr(track, "vehicle_class_confidence", None),
            "classification_model_version": getattr(track, "yolo_model_id", None),
            "quality_status": "unverified",
            "matched_facts": facts,
            "exclusion_result": {},
        }
        if rule["clue_type"] == "speed_observation":
            result.update({
                "video_speed_kmh": facts["speed_kmh"],
                "video_speed_method": "trajectory_enu",
                "video_speed_quality": "unverified",
            })
        return result

    def _matches(self, rule: dict, track, vehicle_class: str, inside_since: float, timestamp: float) -> dict | None:
        definition = rule.get("definition") or {}
        clue_type = rule.get("clue_type")
        if clue_type == "truck_restriction":
            return {"inside_zone": True, "coordinate_system": "ENU"} if vehicle_class == "truck" else None
        if clue_type == "speed_observation":
            speed = getattr(track, "avg_speed_kmh", None)
            limit = definition.get("max_speed_kmh")
            if speed is not None and limit is not None and float(speed) > float(limit):
                return {"inside_zone": True, "coordinate_system": "ENU", "speed_kmh": float(speed), "configured_limit_kmh": float(limit)}
            return None
        min_dwell = float(definition.get("min_dwell_sec", 30.0))
        dwell_sec = timestamp - inside_since
        if dwell_sec < min_dwell:
            return None
        if clue_type == "no_parking":
            speed = getattr(track, "avg_speed_kmh", None)
            max_speed = float(definition.get("max_speed_kmh", 3.0))
            if speed is None or float(speed) > max_speed:
                return None
        if clue_type not in {"no_parking", "dwell", "occupation"}:
            return None
        return {"inside_zone": True, "coordinate_system": "ENU", "dwell_sec": round(dwell_sec, 3)}

    @staticmethod
    def _position_for_zone(track, zone: dict):
        if zone.get("coordinate_system", "ENU") == "GCJ02":
            points = getattr(track, "trajectory_gcj02", None) or []
            return points[-1] if points else None
        return getattr(track, "current_position_enu_m", None)

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            self._entered_at.clear()
            self._emitted.clear()
            return frame_element
        frame_element.enforcement_clues = []
        if not self.enabled:
            return frame_element
        timestamp = float(frame_element.timestamp)
        if self._last_timestamp is not None and (
            timestamp <= self._last_timestamp or timestamp - self._last_timestamp > self._max_observation_gap
        ):
            self._entered_at.clear()
            self._emitted.clear()
        self._last_timestamp = timestamp
        valid_keys = set()
        for track_id, track in mature_tracks_of(frame_element).items():
            observed_at = getattr(track, "current_observation_timestamp_sec", None)
            if observed_at is not None and abs(float(observed_at) - timestamp) > 1e-6:
                continue
            vehicle_class = self._vehicle_class(track)
            for rule in self._rules:
                zone_entry = self._zones.get(str(rule.get("zone_id") or ""))
                if zone_entry is None:
                    continue
                zone, polygon = zone_entry
                position = self._position_for_zone(track, zone)
                if not isinstance(position, (list, tuple)) or len(position) != 2:
                    continue
                point = Point(float(position[0]), float(position[1]))
                key = (int(track_id), str(rule["id"]))
                if not polygon.covers(point):
                    continue
                if rule.get("clue_type") == "no_parking":
                    speed = getattr(track, "avg_speed_kmh", None)
                    limit = float((rule.get("definition") or {}).get("max_speed_kmh", 3.0))
                    if speed is None or not math.isfinite(float(speed)) or not 0 <= float(speed) <= limit:
                        continue
                valid_keys.add(key)
                entered_at = self._entered_at.setdefault(key, timestamp)
                facts = self._matches(rule, track, vehicle_class, entered_at, timestamp)
                if facts is None:
                    continue
                facts["coordinate_system"] = zone.get("coordinate_system", "ENU")
                event_key = (int(track_id), str(rule["id"]), entered_at)
                if event_key in self._emitted:
                    continue
                self._emitted.add(event_key)
                frame_element.enforcement_clues.append(
                    self._fact(rule, zone, track, int(track_id), vehicle_class, timestamp, facts)
                )
        self._entered_at = {key: started for key, started in self._entered_at.items() if key in valid_keys}
        self._emitted = {
            event for event in self._emitted
            if event[:2] in self._entered_at and event[2] == self._entered_at[event[:2]]
        }
        return frame_element
