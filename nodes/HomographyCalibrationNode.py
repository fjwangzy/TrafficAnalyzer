import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import (
    compute_homography_from_telemetry,
    compute_homography_from_reference_points,
    is_valid_homography,
    undistort_points,
)
from utils_local.gcp_refinement import GCPRefinement

logger = logging.getLogger(__name__)


class HomographyCalibrationNode:
    """根据遥测数据或配置参考点，计算并注入单应性矩阵到 FrameElement。

    三种模式：
    - auto: 有遥测数据用遥测，否则回退到参考点
    - telemetry: 仅使用遥测数据
    - reference_points: 仅使用配置中的参考点

    增强功能：
    - 镜头畸变校正：配置 dist_coeffs 后，对像素坐标自动去畸变
    - GCP修正：配置 gcp_points 后，用地面控制点修正H矩阵的系统性偏移
    """

    def __init__(self, config: dict) -> None:
        cal = config.get("calibration", {})
        self.mode = cal.get("mode", "auto")
        self.camera_intrinsics = cal.get("camera_intrinsics", {})
        self.reference_points = cal.get("reference_points", [])
        self._static_H: np.ndarray | None = None
        self._logged_no_calibration = False

        # ── 镜头畸变系数 [k1, k2, p1, p2, k3]（可选）──
        self.dist_coeffs = cal.get("dist_coeffs", None)
        if self.dist_coeffs:
            # 将 Hydra ListConfig 等转为普通 list
            self.dist_coeffs = [float(c) for c in self.dist_coeffs]
            logger.info(
                f"HomographyCalibrationNode: 启用镜头畸变校正, "
                f"coeffs={self.dist_coeffs}"
            )

        # ── GCP 修正（可选）──
        gcp_config = cal.get("gcp", {})
        gcp_points = gcp_config.get("points", [])
        gcp_mode = gcp_config.get("mode", "rigid")
        gcp_max_residual = gcp_config.get("max_residual_m", 5.0)

        self._gcp_refiner: GCPRefinement | None = None
        if gcp_points:
            self._gcp_refiner = GCPRefinement(
                gcp_points=gcp_points,
                mode=gcp_mode,
                max_residual_m=gcp_max_residual,
            )
            if self._gcp_refiner.has_enough_points:
                logger.info(
                    f"HomographyCalibrationNode: GCP修正启用, "
                    f"{self._gcp_refiner.point_count} 个控制点, "
                    f"模式={gcp_mode}"
                )
            else:
                logger.warning(
                    f"HomographyCalibrationNode: GCP点不足 "
                    f"({self._gcp_refiner.point_count} 个)，需要至少 "
                    f"{'3' if gcp_mode == 'affine' else '2'} 个"
                )

        # 预计算静态H（reference_points模式或auto回退）
        if self.reference_points and len(self.reference_points) >= 4:
            self._static_H = compute_homography_from_reference_points(self.reference_points)
            if self._static_H is not None:
                logger.info("HomographyCalibrationNode: 从参考点预计算H矩阵成功")
                # 对静态H也做GCP修正
                self._static_H = self._apply_gcp_refinement(self._static_H)

        # ── GCP残差日志标记 ──
        self._logged_gcp_report = False

    def _apply_gcp_refinement(self, H: np.ndarray) -> np.ndarray:
        """如果配置了GCP，对H矩阵做修正并返回修正后的H。"""
        if self._gcp_refiner and self._gcp_refiner.has_enough_points:
            return self._gcp_refiner.refine(H)
        return H

    def _log_gcp_residuals(self, H: np.ndarray) -> None:
        """首次成功时输出GCP残差报告（仅一次）。"""
        if self._logged_gcp_report or not self._gcp_refiner:
            return
        self._logged_gcp_report = True

        report = self._gcp_refiner.compute_residuals(H)
        logger.info(
            f"HomographyCalibrationNode GCP残差报告: "
            f"RMSE={report['rmse_m']:.3f}m, "
            f"max={report['max_error_m']:.3f}m, "
            f"mean={report['mean_error_m']:.3f}m"
        )
        for r in report["residuals"]:
            logger.info(
                f"  {r['label']}: 误差={r['error_m']:.3f}m "
                f"(dx={r['error_x']:.3f}m, dy={r['error_y']:.3f}m)"
            )

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
                # GCP修正（对每帧telemetry H进行修正）
                if is_valid_homography(frame_element.homography_matrix):
                    frame_element.homography_matrix = self._apply_gcp_refinement(
                        frame_element.homography_matrix
                    )
                    self._log_gcp_residuals(frame_element.homography_matrix)
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
                # GCP修正
                if is_valid_homography(frame_element.homography_matrix):
                    frame_element.homography_matrix = self._apply_gcp_refinement(
                        frame_element.homography_matrix
                    )
                    self._log_gcp_residuals(frame_element.homography_matrix)

        elif self.mode == "reference_points":
            frame_element.homography_matrix = self._static_H
            frame_element.calibration_mode = (
                "reference_points" if is_valid_homography(self._static_H) else None
            )

        # 注入畸变系数到 frame_element（供下游 pixel_to_world 使用前去畸变）
        if self.dist_coeffs:
            frame_element.dist_coeffs = self.dist_coeffs
            frame_element.camera_intrinsics = self.camera_intrinsics

        # 仅提示一次（避免日志风暴）
        if frame_element.homography_matrix is None and not self._logged_no_calibration:
            logger.warning(
                "HomographyCalibrationNode: 无可用标定数据，车速将以像素/秒为单位输出"
            )
            self._logged_no_calibration = True

        return frame_element
