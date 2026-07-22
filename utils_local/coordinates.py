"""Canonical GCJ-02 and local ENU coordinate helpers.

Raw DJI/GPS telemetry is WGS84.  The public TrafficAnalyzer contract is
GCJ-02, while metric calculations use a small local tangent plane anchored by
one GCJ-02 longitude/latitude pair.  Conversion happens once at the ingestion
boundary; callers must carry ``coordinate_system`` metadata to avoid applying
the offset twice.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


COORDINATE_SYSTEM = "GCJ02"
TRANSFORM_VERSION = "wgs84-gcj02-local-enu/v1"
_A = 6378245.0
_EE = 0.00669342162296594323
_EARTH_RADIUS_M = 6378137.0


def _outside_china(longitude: float, latitude: float) -> bool:
    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_lat(longitude: float, latitude: float) -> float:
    result = -100.0 + 2.0 * longitude + 3.0 * latitude
    result += 0.2 * latitude * latitude + 0.1 * longitude * latitude
    result += 0.2 * math.sqrt(abs(longitude))
    result += (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(latitude * math.pi) + 40.0 * math.sin(latitude / 3.0 * math.pi)) * 2.0 / 3.0
    result += (160.0 * math.sin(latitude / 12.0 * math.pi) + 320.0 * math.sin(latitude * math.pi / 30.0)) * 2.0 / 3.0
    return result


def _transform_lon(longitude: float, latitude: float) -> float:
    result = 300.0 + longitude + 2.0 * latitude
    result += 0.1 * longitude * longitude + 0.1 * longitude * latitude
    result += 0.1 * math.sqrt(abs(longitude))
    result += (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(longitude * math.pi) + 40.0 * math.sin(longitude / 3.0 * math.pi)) * 2.0 / 3.0
    result += (150.0 * math.sin(longitude / 12.0 * math.pi) + 300.0 * math.sin(longitude / 30.0 * math.pi)) * 2.0 / 3.0
    return result


def wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    """Convert one WGS84 longitude/latitude pair to GCJ-02."""
    longitude = float(longitude)
    latitude = float(latitude)
    if _outside_china(longitude, latitude):
        return longitude, latitude
    delta_lat = _transform_lat(longitude - 105.0, latitude - 35.0)
    delta_lon = _transform_lon(longitude - 105.0, latitude - 35.0)
    rad_lat = latitude / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    delta_lat = (delta_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    delta_lon = (delta_lon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return longitude + delta_lon, latitude + delta_lat


def gcj02_to_enu(
    longitude: float,
    latitude: float,
    anchor_gcj02: Iterable[float],
) -> tuple[float, float]:
    """Project a nearby GCJ-02 point into a local east/north metric plane."""
    anchor_lon, anchor_lat = (float(value) for value in anchor_gcj02)
    lat_rad = math.radians(anchor_lat)
    east = math.radians(float(longitude) - anchor_lon) * _EARTH_RADIUS_M * math.cos(lat_rad)
    north = math.radians(float(latitude) - anchor_lat) * _EARTH_RADIUS_M
    return east, north


def enu_to_gcj02(
    easting_m: float,
    northing_m: float,
    anchor_gcj02: Iterable[float],
) -> tuple[float, float]:
    """Convert local east/north metres back to GCJ-02 longitude/latitude."""
    anchor_lon, anchor_lat = (float(value) for value in anchor_gcj02)
    lat_rad = math.radians(anchor_lat)
    latitude = anchor_lat + math.degrees(float(northing_m) / _EARTH_RADIUS_M)
    longitude = anchor_lon + math.degrees(float(easting_m) / (_EARTH_RADIUS_M * math.cos(lat_rad)))
    return longitude, latitude


def normalize_telemetry_position(telemetry: dict | None) -> dict | None:
    """Attach the canonical GCJ-02 position without mutating raw source values."""
    if not telemetry:
        return telemetry
    result = dict(telemetry)
    existing = result.get("position_gcj02")
    if isinstance(existing, dict) and existing.get("longitude") is not None and existing.get("latitude") is not None:
        result["coordinate_system"] = COORDINATE_SYSTEM
        result.setdefault("coordinate_transform_version", TRANSFORM_VERSION)
        return result
    longitude = result.get("longitude")
    latitude = result.get("latitude")
    if longitude is None or latitude is None:
        return result
    gcj_lon, gcj_lat = wgs84_to_gcj02(float(longitude), float(latitude))
    result["position_gcj02"] = {"longitude": gcj_lon, "latitude": gcj_lat}
    result["coordinate_system"] = COORDINATE_SYSTEM
    result["source_coordinate_system"] = result.get("source_coordinate_system", "WGS84")
    result["coordinate_transform_version"] = TRANSFORM_VERSION
    return result
