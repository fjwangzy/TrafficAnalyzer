import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import (
    compute_homography_from_telemetry,
    compute_homography_from_reference_points,
    is_valid_homography,
)

logger = logging.getLogger(__name__)


class HomographyCalibrationNode:
    """根据遥测数据或配置参考点，计算并注入单应性矩阵到 FrameElement。

    三种模式：
    - auto: 有遥测数据用遥测，否则回退到参考点
    - telemetry: 仅使用遥测数据
    - reference_points: 仅使用配置中的参考点
    """

    def __init__(self, config: dict) -> None:
        cal = config.get("calibration", {})
        self.mode = cal.get("mode", "auto")
        self.camera_intrinsics = cal.get("camera_intrinsics", {})
        self.reference_points = cal.get("reference_points", [])
        self._static_H: np.ndarray | None = None
        self._logged_no_calibration = False

        # 预计算静态H（reference_points模式或auto回退）
        if self.reference_points and len(self.reference_points) >= 4:
            self._static_H = compute_homography_from_reference_points(self.reference_points)
            if self._static_H is not None:
                logger.info("HomographyCalibrationNode: 从参考点预计算H矩阵成功")

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        telemetry = getattr(frame_element, "telemetry", None)

        if self.mode == "auto":
            if telemetry and telemetry.get("altitude_agl", 0) > 0 and self.camera_intrinsics:
                frame_element.homography_matrix = compute_homography_from_telemetry(
                    telemetry,
                    self.camera_intrinsics,
                    (frame_element.frame.shape[1], frame_element.frame.shape[0]),
                )
                frame_element.calibration_mode = "telemetry"
            else:
                frame_element.homography_matrix = self._static_H
                frame_element.calibration_mode = (
                    "reference_points" if is_valid_homography(self._static_H) else None
                )

        elif self.mode == "telemetry":
            if telemetry and telemetry.get("altitude_agl", 0) > 0 and self.camera_intrinsics:
                frame_element.homography_matrix = compute_homography_from_telemetry(
                    telemetry,
                    self.camera_intrinsics,
                    (frame_element.frame.shape[1], frame_element.frame.shape[0]),
                )
                frame_element.calibration_mode = "telemetry"

        elif self.mode == "reference_points":
            frame_element.homography_matrix = self._static_H
            frame_element.calibration_mode = (
                "reference_points" if is_valid_homography(self._static_H) else None
            )

        # 仅提示一次（避免日志风暴）
        if frame_element.homography_matrix is None and not self._logged_no_calibration:
            logger.warning(
                "HomographyCalibrationNode: 无可用标定数据，车速将以像素/秒为单位输出"
            )
            self._logged_no_calibration = True

        return frame_element
