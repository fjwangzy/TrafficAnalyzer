from kafka import KafkaProducer
from json import dumps
import os
import time

from utils_local.utils import profile_time
from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.FrameElement import FrameElement
import logging


class KafkaProducerNode:
    def __init__(self, config) -> None:
        config_kafka = config["kafka_producer_node"]
        bootstrap_servers = config_kafka["bootstrap_servers"]
        self.topic_name = config_kafka["topic_name"]
        self.how_often_sec = config_kafka["how_often_sec"]
        self.camera_id = config_kafka["camera_id"]
        self.last_send_time = None
        self.kafka_producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda x: dumps(x).encode("utf-8"),
        )

        self.buffer_analytics_sec = (
            config["general"]["buffer_analytics"] * 60 + config["general"]["min_time_life_track"]
        )  # 这是缓冲区积累的时间，过早输出统计信息还为时过早

        # ── FPS 计算（基于wall-clock滑动窗口）──
        self._fps_window_sec = 2.0
        self._fps_timestamps = []

        # 扩展topic（用于轨迹和冲突事件）
        base_topic = self.topic_name  # e.g., "statistics_1"
        camera_suffix = base_topic.replace("statistics", "")  # e.g., "_1"
        self.track_complete_topic = f"track_complete{camera_suffix}"
        self.conflicts_topic = f"conflicts{camera_suffix}"

        # intersection_id: use INTERSECTION_ID env var if set (from PipelineManager),
        # otherwise derive from camera_id (legacy mode for Docker camera containers)
        env_intersection_id = os.environ.get("INTERSECTION_ID")
        if env_intersection_id:
            self.intersection_id = env_intersection_id
        else:
            self.intersection_id = f"INT_camera_{self.camera_id}"

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

    @profile_time
    def process(self, frame_element: FrameElement):
        # 如果是VideoEndBreakElement而不是FrameElement则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        current_time = time.time()
        timestamp = frame_element.timestamp
        current_fps = self._compute_fps()

        if frame_element.frame_num == 1:
            self.last_send_time = current_time

        if current_time - self.last_send_time > self.how_often_sec or frame_element.frame_num == 1:
            data = {
                f"camera_id": f"id_{self.camera_id}",
                f"cars": frame_element.info["cars_amount"],
                f"msg_type": "stats",
                f"intersection_id": self.intersection_id,
                # ── 前端所需字段：FPS / 推理 / 跟踪 / 累计 ──
                "fps": current_fps,
                "inference_ms": getattr(frame_element, "inference_ms", 0),
                "active_tracks": len(frame_element.id_list),
                "total_vehicles": frame_element.info["cars_amount"],
                "congestion_index": round(
                    sum(v for v in frame_element.info["roads_activity"].values() if v is not None) / max(1, len(frame_element.info["roads_activity"])),
                    2,
                ),
                f"road_1": (
                    frame_element.info["roads_activity"][1]
                    if timestamp >= self.buffer_analytics_sec
                    else None
                ),
                f"road_2": (
                    frame_element.info["roads_activity"][2]
                    if timestamp >= self.buffer_analytics_sec
                    else None
                ),
                f"road_3": (
                    frame_element.info["roads_activity"][3]
                    if timestamp >= self.buffer_analytics_sec
                    else None
                ),
                f"road_4": (
                    frame_element.info["roads_activity"][4]
                    if timestamp >= self.buffer_analytics_sec
                    else None
                ),
                f"road_5": (
                    frame_element.info["roads_activity"][5]
                    if timestamp >= self.buffer_analytics_sec
                    else None
                ),
            }

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

            # 扩展字段：车道级统计（仅在有标注且点位命中时输出）
            lane_stats = getattr(frame_element, "lane_stats", None)
            data["lane_stats"] = lane_stats  # None when no lane data

            # 扩展字段：冲突事件
            conflicts = getattr(frame_element, "conflict_events", None)
            data["conflict_count"] = len(conflicts) if conflicts else 0

            # 扩展字段：无人机位置（运动补偿）
            anchor = getattr(frame_element, "world_anchor_lat_lon", None)
            drone_disp = getattr(frame_element, "drone_displacement_m", None)
            if anchor and drone_disp is not None:
                data["drone_position"] = {
                    "anchor_lat": round(anchor[0], 6),
                    "anchor_lon": round(anchor[1], 6),
                    "easting_m": round(float(drone_disp[0]), 2),
                    "northing_m": round(float(drone_disp[1]), 2),
                }
            data["is_hovering"] = getattr(frame_element, "is_hovering", False)

            self.kafka_producer.send(self.topic_name, value=data).get(timeout=1)
            logging.info(f"KAFKA sent message: {data} topic {self.topic_name}")
            self.last_send_time = current_time
            frame_element.send_to_kafka = True

        # 发布完成轨迹到独立topic
        completed_tracks = getattr(frame_element, "completed_tracks", None)
        if completed_tracks:
            for ct in completed_tracks:
                ct_msg = {
                    "msg_type": "track_complete",
                    "intersection_id": self.intersection_id,
                    **ct,
                }
                self.kafka_producer.send(self.track_complete_topic, value=ct_msg).get(timeout=1)
                logging.info(f"KAFKA sent track_complete: id={ct.get('track_id')} topic {self.track_complete_topic}")

        # 发布冲突事件到独立topic
        conflict_events = getattr(frame_element, "conflict_events", None)
        if conflict_events:
            for event in conflict_events:
                event_msg = {
                    "msg_type": "conflict",
                    "intersection_id": self.intersection_id,
                    **event,
                }
                self.kafka_producer.send(self.conflicts_topic, value=event_msg).get(timeout=1)
                logging.info(f"KAFKA sent conflict: {event.get('severity')} topic {self.conflicts_topic}")

        return frame_element