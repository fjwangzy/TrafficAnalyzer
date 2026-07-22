import math
from pathlib import Path

import numpy as np
from utils_local.coordinates import enu_to_gcj02

from app.services.survey_capture import parse_dji_json, parse_dji_srt
from app.services.survey_geometry import (
    align_homography_to_map_enu,
    calculate_measurement,
    compute_homography_from_telemetry,
)
from app.services.survey_storage import ContentAddressedStore, resolve_allowlisted_asset


def test_nadir_homography_centers_enu_and_scales_metric_distance():
    matrix = compute_homography_from_telemetry(
        {"altitude_agl": 100, "gimbal_pitch": -90, "gimbal_yaw": 0},
        (1000, 500),
    )
    assert matrix is not None
    metric, values = calculate_measurement("line", [[500, 250], [600, 250]], matrix)
    assert np.allclose(metric[0], [0, 0], atol=1e-6)
    assert math.isclose(values["length_m"], 14.2222, abs_tol=1e-4)


def test_frame_local_homography_is_translated_into_the_channelized_map_enu_frame():
    anchor = [117.028285, 36.703222]
    longitude, latitude = enu_to_gcj02(12, -8, anchor)

    aligned = align_homography_to_map_enu(
        np.eye(3),
        {"position_gcj02": {"longitude": longitude, "latitude": latitude}},
        anchor,
    )

    assert np.allclose(aligned, [[1, 0, 12], [0, 1, -8], [0, 0, 1]], atol=1e-6)


def test_polygon_measurement_returns_area_and_perimeter():
    metric, values = calculate_measurement(
        "area",
        [[0, 0], [4, 0], [4, 3], [0, 3]],
        np.eye(3),
    )
    assert metric == [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]
    assert values == {"area_m2": 12.0, "perimeter_m": 14.0}


def test_real_inter_xqh_srt_is_parseable():
    path = Path(__file__).resolve().parents[2] / "test_videos" / "inter_xqh" / "telemetry.srt"
    records = parse_dji_srt(path)
    assert len(records) == 29_741
    assert records[0]["altitude_agl"] > 50
    assert -90 <= records[0]["gimbal_pitch"] <= 0


def test_content_addressed_evidence_verification_detects_tampering(tmp_path):
    store = ContentAddressedStore(str(tmp_path))
    stored = store.ingest_bytes(b"survey-evidence")

    assert store.verify(stored.storage_key, stored.sha256, stored.size_bytes)

    stored.path.chmod(0o640)
    stored.path.write_bytes(b"tampered")
    assert not store.verify(stored.storage_key, stored.sha256, stored.size_bytes)


def test_real_mp4new_dji_cloud_txt_is_parseable():
    path = (
        Path(__file__).resolve().parents[2]
        / "test_videos/mp4new/srt/解放东路-海右路0625早高峰 srt文件.txt"
    )
    records = parse_dji_json(path)
    assert records
    assert records[0]["timestamp"] == 0
    assert records[0]["altitude_agl"] > 50
    assert -90 <= records[0]["gimbal_pitch"] <= 0


def test_server_asset_reference_hashes_without_copying(tmp_path):
    source_root = tmp_path / "source"
    store_root = tmp_path / "store"
    source_root.mkdir()
    source = source_root / "capture.mp4"
    source.write_bytes(b"original-video")
    store = ContentAddressedStore(str(store_root))

    stored = store.reference_path(source, "capture.mp4")

    assert stored.storage_backend == "server_asset"
    assert stored.path == source
    assert stored.storage_key == "capture.mp4"
    assert list((store_root / "objects").iterdir()) == []


def test_allowlisted_asset_rejects_path_traversal(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"outside")
    try:
        resolve_allowlisted_asset("../outside.mp4", [str(root)], tmp_path)
    except ValueError as exc:
        assert "outside configured survey roots" in str(exc)
    else:
        raise AssertionError("path traversal was accepted")
