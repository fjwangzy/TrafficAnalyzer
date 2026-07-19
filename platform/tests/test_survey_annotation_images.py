from types import SimpleNamespace

import cv2
import numpy as np

from app.services.survey_service import SurveyService, _frame_dict


def _frame() -> SimpleNamespace:
    return SimpleNamespace(
        id="FRM-ANNOTATED",
        task_id="SVY-HISTORY",
        batch_id="BATCH-01",
        frame_number=42,
        timestamp_sec=1.25,
        image_width=320,
        image_height=180,
        homography=[[0.1, 0, -2], [0, -0.1, 5], [0, 0, 1]],
        view_transform=[[2, 0, 10], [0, 2, 20], [0, 0, 1]],
        telemetry={},
        quality={},
        selected=True,
        image_evidence_id="EVI-IMAGE",
        bev_evidence_id="EVI-BEV",
    )


def test_frame_contract_exposes_bev_to_metric_transform_for_live_distance() -> None:
    payload = _frame_dict(_frame())

    assert np.allclose(
        payload["metric_transform"],
        [[0.05, 0, -2.5], [0, -0.05, 6], [0, 0, 1]],
    )


def test_annotated_bev_draws_measurement_edges_and_distance_labels() -> None:
    source = np.full((180, 320, 3), 24, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", source)
    assert ok
    measurements = [
        {
            "id": "M-01",
            "geometry_type": "line",
            "image_geometry": [[40, 60], [260, 120]],
            "metric_geometry": [[0, 0], [12.48, 0]],
            "display_value": "12.48m",
        }
    ]

    rendered = SurveyService._annotated_bev(encoded.tobytes(), measurements)
    image = cv2.imdecode(np.frombuffer(rendered, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert image is not None
    assert image.shape[:2] == source.shape[:2]
    assert np.count_nonzero(cv2.absdiff(image, source) > 32) > 200


def test_pdf_contains_the_annotated_image() -> None:
    source = np.full((180, 320, 3), 180, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", source)
    assert ok
    payload = {
        "task": {"id": "SVY-HISTORY", "location": "测试路口", "version": "v7", "quality": "unverified"},
        "generated_at": "2026-07-17T10:00:00+08:00",
        "measurements": [
            {"id": "M-01", "category": "刹车痕迹", "geometry_type": "line", "display_value": "12.48m", "quality_status": "unverified"}
        ],
    }

    pdf = SurveyService._report_pdf(payload, [encoded.tobytes()])

    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" in pdf
