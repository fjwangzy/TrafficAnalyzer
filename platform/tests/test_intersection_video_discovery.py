from pathlib import Path

import pytest
from services.SrtTelemetryParser import SrtTelemetryParser

from app.services.intersection_video_discovery import HoverIntersectionDiscovery


def _hover_records(longitude=117.022326, latitude=36.702909, start=0, seconds=20):
    return [
        {
            "timestamp": float(second),
            "longitude": longitude + (0.000001 if second % 2 else 0),
            "latitude": latitude,
            "gimbal_pitch": -90,
        }
        for second in range(start, start + seconds + 1)
    ]


def test_discovers_xqh_hover_in_gcj02_and_matches_local_road_context():
    discovery = HoverIntersectionDiscovery()

    result = discovery.discover(
        _hover_records(),
        [
            {
                "inter_id": "011wwe0z19700001",
                "name": "小清河北路与水屯路路口",
                "center_gcj02": [117.028267426, 36.703260199],
                "source": "road_context",
            },
            {
                "inter_id": "INT-OTHER",
                "name": "相邻路口",
                "center_gcj02": [117.0305, 36.7033],
                "source": "road_context",
            },
        ],
    )

    assert result["status"] == "candidates_ready"
    assert result["coordinate_evidence"]["source_coordinate_system"] == "WGS84"
    assert result["coordinate_evidence"]["coordinate_system"] == "GCJ02"
    assert result["hover_segments"][0]["duration_sec"] >= 20
    assert result["hover_segments"][0]["center_wgs84"] == pytest.approx(
        [117.022326, 36.702909], abs=2e-6
    )
    assert result["hover_segments"][0]["center_gcj02"] == pytest.approx(
        [117.028267426, 36.703260199], abs=2e-5
    )
    assert result["hover_segments"][0]["candidates"][0]["inter_id"] == "011wwe0z19700001"
    assert result["hover_segments"][0]["confidence"] == "auto_high_confidence"


def test_no_telemetry_requires_manual_confirmation():
    result = HoverIntersectionDiscovery().discover([], [])

    assert result == {
        "status": "awaiting_confirmation",
        "coordinate_evidence": {
            "source_coordinate_system": "WGS84",
            "coordinate_system": "GCJ02",
            "transform_version": result["coordinate_evidence"]["transform_version"],
            "gps_coverage": 0.0,
        },
        "hover_segments": [],
        "flight_segments": [],
        "binding_quality": "manual_unverified",
        "reason_code": "telemetry_unavailable",
    }


def test_hover_tolerates_up_to_ten_percent_missing_gps_samples():
    records = _hover_records(seconds=20)
    records[10] = {"timestamp": 10.0, "gimbal_pitch": -90}

    result = HoverIntersectionDiscovery().discover(records, [])

    assert result["status"] == "candidates_ready"
    assert result["coordinate_evidence"]["gps_coverage"] == pytest.approx(20 / 21)
    assert result["hover_segments"][0]["duration_sec"] == 20.0


def test_hover_rejects_more_than_ten_percent_missing_gps_samples():
    records = _hover_records(seconds=20)
    for index in (5, 10, 15):
        records[index] = {"timestamp": float(index), "gimbal_pitch": -90}

    result = HoverIntersectionDiscovery().discover(records, [])

    assert result["status"] == "awaiting_confirmation"
    assert result["reason_code"] == "hover_not_detected"


def test_wgs84_candidate_is_not_silently_treated_as_gcj02():
    result = HoverIntersectionDiscovery().discover(
        _hover_records(),
        [{
            "inter_id": "WRONG-COORDINATE-SYSTEM",
            "center_gcj02": [117.022326, 36.702909],
            "source": "road_context",
        }],
    )

    assert result["hover_segments"][0]["candidates"] == []
    assert result["hover_segments"][0]["confidence"] == "admin_confirmed"


def test_adjacent_intersections_require_admin_confirmation():
    center = [117.028267426, 36.703260199]
    result = HoverIntersectionDiscovery().discover(
        _hover_records(),
        [
            {"inter_id": "NEAREST", "center_gcj02": center, "source": "road_context"},
            {"inter_id": "ADJACENT", "center_gcj02": [center[0] + 0.0005, center[1]], "source": "road_context"},
        ],
    )

    assert [item["inter_id"] for item in result["hover_segments"][0]["candidates"]] == [
        "NEAREST", "ADJACENT"
    ]
    assert result["hover_segments"][0]["confidence"] == "admin_confirmed"


def test_non_nadir_or_moving_segments_are_not_hover_segments():
    non_nadir = [{**item, "gimbal_pitch": -70} for item in _hover_records(seconds=20)]
    moving = _hover_records(seconds=20)
    for index, item in enumerate(moving):
        item["longitude"] += index * 0.00002

    assert HoverIntersectionDiscovery().discover(non_nadir, [])["reason_code"] == "hover_not_detected"
    assert HoverIntersectionDiscovery().discover(moving, [])["reason_code"] == "hover_not_detected"


def test_source_discovery_exposes_shared_flight_phase_segments():
    records = [
        {
            **item,
            "altitude_agl": 100.0,
            "gimbal_roll": 0.0,
            "vertical_speed": 0.0,
            "zoom_factor": 1.0,
        }
        for item in _hover_records(seconds=20)
    ]

    result = HoverIntersectionDiscovery().discover(records, [])

    assert result["flight_segments"][-1]["phase"] == "hover_verified"
    assert result["flight_segments"][-1]["classifier_version"] == "flight-motion/v1"


def test_two_hover_centres_more_than_250_metres_are_kept_as_separate_segments():
    records = _hover_records(seconds=20) + _hover_records(
        longitude=117.0260, latitude=36.702909, start=30, seconds=20
    )

    result = HoverIntersectionDiscovery().discover(records, [])

    assert len(result["hover_segments"]) == 2
    assert result["hover_segments"][0]["end_offset_sec"] == 20.0
    assert result["hover_segments"][1]["start_offset_sec"] == 30.0


def test_real_xqh_srt_resolves_the_expected_gcj02_centre_and_intersection():
    telemetry = Path(__file__).resolve().parents[2] / "test_videos/inter_xqh/telemetry.srt"
    if not telemetry.exists():
        pytest.skip("retained XQH SRT is unavailable")

    result = HoverIntersectionDiscovery().discover(
        SrtTelemetryParser(str(telemetry)).records,
        [{
            "inter_id": "011wwe0z19700001",
            "name": "小清河北路与水屯路路口",
            "center_gcj02": [117.028267426, 36.703260199],
            "source": "road_context",
        }],
    )

    segment = result["hover_segments"][0]
    assert segment["center_gcj02"] == pytest.approx([117.028267, 36.703260], abs=1e-6)
    assert segment["candidates"][0]["inter_id"] == "011wwe0z19700001"
