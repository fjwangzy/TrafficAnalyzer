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
        # 图像坐标系 (y轴向下): heading 增大 = 数学逆时针
        # 但 y 轴向下导致视觉上是顺时针 = 右转
        return "right_turn"
    else:
        # heading 减小 = 数学顺时针 = 视觉上逆时针 = 左转
        return "left_turn"


def classify_turning_movement(
    trajectory_points: list[tuple],
    entry_road_center: tuple | None = None,
    exit_road_center: tuple | None = None,
    roundabout_center: tuple | None = None,
    thresholds: dict | None = None,
) -> str:
    """基于轨迹入口/出口行驶方向分类转向行为。

    使用轨迹前段和后段的运动方向（heading）差值来判断：
    - 方向变化小 → 直行
    - 方向变化大且为正（图像坐标逆时针）→ 右转
    - 方向变化大且为负（图像坐标顺时针）→ 左转
    - 方向几乎反转 → 掉头

    注意: 旧版使用"轨迹中心到入口/出口的向量"方法在普通路口场景下
    会将几乎所有轨迹误判为掉头（因为入口和出口相对于中心天然呈 ~180°）。
    改为基于行驶方向的 delta heading 方法，与实际车辆运动方向一致。

    Args:
        trajectory_points: [(cx, cy), ...] 像素坐标序列
        entry_road_center: （已弃用，保留参数兼容）
        exit_road_center:  （已弃用，保留参数兼容）
        roundabout_center: （已弃用，保留参数兼容）
        thresholds:        角度阈值，支持两种格式:
            格式1: {"straight": 30, "turn": 120}
            格式2: {"straight": 30, "u_turn": [150, 180]}

    Returns:
        "straight" | "left_turn" | "right_turn" | "u_turn" | "unknown"
    """
    if not trajectory_points or len(trajectory_points) < 5:
        return "unknown"

    if thresholds is None:
        thresholds = {"straight": 25, "turn": 120}

    # 提取行驶方向 heading
    entry_h, exit_h = _compute_entry_exit_headings(trajectory_points)
    if entry_h is None or exit_h is None:
        return "unknown"

    # 兼容两种阈值格式
    straight_thresh = thresholds.get("straight", 25)
    if "turn" in thresholds:
        u_turn_thresh = thresholds["turn"]
    else:
        u_turn_range = thresholds.get("u_turn", [150, 180])
        u_turn_thresh = list(u_turn_range)[0] if not isinstance(u_turn_range, (int, float)) else u_turn_range

    # 计算方向变化角度 (-180, 180]
    delta = exit_h - entry_h
    delta = ((delta + 180) % 360) - 180

    abs_delta = abs(delta)
    if abs_delta <= straight_thresh:
        return "straight"
    elif abs_delta >= u_turn_thresh:
        return "u_turn"
    elif delta > 0:
        # 图像坐标系 (y轴向下): heading 增大 = 数学逆时针
        # 但 y 轴向下导致视觉上是顺时针 = 右转
        return "right_turn"
    else:
        # heading 减小 = 数学顺时针 = 视觉上逆时针 = 左转
        return "left_turn"


def _compute_entry_exit_headings(
    trajectory_px: list[tuple],
) -> tuple[float | None, float | None]:
    """从轨迹点序列计算入口和出口行驶方向。

    Args:
        trajectory_px: [(cx, cy), ...] 像素坐标序列

    Returns:
        (entry_heading_deg, exit_heading_deg) 或 (None, None)
    """
    if not trajectory_px or len(trajectory_px) < 4:
        return None, None

    pts = np.array(trajectory_px, dtype=np.float64)
    n = len(pts)
    # 使用更大窗口 (n//2) 平滑短轨迹噪声；至少 2 帧，至多 n//2 帧
    window = max(n // 2, 2)
    window = min(window, n - 2)  # 确保不越界
    window = max(window, 2)      # 至少 2

    # 入口朝向：前 window 个点的位移方向
    dx_entry = pts[window, 0] - pts[0, 0]
    dy_entry = pts[window, 1] - pts[0, 1]
    # 最小位移阈值：位移太小则 heading 被噪声主导
    entry_disp = math.sqrt(dx_entry * dx_entry + dy_entry * dy_entry)
    if entry_disp < 10.0:
        return None, None
    entry_h = math.degrees(math.atan2(dy_entry, dx_entry))

    # 出口朝向：后 window 个点的位移方向
    dx_exit = pts[-1, 0] - pts[-1 - window, 0]
    dy_exit = pts[-1, 1] - pts[-1 - window, 1]
    exit_disp = math.sqrt(dx_exit * dx_exit + dy_exit * dy_exit)
    if exit_disp < 10.0:
        return None, None
    exit_h = math.degrees(math.atan2(dy_exit, dx_exit))

    return entry_h, exit_h
