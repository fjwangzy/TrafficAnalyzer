"""Pipeline adapter for image-only background camera-motion estimation."""

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.image_motion import ImageMotionEstimator, ImageMotionObservation
from utils_local.utils import profile_time


class ImageMotionEstimationNode:
    """Attach a visual previous-to-current warp without reading geographic state."""

    def __init__(self, config: dict) -> None:
        quality = config.get("geo_reference", {})
        tracking = config.get("tracking_node", {})
        self._estimator = ImageMotionEstimator(
            visual_max_width=quality.get("visual_max_width", 960),
            min_background_points=quality.get("min_background_points", 40),
            min_inlier_ratio=quality.get("min_inlier_ratio", 0.5),
            max_reprojection_p95_px=quality.get(
                "max_reprojection_p95_px", 3.0
            ),
            max_frame_gap_sec=tracking.get("max_frame_gap_sec", 0.5),
            forward_backward_max_error_px=quality.get(
                "forward_backward_max_error_px", 1.5
            ),
        )

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(frame_element, FrameElement), (
            "ImageMotionEstimationNode | invalid input "
            f"{type(frame_element)}"
        )
        boxes = tuple(
            tuple(float(value) for value in box[:4])
            for box in (frame_element.detected_xyxy or [])
            if len(box) >= 4
        )
        snapshot = self._estimator.observe(
            ImageMotionObservation(
                timestamp_sec=float(frame_element.timestamp),
                frame_num=int(frame_element.frame_num),
                frame_bgr=frame_element.frame,
                detected_xyxy=boxes,
            )
        )
        frame_element.camera_motion_warp = (
            snapshot.previous_to_current_pixel_warp.copy()
            if snapshot.usable_for_tracking
            else None
        )
        frame_element.visual_motion_quality = snapshot.quality_dict()
        return frame_element
