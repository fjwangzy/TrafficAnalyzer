"""GCP（地面控制点）校验与单应性矩阵修正。

提供:
- GCP 点管理与加载
- H 矩阵精度验证（计算残差）
- 基于 GCP 的 H 矩阵仿射修正
- 精度报告输出

用法：
  在 HomographyCalibrationNode 中，遥测/参考点计算出 H 后，
  用 GCP 点验证并修正，消除系统性偏移。
"""

import math
import numpy as np
import cv2
import logging

from utils_local.homography import pixel_to_world

logger = logging.getLogger(__name__)


class GCPPoint:
    """单个地面控制点。"""

    __slots__ = ("pixel_x", "pixel_y", "world_x", "world_y", "label")

    def __init__(
        self,
        pixel_x: float,
        pixel_y: float,
        world_x: float,
        world_y: float,
        label: str = "",
    ):
        self.pixel_x = pixel_x
        self.pixel_y = pixel_y
        self.world_x = world_x
        self.world_y = world_y
        self.label = label

    def __repr__(self) -> str:
        return (
            f"GCP({self.label}: px=({self.pixel_x:.0f},{self.pixel_y:.0f}) "
            f"→ world=({self.world_x:.2f},{self.world_y:.2f}))"
        )


class GCPRefinement:
    """GCP 点管理与 H 矩阵修正。

    支持两种修正模式:
    - affine: 用 GCP 点估算一个仿射变换修正 H 的输出（最少 3 个 GCP）
    - rigid: 用 GCP 点估算一个刚体变换（旋转+平移）修正（最少 2 个 GCP）

    用法:
        refiner = GCPRefinement(gcp_config_list)
        H_corrected = refiner.refine(H_raw)
        report = refiner.compute_residuals(H_corrected)
    """

    def __init__(
        self,
        gcp_points: list[dict | list] | None = None,
        mode: str = "affine",
        max_residual_m: float = 5.0,
    ):
        """
        Args:
            gcp_points: GCP 点列表，每项为:
                - dict: {pixel_x, pixel_y, world_x, world_y, label?}
                - list: [pixel_x, pixel_y, world_x, world_y] 或
                         [pixel_x, pixel_y, world_x, world_y, "label"]
            mode: "affine" 或 "rigid"
            max_residual_m: 单个 GCP 残差超过此值则标记为异常
        """
        self.mode = mode
        self.max_residual_m = max_residual_m
        self.gcps: list[GCPPoint] = []
        self._correction_matrix: np.ndarray | None = None

        if gcp_points:
            for item in gcp_points:
                self._add_point(item)

        if self.gcps:
            logger.info(
                f"GCPRefinement: 加载了 {len(self.gcps)} 个 GCP 点, 模式={mode}"
            )

    def _add_point(self, item: dict | list) -> None:
        """解析并添加一个 GCP 点。"""
        if isinstance(item, dict):
            gcp = GCPPoint(
                pixel_x=float(item["pixel_x"]),
                pixel_y=float(item["pixel_y"]),
                world_x=float(item["world_x"]),
                world_y=float(item["world_y"]),
                label=str(item.get("label", f"GCP-{len(self.gcps) + 1}")),
            )
        elif isinstance(item, (list, tuple)):
            gcp = GCPPoint(
                pixel_x=float(item[0]),
                pixel_y=float(item[1]),
                world_x=float(item[2]),
                world_y=float(item[3]),
                label=str(item[4]) if len(item) > 4 else f"GCP-{len(self.gcps) + 1}",
            )
        else:
            raise ValueError(f"不支持的 GCP 格式: {type(item)}")
        self.gcps.append(gcp)

    @property
    def has_enough_points(self) -> bool:
        """是否有足够的 GCP 点进行修正。"""
        if self.mode == "affine":
            return len(self.gcps) >= 3
        return len(self.gcps) >= 2  # rigid

    @property
    def point_count(self) -> int:
        return len(self.gcps)

    def compute_residuals(self, H: np.ndarray) -> dict:
        """计算 H 矩阵在 GCP 点上的残差。

        Args:
            H: 3x3 单应性矩阵（像素→世界）

        Returns:
            {
                "residuals": [{label, predicted, actual, error_m, error_x, error_y}, ...],
                "rmse_m": float,  # 均方根误差（米）
                "max_error_m": float,
                "mean_error_m": float,
                "outliers": [label, ...],  # 超过 max_residual_m 的点
            }
        """
        if not self.gcps:
            return {"residuals": [], "rmse_m": 0.0, "max_error_m": 0.0,
                    "mean_error_m": 0.0, "outliers": []}

        pixel_pts = np.array(
            [[g.pixel_x, g.pixel_y] for g in self.gcps], dtype=np.float64
        )
        predicted = pixel_to_world(pixel_pts, H)
        actual = np.array(
            [[g.world_x, g.world_y] for g in self.gcps], dtype=np.float64
        )

        errors = predicted - actual
        distances = np.sqrt(errors[:, 0] ** 2 + errors[:, 1] ** 2)

        residuals = []
        outliers = []
        for i, gcp in enumerate(self.gcps):
            r = {
                "label": gcp.label,
                "predicted": [float(predicted[i, 0]), float(predicted[i, 1])],
                "actual": [float(actual[i, 0]), float(actual[i, 1])],
                "error_x": float(errors[i, 0]),
                "error_y": float(errors[i, 1]),
                "error_m": float(distances[i]),
            }
            residuals.append(r)
            if distances[i] > self.max_residual_m:
                outliers.append(gcp.label)

        rmse = float(np.sqrt(np.mean(distances ** 2)))
        return {
            "residuals": residuals,
            "rmse_m": rmse,
            "max_error_m": float(np.max(distances)),
            "mean_error_m": float(np.mean(distances)),
            "outliers": outliers,
        }

    def refine(self, H: np.ndarray) -> np.ndarray:
        """用 GCP 点修正 H 矩阵。

        修正策略：
        1. 用当前 H 将 GCP 像素坐标投影到世界坐标（预测值）
        2. 计算预测值→真实世界坐标的变换（仿射/刚体）
        3. 将修正变换叠加到 H 上

        Args:
            H: 原始 3x3 单应性矩阵

        Returns:
            修正后的 3x3 单应性矩阵。
            如果 GCP 不足或修正失败，返回原始 H。
        """
        if not self.has_enough_points:
            logger.warning(
                f"GCPRefinement: GCP 点不足（{len(self.gcps)} 个），"
                f"需要至少 {'3' if self.mode == 'affine' else '2'} 个，跳过修正"
            )
            return H

        # 用当前 H 投影 GCP 像素坐标到世界坐标
        pixel_pts = np.array(
            [[g.pixel_x, g.pixel_y] for g in self.gcps], dtype=np.float64
        )
        predicted = pixel_to_world(pixel_pts, H)

        actual = np.array(
            [[g.world_x, g.world_y] for g in self.gcps], dtype=np.float64
        )

        # 先计算修正前残差
        pre_errors = np.sqrt(
            (predicted[:, 0] - actual[:, 0]) ** 2
            + (predicted[:, 1] - actual[:, 1]) ** 2
        )
        pre_rmse = float(np.sqrt(np.mean(pre_errors ** 2)))

        # 估算修正变换: predicted → actual
        if self.mode == "affine" and len(self.gcps) >= 3:
            # 仿射变换（6 自由度：缩放 + 旋转 + 平移 + 剪切）
            M, inliers = cv2.estimateAffine2D(
                predicted.reshape(-1, 1, 2).astype(np.float32),
                actual.reshape(-1, 1, 2).astype(np.float32),
                method=cv2.LMEDS,
            )
            if M is None:
                logger.warning("GCPRefinement: 仿射变换估算失败，跳过修正")
                return H
            # M 是 2x3，扩展为 3x3
            correction = np.eye(3, dtype=np.float64)
            correction[:2, :] = M.astype(np.float64)
        else:
            # 刚体变换（4 自由度：缩放 + 旋转 + 平移）
            M, inliers = cv2.estimateAffinePartial2D(
                predicted.reshape(-1, 1, 2).astype(np.float32),
                actual.reshape(-1, 1, 2).astype(np.float32),
                method=cv2.LMEDS,
            )
            if M is None:
                logger.warning("GCPRefinement: 刚体变换估算失败，跳过修正")
                return H
            correction = np.eye(3, dtype=np.float64)
            correction[:2, :] = M.astype(np.float64)

        # 叠加修正: H_new = correction @ H
        H_refined = correction @ H

        # 缓存修正矩阵（供日志和调试）
        self._correction_matrix = correction

        # 计算修正后残差
        post_report = self.compute_residuals(H_refined)

        # 安全检查：如果修正后反而变差，放弃修正
        if post_report["rmse_m"] > pre_rmse * 1.1:
            logger.warning(
                f"GCPRefinement: 修正后 RMSE ({post_report['rmse_m']:.3f}m) "
                f"> 修正前 ({pre_rmse:.3f}m)，放弃修正"
            )
            return H

        logger.info(
            f"GCPRefinement: H矩阵修正完成 — "
            f"RMSE: {pre_rmse:.3f}m → {post_report['rmse_m']:.3f}m, "
            f"max: {post_report['max_error_m']:.3f}m, "
            f"outliers: {post_report['outliers']}"
        )

        # 记录修正矩阵分解（供调试）
        _log_correction_decomposition(correction)

        return H_refined

    def get_pixel_points(self) -> np.ndarray:
        """返回所有 GCP 的像素坐标 Nx2。"""
        return np.array(
            [[g.pixel_x, g.pixel_y] for g in self.gcps], dtype=np.float64
        )

    def get_world_points(self) -> np.ndarray:
        """返回所有 GCP 的世界坐标 Nx2。"""
        return np.array(
            [[g.world_x, g.world_y] for g in self.gcps], dtype=np.float64
        )


def _log_correction_decomposition(correction: np.ndarray) -> None:
    """分解修正矩阵为可读的旋转/缩放/平移参数（调试用）。"""
    try:
        a, b = correction[0, 0], correction[0, 1]
        c, d = correction[1, 0], correction[1, 1]
        tx, ty = correction[0, 2], correction[1, 2]

        # 提取缩放
        sx = math.sqrt(a * a + c * c)
        sy = math.sqrt(b * b + d * d)

        # 提取旋转角度
        rotation_deg = math.degrees(math.atan2(c, a))

        logger.debug(
            f"GCPRefinement 修正分解: "
            f"平移=({tx:.3f}, {ty:.3f})m, "
            f"旋转={rotation_deg:.3f}°, "
            f"缩放=({sx:.4f}, {sy:.4f})"
        )
    except Exception:
        pass
