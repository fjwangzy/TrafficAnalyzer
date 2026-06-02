"""无人机运动补偿工具函数。

提供GPS锚定世界坐标系、无人机位移/速度计算、像素→世界坐标变换、
悬停检测、速度补偿和航向修正。

注(T-402): compensate_speed / compensate_heading / world_to_gps 三个函数
已被 SpeedEstimationNode 和 drone_store 的内联逻辑替代，标记为 deprecated。
保留以备外部工具或测试引用，不应在新代码中使用。
"""

import math
import warnings
import numpy as np
import logging

from utils_local.homography import pixel_to_world

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000


def gps_to_enu_meters(
    lat: float,
    lon: float,
    anchor_lat: float,
    anchor_lon: float,
) -> tuple[float, float]:
    """GPS坐标→东北偏移（米），简化平面近似。

    Args:
        lat, lon: 目标GPS坐标（度）
        anchor_lat, anchor_lon: 世界锚点GPS坐标（度）

    Returns:
        (easting_m, northing_m) 相对anchor的偏移
    """
    d_lat = lat - anchor_lat
    d_lon = lon - anchor_lon
    northing = math.radians(d_lat) * EARTH_RADIUS_M
    easting = math.radians(d_lon) * EARTH_RADIUS_M * math.cos(math.radians(anchor_lat))
    return easting, northing


def compute_drone_displacement(
    telemetry: dict,
    anchor_lat: float,
    anchor_lon: float,
) -> np.ndarray:
    """计算无人机相对世界锚点的东北偏移（米）。

    Args:
        telemetry: 当前帧遥测字典（含latitude, longitude）
        anchor_lat, anchor_lon: 世界锚点GPS坐标

    Returns:
        np.array([easting_m, northing_m])
    """
    lat = telemetry.get("latitude")
    lon = telemetry.get("longitude")
    if lat is None or lon is None:
        return np.zeros(2, dtype=np.float64)
    easting, northing = gps_to_enu_meters(lat, lon, anchor_lat, anchor_lon)
    return np.array([easting, northing], dtype=np.float64)


def compute_drone_velocity_vector(telemetry: dict) -> np.ndarray:
    """从遥测计算无人机速度矢量（m/s，东北坐标系）。

    使用 horizontal_speed（标量m/s）和 attitude_head（航向角，度，北=0，顺时针）。

    Returns:
        np.array([v_east, v_north]) m/s
    """
    speed_ms = telemetry.get("horizontal_speed", 0) or 0
    heading_deg = telemetry.get("attitude_head", 0) or 0
    heading_rad = math.radians(heading_deg)
    v_east = speed_ms * math.sin(heading_rad)
    v_north = speed_ms * math.cos(heading_rad)
    return np.array([v_east, v_north], dtype=np.float64)


def pixel_to_world_compensated(
    points_px: np.ndarray,
    H: np.ndarray,
    drone_displacement_m: np.ndarray,
) -> np.ndarray:
    """像素→世界坐标（含运动补偿）。

    变换链：像素 →[H⁻¹]→ 无人机相对(米) →[+drone_displacement]→ 世界坐标(米)

    Args:
        points_px: Nx2 像素坐标
        H: 3x3 单应性矩阵
        drone_displacement_m: [easting, northing] 无人机世界位移(m)

    Returns:
        Nx2 世界坐标（米，东北坐标系）
    """
    pts_drone = pixel_to_world(points_px, H)
    return pts_drone + drone_displacement_m


def is_hovering(telemetry: dict, threshold_ms: float = 1.0) -> bool:
    """检测无人机是否处于悬停状态。

    Args:
        telemetry: 遥测字典
        threshold_ms: 速度阈值（m/s），低于此值视为悬停

    Returns:
        True 如果无人机基本静止
    """
    return abs(telemetry.get("horizontal_speed", 0) or 0) < threshold_ms


def compensate_speed(
    apparent_speed_vector: np.ndarray,
    drone_velocity: np.ndarray,
) -> np.ndarray:
    """从表观速度中减去无人机速度，得到真实地面速度。

    .. deprecated:: T-402
        SpeedEstimationNode 已内联实现矢量减法。保留仅供测试引用。

    Args:
        apparent_speed_vector: [v_east, v_north] 表观速度(m/s, 世界坐标系)
        drone_velocity: [v_east, v_north] 无人机速度(m/s)

    Returns:
        [v_east, v_north] 真实地面速度(m/s)
    """
    warnings.warn(
        "compensate_speed is deprecated (T-402); use SpeedEstimationNode inline logic",
        DeprecationWarning, stacklevel=2,
    )
    return apparent_speed_vector - drone_velocity


def compensate_heading(
    heading_pixel_deg: float,
    gimbal_yaw_delta: float,
) -> float:
    """修正像素空间航向角，去除云台偏航旋转影响。

    .. deprecated:: T-402
        DirectionFlowNode 已内联实现 heading 修正。保留仅供测试引用。

    Args:
        heading_pixel_deg: 像素空间计算得到的航向（度）
        gimbal_yaw_delta: 当前云台偏航 - 首帧云台偏航（度）

    Returns:
        修正后的世界参考系航向角（度），归一化到[-180, 180]
    """
    warnings.warn(
        "compensate_heading is deprecated (T-402); use DirectionFlowNode inline logic",
        DeprecationWarning, stacklevel=2,
    )
    corrected = heading_pixel_deg - gimbal_yaw_delta
    while corrected > 180:
        corrected -= 360
    while corrected < -180:
        corrected += 360
    return corrected


def world_to_gps(
    easting_m: float,
    northing_m: float,
    anchor_lat: float,
    anchor_lon: float,
) -> tuple[float, float]:
    """世界坐标（东北偏移米）→ GPS坐标。

    .. deprecated:: T-402
        drone_store.update_drone_from_stats() 已内联实现。保留仅供测试引用。

    Args:
        easting_m, northing_m: 世界坐标偏移（米）
        anchor_lat, anchor_lon: 世界锚点GPS

    Returns:
        (latitude, longitude)
    """
    warnings.warn(
        "world_to_gps is deprecated (T-402); use drone_store inline logic",
        DeprecationWarning, stacklevel=2,
    )
    lat = anchor_lat + math.degrees(northing_m / EARTH_RADIUS_M)
    lon = anchor_lon + math.degrees(easting_m / (EARTH_RADIUS_M * math.cos(math.radians(anchor_lat))))
    return lat, lon
