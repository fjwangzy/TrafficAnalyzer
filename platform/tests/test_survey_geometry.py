import math
from pathlib import Path

import numpy as np

from app.services.survey_capture import parse_dji_srt
from app.services.survey_geometry import calculate_measurement, compute_homography_from_telemetry
from app.services.survey_storage import ContentAddressedStore


def test_nadir_homography_centers_enu_and_scales_metric_distance():
    matrix = compute_homography_from_telemetry(
        {"altitude_agl": 100, "gimbal_pitch": -90, "gimbal_yaw": 0},
        (1000, 500),
    )
    assert matrix is not None
    metric, values = calculate_measurement("line", [[500, 250], [600, 250]], matrix)
    assert np.allclose(metric[0], [0, 0], atol=1e-6)
    assert math.isclose(values["length_m"], 14.2222, abs_tol=1e-4)


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
    assert records[0]["altitude_agl"] > 100
    assert records[0]["gimbal_pitch"] == -90


def test_content_addressed_evidence_verification_detects_tampering(tmp_path):
    store = ContentAddressedStore(str(tmp_path))
    stored = store.ingest_bytes(b"survey-evidence")

    assert store.verify(stored.storage_key, stored.sha256, stored.size_bytes)

    stored.path.chmod(0o640)
    stored.path.write_bytes(b"tampered")
    assert not store.verify(stored.storage_key, stored.sha256, stored.size_bytes)
