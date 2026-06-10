"""自动车道推断工具 — 从车辆轨迹数据中自动发现车道。

无需人工标注，通过聚类已完成轨迹的空间相似性自动发现车道中心线，
并为每个车道生成人类可读的标签和交通指标。

算法步骤：
1. 收集时间窗口内的已完成轨迹
2. 按方向类别（直行/左转/右转/掉头）分桶
3. 在每个桶内，按入口/出口空间邻近性聚类
4. 为每个聚类拟合中心线
5. 自动生成车道标签（如 "东→西 直行"）
"""

import math
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

logger = logging.getLogger(__name__)

# ── 方向标签映射 ──────────────────────────────────────────────────────────
DIRECTION_LABELS = {
    "straight": "直行",
    "left_turn": "左转",
    "right_turn": "右转",
    "u_turn": "掉头",
    "unknown": "未知",
}

# ── 方位词对向映射 ──────────────────────────────────────────────────────────
OPPOSITE_CARDINAL = {"东": "西", "西": "东", "南": "北", "北": "南"}

# 像素坐标下的聚类距离阈值（默认值，可配置）
DEFAULT_ENTRY_EXIT_THRESHOLD_PX = 120.0
DEFAULT_MIN_TRACKS_PER_LANE = 3
DEFAULT_CENTERLINE_RESAMPLE_N = 20


@dataclass
class InferredLane:
    """自动推断的车道数据结构。"""
    lane_id: str                          # 唯一标识（如 "lane_1"）
    label: str                            # 人类可读标签（如 "东→西 直行"）
    direction_class: str                  # "straight" | "left_turn" | "right_turn" | "u_turn"
    entry_heading_deg: float              # 入口平均朝向（度）
    exit_heading_deg: float               # 出口平均朝向（度）
    centerline_px: list                   # [[x,y], ...] 中心线像素坐标
    entry_center_px: tuple                # 入口中心 (cx, cy)
    exit_center_px: tuple                 # 出口中心 (cx, cy)
    track_ids: list = field(default_factory=list)  # 聚类内的轨迹ID
    # 实时统计
    count: int = 0                        # 当前车道内活跃车辆数
    avg_speed_kmh: float = 0.0            # 平均车速
    queue_length_m: float = 0.0           # 排队长度（米或像素）
    stopped_count: int = 0                # 排队车辆数
    flow_per_min: float | None = None     # 流量（辆/分钟）
    avg_headway_sec: float | None = None  # 平均车头时距（秒）


def circular_mean_deg(angles_deg: list[float]) -> float:
    """计算角度的环形平均值（正确处理 ±180° 边界问题）。

    普通算术平均在角度环绕时会出错：
    mean(-170, 170) = 0°（东），但正确值应为 ±180°（西）。

    使用 atan2(sin均值, cos均值) 方法正确处理角度环绕。

    Args:
        angles_deg: 角度列表（度）

    Returns:
        环形平均角度（度，范围 [-180, 180)）
    """
    if not angles_deg:
        return 0.0
    if len(angles_deg) == 1:
        return angles_deg[0]

    # Convert degrees to radians for sin/cos
    rads = [math.radians(a) for a in angles_deg]
    sin_sum = sum(math.sin(r) for r in rads)
    cos_sum = sum(math.cos(r) for r in rads)
    return math.degrees(math.atan2(sin_sum / len(angles_deg), cos_sum / len(angles_deg)))


def heading_to_cardinal(heading_deg: float) -> str:
    """将朝向角度（度, atan2坐标系）转换为中文方位词。

    atan2坐标系: 0°=右(东), 90°=下(南), 180°/-180°=左(西), -90°=上(北)
    注意：图像坐标系y轴向下，所以 atan2 的 90° 实际是南。

    Returns:
        "东" | "南" | "西" | "北"
    """
    # 归一化到 [0, 360)
    h = heading_deg % 360
    if h < 45 or h >= 315:
        return "东"
    elif 45 <= h < 135:
        return "南"
    elif 135 <= h < 225:
        return "西"
    else:
        return "北"


def compute_entry_exit_headings(trajectory_px: list) -> tuple[float | None, float | None]:
    """从轨迹点序列计算入口和出口朝向。

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

    # 入口朝向：前 window 个点
    dx_entry = pts[window, 0] - pts[0, 0]
    dy_entry = pts[window, 1] - pts[0, 1]
    entry_disp = math.sqrt(dx_entry * dx_entry + dy_entry * dy_entry)
    if entry_disp < 10.0:
        return None, None  # 位移太小，heading 被噪声主导
    entry_h = math.degrees(math.atan2(dy_entry, dx_entry))

    # 出口朝向：后 window 个点
    dx_exit = pts[-1, 0] - pts[-1 - window, 0]
    dy_exit = pts[-1, 1] - pts[-1 - window, 1]
    exit_disp = math.sqrt(dx_exit * dx_exit + dy_exit * dy_exit)
    if exit_disp < 10.0:
        return None, None
    exit_h = math.degrees(math.atan2(dy_exit, dx_exit))

    return entry_h, exit_h


def resample_polyline(points: np.ndarray, n_samples: int) -> np.ndarray:
    """将折线重采样为等距的 N 个点。

    Args:
        points: (M, 2) 原始折线点
        n_samples: 目标采样数

    Returns:
        (n_samples, 2) 重采样后的点
    """
    if len(points) < 2:
        return np.tile(points[0], (n_samples, 1)) if len(points) == 1 else points

    # 计算累积弧长
    diffs = np.diff(points, axis=0)
    seg_lengths = np.linalg.norm(diffs, axis=1)
    cum_lengths = np.concatenate([[0], np.cumsum(seg_lengths)])
    total_length = cum_lengths[-1]

    if total_length < 1e-6:
        return np.tile(points[0], (n_samples, 1))

    # 等距采样点
    target_lengths = np.linspace(0, total_length, n_samples)
    resampled = np.zeros((n_samples, 2))
    for i, target in enumerate(target_lengths):
        # 找到 target 所在的段
        idx = np.searchsorted(cum_lengths, target, side='right') - 1
        idx = min(idx, len(points) - 2)
        # 线性插值
        seg_len = seg_lengths[idx]
        if seg_len < 1e-6:
            resampled[i] = points[idx]
        else:
            t = (target - cum_lengths[idx]) / seg_len
            resampled[i] = points[idx] + t * diffs[idx]

    return resampled


def cluster_trajectories_spatial(
    tracks: list[dict],
    entry_exit_threshold: float,
) -> list[list[dict]]:
    """基于入口/出口空间邻近性对轨迹进行层次聚类。

    使用 scipy 层次聚类，距离度量为入口和出口距离的最大值。

    Args:
        tracks: 轨迹列表，每条包含 trajectory_px, entry_heading, exit_heading
        entry_exit_threshold: 聚类距离阈值（像素）

    Returns:
        轨迹簇列表
    """
    if len(tracks) <= 1:
        return [tracks] if tracks else []

    n = len(tracks)

    # 构建距离矩阵
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        ti = tracks[i]
        ei = np.array(ti["trajectory_px"][0])
        xi = np.array(ti["trajectory_px"][-1])
        for j in range(i + 1, n):
            tj = tracks[j]
            ej = np.array(tj["trajectory_px"][0])
            xj = np.array(tj["trajectory_px"][-1])
            d_entry = np.linalg.norm(ei - ej)
            d_exit = np.linalg.norm(xi - xj)
            dist_matrix[i, j] = max(d_entry, d_exit)
            dist_matrix[j, i] = dist_matrix[i, j]

    # 层次聚类
    condensed_dist = pdist(np.arange(n)[:, None], metric=lambda u, v: dist_matrix[int(u[0]), int(v[0])])
    # 更稳健的方式：直接构建 condensed distance vector
    condensed = []
    for i in range(n):
        for j in range(i + 1, n):
            condensed.append(dist_matrix[i, j])
    condensed = np.array(condensed)

    if len(condensed) == 0:
        return [tracks]

    Z = linkage(condensed, method='average')
    labels = fcluster(Z, t=entry_exit_threshold, criterion='distance')

    # 按标签分组
    clusters = defaultdict(list)
    for i, label in enumerate(labels):
        clusters[label].append(tracks[i])

    return list(clusters.values())


def merge_similar_clusters(
    clusters: list[tuple[str, list[dict]]],
    merge_threshold_px: float = 200.0,
) -> list[tuple[str, list[dict]]]:
    """合并空间上邻近且方向相同的聚类，减少过度碎片化。

    在 initial clustering 之后，将入口/出口中心距离 < merge_threshold_px
    且方向类别相同的簇合并为一个。

    Args:
        clusters: [(direction_class, tracks), ...] 初始聚类结果
        merge_threshold_px: 合并距离阈值（像素）

    Returns:
        合并后的聚类列表
    """
    if len(clusters) <= 1:
        return clusters

    # 计算每个簇的入口/出口中心
    cluster_info = []
    for direction_class, tracks in clusters:
        entry_pts = np.array([t["trajectory_px"][0] for t in tracks])
        exit_pts = np.array([t["trajectory_px"][-1] for t in tracks])
        cluster_info.append({
            "direction_class": direction_class,
            "tracks": tracks,
            "entry_center": np.mean(entry_pts, axis=0),
            "exit_center": np.mean(exit_pts, axis=0),
        })

    # Union-Find 合并
    n = len(cluster_info)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = cluster_info[i], cluster_info[j]
            if ci["direction_class"] != cj["direction_class"]:
                continue
            d_entry = np.linalg.norm(ci["entry_center"] - cj["entry_center"])
            d_exit = np.linalg.norm(ci["exit_center"] - cj["exit_center"])
            if max(d_entry, d_exit) < merge_threshold_px:
                union(i, j)

    # 按组合并
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    merged = []
    for indices in groups.values():
        direction_class = cluster_info[indices[0]]["direction_class"]
        all_tracks = []
        for idx in indices:
            all_tracks.extend(cluster_info[idx]["tracks"])
        merged.append((direction_class, all_tracks))

    return merged


def fit_centerline(trajectory_group: list[dict], n_samples: int = 20) -> np.ndarray:
    """为一组轨迹拟合中心线。

    将所有轨迹重采样到相同数量的点，然后取均值。

    Args:
        trajectory_group: 轨迹列表，每条包含 trajectory_px
        n_samples: 中心线采样点数

    Returns:
        (n_samples, 2) 中心线坐标
    """
    resampled_all = []
    for track in trajectory_group:
        pts = np.array(track["trajectory_px"], dtype=np.float64)
        if len(pts) < 2:
            continue
        resampled = resample_polyline(pts, n_samples)
        resampled_all.append(resampled)

    if not resampled_all:
        return np.zeros((n_samples, 2))

    # 取所有重采样轨迹的均值
    centerline = np.mean(np.array(resampled_all), axis=0)
    return centerline


def generate_lane_label(
    entry_heading: float,
    exit_heading: float,
    direction_class: str,
) -> str:
    """生成人类可读的车道标签。

    入口使用来向（entry heading 的反方向），出口使用去向（exit heading）。
    验证 direction_class 与 heading delta 一致，不一致时以实际 heading 为准。

    Examples:
        "东→西 直行"
        "南→东 右转"
        "北→西 左转"
    """
    # 验证 direction_class 与 heading delta 的一致性
    # 如果 circular mean 产生不可靠的结果（如入口和出口 heading 几乎相反
    # 但 direction_class 为 "straight"），以实际 heading delta 重新分类
    delta = exit_heading - entry_heading
    delta = ((delta + 180) % 360) - 180
    abs_delta = abs(delta)

    if direction_class == "straight" and abs_delta > 45:
        # "直行" 但 heading 变化 > 45° → 重新分类
        if abs_delta >= 120:
            direction_class = "u_turn"
        elif delta > 0:
            direction_class = "right_turn"  # heading 增大 = 数学CCW = 视觉CW = 右转
        else:
            direction_class = "left_turn"   # heading 减小 = 数学CW = 视觉CCW = 左转
    elif direction_class == "u_turn" and abs_delta < 120:
        # "掉头" 但 heading 变化 < 120° → 不是真正的掉头，重新分类
        if abs_delta <= 25:
            direction_class = "straight"
        elif delta > 0:
            direction_class = "right_turn"
        else:
            direction_class = "left_turn"
    elif direction_class == "left_turn" and delta > 45:
        # "左转" 但 heading 增大（右转方向）→ 以 delta 为准
        if abs_delta >= 120:
            direction_class = "u_turn"
        else:
            direction_class = "right_turn"
    elif direction_class == "right_turn" and delta < -45:
        # "右转" 但 heading 减小（左转方向）→ 以 delta 为准
        if abs_delta >= 120:
            direction_class = "u_turn"
        else:
            direction_class = "left_turn"

    # 入口来向 = 行驶方向的反方向
    entry_dir = heading_to_cardinal((entry_heading + 180) % 360)
    # 出口去向 = 行驶方向
    exit_dir = heading_to_cardinal(exit_heading)

    # 自引用标签保护: 入口和出口方位词相同时，方向标签不应为 左转/右转/掉头
    # 例如 "北→北 掉头" 不合理 — 重新根据 heading delta 修正
    if entry_dir == exit_dir and direction_class in ("left_turn", "right_turn", "u_turn"):
        if direction_class == "u_turn" and abs_delta >= 120:
            # 真正的掉头: 出口方向应为入口来向的对向（掉头后驶向相反方向）
            exit_dir = OPPOSITE_CARDINAL.get(entry_dir, entry_dir)
        elif abs_delta >= 120:
            direction_class = "u_turn"
            exit_dir = OPPOSITE_CARDINAL.get(entry_dir, entry_dir)
        elif abs_delta <= 45:
            direction_class = "straight"
        elif delta > 0:
            direction_class = "right_turn"
        else:
            direction_class = "left_turn"

    dir_label = DIRECTION_LABELS.get(direction_class, direction_class)
    return f"{entry_dir}→{exit_dir} {dir_label}"


def match_active_track_to_lane(
    bbox_xyxy: list,
    track_heading: float | None,
    inferred_lanes: dict[str, 'InferredLane'],
    max_distance_px: float = 200.0,
) -> str | None:
    """将活跃跟踪匹配到最近的推断车道。

    基于 bbox 中心到各车道中心线的最小距离。

    Args:
        bbox_xyxy: [x1, y1, x2, y2]
        track_heading: 当前运动朝向（度）
        inferred_lanes: {lane_id: InferredLane}
        max_distance_px: 最大匹配距离

    Returns:
        最佳匹配的车道ID或None
    """
    if not inferred_lanes:
        return None

    cx = (bbox_xyxy[0] + bbox_xyxy[2]) / 2
    cy = (bbox_xyxy[1] + bbox_xyxy[3]) / 2
    pt = np.array([cx, cy])

    best_lane = None
    best_dist = max_distance_px

    for lane_id, lane in inferred_lanes.items():
        if not lane.centerline_px:
            continue
        centerline = np.array(lane.centerline_px)
        # 计算点到折线的最小距离
        dists = np.linalg.norm(centerline - pt, axis=1)
        min_dist = float(np.min(dists))
        if min_dist < best_dist:
            best_dist = min_dist
            best_lane = lane_id

    return best_lane


def compute_flow_per_min(
    completed_timestamps: list[float],
    window_sec: float,
    current_time: float,
) -> float:
    """计算滑动时间窗口内的流量（辆/分钟）。

    Args:
        completed_timestamps: 完成轨迹的时间戳列表
        window_sec: 滑动窗口长度（秒）
        current_time: 当前时间

    Returns:
        流量（辆/分钟）
    """
    if not completed_timestamps or window_sec <= 0:
        return 0.0

    cutoff = current_time - window_sec
    recent = [t for t in completed_timestamps if t > cutoff]
    if not recent:
        return 0.0

    # 实际时间跨度
    actual_window = min(window_sec, current_time - min(recent))
    if actual_window < 1.0:
        return 0.0

    return len(recent) / (actual_window / 60.0)


def compute_headway(
    completed_timestamps: list[float],
    window_sec: float = 300.0,
    current_time: float = 0.0,
) -> tuple[float | None, float | None]:
    """计算车头时距统计。

    Args:
        completed_timestamps: 排序后的完成时间戳列表
        window_sec: 滑动窗口长度
        current_time: 当前时间

    Returns:
        (avg_headway_sec, min_headway_sec)
    """
    if len(completed_timestamps) < 2:
        return None, None

    cutoff = current_time - window_sec
    recent = sorted([t for t in completed_timestamps if t > cutoff])
    if len(recent) < 2:
        return None, None

    headways = [recent[i] - recent[i - 1] for i in range(1, len(recent)) if recent[i] - recent[i - 1] > 0]
    if not headways:
        return None, None

    return round(sum(headways) / len(headways), 2), round(min(headways), 2)
