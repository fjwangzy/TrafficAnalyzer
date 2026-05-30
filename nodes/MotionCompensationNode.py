"""运动补偿节点：注入世界锚点、无人机位移、速度矢量到FrameElement。

位置：HomographyCalibrationNode之后，TrackerInfoUpdateNode之前。
仅在有遥测数据且标定模式为telemetry时生效；无遥测/reference_points模式时透传。

GPS锚定策略：首帧GPS为世界原点（或配置的anchor），后续帧通过GPS增量定位。
悬停自动跳过速度补偿，避免GPS抖动引入伪运动。
"""

import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.motion_compensation import (
    compute_drone_displacement,
    compute_drone_velocity_vector,
    is_hovering,
)

logger = logging.getLogger(__name__)


class MotionCompensationNode:
    """无人机运动补偿节点。

    注入FrameElement字段：
    - world_anchor_lat_lon: (lat, lon) 世界锚点
    - drone_displacement_m: [easting, northing] 无人机位移（米）
    - drone_velocity_ms: [v_east, v_north] 无人机速度（m/s）
    - gimbal_yaw_initial: 首帧云台偏航角（度）
    - gimbal_yaw_delta: 当前帧云台偏航 - 首帧（度）
    - is_hovering: 是否悬停
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("motion_compensation", {})
        self.enabled = cfg.get("enabled", True)
        self.hover_threshold_ms = cfg.get("hover_threshold_ms", 1.0)

        # 可选手动指定世界锚点
        manual_anchor = cfg.get("world_anchor", None)
        self._manual_anchor = tuple(manual_anchor) if manual_anchor else None

        self._world_anchor: tuple[float, float] | None = None  # (lat, lon)
        self._gimbal_yaw_initial: float | None = None
        self._anchor_samples: list[tuple[float, float]] = []  # GPS采样（取均值）
        self._anchor_sample_count = 10  # 前N帧取GPS均值
        self._logged_init = False
        self._last_displacement: np.ndarray | None = None  # GPS丢失时的回退值

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        telemetry = getattr(frame_element, "telemetry", None)
        if not telemetry:
            return frame_element

        # 仅telemetry标定模式时启用运动补偿
        if frame_element.calibration_mode != "telemetry":
            return frame_element

        # 手动锚点优先
        if self._manual_anchor and self._world_anchor is None:
            self._world_anchor = self._manual_anchor
            self._gimbal_yaw_initial = telemetry.get("gimbal_yaw", 0)
            logger.info(
                f"MotionCompensation: 使用手动世界锚点 = "
                f"({self._world_anchor[0]:.6f}, {self._world_anchor[1]:.6f})"
            )

        # 自动锚点：取前N帧GPS均值
        if self._world_anchor is None and self._manual_anchor is None:
            lat = telemetry.get("latitude")
            lon = telemetry.get("longitude")
            if lat is not None and lon is not None:
                self._anchor_samples.append((lat, lon))
                if len(self._anchor_samples) >= self._anchor_sample_count:
                    avg_lat = sum(s[0] for s in self._anchor_samples) / len(self._anchor_samples)
                    avg_lon = sum(s[1] for s in self._anchor_samples) / len(self._anchor_samples)
                    self._world_anchor = (avg_lat, avg_lon)
                    self._gimbal_yaw_initial = telemetry.get("gimbal_yaw", 0)
                    if not self._logged_init:
                        logger.info(
                            f"MotionCompensation: 世界锚点(GPS均值) = "
                            f"({avg_lat:.6f}, {avg_lon:.6f}), "
                            f"gimbal_yaw_initial = {self._gimbal_yaw_initial:.1f}°"
                        )
                        self._logged_init = True
                return frame_element  # 锚点未就绪，跳过补偿

        if self._world_anchor is None:
            return frame_element

        # 计算无人机世界位移（GPS增量），GPS丢失时保持上次值
        drone_disp = compute_drone_displacement(telemetry, *self._world_anchor)
        if telemetry.get("latitude") is not None and telemetry.get("longitude") is not None:
            self._last_displacement = drone_disp.copy()
        elif self._last_displacement is not None:
            drone_disp = self._last_displacement
            logger.debug("MotionCompensation: GPS丢失，使用上次位移")

        # 计算无人机速度矢量（m/s，东北坐标系）
        drone_vel = compute_drone_velocity_vector(telemetry)

        # 悬停检测
        hovering = is_hovering(telemetry, self.hover_threshold_ms)
        if hovering:
            drone_vel = np.zeros(2, dtype=np.float64)

        # 云台偏航增量（归一化到[-180, 180]避免±180°跳变）
        gimbal_yaw = telemetry.get("gimbal_yaw", 0) or 0
        yaw_delta = gimbal_yaw - (self._gimbal_yaw_initial or 0)
        while yaw_delta > 180:
            yaw_delta -= 360
        while yaw_delta < -180:
            yaw_delta += 360

        # 注入FrameElement
        frame_element.world_anchor_lat_lon = self._world_anchor
        frame_element.drone_displacement_m = drone_disp
        frame_element.drone_velocity_ms = drone_vel
        frame_element.gimbal_yaw_delta = yaw_delta
        frame_element.gimbal_yaw_initial = self._gimbal_yaw_initial
        frame_element.is_hovering = hovering

        return frame_element
