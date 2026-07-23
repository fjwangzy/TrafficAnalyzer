"""Discover stable nadir hover segments and match them to GCJ-02 intersections.

The public ``discover`` interface deliberately owns the coordinate boundary:
DJI longitude/latitude remain WGS84 evidence, while every candidate distance is
computed only after canonical GCJ-02 conversion.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable, Sequence

from utils_local.coordinates import TRANSFORM_VERSION, wgs84_to_gcj02


EARTH_RADIUS_M = 6_378_137.0


def _distance_m(first: Sequence[float], second: Sequence[float]) -> float:
    lon1, lat1 = map(math.radians, first[:2])
    lon2, lat2 = map(math.radians, second[:2])
    delta_lon, delta_lat = lon2 - lon1, lat2 - lat1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


class HoverIntersectionDiscovery:
    """Turn raw DJI telemetry into independently bindable hover segments."""

    def __init__(
        self,
        *,
        minimum_duration_sec: float = 15.0,
        maximum_radius_p95_m: float = 5.0,
        maximum_speed_p95_mps: float = 1.0,
        maximum_candidate_distance_m: float = 250.0,
    ) -> None:
        self.minimum_duration_sec = minimum_duration_sec
        self.maximum_radius_p95_m = maximum_radius_p95_m
        self.maximum_speed_p95_mps = maximum_speed_p95_mps
        self.maximum_candidate_distance_m = maximum_candidate_distance_m

    def discover(
        self,
        records: Sequence[dict[str, Any]],
        candidates: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence = {
            "source_coordinate_system": "WGS84",
            "coordinate_system": "GCJ02",
            "transform_version": TRANSFORM_VERSION,
            "gps_coverage": 0.0,
        }
        if not records:
            return {
                "status": "awaiting_confirmation",
                "coordinate_evidence": evidence,
                "hover_segments": [],
                "binding_quality": "manual_unverified",
                "reason_code": "telemetry_unavailable",
            }

        samples = self._resample(records)
        valid_count = sum(self._has_gps(item) for item in samples)
        evidence["gps_coverage"] = round(valid_count / len(samples), 6) if samples else 0.0
        segments = [
            self._describe_segment(run, candidates)
            for run in self._stable_runs(samples)
            if self._qualifies(run)
        ]
        if not segments:
            return {
                "status": "awaiting_confirmation",
                "coordinate_evidence": evidence,
                "hover_segments": [],
                "binding_quality": "manual_unverified",
                "reason_code": "hover_not_detected",
            }
        return {
            "status": "candidates_ready",
            "coordinate_evidence": evidence,
            "hover_segments": segments,
            "binding_quality": segments[0]["confidence"],
            "reason_code": None,
        }

    @staticmethod
    def _has_gps(record: dict[str, Any]) -> bool:
        try:
            lon = float(record.get("longitude"))
            lat = float(record.get("latitude"))
        except (TypeError, ValueError):
            return False
        return -180 <= lon <= 180 and -90 <= lat <= 90 and not (lon == 0 and lat == 0)

    def _resample(self, records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(records, key=lambda item: float(item.get("timestamp", 0)))
        start = math.ceil(float(ordered[0].get("timestamp", 0)))
        end = math.floor(float(ordered[-1].get("timestamp", 0)))
        result: list[dict[str, Any]] = []
        cursor = 0
        for second in range(start, end + 1):
            while cursor + 1 < len(ordered) and abs(float(ordered[cursor + 1].get("timestamp", 0)) - second) <= abs(float(ordered[cursor].get("timestamp", 0)) - second):
                cursor += 1
            nearest = ordered[cursor]
            if abs(float(nearest.get("timestamp", 0)) - second) <= 0.5:
                result.append({**nearest, "timestamp": float(second)})
            else:
                result.append({"timestamp": float(second)})
        return result

    def _stable_runs(self, samples: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        runs: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        last_valid: dict[str, Any] | None = None
        for sample in samples:
            pitch = sample.get("gimbal_pitch")
            qualified = self._has_gps(sample) and pitch is not None and float(pitch) <= -80
            if qualified and last_valid:
                previous = last_valid
                distance = _distance_m(
                    [previous["longitude"], previous["latitude"]],
                    [sample["longitude"], sample["latitude"]],
                )
                delta = max(float(sample["timestamp"]) - float(previous["timestamp"]), 1.0)
                if distance / delta > self.maximum_speed_p95_mps:
                    runs.append(current)
                    current = []
                    last_valid = None
            if qualified:
                current.append(sample)
                last_valid = sample
            elif current and pitch is not None and float(pitch) <= -80:
                current.append(sample)
            elif current:
                runs.append(current)
                current = []
                last_valid = None
        if current:
            runs.append(current)
        return runs

    def _qualifies(self, run: Sequence[dict[str, Any]]) -> bool:
        if not run or float(run[-1]["timestamp"]) - float(run[0]["timestamp"]) < self.minimum_duration_sec:
            return False
        valid = [item for item in run if self._has_gps(item)]
        if len(valid) / len(run) < 0.9:
            return False
        center = [median(float(item["longitude"]) for item in valid), median(float(item["latitude"]) for item in valid)]
        radius_p95 = _percentile(
            (_distance_m([item["longitude"], item["latitude"]], center) for item in valid),
            0.95,
        )
        speeds = [
            _distance_m(
                [valid[index - 1]["longitude"], valid[index - 1]["latitude"]],
                [valid[index]["longitude"], valid[index]["latitude"]],
            )
            / max(float(valid[index]["timestamp"]) - float(valid[index - 1]["timestamp"]), 1.0)
            for index in range(1, len(valid))
        ]
        return radius_p95 <= self.maximum_radius_p95_m and _percentile(speeds, 0.95) <= self.maximum_speed_p95_mps

    def _describe_segment(
        self,
        run: Sequence[dict[str, Any]],
        candidates: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        valid = [item for item in run if self._has_gps(item)]
        center_wgs84 = [
            median(float(item["longitude"]) for item in valid),
            median(float(item["latitude"]) for item in valid),
        ]
        center_gcj02 = list(wgs84_to_gcj02(*center_wgs84))
        local = [item for item in candidates if item.get("source") == "road_context"]
        pool = local or list(candidates)
        matched = sorted(
            (
                {
                    **item,
                    "distance_m": round(_distance_m(center_gcj02, item["center_gcj02"]), 3),
                }
                for item in pool
                if item.get("center_gcj02")
            ),
            key=lambda item: item["distance_m"],
        )
        matched = [item for item in matched if item["distance_m"] <= self.maximum_candidate_distance_m]
        nearest = matched[0]["distance_m"] if matched else math.inf
        second = matched[1]["distance_m"] if len(matched) > 1 else math.inf
        confidence = (
            "auto_high_confidence"
            if nearest <= 80 and second - nearest >= 80
            else "admin_confirmed"
        )
        center = center_wgs84
        return {
            "start_offset_sec": float(run[0]["timestamp"]),
            "end_offset_sec": float(run[-1]["timestamp"]),
            "duration_sec": float(run[-1]["timestamp"]) - float(run[0]["timestamp"]),
            "center_wgs84": center_wgs84,
            "center_gcj02": center_gcj02,
            "position_radius_p95_m": round(
                _percentile(
                    (_distance_m([item["longitude"], item["latitude"]], center) for item in valid),
                    0.95,
                ),
                3,
            ),
            "candidates": matched,
            "confidence": confidence,
        }
