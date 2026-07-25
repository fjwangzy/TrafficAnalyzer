import cv2
import numpy as np

from elements.FrameElement import FrameElement
from nodes.ImageMotionEstimationNode import ImageMotionEstimationNode
from utils_local.image_motion import ImageMotionEstimator, ImageMotionObservation


def _textured_frame(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for x, y in rng.integers([12, 12], [308, 228], size=(120, 2)):
        cv2.circle(frame, (int(x), int(y)), 2, (255, 255, 255), thickness=-1)
    return frame


def test_background_image_motion_recovers_previous_to_current_warp():
    estimator = ImageMotionEstimator(
        visual_max_width=320,
        min_background_points=40,
        min_inlier_ratio=0.5,
        max_reprojection_p95_px=3.0,
    )
    previous = _textured_frame()
    expected = np.array(
        [[1.0, 0.0, 8.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    current = cv2.warpPerspective(previous, expected, (320, 240))

    bootstrap = estimator.observe(
        ImageMotionObservation(0.0, 0, previous, ())
    )
    result = estimator.observe(
        ImageMotionObservation(0.1, 1, current, ())
    )

    assert bootstrap.status == "bootstrap"
    assert bootstrap.previous_to_current_pixel_warp is None
    assert result.status == "verified"
    assert result.feature_count >= 40
    assert result.previous_to_current_pixel_warp is not None
    np.testing.assert_allclose(
        result.previous_to_current_pixel_warp,
        expected,
        atol=0.75,
    )


def test_pipeline_node_writes_only_visual_motion_to_tracking_warp():
    node = ImageMotionEstimationNode(
        {
            "geo_reference": {
                "visual_max_width": 320,
                "min_background_points": 40,
                "min_inlier_ratio": 0.5,
                "max_reprojection_p95_px": 3.0,
            },
            "tracking_node": {"max_frame_gap_sec": 0.5},
        }
    )
    previous = _textured_frame()
    expected = np.array(
        [[1.0, 0.0, -6.0], [0.0, 1.0, 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    current = cv2.warpPerspective(previous, expected, (320, 240))

    def frame(timestamp, number, image):
        return FrameElement(
            "video.mp4",
            image,
            timestamp,
            number,
            {},
            detected_conf=[],
            detected_cls=[],
            detected_cls_ids=[],
            detected_xyxy=[],
        )

    first = node.process(frame(0.0, 0, previous))
    second = node.process(frame(0.1, 1, current))

    assert first.visual_motion_quality["status"] == "bootstrap"
    assert first.camera_motion_warp is None
    assert second.visual_motion_quality["status"] == "verified"
    np.testing.assert_allclose(second.camera_motion_warp, expected, atol=0.75)
