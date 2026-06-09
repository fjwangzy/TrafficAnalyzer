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


def build_camera_matrix(
    camera_intrinsics: dict,
    image_size: tuple[int, int],
) -> np.ndarray:
    """构建相机内参矩阵 K。

    Args:
        camera_intrinsics: {focal_length_mm, sensor_width_mm, sensor_height_mm}
        image_size: (width, height) 像素

    Returns:
        3x3 相机内参矩阵
    """
    img_w, img_h = image_size
    fl = camera_intrinsics["focal_length_mm"]
    sw = camera_intrinsics["sensor_width_mm"]
    sh = camera_intrinsics.get("sensor_height_mm", sw * img_h / img_w)
    zoom = camera_intrinsics.get("zoom_factor", 1.0)
    effective_fl = fl / zoom if zoom > 0 else fl

    fx = effective_fl * img_w / sw
    fy = effective_fl * img_h / sh
    return np.array([
        [fx, 0, img_w / 2.0],
        [0, fy, img_h / 2.0],
        [0, 0, 1.0],
    ], dtype=np.float64)


def undistort_points(
    points_px: np.ndarray,
    camera_intrinsics: dict,
    image_size: tuple[int, int],
    dist_coeffs: list[float] | np.ndarray | None = None,
) -> np.ndarray:
    """对像素坐标做镜头畸变校正（Brown-Conrady模型）。

    Args:
        points_px: Nx2 像素坐标
        camera_intrinsics: 相机内参字典
        image_size: (width, height) 像素
        dist_coeffs: [k1, k2, p1, p2, k3] 畸变系数，None或空则跳过

    Returns:
        Nx2 去畸变后的像素坐标
    """
    if dist_coeffs is None or len(dist_coeffs) == 0:
        return points_px

    K = build_camera_matrix(camera_intrinsics, image_size)
    dc = np.array(dist_coeffs, dtype=np.float64)

    # cv2.undistortPoints 输入要求 Nx1x2
    pts_in = points_px.reshape(-1, 1, 2).astype(np.float64)
    # P=K 使输出仍为像素坐标（而非归一化坐标）
    pts_out = cv2.undistortPoints(pts_in, K, dc, P=K)
    return pts_out.reshape(-1, 2)


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

        # 像素→ENU世界坐标映射：
        #   像素 x 向右 = 世界 East（同向）
        #   像素 y 向下 = 世界 South = -North（反向，需取负）
        #
        # 对于 gimbal_yaw = θ（DJI: 从北顺时针，弧度）：
        #   图像上方指向世界方向 θ
        #   图像右方指向世界方向 θ+90°
        #
        # 推导：
        #   dx, dy = 像素偏移（右+, 下+）
        #   image_right  → ENU (cos θ, -sin θ)
        #   image_up(-dy) → ENU (sin θ,  cos θ)
        #
        #   world_east  = gsd_x·dx·cosθ + gsd_y·(-dy)·sinθ
        #               = gsd_x·cosθ·dx - gsd_y·sinθ·dy
        #   world_north = gsd_x·dx·(-sinθ) + gsd_y·(-dy)·cosθ
        #               = -gsd_x·sinθ·dx - gsd_y·cosθ·dy
        H = np.array([
            [ gsd_x * cos_y, -gsd_y * sin_y, 0],
            [-gsd_x * sin_y, -gsd_y * cos_y, 0],
            [0,               0,              1],
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

        # 基底旋转：像素Y轴(下)与世界Y轴(北/上)方向相反
        # R_flip = Rx(180°) 将世界坐标的 Y-up/Z-up 映射到
        # 相机坐标的 Y-down/Z-backward 约定
        R_flip = np.array([
            [1,  0,  0],
            [0, -1,  0],
            [0,  0, -1],
        ], dtype=np.float64)

        # 旋转矩阵（云台角度 + 基底翻转）
        Rz = _rotation_z(g_yaw)
        Ry = _rotation_y(g_pitch + math.pi / 2)  # 修正：-90度为正下方
        Rx = _rotation_x(g_roll)
        R = Rz @ Ry @ Rx @ R_flip

        # 相机位于无人机正下方高度agl处
        # 注：使用 t = [0,0,agl]（相机位置），配合 R_flip 后
        # 等效于标准 CV 的 t = -R @ C 约定
        t = np.array([0, 0, agl], dtype=np.float64)

        # 投影矩阵 P = K @ [R | t]  (3x4)
        Rt = np.hstack([R, t.reshape(3, 1)])
        P = K @ Rt

        # 地面平面 z=0 的单应性矩阵（世界→像素方向）：
        # 取 P 的第1、2、4列（消除z列），得到 3x3 矩阵
        H_w2p = np.column_stack([P[:, 0], P[:, 1], P[:, 3]])

        # 反转得到像素→世界方向（pixel_to_world 需要此方向）
        det = np.linalg.det(H_w2p)
        if abs(det) < 1e-10:
            logger.warning(
                "Oblique H_w2p 奇异（可能俯仰角过小），回退到 Nadir 近似"
            )
            # 回退到 Nadir 模式
            gsd_x = agl * sw / (effective_fl * img_w)
            gsd_y = agl * sh / (effective_fl * img_h)
            cx, cy = img_w / 2.0, img_h / 2.0
            cos_y = math.cos(g_yaw)
            sin_y = math.sin(g_yaw)
            H = np.array([
                [ gsd_x * cos_y, -gsd_y * sin_y, 0],
                [-gsd_x * sin_y, -gsd_y * cos_y, 0],
                [0,               0,              1],
            ], dtype=np.float64)
            offset = H @ np.array([cx, cy, 1.0])
            H[0, 2] = -offset[0]
            H[1, 2] = -offset[1]
        else:
            H = np.linalg.inv(H_w2p)

            # 设置平移：图像中心 (cx,cy) 映射到世界原点 (0,0)
            cx, cy = img_w / 2.0, img_h / 2.0
            center_h = np.array([cx, cy, 1.0])
            center_world_h = H @ center_h
            # 齐次坐标→欧氏坐标
            center_world = center_world_h[:2] / center_world_h[2]
            # 调整H的平移列，使中心映射到(0,0)
            H_adjust = np.eye(3, dtype=np.float64)
            H_adjust[0, 2] = -center_world[0]
            H_adjust[1, 2] = -center_world[1]
            H = H_adjust @ H

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
