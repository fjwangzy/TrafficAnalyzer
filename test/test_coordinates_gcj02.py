from utils_local.coordinates import (
    COORDINATE_SYSTEM,
    enu_to_gcj02,
    gcj02_to_enu,
    normalize_telemetry_position,
    wgs84_to_gcj02,
)


def test_wgs84_to_gcj02_shifts_jinan_position():
    longitude, latitude = wgs84_to_gcj02(117.022330, 36.702909)
    assert longitude > 117.027
    assert latitude > 36.702
    assert abs(longitude - 117.028) < 0.002


def test_gcj02_local_enu_round_trip():
    anchor = [117.028285, 36.703222]
    point = [117.028901, 36.703786]
    east, north = gcj02_to_enu(*point, anchor)
    restored = enu_to_gcj02(east, north, anchor)
    assert restored[0] == pytest.approx(point[0], abs=1e-9)
    assert restored[1] == pytest.approx(point[1], abs=1e-9)


def test_normalize_telemetry_is_idempotent_for_gcj02():
    source = {"position_gcj02": {"longitude": 117.1, "latitude": 36.7}}
    result = normalize_telemetry_position(source)
    assert result["position_gcj02"] == source["position_gcj02"]
    assert result["coordinate_system"] == COORDINATE_SYSTEM


import pytest
