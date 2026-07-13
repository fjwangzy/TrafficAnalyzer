import logging
import time as _time
import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography

logger = logging.getLogger(__name__)


class ConflictDetectionNode:
    """机非冲突检测节点：基于 near-miss 证据漏斗检测机非冲突。

    需要单应性标定才能准确计算米级距离。无标定时跳过（避免误报）。
    四层漏斗：碰撞预测 → 场景分类 → 避险证据 → 严重度分级。
    支持右转/左转专项场景和通用交汇场景（直行交叉、变道切入等）。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("conflict_detection", {})
        self.enabled = cfg.get("enabled", True)
        self.prediction_horizon_sec = cfg.get("prediction_horizon_sec", 5.0)
        self.critical_horizon_sec = cfg.get("critical_horizon_sec", 3.0)
        self.hard_ttc_sec = cfg.get("hard_ttc_sec", 2.0)
        self.hard_pet_sec = cfg.get("hard_pet_sec", 1.0)
        self.sample_interval_sec = cfg.get("sample_interval_sec", 0.2)
        self.collision_radius_m = cfg.get("collision_radius_m", 2.0)
        self.enable_same_time_cpa = cfg.get("enable_same_time_cpa", False)
        self.same_time_collision_radius_m = cfg.get(
            "same_time_collision_radius_m",
            min(self.collision_radius_m, 0.8),
        )
        self.arrival_time_tolerance_sec = cfg.get("arrival_time_tolerance_sec", 1.0)
        self.relative_speed_min_ms = cfg.get("relative_speed_min_ms", 0.5)
        self.min_history_points = cfg.get("min_history_points", 4)
        self.min_conflict_angle_deg = cfg.get("min_conflict_angle_deg", 30.0)
        self.max_conflict_angle_deg = cfg.get("max_conflict_angle_deg", 150.0)
        self.turn_angle_threshold_deg = cfg.get("turn_angle_threshold_deg", 45.0)
        self.min_turn_leg_m = cfg.get("min_turn_leg_m", 2.0)
        self.straight_angle_threshold_deg = cfg.get("straight_angle_threshold_deg", 25.0)
        self.hard_deceleration_ms2 = cfg.get("hard_deceleration_ms2", -3.0)
        self.hard_heading_change_deg = cfg.get("hard_heading_change_deg", 60.0)
        self.stop_speed_ms = cfg.get("stop_speed_ms", 1.0)
        self.moving_speed_ms = cfg.get("moving_speed_ms", 2.0)
        self.min_segment_speed_ms = cfg.get("min_segment_speed_ms", 0.2)
        self.max_pair_distance_m = cfg.get("max_pair_distance_m", 15.0)
        self.min_trajectory_length_m = cfg.get("min_trajectory_length_m", 3.0)
        self.emit_cooldown_sec = cfg.get("emit_cooldown_sec", 2.0)
        # (pair_key) -> {"severity": str, "timestamp": float}
        self._reported_pairs: dict[tuple, dict] = {}
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
            motion_profile = self._motion_profile(track, H)
            velocity_ms = self._prediction_velocity_ms(
                self._velocity_ms(track),
                motion_profile,
            )
            # 过滤从未真正移动过的车辆（纯 bbox 抖动噪声）
            # 用 max_speed_kmh 而非 avg_speed_kmh：急停过的车依然保留
            if track.max_speed_kmh < 5.0:
                continue
            # 过滤轨迹长度不足的目标（路边停靠车辆等），要求世界坐标累计位移 >= 阈值
            if len(track.position_history) >= 2:
                pts_px = np.array([(p[0], p[1]) for p in track.position_history])
                pts_world = pixel_to_world(pts_px, H)
                traj_length = float(np.sum(np.linalg.norm(np.diff(pts_world, axis=0), axis=1)))
                if traj_length < self.min_trajectory_length_m:
                    continue
            else:
                continue  # 位置点不足，无法判断轨迹
            entry = {
                "track_id": track_id,
                "center_px": (cx, cy),
                "speed_kmh": track.avg_speed_kmh,
                "velocity_ms": velocity_ms,
                "vehicle_class": track.vehicle_class,
                "motion_profile": motion_profile,
            }
            if track.vehicle_class == "motor":
                motor_tracks.append(entry)
            elif track.vehicle_class == "non_motor":
                non_motor_tracks.append(entry)

        # 冲突检测
        conflict_events = []
        now = frame_element.timestamp
        live_track_ids = set(frame_element.buffer_tracks.keys())
        inactive_pairs = [
            k for k in self._reported_pairs
            if k[0] not in live_track_ids or k[1] not in live_track_ids
        ]
        for k in inactive_pairs:
            self._reported_pairs.pop(k, None)

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

                # 距离预过滤：两车世界坐标距离 > 阈值，直接跳过
                pair_dist = float(np.linalg.norm(pts[0] - pts[1]))
                if pair_dist > self.max_pair_distance_m:
                    continue

                prediction = self._predict_collision(
                    pts[0],
                    pts[1],
                    motor["velocity_ms"],
                    non_motor["velocity_ms"],
                )
                if prediction is None:
                    continue

                scene = self._classify_scene(
                    motor["motion_profile"],
                    non_motor["motion_profile"],
                    prediction,
                )
                if scene is None:
                    continue

                evidence = self._collect_evidence(
                    prediction,
                    motor["motion_profile"],
                    non_motor["motion_profile"],
                    scene,
                )
                if not evidence:
                    continue

                severity = self._classify_severity(prediction, evidence, scene)
                if severity and self._should_emit_pair(pair_key, severity, now):
                    event = {
                        "motor_id": int(motor["track_id"]),
                        "non_motor_id": int(non_motor["track_id"]),
                        "prediction_type": prediction["prediction_type"],
                        "distance_m": round(prediction["distance_m"], 2),
                        "ttc_sec": round(prediction["ttc_sec"], 2),
                        "pet_sec": round(prediction["pet_sec"], 2),
                        "arrival_time_delta_sec": round(
                            prediction["arrival_time_delta_sec"], 2
                        ),
                        "severity": severity,
                        "conflict_scene": scene,
                        "conflict_angle_deg": round(prediction["conflict_angle_deg"], 1),
                        "evidence": evidence,
                        "risk_score": self._risk_score(prediction, evidence),
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
                    self._reported_pairs[pair_key] = {
                        "severity": severity, "timestamp": now
                    }

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

    def _prediction_velocity_ms(
        self,
        track_velocity_ms: np.ndarray | None,
        motion_profile: dict | None,
    ) -> np.ndarray | None:
        """有历史轨迹时，用最近轨迹方向预测；速度大小沿用测速节点。"""
        if motion_profile is None:
            return track_velocity_ms

        recent_velocity = motion_profile.get("recent_velocity_ms")
        if recent_velocity is None:
            return track_velocity_ms

        recent_velocity = np.asarray(recent_velocity, dtype=np.float64)
        recent_speed = float(np.linalg.norm(recent_velocity))
        if recent_velocity.shape != (2,) or recent_speed < self.relative_speed_min_ms:
            return track_velocity_ms

        speed = None
        if track_velocity_ms is not None:
            track_speed = float(np.linalg.norm(track_velocity_ms))
            if track_speed >= self.relative_speed_min_ms:
                speed = track_speed
        if speed is None:
            speed = recent_speed

        return recent_velocity / recent_speed * speed

    def _motion_profile(self, track, H) -> dict | None:
        history = getattr(track, "position_history", None) or []
        if len(history) < self.min_history_points:
            return None

        clean_history = [
            (float(x), float(y), float(t))
            for x, y, t in history
            if np.isfinite(x) and np.isfinite(y) and np.isfinite(t)
        ]
        if len(clean_history) < self.min_history_points:
            return None

        pts_px = np.array([(x, y) for x, y, _ in clean_history], dtype=np.float64)
        times = np.array([t for _, _, t in clean_history], dtype=np.float64)
        if np.any(np.diff(times) <= 0):
            return None

        pts_world = pixel_to_world(pts_px, H)
        deltas = np.diff(pts_world, axis=0)
        dt = np.diff(times)
        segment_velocities = deltas / dt[:, None]
        segment_speeds = np.linalg.norm(segment_velocities, axis=1)

        moving = segment_speeds >= self.min_segment_speed_ms
        if not np.any(moving):
            return None

        headings = np.full(segment_speeds.shape, np.nan, dtype=np.float64)
        headings[moving] = np.degrees(
            np.arctan2(segment_velocities[moving, 1], segment_velocities[moving, 0])
        )
        valid_headings = headings[np.isfinite(headings)]
        if valid_headings.size < 2:
            return None

        turn_angle = self._normalize_angle_deg(valid_headings[-1] - valid_headings[0])
        path_delta = pts_world[-1] - pts_world[0]
        first_heading_rad = np.radians(valid_headings[0])
        last_heading_rad = np.radians(valid_headings[-1])
        first_dir = np.array([np.cos(first_heading_rad), np.sin(first_heading_rad)])
        last_dir = np.array([np.cos(last_heading_rad), np.sin(last_heading_rad)])
        turn_leg_min = min(
            abs(float(np.dot(path_delta, first_dir))),
            abs(float(np.dot(path_delta, last_dir))),
        )
        heading_steps = np.array(
            [
                self._normalize_angle_deg(valid_headings[i] - valid_headings[i - 1])
                for i in range(1, valid_headings.size)
            ],
            dtype=np.float64,
        )
        max_heading_change = (
            float(np.max(np.abs(heading_steps))) if heading_steps.size else 0.0
        )

        acceleration = np.array([], dtype=np.float64)
        if segment_speeds.size >= 2:
            speed_dt = np.diff((times[:-1] + times[1:]) / 2.0)
            valid_dt = speed_dt > 0
            if np.any(valid_dt):
                acceleration = np.diff(segment_speeds)[valid_dt] / speed_dt[valid_dt]
        min_acceleration = (
            float(np.min(acceleration)) if acceleration.size else 0.0
        )

        recent_velocity = segment_velocities[moving][-1]
        current_velocity = self._prediction_velocity_ms(
            self._velocity_ms(track),
            {"recent_velocity_ms": recent_velocity},
        )
        if current_velocity is None:
            current_velocity = recent_velocity
        current_speed = float(np.linalg.norm(current_velocity))
        is_stopped = (
            current_speed <= self.stop_speed_ms
            and float(np.max(segment_speeds)) >= self.moving_speed_ms
        )

        return {
            "turn_angle_deg": float(turn_angle),
            "turn_leg_min_m": turn_leg_min,
            "max_heading_change_deg": max_heading_change,
            "min_acceleration_ms2": min_acceleration,
            "current_speed_ms": current_speed,
            "recent_velocity_ms": recent_velocity,
            "is_stopped": is_stopped,
            "is_straight": abs(turn_angle) <= self.straight_angle_threshold_deg,
        }

    def _predict_collision(
        self,
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray | None,
        non_motor_velocity_ms: np.ndarray | None,
    ) -> dict | None:
        if motor_velocity_ms is None or non_motor_velocity_ms is None:
            return None

        # 至少一方速度 >= 1 m/s（允许急停方接近 0）
        motor_speed = float(np.linalg.norm(motor_velocity_ms))
        non_motor_speed = float(np.linalg.norm(non_motor_velocity_ms))
        if motor_speed < 1.0 and non_motor_speed < 0.5:
            return None

        # 物理验证：两车必须真的在靠近（相对位置·相对速度 < 0）
        relative_position = non_motor_pos_m - motor_pos_m
        relative_vel = non_motor_velocity_ms - motor_velocity_ms
        closing_rate = float(np.dot(relative_position, relative_vel))
        if closing_rate >= 0:
            # 距离正在增大或保持不变，不可能碰撞
            return None

        conflict_angle = self._conflict_angle_deg(
            motor_velocity_ms,
            non_motor_velocity_ms,
        )
        if conflict_angle is None or not self._is_valid_conflict_angle(conflict_angle):
            return None

        # 过滤同向并行：冲突角度较小（< 60°）时，检查沿连线方向的接近速度
        # 同向并行车辆虽然 closing_rate < 0（微小横向漂移），但沿连线方向的
        # 实际接近速度很低，不构成碰撞风险
        if conflict_angle < 60.0:
            pair_vec = non_motor_pos_m - motor_pos_m
            pair_dist = float(np.linalg.norm(pair_vec))
            if pair_dist > 0.1:
                pair_dir = pair_vec / pair_dist
                # 沿连线方向的相对速度（正值=远离，负值=靠近）
                closing_along_line = float(np.dot(relative_vel, pair_dir))
                # 接近速度太低（< 1 m/s），视为并行通行
                if abs(closing_along_line) < 1.0:
                    return None

        relative_speed = float(np.linalg.norm(relative_vel))
        if relative_speed < self.relative_speed_min_ms:
            return None

        if self.prediction_horizon_sec <= 0 or self.sample_interval_sec <= 0:
            return None

        candidates = []

        if self.enable_same_time_cpa:
            same_time = self._predict_same_time_collision(
                motor_pos_m,
                non_motor_pos_m,
                motor_velocity_ms,
                non_motor_velocity_ms,
                conflict_angle,
            )
            if same_time is not None:
                candidates.append(same_time)

        path_intersection = self._predict_path_intersection_collision(
            motor_pos_m,
            non_motor_pos_m,
            motor_velocity_ms,
            non_motor_velocity_ms,
            conflict_angle,
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
        conflict_angle_deg: float,
    ) -> dict | None:
        """双方在同一预测时刻进入实际碰撞半径。"""

        relative_position = non_motor_pos_m - motor_pos_m
        relative_velocity = non_motor_velocity_ms - motor_velocity_ms
        relative_speed_sq = float(np.dot(relative_velocity, relative_velocity))
        if relative_speed_sq <= 1e-9:
            return None

        closest_time = -float(np.dot(relative_position, relative_velocity)) / relative_speed_sq
        if closest_time <= 0 or closest_time > self.prediction_horizon_sec:
            return None

        motor_future = motor_pos_m + closest_time * motor_velocity_ms
        non_motor_future = non_motor_pos_m + closest_time * non_motor_velocity_ms
        distance = float(np.linalg.norm(motor_future - non_motor_future))
        if distance > self.same_time_collision_radius_m:
            return None

        return {
            "prediction_type": "same_time_cpa",
            "ttc_sec": closest_time,
            "distance_m": distance,
            "pet_sec": 0.0,
            "arrival_time_delta_sec": 0.0,
            "conflict_angle_deg": conflict_angle_deg,
            "motor_position_m": motor_future,
            "non_motor_position_m": non_motor_future,
            "motor_arrival_ttc_sec": closest_time,
            "non_motor_arrival_ttc_sec": closest_time,
        }

    def _predict_path_intersection_collision(
        self,
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray,
        non_motor_velocity_ms: np.ndarray,
        conflict_angle_deg: float,
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
        min_same_time_distance = self._closest_same_time_distance_m(
            motor_pos_m,
            non_motor_pos_m,
            motor_velocity_ms,
            non_motor_velocity_ms,
            min(motor_ttc, non_motor_ttc),
            max(motor_ttc, non_motor_ttc),
        )
        if min_same_time_distance > self.same_time_collision_radius_m:
            return None

        return {
            "prediction_type": "path_intersection",
            "ttc_sec": max(motor_ttc, non_motor_ttc),
            "distance_m": 0.0,
            "pet_sec": arrival_delta,
            "arrival_time_delta_sec": arrival_delta,
            "conflict_angle_deg": conflict_angle_deg,
            "motor_position_m": conflict_point,
            "non_motor_position_m": conflict_point,
            "motor_arrival_ttc_sec": motor_ttc,
            "non_motor_arrival_ttc_sec": non_motor_ttc,
            "min_same_time_distance_m": min_same_time_distance,
        }

    @staticmethod
    def _closest_same_time_distance_m(
        motor_pos_m: np.ndarray,
        non_motor_pos_m: np.ndarray,
        motor_velocity_ms: np.ndarray,
        non_motor_velocity_ms: np.ndarray,
        start_time_sec: float,
        end_time_sec: float,
    ) -> float:
        """双方到达路径交点期间，连续同刻中心距的最小值。"""
        start = float(start_time_sec)
        end = float(end_time_sec)
        if end < start:
            start, end = end, start

        relative_position = non_motor_pos_m - motor_pos_m
        relative_velocity = non_motor_velocity_ms - motor_velocity_ms
        relative_speed_sq = float(np.dot(relative_velocity, relative_velocity))

        candidate_times = [start, end]
        if relative_speed_sq > 1e-9:
            closest_time = -float(np.dot(relative_position, relative_velocity)) / relative_speed_sq
            candidate_times.append(min(max(closest_time, start), end))

        distances = [
            float(np.linalg.norm(
                (non_motor_pos_m + t * non_motor_velocity_ms)
                - (motor_pos_m + t * motor_velocity_ms)
            ))
            for t in candidate_times
        ]
        return min(distances)

    def _classify_scene(
        self,
        motor_profile: dict | None,
        non_motor_profile: dict | None,
        prediction: dict,
    ) -> str | None:
        """场景分类：识别右转/左转专项场景和通用交汇场景。

        改进：不再要求机动车必须完成大角度转弯，也不再要求非机动车必须直行。
        只要至少一方在移动，即可进入通用交汇场景进行后续证据判定。
        """
        if motor_profile is None or non_motor_profile is None:
            return None

        # 至少一方在移动（双方都停着不算冲突）
        if (motor_profile["current_speed_ms"] < self.relative_speed_min_ms
                and non_motor_profile["current_speed_ms"] < self.relative_speed_min_ms):
            return None

        motor_turn = motor_profile["turn_angle_deg"]

        # 专项场景：机动车明确右转 + 非机动车近似直行
        if (motor_turn <= -self.turn_angle_threshold_deg
                and non_motor_profile["is_straight"]
                and motor_profile["turn_leg_min_m"] >= self.min_turn_leg_m):
            return "suspected_right_turn_mv_nmv"

        # 专项场景：机动车明确左转 + 非机动车近似直行
        if (motor_turn >= self.turn_angle_threshold_deg
                and non_motor_profile["is_straight"]
                and motor_profile["turn_leg_min_m"] >= self.min_turn_leg_m):
            return "suspected_unprotected_left_turn"

        # 通用交汇场景：直行交叉、变道切入、小角度汇流等
        return "general_crossing"

    def _collect_evidence(
        self,
        prediction: dict,
        motor_profile: dict | None,
        non_motor_profile: dict | None,
        scene: str = "",
    ) -> list[str]:
        evidence = []
        is_path_intersection = prediction.get("prediction_type") == "path_intersection"
        hard_ttc = prediction["ttc_sec"] <= self.hard_ttc_sec
        hard_pet = (
            is_path_intersection
            and prediction["pet_sec"] <= self.hard_pet_sec
        )
        if hard_ttc:
            evidence.append("hard_ttc_or_pet")
        if hard_pet:
            evidence.append("hard_pet")

        profiles = [p for p in (motor_profile, non_motor_profile) if p is not None]
        if any(
            p["min_acceleration_ms2"] <= self.hard_deceleration_ms2
            for p in profiles
        ):
            evidence.append("hard_deceleration")
        # 机动车右/左转本身会产生大 heading 变化，不能直接当作避险急转向。
        if (
            non_motor_profile is not None
            and non_motor_profile["max_heading_change_deg"] >= self.hard_heading_change_deg
        ):
            evidence.append("hard_steering")
        if any(p["is_stopped"] for p in profiles):
            evidence.append("stop_or_yield")

        behavior_evidence = {
            "hard_deceleration",
            "hard_steering",
            "stop_or_yield",
        }

        # 通用交汇场景要求更严格：必须有 hard_ttc/pet 证据，仅靠行为证据不够
        if scene == "general_crossing":
            if "hard_ttc_or_pet" in evidence or "hard_pet" in evidence:
                return evidence
            return []

        # 专项场景（右转/左转）：hard_ttc 或 任意行为证据即可
        if "hard_ttc_or_pet" in evidence or behavior_evidence.intersection(evidence):
            return evidence
        return []

    def _classify_severity(self, prediction: dict, evidence: list[str], scene: str = "") -> str:
        """根据 TTC/PET 和避险证据分类冲突严重度。"""
        # 通用交汇场景：只有 hard_ttc + 行为证据 才升级 critical
        if scene == "general_crossing":
            if "hard_ttc_or_pet" in evidence and (
                "hard_deceleration" in evidence
                or "hard_steering" in evidence
                or "stop_or_yield" in evidence
            ):
                return "critical"
            return "warning"

        # 专项场景（右转/左转）：沿用原逻辑
        if "hard_ttc_or_pet" in evidence:
            return "critical"
        if "hard_pet" in evidence and (
            "hard_deceleration" in evidence
            or "hard_steering" in evidence
            or "stop_or_yield" in evidence
        ):
            return "critical"
        if "hard_deceleration" in evidence or "stop_or_yield" in evidence:
            return "critical"
        return "warning"

    def _risk_score(self, prediction: dict, evidence: list[str]) -> int:
        score = 0
        if prediction["ttc_sec"] <= self.hard_ttc_sec:
            score += 40
        elif prediction["ttc_sec"] <= self.critical_horizon_sec:
            score += 25
        else:
            score += 10

        if (
            prediction.get("prediction_type") == "path_intersection"
            and prediction["pet_sec"] <= self.hard_pet_sec
        ):
            score += 30
        if "hard_deceleration" in evidence:
            score += 20
        if "stop_or_yield" in evidence:
            score += 20
        if "hard_steering" in evidence:
            score += 10
        return min(score, 100)

    def _conflict_angle_deg(
        self,
        motor_velocity_ms: np.ndarray,
        non_motor_velocity_ms: np.ndarray,
    ) -> float | None:
        motor_speed = float(np.linalg.norm(motor_velocity_ms))
        non_motor_speed = float(np.linalg.norm(non_motor_velocity_ms))
        if (
            motor_speed < self.relative_speed_min_ms
            or non_motor_speed < self.relative_speed_min_ms
        ):
            return None
        cos_theta = float(
            np.dot(motor_velocity_ms, non_motor_velocity_ms)
            / (motor_speed * non_motor_speed)
        )
        cos_theta = max(min(cos_theta, 1.0), -1.0)
        return float(np.degrees(np.arccos(cos_theta)))

    def _is_valid_conflict_angle(self, angle_deg: float) -> bool:
        return self.min_conflict_angle_deg <= angle_deg <= self.max_conflict_angle_deg

    @staticmethod
    def _normalize_angle_deg(angle: float) -> float:
        return (angle + 180.0) % 360.0 - 180.0

    def _should_emit_pair(self, pair_key: tuple, severity: str, now: float) -> bool:
        """基于时间冷却的去重：同级别每 emit_cooldown_sec 秒允许重发一次，升级则立即发出。"""
        previous = self._reported_pairs.get(pair_key)
        if previous is None:
            return True
        prev_severity = previous["severity"]
        prev_time = previous["timestamp"]
        # 严重度升级 → 立即发出
        if self._severity_rank.get(severity, 0) > self._severity_rank.get(prev_severity, 0):
            return True
        # 同级别 → 冷却期后允许重发
        if now - prev_time >= self.emit_cooldown_sec:
            return True
        return False
