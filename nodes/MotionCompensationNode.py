"""运动补偿节点：注入 GCJ-02 锚点、无人机位移、速度矢量到 FrameElement。

位置：HomographyCalibrationNode之后，TrackerInfoUpdateNode之前。
runtime_map 模式使用已验证影像配准时刻作为位移零点；telemetry 模式保留首帧锚定策略。

GPS锚定策略：首帧 GCJ-02 位置为 ENU 原点（或配置的 anchor），后续帧通过 GPS 增量定位。
悬停自动跳过速度补偿，避免GPS抖动引入伪运动。
"""

import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.motion_compensation import (
    compute_drone_velocity_vector,
    is_hovering,
)
from utils_local.coordinates import gcj02_to_enu, normalize_telemetry_position

logger = logging.getLogger(__name__)


class MotionCompensationNode:
    """无人机运动补偿节点。

    注入FrameElement字段：
    - anchor_gcj02: (longitude, latitude) canonical GCJ-02 anchor
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

        # 可选手动指定 GCJ-02 锚点
        manual_anchor = cfg.get("anchor_gcj02", None)
        self._manual_anchor = tuple(manual_anchor) if manual_anchor else None

        self._anchor_gcj02: tuple[float, float] | None = None  # (longitude, latitude)
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

        telemetry = normalize_telemetry_position(getattr(frame_element, "telemetry", None))
        if telemetry:
            frame_element.telemetry = telemetry

        if frame_element.calibration_mode == "runtime_map":
            bundle = getattr(frame_element, "runtime_map_bundle", None) or {}
            registration = getattr(frame_element, "runtime_visual_registration", None) or {}
            anchor = bundle.get("anchor_gcj02")
            if not anchor:
                raise ValueError("runtime_map frame is missing anchor_gcj02")
            residuals = registration.get("residuals") or {}
            registration_pose = registration.get("registration_pose") or {}
            reference = registration_pose.get("position_gcj02") or residuals.get(
                "registration_position_gcj02"
            )
            if not isinstance(reference, (list, tuple)) or len(reference) != 2:
                raise ValueError(
                    "runtime visual registration is missing registration_position_gcj02"
                )
            frame_element.anchor_gcj02 = tuple(anchor)
            position = (telemetry or {}).get("position_gcj02") or {}
            if position.get("longitude") is not None and position.get("latitude") is not None:
                drone_disp = np.asarray(
                    gcj02_to_enu(
                        position["longitude"], position["latitude"], reference
                    ),
                    dtype=np.float64,
                )
                self._last_displacement = drone_disp.copy()
            elif self._last_displacement is not None:
                drone_disp = self._last_displacement
            else:
                drone_disp = np.zeros(2, dtype=np.float64)

            drone_vel = compute_drone_velocity_vector(telemetry or {})
            hovering = is_hovering(telemetry or {}, self.hover_threshold_ms)
            if hovering:
                drone_vel = np.zeros(2, dtype=np.float64)
            reference_yaw = registration_pose.get("gimbal_yaw")
            if reference_yaw is None:
                reference_yaw = residuals.get("registration_gimbal_yaw_deg")
            if reference_yaw is None:
                reference_yaw = (telemetry or {}).get("gimbal_yaw", 0) or 0
            gimbal_yaw = (telemetry or {}).get("gimbal_yaw", reference_yaw) or reference_yaw
            yaw_delta = float(gimbal_yaw) - float(reference_yaw)
            while yaw_delta > 180:
                yaw_delta -= 360
            while yaw_delta < -180:
                yaw_delta += 360
            frame_element.drone_displacement_m = drone_disp
            frame_element.drone_velocity_ms = drone_vel
            frame_element.gimbal_yaw_initial = float(reference_yaw)
            frame_element.gimbal_yaw_delta = yaw_delta
            frame_element.is_hovering = hovering
            return frame_element

        if not telemetry:
            return frame_element

        # 仅 telemetry 标定模式使用自动/手动锚点策略。
        if frame_element.calibration_mode != "telemetry":
            return frame_element

        # 手动锚点优先
        if self._manual_anchor and self._anchor_gcj02 is None:
            self._anchor_gcj02 = self._manual_anchor
            self._gimbal_yaw_initial = telemetry.get("gimbal_yaw", 0)
            logger.info(
                f"MotionCompensation: 使用手动 GCJ-02 锚点 = "
                f"({self._anchor_gcj02[0]:.6f}, {self._anchor_gcj02[1]:.6f})"
            )

        # 自动锚点：取前N帧GPS均值
        if self._anchor_gcj02 is None and self._manual_anchor is None:
            position = telemetry.get("position_gcj02") or {}
            lon = position.get("longitude")
            lat = position.get("latitude")
            if lat is not None and lon is not None:
                self._anchor_samples.append((lon, lat))
                if len(self._anchor_samples) >= self._anchor_sample_count:
                    avg_lon = sum(s[0] for s in self._anchor_samples) / len(self._anchor_samples)
                    avg_lat = sum(s[1] for s in self._anchor_samples) / len(self._anchor_samples)
                    self._anchor_gcj02 = (avg_lon, avg_lat)
                    self._gimbal_yaw_initial = telemetry.get("gimbal_yaw", 0)
                    if not self._logged_init:
                        logger.info(
                            f"MotionCompensation: GCJ-02 锚点(GPS均值) = "
                            f"({avg_lon:.6f}, {avg_lat:.6f}), "
                            f"gimbal_yaw_initial = {self._gimbal_yaw_initial:.1f}°"
                        )
                        self._logged_init = True
                return frame_element  # 锚点未就绪，跳过补偿

        if self._anchor_gcj02 is None:
            return frame_element

        # 计算无人机 ENU 位移（GPS 增量），GPS 丢失时保持上次值
        position = telemetry.get("position_gcj02") or {}
        if position.get("longitude") is not None and position.get("latitude") is not None:
            drone_disp = np.asarray(
                gcj02_to_enu(position["longitude"], position["latitude"], self._anchor_gcj02),
                dtype=np.float64,
            )
            self._last_displacement = drone_disp.copy()
        elif self._last_displacement is not None:
            drone_disp = self._last_displacement
            logger.debug("MotionCompensation: GPS丢失，使用上次位移")
        else:
            drone_disp = np.zeros(2, dtype=np.float64)

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
        frame_element.anchor_gcj02 = self._anchor_gcj02
        frame_element.drone_displacement_m = drone_disp
        frame_element.drone_velocity_ms = drone_vel
        frame_element.gimbal_yaw_delta = yaw_delta
        frame_element.gimbal_yaw_initial = self._gimbal_yaw_initial
        frame_element.is_hovering = hovering

        return frame_element
