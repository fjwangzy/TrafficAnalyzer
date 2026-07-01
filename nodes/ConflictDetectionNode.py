import logging
import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography

logger = logging.getLogger(__name__)


class ConflictDetectionNode:
    """机非冲突检测节点：基于未来轨迹预测检测机动车与非机动车冲突。

    需要单应性标定才能准确计算米级距离。无标定时跳过（避免误报）。
    双方在预测窗口内同刻进入碰撞半径，或路径交点到达时间差满足阈值时生成事件；
    当前距离较近但未来不碰撞时不再作为 conflict 上报。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("conflict_detection", {})
        self.enabled = cfg.get("enabled", True)
        self.prediction_horizon_sec = cfg.get("prediction_horizon_sec", 5.0)
        self.critical_horizon_sec = cfg.get("critical_horizon_sec", 3.0)
        self.sample_interval_sec = cfg.get("sample_interval_sec", 0.2)
        self.collision_radius_m = cfg.get("collision_radius_m", 2.0)
        self.arrival_time_tolerance_sec = cfg.get("arrival_time_tolerance_sec", 1.0)
        self.relative_speed_min_ms = cfg.get("relative_speed_min_ms", 0.5)
        self._reported_pair_severity: dict[tuple, str] = {}
        self._severity_rank = {"warning": 1, "critical": 2}

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            frame_element.conflict_events = []
            return frame_element

        H = frame_element.homography_matrix
        if not is_valid_homography(H):
            frame_element.conflict_events = []
            return frame_element

        # 分离机动车和非机动车轨迹
        motor_tracks = []
        non_motor_tracks = []
        for i, track_id in enumerate(frame_element.id_list):
            track = frame_element.buffer_tracks.get(track_id)
            if not track:
                continue
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            entry = {
                "track_id": track_id,
                "center_px": (cx, cy),
                "speed_kmh": track.avg_speed_kmh,
                "velocity_ms": self._velocity_ms(track),
                "vehicle_class": track.vehicle_class,
            }
            if track.vehicle_class == "motor":
                motor_tracks.append(entry)
            elif track.vehicle_class == "non_motor":
                non_motor_tracks.append(entry)

        # 冲突检测
        conflict_events = []
        live_track_ids = set(frame_element.buffer_tracks.keys())
        inactive_pairs = [
            k for k in self._reported_pair_severity
            if k[0] not in live_track_ids or k[1] not in live_track_ids
        ]
        for k in inactive_pairs:
            self._reported_pair_severity.pop(k, None)

        for motor in motor_tracks:
            for non_motor in non_motor_tracks:
                pair_key = (
                    min(motor["track_id"], non_motor["track_id"]),
                    max(motor["track_id"], non_motor["track_id"]),
                )
                # 计算当前世界坐标（无人机相对米制坐标）
                pts = pixel_to_world(
                    np.array([motor["center_px"], non_motor["center_px"]]), H
                )

                prediction = self._predict_collision(
                    pts[0],
                    pts[1],
                    motor["velocity_ms"],
                    non_motor["velocity_ms"],
                )
                if prediction is None:
                    continue

                severity = self._classify_severity(prediction["ttc_sec"])
                if severity and self._should_emit_pair(pair_key, severity):
                    event = {
                        "motor_id": motor["track_id"],
                        "non_motor_id": non_motor["track_id"],
                        "distance_m": round(prediction["distance_m"], 2),
                        "ttc_sec": round(prediction["ttc_sec"], 2),
                        "arrival_time_delta_sec": round(
                            prediction["arrival_time_delta_sec"], 2
                        ),
                        "severity": severity,
                        "motor_speed_kmh": round(motor["speed_kmh"], 1),
                    }
                    if "motor_arrival_ttc_sec" in prediction:
                        event["motor_arrival_ttc_sec"] = round(
                            prediction["motor_arrival_ttc_sec"], 2
                        )
                    if "non_motor_arrival_ttc_sec" in prediction:
                        event["non_motor_arrival_ttc_sec"] = round(
                            prediction["non_motor_arrival_ttc_sec"], 2
                        )

                    # 预测冲突点世界坐标（含运动补偿）
                    drone_disp = getattr(frame_element, "drone_displacement_m", None)
                    world_anchor = getattr(frame_element, "world_anchor_lat_lon", None)
                    if drone_disp is not None:
                        motor_world = prediction["motor_position_m"] + drone_disp
                        non_motor_world = prediction["non_motor_position_m"] + drone_disp
                        event["motor_position_m"] = [
                            round(float(motor_world[0]), 2),
                            round(float(motor_world[1]), 2),
                        ]
                        event["non_motor_position_m"] = [
                            round(float(non_motor_world[0]), 2),
                            round(float(non_motor_world[1]), 2),
                        ]
                        if world_anchor:
                            event["world_anchor_lat_lon"] = [
                                round(world_anchor[0], 6),
                                round(world_anchor[1], 6),
                            ]

                    conflict_events.append(event)
                    self._reported_pair_severity[pair_key] = severity

        frame_element.conflict_events = conflict_events
        return frame_element

    def _velocity_ms(self, track) -> np.ndarray | None:
        vel = getattr(track, "velocity_ms", None)
        if vel is None:
            return None
        arr = np.asarray(vel, dtype=np.float64)
        if arr.shape != (2,) or not np.all(np.isfinite(arr)):
            return None
        return arr

    def _predict_collision(
        self,
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray | None,
        non_motor_velocity_ms: np.ndarray | None,
    ) -> dict | None:
        if motor_velocity_ms is None or non_motor_velocity_ms is None:
            return None

        relative_vel = non_motor_velocity_ms - motor_velocity_ms
        relative_speed = float(np.linalg.norm(relative_vel))
        if relative_speed < self.relative_speed_min_ms:
            return None

        if self.prediction_horizon_sec <= 0 or self.sample_interval_sec <= 0:
            return None

        candidates = []

        same_time = self._predict_same_time_collision(
            motor_pos_m,
            non_motor_pos_m,
            motor_velocity_ms,
            non_motor_velocity_ms,
        )
        if same_time is not None:
            candidates.append(same_time)

        path_intersection = self._predict_path_intersection_collision(
            motor_pos_m,
            non_motor_pos_m,
            motor_velocity_ms,
            non_motor_velocity_ms,
        )
        if path_intersection is not None:
            candidates.append(path_intersection)

        if not candidates:
            return None

        return min(candidates, key=lambda item: item["ttc_sec"])

    def _predict_same_time_collision(
        self,
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray,
        non_motor_velocity_ms: np.ndarray,
    ) -> dict | None:
        """双方在同一预测时刻进入碰撞半径。"""

        times = np.arange(
            self.sample_interval_sec,
            self.prediction_horizon_sec + self.sample_interval_sec / 2.0,
            self.sample_interval_sec,
            dtype=np.float64,
        )
        if times.size == 0:
            return None

        motor_future = motor_pos_m[None, :] + times[:, None] * motor_velocity_ms[None, :]
        non_motor_future = (
            non_motor_pos_m[None, :] + times[:, None] * non_motor_velocity_ms[None, :]
        )
        distances = np.linalg.norm(motor_future - non_motor_future, axis=1)
        hit_indices = np.flatnonzero(distances <= self.collision_radius_m)
        if hit_indices.size == 0:
            return None

        idx = int(hit_indices[0])
        return {
            "ttc_sec": float(times[idx]),
            "distance_m": float(distances[idx]),
            "arrival_time_delta_sec": 0.0,
            "motor_position_m": motor_future[idx],
            "non_motor_position_m": non_motor_future[idx],
            "motor_arrival_ttc_sec": float(times[idx]),
            "non_motor_arrival_ttc_sec": float(times[idx]),
        }

    def _predict_path_intersection_collision(
        self,
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray,
        non_motor_velocity_ms: np.ndarray,
    ) -> dict | None:
        """交叉路口路径交点到达时间检测。

        对两条恒速预测射线求交点；双方到达同一空间交点的时间差
        小于配置阈值时视为冲突。平行/同向场景由同刻采样逻辑覆盖。
        """

        motor_speed = float(np.linalg.norm(motor_velocity_ms))
        non_motor_speed = float(np.linalg.norm(non_motor_velocity_ms))
        if (
            motor_speed < self.relative_speed_min_ms
            or non_motor_speed < self.relative_speed_min_ms
        ):
            return None

        matrix = np.column_stack((motor_velocity_ms, -non_motor_velocity_ms))
        det = float(np.linalg.det(matrix))
        if abs(det) < 1e-6:
            return None

        motor_ttc, non_motor_ttc = np.linalg.solve(
            matrix,
            non_motor_pos_m - motor_pos_m,
        )
        motor_ttc = float(motor_ttc)
        non_motor_ttc = float(non_motor_ttc)

        if motor_ttc <= 0 or non_motor_ttc <= 0:
            return None
        if (
            motor_ttc > self.prediction_horizon_sec
            or non_motor_ttc > self.prediction_horizon_sec
        ):
            return None

        arrival_delta = abs(motor_ttc - non_motor_ttc)
        if arrival_delta > self.arrival_time_tolerance_sec:
            return None

        conflict_point = motor_pos_m + motor_ttc * motor_velocity_ms
        return {
            "ttc_sec": max(motor_ttc, non_motor_ttc),
            "distance_m": 0.0,
            "arrival_time_delta_sec": arrival_delta,
            "motor_position_m": conflict_point,
            "non_motor_position_m": conflict_point,
            "motor_arrival_ttc_sec": motor_ttc,
            "non_motor_arrival_ttc_sec": non_motor_ttc,
        }

    def _classify_severity(self, ttc: float) -> str:
        """根据预测碰撞时间分类冲突严重度。"""
        if ttc <= self.critical_horizon_sec:
            return "critical"
        return "warning"

    def _should_emit_pair(self, pair_key: tuple, severity: str) -> bool:
        previous = self._reported_pair_severity.get(pair_key)
        if previous is None:
            return True
        return self._severity_rank[severity] > self._severity_rank[previous]
