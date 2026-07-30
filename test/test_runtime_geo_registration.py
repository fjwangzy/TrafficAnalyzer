import json

import numpy as np

from elements.FrameElement import FrameElement
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from utils_local.runtime_geo import load_runtime_geo_registration


def _registration(source_profile_id="SRC-1"):
    return {
        "id": "SGR-1",
        "source_profile_id": source_profile_id,
        "status": "verified",
        "coordinate_system": "GCJ02",
        "coordinate_transform_version": "wgs84-gcj02/v1",
        "anchor_gcj02": [117.0, 36.0],
        "homography_pixel_to_enu": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "registration_pose": {},
        "camera_calibration": {},
        "coverage_enu_m": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [60, 0], [60, 40], [0, 40], [0, 0]]],
        },
        "checksum": "fixture",
    }


def test_explicit_source_geo_registration_loads_without_runtime_map(monkeypatch):
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-1")
    monkeypatch.setenv(
        "RUNTIME_GEO_REGISTRATION_JSON", json.dumps(_registration())
    )
    monkeypatch.delenv("RUNTIME_MAP_BUNDLE_JSON", raising=False)

    registration = load_runtime_geo_registration({})
    node = HomographyCalibrationNode({"calibration": {"mode": "auto"}})
    frame = FrameElement("video.mp4", np.zeros((40, 60, 3)), 0.0, 0, {})
    result = node.process(frame)

    assert registration["id"] == "SGR-1"
    assert result.calibration_mode == "runtime_geo"
    assert result.runtime_geo_registration["source_profile_id"] == "SRC-1"
    assert result.runtime_map_bundle is None
    assert result.map_version_id is None
    np.testing.assert_allclose(result.homography_matrix, np.eye(3))
    assert result.anchor_gcj02 == (117.0, 36.0)
    assert result.runtime_geo_registration["coverage_enu_m"] == (
        result.runtime_geo_registration["map_coverage_enu_m"]
    )


def test_legacy_runtime_map_selects_exact_source_as_independent_geo_registration(
    monkeypatch,
):
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-2")
    monkeypatch.delenv("RUNTIME_GEO_REGISTRATION_JSON", raising=False)
    bundle = {
        "map_status": "lane_verified",
        "coordinate_system": "GCJ02",
        "coordinate_transform_version": "wgs84-gcj02/v1",
        "anchor_gcj02": [117.0, 36.0],
        "map_coverage_enu_m": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [60, 0], [60, 40], [0, 40], [0, 0]]],
        },
        "visual_registrations": [
            {
                "source_profile_id": "SRC-1",
                "status": "verified",
                "homography_pixel_to_enu": [[1, 0, 1], [0, 1, 1], [0, 0, 1]],
            },
            {
                "source_profile_id": "SRC-2",
                "status": "verified",
                "homography_pixel_to_enu": [[2, 0, 2], [0, 2, 2], [0, 0, 1]],
            },
        ],
    }

    registration = load_runtime_geo_registration({}, runtime_map_bundle=bundle)

    assert registration["source_profile_id"] == "SRC-2"
    assert registration["homography_pixel_to_enu"] == [
        [2.0, 0.0, 2.0],
        [0.0, 2.0, 2.0],
        [0.0, 0.0, 1.0],
    ]
    assert registration["coverage_enu_m"] == bundle["map_coverage_enu_m"]


def test_legacy_runtime_map_does_not_guess_registration_for_another_source(
    monkeypatch,
):
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-MISSING")
    monkeypatch.delenv("RUNTIME_GEO_REGISTRATION_JSON", raising=False)
    bundle = {
        "map_status": "lane_verified",
        "coordinate_system": "GCJ02",
        "coordinate_transform_version": "wgs84-gcj02/v1",
        "anchor_gcj02": [117.0, 36.0],
        "visual_registrations": [_registration("SRC-1")],
    }

    assert load_runtime_geo_registration({}, runtime_map_bundle=bundle) is None
