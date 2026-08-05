import base64
import copy
import logging
import os

import cv2
import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.coordinates import enu_to_gcj02
from utils_local.homography import is_valid_homography, pixel_to_world, undistort_points
from utils_local.motion_compensation import pixel_to_world_compensated
from utils_local.utils import intersects_central_point, profile_time

logger = logging.getLogger("buffer_tracks")

DEFAULT_NON_MOTOR_CLASS_NAMES = {
    "pedestrian",
    "person",
    "people",
    "bicycle",
    "tricycle",
    "awning-tricycle",
    "motor",
    "motorcycle",
    "motorbike",
    "e-bike",
    "electric-bike",
    "electric-bicycle",
    "ebike",
    "scooter",
    "electric-scooter",
}
DEFAULT_NON_MOTOR_CLASS_IDS = {0, 1, 2, 6, 7, 9}


def _normalize_class_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _configured_non_motor_sets(classification_cfg: dict | None = None) -> tuple[set[str], set[int]]:
    cfg = classification_cfg or {}
    class_names = cfg.get("non_motor_class_names", DEFAULT_NON_MOTOR_CLASS_NAMES)
    class_ids = cfg.get("non_motor_class_ids", DEFAULT_NON_MOTOR_CLASS_IDS)
    non_motor_names = {_normalize_class_name(str(name)) for name in class_names}
    non_motor_ids = {int(class_id) for class_id in class_ids}
    return non_motor_names, non_motor_ids


def classify_vehicle(
    yolo_class_id: int | None,
    yolo_class_name: str | None = None,
    classification_cfg: dict | None = None,
) -> str:
    """根据配置的非机动车类别分类；未配置但有类别信息时默认机动车。"""
    non_motor_names, non_motor_ids = _configured_non_motor_sets(classification_cfg)
    if yolo_class_name:
        normalized = _normalize_class_name(yolo_class_name)
        if normalized in non_motor_names:
            return "non_motor"
        return "motor"
    if yolo_class_id is None:
        return "unknown"
    if yolo_class_id in non_motor_ids:
        return "non_motor"
    return "motor"


class TrackerInfoUpdateNode:
    """活动跟踪更新模块"""

    def __init__(self, config: dict) -> None:
        self.buffer_tracks = {}  # 生命周期尚未结束的活动轨迹
        self.legacy_max_lost_sec = float(
            config.get("tracking_node", {}).get("max_lost_sec", 2.0)
        )

        # 完成轨迹归档参数。实时目标不使用这些门槛：检测关联首次出现
        # 即进入 mature/active；短轨迹只在结束归档时被过滤。
        trajectory_cfg = config.get("trajectory", {})
        self.min_track_duration = trajectory_cfg.get("min_track_duration_sec", 2.0)
        self.min_trajectory_points = 5
        self.vehicle_classification_cfg = config.get("vehicle_classification", {})
        self.class_mapping_version = self.vehicle_classification_cfg.get(
            "mapping_version", "vehicle-classification/v1"
        )
        self._ever_mature_track_ids: set[int] = set()
        self._regressed_candidate_track_ids: set[int] = set()
        self._same_id_mature_to_candidate_count = 0
        self._completed_track_ids: set[int] = set()
        self._last_frame_element: FrameElement | None = None

    def flush(
        self,
        timestamp: float,
        reason: str,
        terminated_track_ids: list[int] | None = None,
    ) -> FrameElement | None:
        """Serialize every remaining formal business track at a terminal boundary."""
        if not self.buffer_tracks or self._last_frame_element is None:
            self.buffer_tracks.clear()
            return None
        frame_element = copy.copy(self._last_frame_element)
        frame_element.timestamp = max(
            float(timestamp), float(self._last_frame_element.timestamp)
        )
        frame_element.frame = None
        frame_element.dist_coeffs = None
        frame_element.id_list = []
        frame_element.tracked_xyxy = []
        frame_element.tracked_cls = []
        frame_element.tracked_cls_ids = []
        frame_element.tracked_conf = []
        frame_element.formal_track_ids = []
        frame_element.tracking_diagnostics = {
            **(getattr(frame_element, "tracking_diagnostics", None) or {}),
            "terminated_track_ids": (
                terminated_track_ids
                if terminated_track_ids is not None
                else sorted(self.buffer_tracks)
            ),
            "termination_reason": reason,
        }
        flushed = self.process(frame_element)
        self._last_frame_element = None
        return flushed

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        # 如果输入是VideoEndBreakElement而不是FrameElement，则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"TrackerInfoUpdateNode | 输入元素格式错误 {type(frame_element)}"

        quality_is_explicit = getattr(frame_element, "geo_reference_quality", None) is not None
        trajectory_eligible = bool(
            getattr(frame_element, "trajectory_output_eligible", False)
        )
        trajectory_association_ids = getattr(
            frame_element, "trajectory_association_ids", None
        )
        allowed_ids = (
            set(trajectory_association_ids)
            if trajectory_association_ids is not None
            else None
        )
        all_id_list = frame_element.id_list or []
        tracking_entries = (
            list(enumerate(all_id_list))
            if (trajectory_eligible or not quality_is_explicit)
            else []
        )
        if allowed_ids is not None:
            tracking_entries = [
                (index, track_id)
                for index, track_id in tracking_entries
                if track_id in allowed_ids
            ]
        tracked_cls_ids = getattr(frame_element, "tracked_cls_ids", None)
        tracked_cls_names = getattr(frame_element, "tracked_cls", None)
        track_id_by_association = (
            getattr(frame_element, "track_id_by_association", None)
            or getattr(frame_element, "formal_track_id_by_association", None)
            or {}
        )
        previous_formal_id_by_association = (
            getattr(frame_element, "previous_formal_track_id_by_association", None)
            or {}
        )
        tracking_diagnostics = getattr(frame_element, "tracking_diagnostics", None) or {}
        post_tracking_world_projection = (
            tracking_diagnostics.get("world_projection_stage") == "post_bytetrack"
        )
        association_trajectory_by_id = {
            int(item.get("association_id", item.get("track_id"))): item
            for item in (
                getattr(frame_element, "association_trajectories", None) or []
            )
            if item.get("association_id", item.get("track_id")) is not None
        }

        for i, association_id in tracking_entries:
            id = int(track_id_by_association.get(association_id, association_id))
            # 更新或创建新跟踪
            if id not in self.buffer_tracks:
                # 创建新键
                self.buffer_tracks[id] = TrackElement(
                    id=id,
                    timestamp_first=frame_element.timestamp,
                )
                self.buffer_tracks[id].trajectory_output_eligible = True
                self.buffer_tracks[id].association_id = int(association_id)
                self.buffer_tracks[id].track_family_id = (
                    f"association:{int(association_id)}"
                )
                self.buffer_tracks[id].previous_track_id = (
                    previous_formal_id_by_association.get(association_id)
                )
                # 设置YOLO原始类别和车辆分类
                if tracked_cls_ids and i < len(tracked_cls_ids):
                    self.buffer_tracks[id].yolo_class_id = tracked_cls_ids[i]
                    class_name = (
                        tracked_cls_names[i]
                        if tracked_cls_names and i < len(tracked_cls_names)
                        else None
                    )
                    self.buffer_tracks[id].yolo_class_name = class_name
                    self.buffer_tracks[id].yolo_model_id = getattr(
                        frame_element, "yolo_model_id", None
                    )
                    self.buffer_tracks[id].class_mapping_version = self.class_mapping_version
                    self.buffer_tracks[id].vehicle_class = classify_vehicle(
                        tracked_cls_ids[i],
                        class_name,
                        self.vehicle_classification_cfg,
                    )
                    self.buffer_tracks[id].class_id_history.append(tracked_cls_ids[i])
            else:
                # 更新最后检测时间
                self.buffer_tracks[id].update(frame_element.timestamp)
                # 累积分类历史用于多帧投票
                if tracked_cls_ids and i < len(tracked_cls_ids):
                    self.buffer_tracks[id].class_id_history.append(tracked_cls_ids[i])

            track = self.buffer_tracks[id]
            track.tracking_method = tracking_diagnostics.get(
                "tracking_method", track.tracking_method
            )
            track.tracking_quality = tracking_diagnostics.get(
                "tracking_quality", track.tracking_quality
            )
            track.geo_analytics_eligible = track.geo_analytics_eligible or bool(
                frame_element.geo_analytics_eligible
            )
            track.road_analytics_eligible = track.road_analytics_eligible or bool(
                frame_element.road_analytics_eligible
            )
            track.tcc_analytics_eligible = track.tcc_analytics_eligible or bool(
                frame_element.tcc_analytics_eligible
            )
            track.road_context_status = getattr(
                frame_element, "road_context_status", track.road_context_status
            )
            geo_quality = getattr(frame_element, "geo_reference_quality", None) or {}
            track.geo_reference_quality = geo_quality.get(
                "geo_status", geo_quality.get("status", "degraded")
            )
            track.quality_reasons = list(
                dict.fromkeys([*track.quality_reasons, *(geo_quality.get("reasons") or [])])
            )
            phase = getattr(frame_element, "flight_phase", None)
            if phase and (not track.flight_phases or track.flight_phases[-1] != phase):
                track.flight_phases.append(phase)
            segment_id = getattr(frame_element, "flight_segment_id", None)
            if segment_id and segment_id not in track.flight_segment_ids:
                track.flight_segment_ids.append(segment_id)

            # 累积轨迹点（bbox中心像素坐标）
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            self.buffer_tracks[id].trajectory_points.append((cx, cy))
            self.buffer_tracks[id].trajectory_timestamps_sec.append(frame_element.timestamp)
            self.buffer_tracks[id].trajectory_frame_nums.append(int(frame_element.frame_num))
            if (
                os.environ.get("TRAJECTORY_STORAGE_PROFILE") == "replay_v2"
                and frame_element.frame is not None
            ):
                confidence = float(
                    frame_element.tracked_conf[i]
                    if getattr(frame_element, "tracked_conf", None) and i < len(frame_element.tracked_conf)
                    else 0.0
                )
                if confidence > track.appearance_crop_confidence:
                    height, width = frame_element.frame.shape[:2]
                    x1 = max(0, min(width, int(round(bbox[0]))))
                    y1 = max(0, min(height, int(round(bbox[1]))))
                    x2 = max(0, min(width, int(round(bbox[2]))))
                    y2 = max(0, min(height, int(round(bbox[3]))))
                    if x2 > x1 and y2 > y1:
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            frame_element.frame[y1:y2, x1:x2],
                            [int(cv2.IMWRITE_JPEG_QUALITY), 80],
                        )
                        if ok:
                            track.appearance_crop_jpeg = base64.b64encode(encoded).decode("ascii")
                            track.appearance_crop_confidence = confidence
            track.point_quality_lineage.append(
                {
                    "timestamp_sec": frame_element.timestamp,
                    "frame_num": int(frame_element.frame_num),
                    "flight_phase": phase,
                    "flight_segment_id": segment_id,
                    "geo_reference_quality": geo_quality.get(
                        "geo_status", geo_quality.get("status")
                    ),
                    "tracking_quality": track.tracking_quality,
                }
            )

            # Canonical trajectory geometry uses the vehicle ground-contact point
            # and is projected with the transform of this exact frame.  Keeping
            # these points incrementally avoids reprojecting history with a later
            # camera pose when the track completes.
            ground_x = cx
            ground_y = float(bbox[3])
            track = self.buffer_tracks[id]
            # Map lineage belongs to road matching only. Unmatched tracks may
            # retain the selected map version without making world projection
            # depend on it.
            if getattr(frame_element, "map_version_id", None):
                track.map_version_id = frame_element.map_version_id
            track.ground_contact_points_px.append((ground_x, ground_y))
            absolute_H = getattr(frame_element, "pixel_to_world_enu", None)
            H = frame_element.homography_matrix
            drone_disp = getattr(frame_element, "drone_displacement_m", None)
            anchor_gcj02 = getattr(frame_element, "anchor_gcj02", None)
            can_use_absolute = is_valid_homography(absolute_H)
            can_use_legacy = is_valid_homography(H) and drone_disp is not None
            projected_trajectory = association_trajectory_by_id.get(
                int(association_id), {}
            )
            projected_world_history = projected_trajectory.get(
                "trajectory_enu_m"
            ) or []
            projected_world_point = (
                projected_world_history[-1] if projected_world_history else None
            )
            projected_gcj02_history = projected_trajectory.get(
                "trajectory_gcj02"
            ) or []
            projected_gcj02_point = (
                projected_gcj02_history[-1]
                if projected_gcj02_history
                else None
            )
            if post_tracking_world_projection and projected_world_point is not None:
                point_enu = (
                    float(projected_world_point[0]),
                    float(projected_world_point[1]),
                )
                track.trajectory_enu_m.append(point_enu)
                track.position_history_enu_m.append(
                    (point_enu[0], point_enu[1], frame_element.timestamp)
                )
                if projected_gcj02_point is not None:
                    track.trajectory_gcj02.append(
                        (
                            float(projected_gcj02_point[0]),
                            float(projected_gcj02_point[1]),
                        )
                    )
                track.current_position_enu_m = [point_enu[0], point_enu[1]]
            elif post_tracking_world_projection:
                track.trajectory_enu_m.append(None)
                track.trajectory_gcj02.append(None)
            elif not post_tracking_world_projection and (
                can_use_absolute or can_use_legacy
            ):
                ground_px = np.asarray([[ground_x, ground_y]], dtype=np.float64)
                dist_coeffs = getattr(frame_element, "dist_coeffs", None)
                cam_intrinsics = getattr(frame_element, "camera_intrinsics", None)
                if dist_coeffs and cam_intrinsics:
                    ground_px = undistort_points(
                        ground_px,
                        cam_intrinsics,
                        (frame_element.frame.shape[1], frame_element.frame.shape[0]),
                        dist_coeffs,
                    )
                world = (
                    pixel_to_world(ground_px, absolute_H)[0]
                    if can_use_absolute
                    else pixel_to_world_compensated(ground_px, H, drone_disp)[0]
                )
                point_enu = (float(world[0]), float(world[1]))
                track.trajectory_enu_m.append(point_enu)
                track.position_history_enu_m.append(
                    (point_enu[0], point_enu[1], frame_element.timestamp)
                )
                if anchor_gcj02:
                    track.trajectory_gcj02.append(
                        enu_to_gcj02(point_enu[0], point_enu[1], anchor_gcj02)
                    )
                track.current_position_enu_m = [point_enu[0], point_enu[1]]

            # One canonical index spans pixel, source time, frame number, ENU
            # and GCJ-02. Missing enrichment is represented by null rather than
            # shortening a coordinate array.
            while len(track.trajectory_enu_m) < len(track.trajectory_points):
                track.trajectory_enu_m.append(None)
            while len(track.trajectory_gcj02) < len(track.trajectory_points):
                track.trajectory_gcj02.append(None)

            # 累积position_history（含时间戳，供SpeedEstimationNode和DirectionFlowNode使用）
            self.buffer_tracks[id].position_history.append((cx, cy, frame_element.timestamp))
            # 限制position_history大小（SpeedEstimationNode会进一步裁剪到history_frames）
            if len(self.buffer_tracks[id].position_history) > 60:
                self.buffer_tracks[id].position_history = self.buffer_tracks[id].position_history[-60:]
            if len(self.buffer_tracks[id].position_history_enu_m) > 60:
                self.buffer_tracks[id].position_history_enu_m = (
                    self.buffer_tracks[id].position_history_enu_m[-60:]
                )

            # 出口道路检测：车辆从一条道路移动到另一条道路时记录exit_road
            current_road = intersects_central_point(
                tracked_xyxy=frame_element.tracked_xyxy[i],
                polygons=frame_element.roads_info,
            )
            track = self.buffer_tracks[id]
            if (current_road is not None
                    and track.start_road is not None
                    and current_road != track.start_road
                    and track.exit_road is None):
                track.exit_road = current_road

            # 寻找与道路多边形的第一次交集
            if self.buffer_tracks[id].start_road is None:
                self.buffer_tracks[id].start_road = intersects_central_point(
                    tracked_xyxy=frame_element.tracked_xyxy[i],
                    polygons=frame_element.roads_info,
                )
                # 检查函数是否最终提供了实际的道路编号：
                if self.buffer_tracks[id].start_road is not None:
                    # 然后保存该时刻：
                    self.buffer_tracks[id].timestamp_init_road = frame_element.timestamp

        for track in self.buffer_tracks.values():
            # Realtime lifecycle has no candidate cooldown: every association
            # accepted by the image tracker is a target on its first sighting.
            track.trajectory_output_eligible = True
            self._ever_mature_track_ids.add(int(track.id))

        # 统计窗口不得结束图像轨迹。新版链路只消费显式终止事实；legacy
        # 回滚链路没有该事实，因此仅按最后观测时间清理已离开当前帧的轨迹。
        keys_to_remove = []
        termination_reason = tracking_diagnostics.get("termination_reason")
        if not post_tracking_world_projection:
            current_ids = {
                int(track_id_by_association.get(association_id, association_id))
                for association_id in all_id_list
            }
            for key, track_element in self.buffer_tracks.items():
                if (
                    key not in current_ids
                    and frame_element.timestamp - track_element.timestamp_last
                    > self.legacy_max_lost_sec
                ):
                    track_element.termination_reason = "association_timeout"
                    termination_reason = termination_reason or "association_timeout"
                    keys_to_remove.append(key)

        terminated_track_ids = set(tracking_diagnostics.get("terminated_track_ids") or [])
        for key in terminated_track_ids:
            if key in self.buffer_tracks:
                self.buffer_tracks[key].termination_reason = termination_reason
                if key not in keys_to_remove:
                    keys_to_remove.append(key)

        # 发射完成轨迹数据（供下游节点使用）
        # 运动补偿数据（用于世界坐标转换）
        H = frame_element.homography_matrix
        has_H = is_valid_homography(H)
        drone_disp = getattr(frame_element, "drone_displacement_m", None)
        anchor_gcj02 = getattr(frame_element, "anchor_gcj02", None)
        can_convert_world = has_H and drone_disp is not None

        # 镜头畸变校正数据
        dist_coeffs = getattr(frame_element, "dist_coeffs", None)
        cam_intrinsics = getattr(frame_element, "camera_intrinsics", None)
        img_size = (frame_element.frame.shape[1], frame_element.frame.shape[0]) if dist_coeffs else None

        completed_tracks = []
        for key in keys_to_remove:
            track = self.buffer_tracks[key]
            duration = track.timestamp_last - track.timestamp_first
            if (
                duration >= self.min_track_duration
                and len(track.trajectory_points) >= self.min_trajectory_points
                and bool(track.termination_reason)
                and int(track.id) not in self._completed_track_ids
            ):
                # 多帧分类投票：用轨迹生命周期内积累的类别历史重新判定最终分类
                if track.class_id_history:
                    from collections import Counter
                    voted_class_id = Counter(track.class_id_history).most_common(1)[0][0]
                    track.yolo_class_id = voted_class_id
                    track.vehicle_class = classify_vehicle(
                        voted_class_id,
                        track.yolo_class_name,
                        self.vehicle_classification_cfg,
                    )
                completed_track_data = {
                    "track_id": track.id,
                    "start_road": track.start_road,
                    "exit_road": track.exit_road,
                    "turn_behavior": track.turn_behavior,
                    "vehicle_class": track.vehicle_class,
                    "yolo_class_id": track.yolo_class_id,
                    "yolo_class_name": track.yolo_class_name,
                    "yolo_model_id": track.yolo_model_id,
                    "class_mapping_version": track.class_mapping_version,
                    "duration_sec": round(duration, 2),
                    "avg_speed_kmh": (
                        round(track.avg_speed_kmh, 1)
                        if track.avg_speed_kmh is not None
                        else None
                    ),
                    "max_speed_kmh": (
                        round(track.max_speed_kmh, 1)
                        if track.max_speed_kmh is not None
                        else None
                    ),
                    # Canonical pixel geometry uses the same vehicle ground-contact
                    # anchor as ENU/GCJ-02. Bbox centers remain available explicitly
                    # for legacy visualization and diagnostics.
                    "trajectory_px": track.ground_contact_points_px,
                    "trajectory_bbox_center_px": track.trajectory_points,
                    "ground_contact_points_px": track.ground_contact_points_px,
                    "trajectory_timestamps_sec": track.trajectory_timestamps_sec,
                    "trajectory_frame_nums": track.trajectory_frame_nums,
                    "trajectory_time_offsets_sec": [
                        round(value - track.timestamp_first, 3)
                        for value in track.trajectory_timestamps_sec
                    ],
                    "timestamp_first": track.timestamp_first,
                    "timestamp_last": track.timestamp_last,
                    "map_version_id": track.map_version_id,
                    "matched_lane_key": track.matched_lane_key,
                    "source_lane_id": track.source_lane_id,
                    "matched_link_id": track.matched_link_id,
                    "movement_key": track.movement_key,
                    "map_match_confidence": track.map_match_confidence,
                    "tracking_method": track.tracking_method,
                    "tracking_quality": track.tracking_quality,
                    "flight_phases": track.flight_phases,
                    "flight_segment_ids": track.flight_segment_ids,
                    "termination_reason": track.termination_reason,
                    "track_family_id": track.track_family_id,
                    "previous_track_id": track.previous_track_id,
                    "point_quality_lineage": track.point_quality_lineage,
                    "trajectory_output_eligible": True,
                    "geo_analytics_eligible": track.geo_analytics_eligible,
                    "road_analytics_eligible": track.road_analytics_eligible,
                    "tcc_analytics_eligible": track.tcc_analytics_eligible,
                    "geo_reference_quality": track.geo_reference_quality,
                    "road_match_quality": track.road_match_quality,
                    "quality_reasons": track.quality_reasons,
                    "road_context_status": track.road_context_status,
                    "quality_status": (
                        "verified" if track.road_analytics_eligible else "degraded"
                    ),
                    "formal_analytics_eligible": track.road_analytics_eligible,
                }
                if track.appearance_crop_jpeg:
                    completed_track_data["appearance_crop_jpeg"] = track.appearance_crop_jpeg
                if track.association_id is not None:
                    completed_track_data["association_id"] = int(
                        track.association_id
                    )

                completed_track_data["trajectory_enu_m"] = [
                    [round(point[0], 2), round(point[1], 2)]
                    if point is not None
                    else None
                    for point in track.trajectory_enu_m
                ]
                completed_track_data["trajectory_gcj02"] = [
                    [round(point[0], 8), round(point[1], 8)]
                    if point is not None
                    else None
                    for point in track.trajectory_gcj02
                ]
                valid_enu = [
                    point
                    for point in completed_track_data["trajectory_enu_m"]
                    if point is not None
                ]
                if valid_enu:
                    completed_track_data["entry_point_enu_m"] = valid_enu[0]
                    completed_track_data["exit_point_enu_m"] = valid_enu[-1]

                # 入口/出口点世界坐标
                if (
                    can_convert_world
                    and track.ground_contact_points_px
                    and not any(point is not None for point in track.trajectory_enu_m)
                    and not post_tracking_world_projection
                ):
                    entry_px = np.array([track.ground_contact_points_px[0]], dtype=np.float64)
                    exit_px = np.array([track.ground_contact_points_px[-1]], dtype=np.float64)
                    # 镜头畸变校正
                    if dist_coeffs and cam_intrinsics and img_size:
                        entry_px = undistort_points(entry_px, cam_intrinsics, img_size, dist_coeffs)
                        exit_px = undistort_points(exit_px, cam_intrinsics, img_size, dist_coeffs)
                    entry_world = pixel_to_world_compensated(entry_px, H, drone_disp)[0]
                    exit_world = pixel_to_world_compensated(exit_px, H, drone_disp)[0]
                    completed_track_data["entry_point_enu_m"] = [
                        round(float(entry_world[0]), 2), round(float(entry_world[1]), 2)
                    ]
                    completed_track_data["exit_point_enu_m"] = [
                        round(float(exit_world[0]), 2), round(float(exit_world[1]), 2)
                    ]
                    if anchor_gcj02:
                        completed_track_data["anchor_gcj02"] = [
                            round(anchor_gcj02[0], 6), round(anchor_gcj02[1], 6)
                        ]

                completed_tracks.append(completed_track_data)
                self._completed_track_ids.add(int(track.id))
            self.buffer_tracks.pop(key)  # 从字典中删除元素
            # A sparse replay can retire thousands of short-lived tracks at EOF.
            # Keep the per-track detail available for diagnostics without flooding
            # the mission subprocess tail and hiding the actual failure traceback.
            logger.debug(f"Removed tracker with key {key}")

        candidate_trajectories = [
            {
                "track_id": track.id,
                "association_id": track.association_id,
                "tracking_method": track.tracking_method,
                "tracking_quality": track.tracking_quality,
                "trajectory_output_eligible": False,
                "trajectory_px": [list(point) for point in track.ground_contact_points_px],
                "trajectory_enu_m": [
                    list(point) if point is not None else None
                    for point in track.trajectory_enu_m
                ],
                "trajectory_gcj02": [
                    list(point) if point is not None else None
                    for point in track.trajectory_gcj02
                ],
                "trajectory_timestamps_sec": list(track.trajectory_timestamps_sec),
                "trajectory_frame_nums": list(track.trajectory_frame_nums),
                "quality_reasons": list(track.quality_reasons),
            }
            for track in self.buffer_tracks.values()
            if not track.trajectory_output_eligible
        ]
        eligible_active_tracks = sum(
            track.trajectory_output_eligible for track in self.buffer_tracks.values()
        )
        candidate_track_ids = {
            int(track.id)
            for track in self.buffer_tracks.values()
            if not track.trajectory_output_eligible
        }
        newly_regressed_ids = (
            candidate_track_ids
            & self._ever_mature_track_ids
            - self._regressed_candidate_track_ids
        )
        if newly_regressed_ids:
            self._same_id_mature_to_candidate_count += len(newly_regressed_ids)
            self._regressed_candidate_track_ids.update(newly_regressed_ids)

        mature_tracks = {
            track_id: track
            for track_id, track in self.buffer_tracks.items()
            if track.trajectory_output_eligible
        }
        frame_element.trajectory_output_eligible = bool(
            eligible_active_tracks or completed_tracks
        )
        frame_element.candidate_trajectories = candidate_trajectories
        diagnostics = tracking_diagnostics
        diagnostics["trajectory_track_count"] = eligible_active_tracks
        diagnostics["candidate_track_count"] = len(candidate_trajectories)
        diagnostics["lifecycle"] = {
            "active_track_count": len(self.buffer_tracks),
            "mature_track_count": len(mature_tracks),
            "candidate_track_count": len(candidate_trajectories),
            "completed_track_count": len(completed_tracks),
            "same_id_mature_to_candidate_count": (
                self._same_id_mature_to_candidate_count
            ),
            "termination_reason": termination_reason,
        }
        frame_element.tracking_diagnostics = diagnostics

        # 记录处理结果：
        frame_element.buffer_tracks = self.buffer_tracks
        frame_element.active_tracks = self.buffer_tracks
        frame_element.mature_tracks = mature_tracks
        frame_element.mature_trajectory_association_ids = sorted(
            int(track.association_id)
            for track in mature_tracks.values()
            if track.association_id is not None
        )
        frame_element.completed_tracks = completed_tracks if completed_tracks else None
        self._last_frame_element = frame_element

        return frame_element
