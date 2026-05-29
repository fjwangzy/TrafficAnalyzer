"""
单应性矩阵计算工具（遥测模式 + 参考点模式）

提供像素坐标与世界坐标（米）之间的透视变换能力。
- 遥测模式：从无人机飞行遥测（高度、云台角度、GPS）+ 相机内参自动计算
- 参考点模式：传统4+像素↔世界坐标对应点
"""

import math
import numpy as np
import cv2
import logging

logger = logging.getLogger(__name__)


def compute_homography_from_telemetry(
    telemetry: dict,
    camera_intrinsics: dict,
    image_size: tuple[int, int],
) -> np.ndarray:
    """
    从飞行遥测自动计算单应性矩阵。

    Args:
        telemetry: 遥测字典 (altitude_agl, gimbal_pitch/yaw/roll, zoom_factor, ...)
        camera_intrinsics: 相机内参 (focal_length_mm, sensor_width_mm, sensor_height_mm)
        image_size: (width, height) 像素

    Returns:
        3x3 单应性矩阵 H（像素→地面米坐标）
    """
    img_w, img_h = image_size
    fl = camera_intrinsics["focal_length_mm"]
    sw = camera_intrinsics["sensor_width_mm"]
    sh = camera_intrinsics.get("sensor_height_mm", sw * img_h / img_w)
    zoom = telemetry.get("zoom_factor", 1.0)

    # 变焦影响等效焦距
    effective_fl = fl / zoom if zoom > 0 else fl

    agl = telemetry["altitude_agl"]  # 离地高度(米)
    g_pitch = math.radians(telemetry.get("gimbal_pitch", -90))
    g_yaw = math.radians(telemetry.get("gimbal_yaw", 0))
    g_roll = math.radians(telemetry.get("gimbal_roll", 0))

    if abs(g_pitch + math.pi / 2) < math.radians(10):
        # === Nadir 模式：简化 2D 相似变换 ===
        gsd_x = agl * sw / (effective_fl * img_w)
        gsd_y = agl * sh / (effective_fl * img_h)

        cx, cy = img_w / 2.0, img_h / 2.0
        cos_y = math.cos(g_yaw)
        sin_y = math.sin(g_yaw)

        H = np.array([
            [gsd_x * cos_y, -gsd_x * sin_y, 0],
            [gsd_y * sin_y,  gsd_y * cos_y,  0],
            [0,              0,               1],
        ], dtype=np.float64)

        # 设置平移：图像中心 (cx,cy) 映射到世界原点 (0,0)
        offset = H @ np.array([cx, cy, 1.0])
        H[0, 2] = -offset[0]
        H[1, 2] = -offset[1]
    else:
        # === Oblique 模式：完整透视变换 ===
        # 相机内参矩阵（像素单位）
        fx = effective_fl * img_w / sw
        fy = effective_fl * img_h / sh
        K = np.array([
            [fx, 0,  img_w / 2.0],
            [0,  fy, img_h / 2.0],
            [0,  0,  1.0],
        ], dtype=np.float64)

        # 旋转矩阵（云台角度）
        Rz = _rotation_z(g_yaw)
        Ry = _rotation_y(g_pitch + math.pi / 2)  # 修正：-90度为正下方
        Rx = _rotation_x(g_roll)
        R = Rz @ Ry @ Rx

        # 相机位于无人机正下方高度agl处
        t = np.array([0, 0, agl], dtype=np.float64)

        # 投影矩阵 P = K @ [R | t]  (3x4)
        Rt = np.hstack([R, t.reshape(3, 1)])
        P = K @ Rt

        # 地面平面 z=0 的单应性矩阵：
        # 取 P 的第1、2、4列（消除z列），得到 3x3 矩阵
        H = np.column_stack([P[:, 0], P[:, 1], P[:, 3]])

    return H


def compute_homography_from_reference_points(
    reference_points: list[list[float]],
) -> np.ndarray | None:
    """
    传统方式：从像素↔世界坐标对应点计算单应性矩阵。
    用于无遥测数据的固定摄像头场景。

    Args:
        reference_points: [[px, py, world_x_m, world_y_m], ...] 至少4个点

    Returns:
        3x3 单应性矩阵 H，或 None（若点数不足）
    """
    if len(reference_points) < 4:
        return None

    pts_pixel = np.array([[p[0], p[1]] for p in reference_points], dtype=np.float64)
    pts_world = np.array([[p[2], p[3]] for p in reference_points], dtype=np.float64)
    H, status = cv2.findHomography(pts_pixel, pts_world, cv2.RANSAC, 5.0)
    return H


def pixel_to_world(points_px: np.ndarray, H: np.ndarray) -> np.ndarray:
    """
    将 Nx2 像素坐标变换为世界坐标（米）。

    Args:
        points_px: Nx2 numpy array of pixel coordinates
        H: 3x3 homography matrix

    Returns:
        Nx2 numpy array of world coordinates in meters
    """
    ones = np.ones((points_px.shape[0], 1))
    pts_h = np.hstack([points_px, ones])
    pts_world_h = (H @ pts_h.T).T
    pts_world = pts_world_h[:, :2] / pts_world_h[:, 2:3]
    return pts_world


def pixels_per_meter_at(point_px: np.ndarray, H: np.ndarray) -> float:
    """计算特定图像位置处的像素/米比率。"""
    H_inv = np.linalg.inv(H)
    world_pt = pixel_to_world(point_px.reshape(1, 2), H)[0]
    offset_world = world_pt + np.array([1.0, 0.0])
    h1 = np.array([point_px[0], point_px[1], 1.0])
    h2 = np.array([offset_world[0], offset_world[1], 1.0])
    px1 = H_inv @ h1
    px1 /= px1[2]
    px2 = H_inv @ h2
    px2 /= px2[2]
    return float(np.linalg.norm(px2[:2] - px1[:2]))


def is_valid_homography(H: np.ndarray | None) -> bool:
    """检查单应性矩阵是否有效（非None、非奇异）。"""
    if H is None:
        return False
    if H.shape != (3, 3):
        return False
    det = np.linalg.det(H)
    return abs(det) > 1e-10


def _rotation_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def _rotation_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def _rotation_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
