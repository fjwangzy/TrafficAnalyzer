"""GeoJsonExportNode — 将 BEV 投影轨迹导出为 GeoJSON 文件。

收集管道中完成的轨迹（completed_tracks），将像素坐标经单应性矩阵
投影到 BEV（鸟瞰图）世界坐标后，以 GeoJSON LineString 格式写入
output 目录。

坐标系：公共 GeoJSON 固定为 GCJ-02；无 GCJ-02 锚点的轨迹不导出。
"""
import json
import logging
import math
import os
import time
from datetime import datetime, timezone

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.homography import is_valid_homography, undistort_points
from utils_local.motion_compensation import pixel_to_world_compensated
from utils_local.coordinates import enu_to_gcj02

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000


def enu_to_gps(
    easting_m: float,
    northing_m: float,
    anchor_lat: float,
    anchor_lon: float,
) -> tuple[float, float]:
    """东北偏移（米）→ GPS 经纬度。

    Returns:
        (latitude, longitude) in degrees
    """
    lat = anchor_lat + math.degrees(northing_m / EARTH_RADIUS_M)
    lon = anchor_lon + math.degrees(
        easting_m / (EARTH_RADIUS_M * math.cos(math.radians(anchor_lat)))
    )
    return lat, lon


class GeoJsonExportNode:
    """收集完成轨迹并在流结束（或定期）导出为 GeoJSON 文件。

    配置项（config["geojson_export"]）：
        enabled: bool              是否启用（默认 True）
        output_dir: str            输出目录（默认 "output"）
        filename: str              输出文件名（默认自动生成）
        export_interval_sec: float 定期导出间隔秒数，0=仅流结束时导出
        use_gps: bool              有锚点时是否转为 GPS 坐标（默认 True）
        include_metadata: bool     是否在 properties 中包含元数据（默认 True）
        simplify_tolerance_m: float 轨迹简化容忍度（米），0=不简化
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("geojson_export", {})
        self.enabled = cfg.get("enabled", True)
        self.output_dir = cfg.get("output_dir", "output")
        self.filename = cfg.get("filename", None)
        self.export_interval_sec = cfg.get("export_interval_sec", 0)
        self.use_gps = cfg.get("use_gps", True)
        self.include_metadata = cfg.get("include_metadata", True)
        self.simplify_tolerance_m = cfg.get("simplify_tolerance_m", 0.5)

        self._collected_tracks: list[dict] = []
        self._last_export_time = 0.0
        self._anchor_gcj02: tuple[float, float] | None = None
        self._export_count = 0

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)

    def _generate_filename(self) -> str:
        """生成带时间戳的文件名。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"trajectories_{ts}.geojson"

    def _collect_track(self, ct: dict, frame_element: FrameElement) -> dict:
        """收集一条完成轨迹的 BEV 投影数据。

        Returns:
            包含 BEV 坐标轨迹的字典，准备写入 GeoJSON。
        """
        anchor_gcj02 = ct.get("anchor_gcj02") or getattr(
            frame_element, "anchor_gcj02", None
        )

        # 记住锚点（取第一个有效值）
        if anchor_gcj02 and self._anchor_gcj02 is None:
            self._anchor_gcj02 = tuple(anchor_gcj02)

        # Completed tracks already own their point-wise world facts. Prefer the
        # canonical GCJ-02 sequence so EOF flushes never depend on a synthetic
        # current frame or reproject history through the final frame's H.
        geo_coordinates = [
            [round(float(point[0]), 8), round(float(point[1]), 8)]
            for point in (ct.get("trajectory_gcj02") or [])
            if isinstance(point, (list, tuple))
            and len(point) >= 2
            and point[0] is not None
            and point[1] is not None
            and math.isfinite(float(point[0]))
            and math.isfinite(float(point[1]))
        ]
        crs = "GCJ02"

        if len(geo_coordinates) < 2:
            trajectory_px = ct.get("trajectory_px", [])
            if (
                not trajectory_px
                or len(trajectory_px) < 2
                or frame_element.frame is None
            ):
                return None
            H = frame_element.homography_matrix
            drone_disp = getattr(frame_element, "drone_displacement_m", None)
            if not is_valid_homography(H) or drone_disp is None:
                return None
            img_h, img_w = frame_element.frame.shape[:2]
            pts_px = np.array(trajectory_px, dtype=np.float64)
            dist_coeffs = getattr(frame_element, "dist_coeffs", None)
            cam_intrinsics = getattr(frame_element, "camera_intrinsics", None)
            if dist_coeffs and cam_intrinsics:
                pts_px = undistort_points(
                    pts_px, cam_intrinsics, (img_w, img_h), dist_coeffs
                )
            bev_points = pixel_to_world_compensated(pts_px, H, drone_disp).tolist()
            if not self.use_gps or not anchor_gcj02:
                return None
            geo_coordinates = []
            for point in bev_points:
                lon, lat = enu_to_gcj02(point[0], point[1], anchor_gcj02)
                geo_coordinates.append([round(lon, 8), round(lat, 8)])

        if not geo_coordinates or len(geo_coordinates) < 2:
            return None

        # ── 轨迹简化（Douglas-Peucker 米级容忍度）─────────────
        if self.simplify_tolerance_m > 0 and len(geo_coordinates) > 5:
            geo_coordinates = self._simplify_linestring(
                geo_coordinates, self.simplify_tolerance_m
            )

        # ── 构建 GeoJSON Feature ────────────────────────────────
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": geo_coordinates,
            },
            "properties": {
                "track_id": ct.get("track_id"),
                "crs": crs,
            },
        }

        if self.include_metadata:
            props = feature["properties"]
            props.update({
                "start_road": ct.get("start_road"),
                "exit_road": ct.get("exit_road"),
                "turn_behavior": ct.get("turn_behavior"),
                "vehicle_class": ct.get("vehicle_class", "unknown"),
                "duration_sec": ct.get("duration_sec"),
                "avg_speed_kmh": ct.get("avg_speed_kmh"),
                "max_speed_kmh": ct.get("max_speed_kmh"),
                "timestamp_first": ct.get("timestamp_first"),
                "timestamp_last": ct.get("timestamp_last"),
                "point_count": len(geo_coordinates),
            })
            # 入口/出口世界坐标（米）
            if "entry_point_enu_m" in ct:
                props["entry_point_enu_m"] = ct["entry_point_enu_m"]
            if "exit_point_enu_m" in ct:
                props["exit_point_enu_m"] = ct["exit_point_enu_m"]
            # 世界锚点
            if anchor_gcj02:
                props["anchor_gcj02"] = [
                    round(anchor_gcj02[0], 6), round(anchor_gcj02[1], 6)
                ]

        return feature

    @staticmethod
    def _simplify_linestring(
        coords: list[list[float]], tolerance: float
    ) -> list[list[float]]:
        """Ramer-Douglas-Peucker 线简化算法。

        Args:
            coords: [[x, y], ...] 坐标序列
            tolerance: 距离容忍度（单位与坐标一致，通常为米）

        Returns:
            简化后的坐标序列（至少保留首尾两点）
        """
        if len(coords) <= 2:
            return coords

        def _point_line_distance(point, start, end):
            if start == end:
                return math.hypot(point[0] - start[0], point[1] - start[1])
            n = abs(
                (end[0] - start[0]) * (start[1] - point[1])
                - (start[0] - point[0]) * (end[1] - start[1])
            )
            d = math.hypot(end[0] - start[0], end[1] - start[1])
            return n / d if d > 0 else 0

        def _rdp(points, epsilon):
            dmax = 0.0
            index = 0
            for i in range(1, len(points) - 1):
                d = _point_line_distance(points[i], points[0], points[-1])
                if d > dmax:
                    index = i
                    dmax = d
            if dmax > epsilon:
                left = _rdp(points[: index + 1], epsilon)
                right = _rdp(points[index:], epsilon)
                return left[:-1] + right
            else:
                return [points[0], points[-1]]

        simplified = _rdp(coords, tolerance)
        # 确保至少保留首尾
        if len(simplified) < 2:
            return [coords[0], coords[-1]]
        return simplified

    def _export_geojson(self, reason: str = "periodic") -> str | None:
        """将收集的轨迹写入 GeoJSON 文件。

        Returns:
            输出文件路径，或 None（无数据时）。
        """
        if not self._collected_tracks:
            return None

        geojson = {
            "type": "FeatureCollection",
            "coordinate_system": "GCJ02",
            "features": self._collected_tracks,
            "metadata": {
                "description": "BEV-projectd vehicle trajectories from TrafficAnalyzer",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "track_count": len(self._collected_tracks),
                "source_crs": "pixel → homography → ENU meters → GCJ-02",
            },
        }

        fname = self.filename or self._generate_filename()
        filepath = os.path.join(self.output_dir, fname)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(geojson, f, indent=2, ensure_ascii=False)

        logger.info(
            f"GeoJsonExportNode: 导出 {len(self._collected_tracks)} 条轨迹 → "
            f"{filepath} ({reason})"
        )
        self._export_count += 1
        return filepath

    def process(self, frame_element: FrameElement) -> FrameElement:
        if not self.enabled:
            return frame_element

        # ── 流结束：最终导出 ────────────────────────────────────
        if isinstance(frame_element, VideoEndBreakElement):
            filepath = self._export_geojson(reason="stream_end")
            if filepath:
                logger.info(
                    f"GeoJsonExportNode: 最终导出完成，共 "
                    f"{self._export_count} 个文件"
                )
            return frame_element

        # ── 收集本帧完成轨迹 ────────────────────────────────────
        completed = getattr(frame_element, "completed_tracks", None)
        if completed:
            for ct in completed:
                feature = self._collect_track(ct, frame_element)
                if feature:
                    self._collected_tracks.append(feature)

        # ── 定期导出 ────────────────────────────────────────────
        if self.export_interval_sec > 0:
            now = time.time()
            if now - self._last_export_time > self.export_interval_sec:
                if self._collected_tracks:
                    self._export_geojson(reason="periodic")
                    self._last_export_time = now

        return frame_element
