"""KafkaProducerNode — 异步发送 + 遥测发布 + 动态道路数 + 多因子拥堵指数

改进点（审查报告 T-101 / T-103 / T-201 / T-203）:
  T-101: 独立发送线程 + 有界队列，Kafka 不可用时不阻塞管道
  T-103: 新增 telemetry_{N} topic，5Hz 节流发布遥测数据
  T-201: roads_activity 改为动态数组 [{"id": 1, "activity": 4.2}, ...]
  T-203: congestion_index 改为多因子计算 (车辆密度 + 排队 + 低速比例)
"""
import logging
import os
import time
import base64
from queue import Queue, Full
from threading import Thread

import cv2
from kafka import KafkaProducer
from json import dumps

from utils_local.utils import profile_time
from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.FrameElement import FrameElement

logger = logging.getLogger(__name__)


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
            # 增加重试和超时配置以提高可靠性
            retries=3,
            request_timeout_ms=5000,
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

        # ── T-103: 遥测发布 ──
        self.telemetry_topic = f"telemetry{camera_suffix}"
        self._telemetry_interval = 0.2  # 5Hz 节流
        self._last_telemetry_time = 0.0

        # ── T-101: 异步发送线程 + 有界队列 ──
        self._send_queue: Queue = Queue(maxsize=200)
        self._sender_thread = Thread(
            target=self._send_loop, name="kafka_sender", daemon=True
        )
        self._sender_thread.start()
        self._dropped_count = 0  # 队列满时丢弃的消息计数

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

    def _send_loop(self):
        """后台发送线程：从有界队列取消息并发送到 Kafka。

        独立于主管道线程运行，Kafka 阻塞不影响管道帧率。
        发送失败仅记录日志，不抛异常。
        """
        while True:
            try:
                topic, data = self._send_queue.get(timeout=1.0)
            except Exception:
                continue  # 队列空，继续等待
            try:
                future = self.kafka_producer.send(topic, value=data)
                future.add_callback(self._on_send_success, topic=topic)
                future.add_errback(self._on_send_error, topic=topic)
            except Exception as e:
                logger.warning(f"Kafka send failed (topic={topic}): {e}")

    @staticmethod
    def _on_send_success(record_metadata, topic=None):
        logger.debug(
            f"Kafka sent OK: topic={topic} partition={record_metadata.partition} "
            f"offset={record_metadata.offset}"
        )

    @staticmethod
    def _on_send_error(exc, topic=None):
        logger.warning(f"Kafka send error (topic={topic}): {exc}")

    def _enqueue(self, topic: str, data: dict):
        """非阻塞入队。队列满时丢弃消息并计数。"""
        try:
            self._send_queue.put_nowait((topic, data))
        except Full:
            self._dropped_count += 1
            if self._dropped_count % 100 == 1:
                logger.warning(
                    f"Kafka send queue full, dropped {self._dropped_count} messages total"
                )

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
        if width > self._snapshot_width:
            scale = self._snapshot_width / width
            out_frame = cv2.resize(
                frame,
                (self._snapshot_width, int(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        ok, buf = cv2.imencode(
            ".jpg",
            out_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self._snapshot_jpeg_quality)],
        )
        if not ok:
            return None

        out_height, out_width = out_frame.shape[:2]
        return {
            "annotation_snapshot_jpeg": base64.b64encode(buf).decode("ascii"),
            "annotation_snapshot_width": out_width,
            "annotation_snapshot_height": out_height,
        }

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
            cars_amount = frame_element.info["cars_amount"]
            roads_activity = frame_element.info["roads_activity"]

            # T-201: 动态道路数 — 从 roads_activity dict 构建数组
            roads_array = []
            for road_id in sorted(roads_activity.keys()):
                val = roads_activity[road_id]
                roads_array.append({
                    "id": road_id,
                    "activity": round(val, 2) if timestamp >= self.buffer_analytics_sec else None,
                })

            data = {
                "camera_id": f"id_{self.camera_id}",
                "cars": cars_amount,
                "msg_type": "stats",
                "intersection_id": self.intersection_id,
                # ── 前端所需字段：FPS / 推理 / 跟踪 / 累计 ──
                "fps": current_fps,
                "inference_ms": getattr(frame_element, "inference_ms", 0),
                "active_tracks": len(frame_element.id_list),
                "total_vehicles": cars_amount,
                # T-201: 动态道路数组（替代 road_1..road_5）
                "roads": roads_array,
                "road_polygons": frame_element.roads_info,
                # T-203: 多因子拥堵指数
                "congestion_index": self._compute_congestion_index(
                    cars_amount, roads_activity, frame_element
                ),
            }

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
            if data["is_hovering"]:
                snapshot = self._encode_annotation_snapshot(frame_element)
                if snapshot:
                    data.update(snapshot)

            # T-101: 异步发送（替代同步 .get(timeout=1)）
            self._enqueue(self.topic_name, data)
            logger.info(f"KAFKA enqueued stats: topic={self.topic_name} cars={cars_amount}")
            self.last_send_time = current_time
            frame_element.send_to_kafka = True

        # 发布完成轨迹到独立topic（T-101: 异步发送）
        completed_tracks = getattr(frame_element, "completed_tracks", None)
        if completed_tracks:
            for ct in completed_tracks:
                ct_msg = {
                    "msg_type": "track_complete",
                    "intersection_id": self.intersection_id,
                    **ct,
                }
                self._enqueue(self.track_complete_topic, ct_msg)
                logger.info(f"KAFKA enqueued track_complete: id={ct.get('track_id')} topic={self.track_complete_topic}")

        # 发布冲突事件到独立topic（T-101: 异步发送）
        conflict_events = getattr(frame_element, "conflict_events", None)
        if conflict_events:
            for event in conflict_events:
                event_msg = {
                    "msg_type": "conflict",
                    "intersection_id": self.intersection_id,
                    **event,
                }
                self._enqueue(self.conflicts_topic, event_msg)
                logger.info(f"KAFKA enqueued conflict: {event.get('severity')} topic={self.conflicts_topic}")

        # ── T-103: 遥测发布（5Hz 节流） ──
        telemetry = getattr(frame_element, "telemetry", None)
        if telemetry and (current_time - self._last_telemetry_time > self._telemetry_interval):
            tel_msg = {
                "msg_type": "telemetry",
                "drone_id": f"drone_{self.camera_id}",
                "intersection_id": self.intersection_id,
                **telemetry,
            }
            self._enqueue(self.telemetry_topic, tel_msg)
            self._last_telemetry_time = current_time
            logger.debug(f"KAFKA enqueued telemetry: topic={self.telemetry_topic}")

        return frame_element
