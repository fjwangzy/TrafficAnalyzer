"""车道多边形操作和排队长度计算工具。"""

import numpy as np
from shapely.geometry import Point, Polygon, LineString

from utils_local.homography import pixel_to_world


def assign_vehicle_to_lane(bbox_xyxy: list, lane_polygons: dict) -> str | None:
    """确定bbox中心点所在的车道。

    Args:
        bbox_xyxy: [x1, y1, x2, y2] 边界框坐标
        lane_polygons: {lane_id: shapely.Polygon} 车道多边形字典

    Returns:
        车道ID（str）或 None（未命中任何车道）
    """
    cx = (bbox_xyxy[0] + bbox_xyxy[2]) / 2
    cy = (bbox_xyxy[1] + bbox_xyxy[3]) / 2
    pt = Point(cx, cy)
    for lane_id, poly in lane_polygons.items():
        if poly.contains(pt):
            return lane_id
    return None


def compute_queue_extent(
    stopped_vehicles: list[dict],
    H: np.ndarray | None,
    stop_line: list | None = None,
) -> float:
    """计算排队长度（米或像素）。

    如果有停车线和H矩阵：计算排队车辆到停车线的最大世界距离。
    如果有H矩阵但无停车线：计算排队车辆之间的最大世界距离。
    无H矩阵：返回像素距离（供相对比较）。

    Args:
        stopped_vehicles: [{"bbox_center_px": (cx, cy), ...}, ...]
        H: 3x3 单应性矩阵
        stop_line: [[x1,y1], [x2,y2]] 停车线像素坐标（可选）

    Returns:
        排队长度（米或像素）
    """
    if not stopped_vehicles:
        return 0.0

    max_dist = 0.0

    if stop_line is not None and H is not None:
        # 世界坐标：到停车线的距离
        sl_pts = np.array(stop_line, dtype=np.float64)
        sl_world = pixel_to_world(sl_pts, H)
        sl_world_line = LineString(sl_world)

        for v in stopped_vehicles:
            cx, cy = v["bbox_center_px"]
            world_pt = pixel_to_world(np.array([[cx, cy]]), H)[0]
            dist_m = sl_world_line.distance(Point(world_pt[0], world_pt[1]))
            max_dist = max(max_dist, dist_m)

    elif H is not None and len(stopped_vehicles) >= 2:
        # 世界坐标：排队车辆间最大距离
        centers = np.array([v["bbox_center_px"] for v in stopped_vehicles], dtype=np.float64)
        world_pts = pixel_to_world(centers, H)
        for i in range(len(world_pts)):
            for j in range(i + 1, len(world_pts)):
                dist = float(np.linalg.norm(world_pts[i] - world_pts[j]))
                max_dist = max(max_dist, dist)

    elif len(stopped_vehicles) >= 2:
        # 像素距离回退
        centers = [v["bbox_center_px"] for v in stopped_vehicles]
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                dx = centers[i][0] - centers[j][0]
                dy = centers[i][1] - centers[j][1]
                dist_px = (dx * dx + dy * dy) ** 0.5
                max_dist = max(max_dist, dist_px)

    return max_dist


def segment_queues_by_gap(
    queued_vehicles_world: list[dict],
    gap_threshold_m: float = 8.0,
) -> list[list[dict]]:
    """基于间隙将排队车辆分段。

    Args:
        queued_vehicles_world: 按到停车线距离排序的车辆列表
        gap_threshold_m: 间隙阈值（米），超过则视为不同队列

    Returns:
        队列段列表
    """
    if not queued_vehicles_world:
        return []

    sorted_v = sorted(queued_vehicles_world, key=lambda v: v.get("dist_to_stopline", 0))
    queues: list[list[dict]] = [[sorted_v[0]]]

    for i in range(1, len(sorted_v)):
        gap = sorted_v[i]["dist_to_stopline"] - sorted_v[i - 1]["dist_to_stopline"]
        if gap > gap_threshold_m:
            queues.append([])
        queues[-1].append(sorted_v[i])

    return queues
