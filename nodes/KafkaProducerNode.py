"""KafkaProducerNode — 异步发送 + 遥测发布 + 动态道路数 + 多因子拥堵指数

改进点（审查报告 T-101 / T-103 / T-201 / T-203）:
  T-101: 独立发送线程 + 有界队列，Kafka 不可用时不阻塞管道
  T-103: 新增 uav_telemetry_{N} topic，5Hz 节流发布遥测数据
  T-201: roads_activity 改为动态数组 [{"id": 1, "activity": 4.2}, ...]
  T-203: congestion_index 改为多因子计算 (车辆密度 + 排队 + 低速比例)
"""
import logging
import os
import time
import base64
import re
import uuid
from datetime import UTC, datetime

import cv2
from kafka import KafkaProducer
from json import dumps

from utils_local.utils import profile_time
from utils_local.coordinates import enu_to_gcj02, normalize_telemetry_position
from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.FrameElement import FrameElement
from nodes.ReliableKafkaPublisher import ReliableKafkaPublisher

logger = logging.getLogger(__name__)


def is_business_tcc_event(event: dict) -> bool:
    """Return whether an event belongs to the canonical path-intersection TCC count."""
    prediction_type = event.get("prediction_type")
    distance_m = event.get("distance_m")
    try:
        at_path_intersection = abs(float(distance_m)) <= 0.01
    except (TypeError, ValueError):
        at_path_intersection = False
    return at_path_intersection and prediction_type in {None, "path_intersection"}


class KafkaProducerNode:
    def __init__(self, config) -> None:
        config_kafka = config["kafka_producer_node"]
        bootstrap_servers = config_kafka["bootstrap_servers"]
        self.camera_id = config_kafka["camera_id"]
        self.drone_id = config_kafka.get("drone_id") or os.environ.get("DRONE_ID") or f"drone_{self.camera_id}"
        self.topic_name, self.track_complete_topic, self.conflicts_topic, self.telemetry_topic = (
            self._canonical_topics(self.camera_id)
        )
        self.how_often_sec = config_kafka["how_often_sec"]
        self.last_send_time = None
        self.kafka_producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda x: dumps(x).encode("utf-8"),
            # 增加重试和超时配置以提高可靠性
            retries=3,
            request_timeout_ms=5000,
        )

        self.mission_id = os.environ.get("MISSION_ID")
        self.pipeline_id = os.environ.get("PIPELINE_ID")
        self.run_id = os.environ.get("RUN_ID") or self.pipeline_id
        self.source_profile_id = os.environ.get("SOURCE_PROFILE_ID")
        self.inter_id = os.environ.get("INTER_ID") or os.environ.get("INTERSECTION_ID")
        self.road_data_version = os.environ.get("ROAD_DATA_VERSION")
        self.road_context_status = os.environ.get("ROAD_CONTEXT_STATUS", "missing")
        self.quality_status = os.environ.get("QUALITY_STATUS", "unverified")
        spool_dir = os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool")
        spool_name = re.sub(
            r"[^A-Za-z0-9_.-]", "_", self.pipeline_id or f"camera-{self.camera_id}"
        )
        self.publisher = ReliableKafkaPublisher(
            self.kafka_producer,
            os.path.join(spool_dir, spool_name),
            queue_size=int(config_kafka.get("send_queue_size", 200)),
        )

        self.buffer_analytics_sec = (
            config["general"]["buffer_analytics"] * 60 + config["general"]["min_time_life_track"]
        )  # 这是缓冲区积累的时间，过早输出统计信息还为时过早

        # ── FPS 计算（基于wall-clock滑动窗口）──
        self._fps_window_sec = 2.0
        self._fps_timestamps = []

        # intersection_id: use INTERSECTION_ID env var if set (from PipelineManager),
        # otherwise derive from camera_id (legacy mode for Docker camera containers)
        env_intersection_id = os.environ.get("INTERSECTION_ID")
        if env_intersection_id:
            self.intersection_id = env_intersection_id
        else:
            self.intersection_id = f"INT_camera_{self.camera_id}"

        # ── T-103: 遥测发布 ──
        self._telemetry_interval = 0.2  # 5Hz 节流
        self._last_telemetry_time = 0.0

        # ── T-203: 拥堵指数参数 ──
        # 路口设计通行能力（辆/分钟），用于归一化车辆密度因子
        # 可从配置覆盖，默认 30 veh/min（典型四向路口）
        self._capacity_veh_per_min = config.get("kafka_producer_node", {}).get(
            "capacity_veh_per_min", 30.0
        )
        # 排队长度阈值（米），超过视为严重排队
        self._queue_threshold_m = config.get("kafka_producer_node", {}).get(
            "queue_threshold_m", 80.0
        )
        # 自由流速度（km/h），用于计算低速因子
        self._free_flow_speed_kmh = config.get("kafka_producer_node", {}).get(
            "free_flow_speed_kmh", 40.0
        )
        self._snapshot_width = config.get("kafka_producer_node", {}).get(
            "annotation_snapshot_width", 960
        )
        self._snapshot_jpeg_quality = config.get("kafka_producer_node", {}).get(
            "annotation_snapshot_jpeg_quality", 75
        )
        self._hover_annotation_snapshot_enabled = bool(
            config.get("kafka_producer_node", {}).get(
                "hover_annotation_snapshot_enabled", True
            )
        )
        self._active_trajectory_tail_points = int(
            config.get("kafka_producer_node", {}).get("active_trajectory_tail_points", 30)
        )
        self._event_snapshot_congestion_threshold = float(
            config.get("kafka_producer_node", {}).get("event_snapshot_congestion_threshold", 4.0)
        )
        self._event_snapshot_consecutive_samples = int(
            config.get("kafka_producer_node", {}).get("event_snapshot_consecutive_samples", 30)
        )
        self._congestion_snapshot_count = 0

    @staticmethod
    def _canonical_topics(camera_id) -> tuple[str, str, str, str]:
        """Build the frozen camera-scoped Topic set without string derivation."""
        value = str(camera_id)
        if not value or len(value) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("camera_id contains unsupported Topic characters")
        return (
            f"uav_statistics_{value}",
            f"uav_track_complete_{value}",
            f"uav_conflicts_{value}",
            f"uav_telemetry_{value}",
        )

    def _canonical_envelope(
        self,
        msg_type: str,
        data: dict,
        frame_element: FrameElement,
    ) -> dict:
        """Wrap business data in the ADR-019 v1 message envelope."""
        produced_at = datetime.now(UTC)
        telemetry = getattr(frame_element, "telemetry", None) or {}
        recorded_at = telemetry.get("recorded_at")
        occurred_at = recorded_at or produced_at.isoformat()
        if recorded_at and getattr(frame_element, "source_is_realtime", False):
            semantics = "event_time"
            time_quality = "verified"
        elif recorded_at:
            semantics = "reconstructed"
            time_quality = "reconstructed"
        else:
            semantics = "consumer_time"
            time_quality = "ingest_only"
        frame_quality = getattr(frame_element, "geo_reference_quality", None)
        dynamic_quality = (
            frame_quality.get("status")
            if isinstance(frame_quality, dict)
            else getattr(self, "quality_status", "unverified")
        )
        payload_quality = data.get("tracking_quality")
        if isinstance(payload_quality, str) and payload_quality in {"degraded", "unverified"}:
            dynamic_quality = payload_quality
        elif isinstance(payload_quality, dict) and any(
            value in {"degraded", "unverified"} for value in payload_quality.values()
        ):
            dynamic_quality = "degraded"
        if msg_type == "uav_conflict":
            if time_quality in {"ingest_only", "quarantined"}:
                dynamic_quality = "unverified"
            elif time_quality == "inferred" and dynamic_quality == "verified":
                dynamic_quality = "degraded"
        return {
            "message_id": str(uuid.uuid4()),
            "msg_type": msg_type,
            "schema_version": f"{msg_type}/v1",
            "occurred_at": occurred_at,
            "produced_at": produced_at.isoformat(),
            "source_system": "uav_traffic_analyzer_ai",
            "camera_id": f"id_{self.camera_id}",
            "drone_id": getattr(self, "drone_id", f"drone_{self.camera_id}"),
            "intersection_id": self.intersection_id,
            "inter_id": getattr(self, "inter_id", self.intersection_id),
            "road_data_version": getattr(self, "road_data_version", None),
            "road_context_status": getattr(self, "road_context_status", "missing"),
            "trace_id": str(uuid.uuid4()),
            "source_time_raw": {"frame_timestamp_sec": frame_element.timestamp},
            "source_time_semantics": semantics,
            "time_quality": time_quality,
            "quality_status": dynamic_quality,
            "data": {
                "mission_id": getattr(self, "mission_id", None),
                "pipeline_id": getattr(self, "pipeline_id", None),
                "run_id": getattr(self, "run_id", None),
                "source_profile_id": getattr(self, "source_profile_id", None),
                **data,
            },
        }

    def _enqueue(self, topic: str, data: dict, *, durable: bool = False):
        self.publisher.publish(topic, data, durable=durable)

    def _delivery_snapshot(self) -> dict:
        publisher = getattr(self, "publisher", None)
        if publisher is None:
            return {
                "expected_samples": 0,
                "actual_samples": 0,
                "dropped_samples": 0,
                "coverage_ratio": 1.0,
                "drop_reason": None,
                "durable_pending": 0,
            }
        return publisher.snapshot()

    def _compute_fps(self) -> float:
        """基于wall-clock滑动窗口计算实时FPS。"""
        now = time.time()
        self._fps_timestamps.append(now)
        cutoff = now - self._fps_window_sec
        self._fps_timestamps = [t for t in self._fps_timestamps if t > cutoff]
        if len(self._fps_timestamps) >= 2:
            dt = self._fps_timestamps[-1] - self._fps_timestamps[0]
            if dt > 0:
                return round(len(self._fps_timestamps) / dt, 1)
        return 0.0

    def _compute_congestion_index(
        self, cars: int, roads_activity: dict, frame_element: FrameElement
    ) -> float:
        """多因子拥堵指数 (0-10)。

        因子1: 车辆密度 (0-4分) — 当前车辆数 / 路口通行能力
        因子2: 排队严重度 (0-3分) — 最大排队长度 / 阈值
        因子3: 低速比例 (0-3分) — 排队车辆占比
        """
        # 因子1: 车辆密度 (0-4)
        density = cars / max(self._capacity_veh_per_min, 1)
        vehicle_score = min(density, 1.0) * 4

        # 因子2: 排队严重度 (0-3) — 从 direction_stats 或 lane_stats 获取排队长度
        max_queue_m = 0.0
        direction_stats = getattr(frame_element, "direction_stats", None)
        if direction_stats:
            for d_key in ("straight", "left_turn", "right_turn", "u_turn"):
                d = direction_stats.get(d_key, {})
                q = d.get("queue_length_m", 0)
                if q > max_queue_m:
                    max_queue_m = q
        lane_stats = getattr(frame_element, "lane_stats", None)
        if lane_stats:
            for lid, lv in lane_stats.items():
                q = lv.get("queue_length_m", 0) if isinstance(lv, dict) else 0
                if q > max_queue_m:
                    max_queue_m = q
        queue_score = min(max_queue_m / max(self._queue_threshold_m, 1), 1.0) * 3

        # 因子3: 低速比例 (0-3) — 从 buffer_tracks 中统计低速车辆占比
        slow_count = 0
        total_tracks = 0
        for track in frame_element.buffer_tracks.values():
            total_tracks += 1
            if track.avg_speed_kmh < 10:
                slow_count += 1
        slow_ratio = slow_count / max(total_tracks, 1)
        speed_score = slow_ratio * 3

        return round(vehicle_score + queue_score + speed_score, 1)

    def _encode_annotation_snapshot(self, frame_element: FrameElement) -> dict | None:
        """Return a compact JPEG snapshot for hover-created annotation tasks."""
        frame = getattr(frame_element, "frame_result", None)
        if frame is None:
            frame = getattr(frame_element, "frame", None)
        if frame is None:
            return None

        height, width = frame.shape[:2]
        out_frame = frame
        snapshot_width = int(getattr(self, "_snapshot_width", 960))
        jpeg_quality = int(getattr(self, "_snapshot_jpeg_quality", 75))
        if width > snapshot_width:
            scale = snapshot_width / width
            out_frame = cv2.resize(
                frame,
                (snapshot_width, int(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        ok, buf = cv2.imencode(
            ".jpg",
            out_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
        )
        if not ok:
            return None

        out_height, out_width = out_frame.shape[:2]
        return {
            "annotation_snapshot_jpeg": base64.b64encode(buf).decode("ascii"),
            "annotation_snapshot_width": out_width,
            "annotation_snapshot_height": out_height,
        }

    def _needs_hover_annotation_snapshot(self, frame_element: FrameElement) -> bool:
        """Return whether this hover frame still needs a lane-annotation image.

        A complete Runtime Road Map Bundle already contains the published
        lane-verified map. Re-sending a base64 JPEG on every hover stats sample
        is redundant and can push the canonical realtime record over Kafka's
        request-size limit.
        """
        if not getattr(self, "_hover_annotation_snapshot_enabled", True):
            return False
        if not getattr(frame_element, "is_hovering", False):
            return False
        frame_status = getattr(frame_element, "road_context_status", None)
        pipeline_status = getattr(self, "road_context_status", "missing")
        return "complete" not in {frame_status, pipeline_status}

    def _build_active_trajectories(self, frame_element: FrameElement) -> list[dict]:
        """Serialize active track trajectories for real-time BEV rendering.

        Completed tracks are still published on uav_track_complete_*; this snapshot
        lets the platform draw in-progress trajectories at the same cadence as
        the left-side detection stream.
        """
        buffer_tracks = getattr(frame_element, "buffer_tracks", None) or {}
        if not buffer_tracks:
            return []

        anchor_gcj02 = getattr(frame_element, "anchor_gcj02", None)

        active = []
        for track_id, track in sorted(buffer_tracks.items(), key=lambda item: item[0]):
            bbox_center_px = getattr(track, "trajectory_points", None) or []
            ground_contact_px = getattr(track, "ground_contact_points_px", None) or []
            trajectory_px = (
                ground_contact_px
                if len(ground_contact_px) == len(bbox_center_px) and ground_contact_px
                else bbox_center_px
            )
            if not trajectory_px:
                continue

            tail_points = max(getattr(self, "_active_trajectory_tail_points", 30), 1)
            total_points = len(trajectory_px)
            tail_start = max(total_points - tail_points, 0)
            trajectory_tail_px = trajectory_px[tail_start:]

            px_points = [
                [round(float(x), 2), round(float(y), 2)]
                for x, y in trajectory_tail_px
            ]
            item = {
                "track_id": track.id,
                "vehicle_class": track.vehicle_class,
                "yolo_class_id": track.yolo_class_id,
                "yolo_class_name": track.yolo_class_name,
                "yolo_model_id": track.yolo_model_id,
                "class_mapping_version": track.class_mapping_version,
                "direction_class": track.direction_class,
                "turn_behavior": track.turn_behavior,
                "duration_sec": round(track.timestamp_last - track.timestamp_first, 2),
                "avg_speed_kmh": round(track.avg_speed_kmh, 1),
                "max_speed_kmh": round(track.max_speed_kmh, 1),
                "trajectory_px": px_points,
                "trajectory_point_count": total_points,
                "trajectory_tail_start": tail_start,
                "is_trajectory_tail": tail_start > 0,
                "timestamp_first": track.timestamp_first,
                "timestamp_last": track.timestamp_last,
            }
            if getattr(track, "association_id", None) is not None:
                item["association_id"] = int(track.association_id)
            if len(ground_contact_px) == len(bbox_center_px) and ground_contact_px:
                item["trajectory_bbox_center_px"] = [
                    [round(float(x), 2), round(float(y), 2)]
                    for x, y in bbox_center_px[tail_start:]
                ]
            timestamps = getattr(track, "trajectory_timestamps_sec", None) or []
            if len(timestamps) == total_points:
                item["trajectory_timestamps_sec"] = [
                    round(float(value), 3) for value in timestamps[tail_start:]
                ]
            frame_nums = getattr(track, "trajectory_frame_nums", None) or []
            if len(frame_nums) == total_points:
                item["trajectory_frame_nums"] = [
                    int(value) for value in frame_nums[tail_start:]
                ]

            trajectory_enu = getattr(track, "trajectory_enu_m", None) or []
            # Every ENU point was resolved with the projection of its own source
            # frame in TrackerInfoUpdateNode.  Reprojecting trajectory_px with the
            # latest frame H corrupts history whenever the UAV is moving.
            if len(trajectory_enu) == total_points:
                pts_world = trajectory_enu[tail_start:]
                world_points = [
                    [round(float(x), 2), round(float(y), 2)]
                    for x, y in pts_world
                ]
                item["trajectory_enu_m"] = world_points
                item["current_point_enu_m"] = world_points[-1]
                if anchor_gcj02:
                    item["anchor_gcj02"] = [
                        round(anchor_gcj02[0], 6),
                        round(anchor_gcj02[1], 6),
                    ]
                    stored_gcj02 = getattr(track, "trajectory_gcj02", None) or []
                    if len(stored_gcj02) == total_points:
                        gcj02_tail = stored_gcj02[tail_start:]
                    else:
                        gcj02_tail = [
                            enu_to_gcj02(point[0], point[1], anchor_gcj02)
                            for point in world_points
                        ]
                    item["trajectory_gcj02"] = [
                        [round(lon, 8), round(lat, 8)] for lon, lat in gcj02_tail
                    ]
                item["map_version_id"] = getattr(track, "map_version_id", None)
                item["matched_lane_key"] = getattr(track, "matched_lane_key", None)
                item["source_lane_id"] = getattr(track, "source_lane_id", None)
                item["matched_link_id"] = getattr(track, "matched_link_id", None)
                item["movement_key"] = getattr(track, "movement_key", None)
                item["map_match_confidence"] = getattr(track, "map_match_confidence", None)
            elif trajectory_enu:
                item["tracking_quality"] = "degraded"
                item["quality_reasons"] = ["trajectory_point_alignment_mismatch"]

            active.append(item)

        return active

    def _build_candidate_trajectories(self, frame_element: FrameElement) -> list[dict]:
        """Serialize only the bounded candidate preview contract for realtime BEV."""
        scalar_keys = (
            "track_id", "association_id", "tracking_method", "tracking_quality",
            "quality_status", "formal_analytics_eligible", "quality_reasons",
            "flight_phase", "flight_segment_id", "anchor_gcj02",
            "vehicle_class", "yolo_class_id", "yolo_class_name",
        )
        sequence_keys = (
            "trajectory_px", "trajectory_bbox_center_px", "trajectory_enu_m",
            "trajectory_gcj02", "trajectory_timestamps_sec", "trajectory_frame_nums",
        )
        tail_points = max(getattr(self, "_active_trajectory_tail_points", 30), 1)
        result = []
        for candidate in getattr(frame_element, "candidate_trajectories", None) or []:
            if not isinstance(candidate, dict):
                continue
            item = {key: candidate[key] for key in scalar_keys if key in candidate}
            for key in sequence_keys:
                values = candidate.get(key)
                if isinstance(values, list):
                    item[key] = values[-tail_points:]
            result.append(item)
        return result

    def publish_completed_tracks(self, frame_element: FrameElement) -> int:
        """Publish completed tracks before a terminal sentinel closes the publisher."""
        completed_tracks = getattr(frame_element, "completed_tracks", None) or []
        for track in completed_tracks:
            message = {"intersection_id": self.intersection_id, **track}
            message = self._canonical_envelope(
                "uav_track_complete", message, frame_element
            )
            self._enqueue(self.track_complete_topic, message, durable=True)
            logger.debug(
                "KAFKA enqueued track_complete: id=%s topic=%s",
                track.get("track_id"),
                self.track_complete_topic,
            )
        return len(completed_tracks)

    @profile_time
    def process(self, frame_element: FrameElement):
        # 如果是VideoEndBreakElement而不是FrameElement则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            publisher = getattr(self, "publisher", None)
            if publisher is not None:
                final_delivery = publisher.close()
                logger.info("Kafka publisher closed: %s", final_delivery)
            return frame_element

        current_time = time.time()
        timestamp = frame_element.timestamp
        current_fps = self._compute_fps()

        if self.last_send_time is None or frame_element.frame_num == 1:
            self.last_send_time = current_time

        if current_time - self.last_send_time > self.how_often_sec or self.last_send_time == current_time:
            cars_amount = frame_element.info.get("cars_amount")
            roads_activity = frame_element.info.get("roads_activity") or {}
            formal_eligible = bool(
                getattr(frame_element, "formal_analytics_eligible", False)
            ) if getattr(frame_element, "geo_reference_quality", None) is not None else True

            # T-201: 动态道路数 — 从 roads_activity dict 构建数组
            roads_array = []
            for road_id in sorted(roads_activity.keys()):
                val = roads_activity[road_id]
                roads_array.append({
                    "id": road_id,
                    "activity": round(val, 2) if timestamp >= self.buffer_analytics_sec else None,
                })

            congestion_index = (
                self._compute_congestion_index(
                    int(cars_amount or 0), roads_activity, frame_element
                )
                if formal_eligible
                else None
            )
            tracking_diagnostics = getattr(frame_element, "tracking_diagnostics", None)
            if isinstance(tracking_diagnostics, dict):
                tracking_diagnostics = {
                    key: value
                    for key, value in tracking_diagnostics.items()
                    if not key.startswith("shadow_")
                }
            geo_quality = getattr(frame_element, "geo_reference_quality", None)
            candidate_trajectories = self._build_candidate_trajectories(frame_element)
            data = {
                "camera_id": f"id_{self.camera_id}",
                "cars": cars_amount,
                "intersection_id": self.intersection_id,
                # ── 前端所需字段：FPS / 推理 / 跟踪 / 累计 ──
                "fps": current_fps,
                "inference_ms": getattr(frame_element, "inference_ms", 0),
                "source_capture_time": getattr(frame_element, "source_capture_time", None),
                "source_drop_count": getattr(frame_element, "source_drop_count", 0),
                "source_drop_reason": getattr(frame_element, "source_drop_reason", None),
                "active_tracks": len(frame_element.buffer_tracks or {}),
                "candidate_tracks": len(candidate_trajectories),
                "total_vehicles": cars_amount,
                "active_trajectories": self._build_active_trajectories(frame_element),
                "candidate_trajectories": candidate_trajectories,
                # T-201: 动态道路数组（替代 road_1..road_5）
                "roads": roads_array,
                "road_polygons": frame_element.roads_info,
                # T-203: 多因子拥堵指数
                "congestion_index": congestion_index,
                "flight_phase": getattr(frame_element, "flight_phase", None),
                "flight_segment_id": getattr(frame_element, "flight_segment_id", None),
                "geo_reference_quality": geo_quality,
                "tracking_diagnostics": tracking_diagnostics,
                "formal_analytics_eligible": formal_eligible,
                **self._delivery_snapshot(),
            }
            snapshot_threshold = getattr(self, "_event_snapshot_congestion_threshold", 4.0)
            snapshot_samples = getattr(self, "_event_snapshot_consecutive_samples", 30)
            if congestion_index is not None and congestion_index > snapshot_threshold:
                self._congestion_snapshot_count = getattr(self, "_congestion_snapshot_count", 0) + 1
                if self._congestion_snapshot_count == snapshot_samples:
                    snapshot = self._encode_annotation_snapshot(frame_element)
                    if snapshot:
                        data["event_snapshot_jpeg"] = snapshot["annotation_snapshot_jpeg"]
                        data["event_snapshot_width"] = snapshot["annotation_snapshot_width"]
                        data["event_snapshot_height"] = snapshot["annotation_snapshot_height"]
                    data["event_rule"] = {
                        "rule_id": "congestion.sustained.v1",
                        "threshold": snapshot_threshold,
                        "consecutive_samples": snapshot_samples,
                    }
            else:
                self._congestion_snapshot_count = 0

            # 向后兼容：保留 road_1..road_N 字段（最多 8 条，不足的为 None）
            for road_id in range(1, max(len(roads_activity) + 1, 6)):
                val = roads_activity.get(road_id)
                data[f"road_{road_id}"] = (
                    round(val, 2) if (val is not None and timestamp >= self.buffer_analytics_sec) else None
                )

            # 扩展字段：方向流量统计（始终输出）
            direction_stats = getattr(frame_element, "direction_stats", None)
            if direction_stats:
                data["direction_flow"] = direction_stats
                data["queue_count"] = getattr(frame_element, "queue_count", 0)
                # 计算整体平均车速
                all_speeds = []
                for d in ["straight", "left_turn", "right_turn", "u_turn"]:
                    if d in direction_stats and direction_stats[d].get("avg_speed_kmh", 0) > 0:
                        all_speeds.append(direction_stats[d]["avg_speed_kmh"])
                data["avg_speed_kmh"] = round(sum(all_speeds) / len(all_speeds), 1) if all_speeds else 0

            # 扩展字段：车道级统计 — 向下兼容统一输出
            # 优先级：人工标注 > 模型检测 > 自动推断
            lane_stats = getattr(frame_element, "lane_stats", None)
            inferred_lanes = getattr(frame_element, "inferred_lanes", None)
            lane_source = getattr(frame_element, "lane_source", None)
            data["lane_stats"] = lane_stats  # 原始格式保留（向后兼容）

            if lane_stats:
                # 来源：人工标注 或 模型检测（LaneAnalysisNode 统一输出）
                data["lane_source"] = lane_source if lane_source else "manual"
                data["lanes"] = [
                    {
                        "lane_id": lid,
                        "name": f"车道 {lid}",
                        "direction": "unknown",
                        "flow_veh_per_min": v.get("count", 0),
                        "avg_speed_kmh": v.get("avg_speed_kmh", 0),
                        "queue_length_m": v.get("queue_length_m", 0),
                        "stopped_count": v.get("stopped_count", 0),
                        "headway_sec": round(60.0 / v["count"], 1) if v.get("count", 0) > 0 else None,
                    }
                    for lid, v in lane_stats.items()
                ]
            elif inferred_lanes:
                # 来源：自动推断
                data["lane_source"] = "auto"
                data["inferred_lanes"] = {
                    lane_id: {
                        "label": lane.label,
                        "direction_class": lane.direction_class,
                        "count": lane.count,
                        "avg_speed_kmh": lane.avg_speed_kmh,
                        "queue_length_m": lane.queue_length_m,
                        "stopped_count": lane.stopped_count,
                        "flow_per_min": lane.flow_per_min,
                        "avg_headway_sec": lane.avg_headway_sec,
                    }
                    for lane_id, lane in inferred_lanes.items()
                }
                data["lanes"] = [
                    {
                        "lane_id": lane_id,
                        "name": lane.label,
                        "direction": lane.direction_class,
                        "flow_veh_per_min": lane.flow_per_min,
                        "avg_speed_kmh": lane.avg_speed_kmh,
                        "queue_length_m": lane.queue_length_m,
                        "stopped_count": lane.stopped_count,
                        "headway_sec": lane.avg_headway_sec,
                    }
                    for lane_id, lane in inferred_lanes.items()
                ]
            else:
                data["lane_source"] = None

            # 扩展字段：冲突事件
            conflicts = getattr(frame_element, "conflict_events", None)
            data["conflict_count"] = sum(
                1 for event in (conflicts or []) if is_business_tcc_event(event)
            )
            data["tcc_diagnostics"] = getattr(frame_element, "tcc_diagnostics", None)

            # 扩展字段：无人机位置（运动补偿）
            anchor = getattr(frame_element, "anchor_gcj02", None)
            drone_disp = getattr(frame_element, "drone_displacement_m", None)
            if anchor and drone_disp is not None:
                longitude, latitude = enu_to_gcj02(drone_disp[0], drone_disp[1], anchor)
                data["position_gcj02"] = {
                    "longitude": round(longitude, 8),
                    "latitude": round(latitude, 8),
                }
                data["anchor_gcj02"] = [round(anchor[0], 8), round(anchor[1], 8)]
                data["position_enu_m"] = {
                    "easting_m": round(float(drone_disp[0]), 2),
                    "northing_m": round(float(drone_disp[1]), 2),
                }
                data["coordinate_system"] = "GCJ02"
            data["is_hovering"] = getattr(frame_element, "is_hovering", False)
            if self._needs_hover_annotation_snapshot(frame_element):
                snapshot = self._encode_annotation_snapshot(frame_element)
                if snapshot:
                    data.update(snapshot)

            # T-101: 异步发送（替代同步 .get(timeout=1)）
            self._enqueue(self.topic_name, self._canonical_envelope("uav_stats", data, frame_element))
            logger.info(f"KAFKA enqueued stats: topic={self.topic_name} cars={cars_amount}")
            self.last_send_time = current_time
            frame_element.send_to_kafka = True

        # 发布完成轨迹到独立topic（T-101: 异步发送）
        self.publish_completed_tracks(frame_element)

        # 冲突事件必须等待进程 3 的真实 ShowNode 输出。这里只冻结 canonical
        # 信封并随 FrameElement 传递；禁止在 Kafka 进程内重绘证据帧。
        conflict_events = getattr(frame_element, "conflict_events", None)
        pending_tcc_envelopes = []
        if conflict_events:
            for event in conflict_events:
                event_msg = {"intersection_id": self.intersection_id, **event}
                event_msg = self._canonical_envelope("uav_conflict", event_msg, frame_element)
                pending_tcc_envelopes.append(event_msg)
        frame_element.pending_tcc_envelopes = pending_tcc_envelopes

        # ── T-103: 遥测发布（5Hz 节流） ──
        telemetry = normalize_telemetry_position(getattr(frame_element, "telemetry", None))
        if telemetry and (current_time - self._last_telemetry_time > self._telemetry_interval):
            public_telemetry = {
                key: value for key, value in telemetry.items()
                if key not in {"latitude", "longitude", "lat", "lon"}
            }
            tel_msg = {
                "drone_id": getattr(self, "drone_id", f"drone_{self.camera_id}"),
                "intersection_id": self.intersection_id,
                **public_telemetry,
            }
            tel_msg = self._canonical_envelope("uav_telemetry", tel_msg, frame_element)
            self._enqueue(self.telemetry_topic, tel_msg)
            self._last_telemetry_time = current_time
            logger.debug(f"KAFKA enqueued telemetry: topic={self.telemetry_topic}")

        return frame_element
