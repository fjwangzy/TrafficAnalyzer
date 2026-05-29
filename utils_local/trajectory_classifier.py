"""转向行为分类工具。

基于轨迹运动方向变化角度分类为：直行/左转/右转/掉头。
"""

import math
import numpy as np


def compute_heading(position_history: list[tuple], n_frames: int = 5) -> float | None:
    """从轨迹点序列计算运动方向角度（度）。

    Args:
        position_history: [(cx, cy, timestamp), ...] 或 [(cx, cy), ...]
        n_frames: 用于计算方向的最小帧数

    Returns:
        运动方向角度（度，atan2），或 None（数据不足或静止）
    """
    if len(position_history) < n_frames:
        return None

    # 取首尾点计算位移向量
    x0, y0 = position_history[0][0], position_history[0][1]
    x1, y1 = position_history[-1][0], position_history[-1][1]
    dx, dy = x1 - x0, y1 - y0
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return None  # 静止车辆
    return math.degrees(math.atan2(dy, dx))


def classify_direction(
    entry_heading: float,
    exit_heading: float,
    thresholds: dict | None = None,
) -> str:
    """根据入口方向和出口方向的夹角分类行驶方向。

    Args:
        entry_heading: 轨迹前半段的运动方向角度（度）
        exit_heading:  轨迹后半段的运动方向角度（度）
        thresholds:    角度阈值 {"straight": 25, "turn": 120}

    Returns:
        "straight" | "left_turn" | "right_turn" | "u_turn" | "unknown"
    """
    if thresholds is None:
        thresholds = {"straight": 25, "turn": 120}

    # 计算方向变化角度（-180度 ~ 180度）
    delta = exit_heading - entry_heading
    delta = ((delta + 180) % 360) - 180  # 归一化

    abs_delta = abs(delta)
    straight_thresh = thresholds.get("straight", 25)
    turn_thresh = thresholds.get("turn", 120)

    if abs_delta <= straight_thresh:
        return "straight"
    elif abs_delta >= turn_thresh:
        return "u_turn"
    elif delta > 0:
        return "left_turn"
    else:
        return "right_turn"


def classify_turning_movement(
    trajectory_points: list[tuple],
    entry_road_center: tuple | None = None,
    exit_road_center: tuple | None = None,
    roundabout_center: tuple | None = None,
    thresholds: dict | None = None,
) -> str:
    """基于轨迹入口→出口几何关系分类转向行为（完整版，用于TrajectoryNode）。

    Args:
        trajectory_points: [(cx, cy), ...] 像素坐标序列
        entry_road_center: 入口道路中心坐标（可选）
        exit_road_center:  出口道路中心坐标（可选）
        roundabout_center: 环形交叉路口中心坐标（可选）
        thresholds:        角度阈值

    Returns:
        "straight" | "left_turn" | "right_turn" | "u_turn" | "unknown"
    """
    if not trajectory_points or len(trajectory_points) < 5:
        return "unknown"

    if thresholds is None:
        thresholds = {"straight": 30, "u_turn": [150, 180]}

    p_entry = np.array(trajectory_points[0])
    p_exit = np.array(trajectory_points[-1])

    # 确定参考中心点
    if roundabout_center is not None:
        center = np.array(roundabout_center)
    else:
        center = np.mean(np.array(trajectory_points), axis=0)

    v_entry = p_entry - center
    v_exit = p_exit - center

    dot = float(np.dot(v_entry, v_exit))
    cross = float(np.cross(v_entry, v_exit))
    angle_deg = math.degrees(math.atan2(cross, dot))
    abs_angle = abs(angle_deg)

    u_turn_range = thresholds.get("u_turn", [150, 180])
    u_turn_thresh = u_turn_range[0] if isinstance(u_turn_range, list) else u_turn_range

    if abs_angle <= thresholds.get("straight", 30):
        return "straight"
    elif abs_angle >= u_turn_thresh:
        return "u_turn"
    elif angle_deg > 0:
        return "left_turn"
    else:
        return "right_turn"
