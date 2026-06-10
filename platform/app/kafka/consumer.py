"""Kafka consumer service — consumes pipeline messages, persists to InfluxDB,
and broadcasts via WebSocket.

改进点（审查报告 T-102 / T-403 / T-201）:
  T-102: track_complete / conflict 事件持久化到 InfluxDB
  T-403: 降级模式下指数退避自动重连
  T-201: 动态道路数兼容（consumer 已接收 roads 数组）
"""
import asyncio
import json
import logging
import re
import time
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.kafka.ws_manager import WSManager
from app.models.drone_store import update_drone_telemetry, update_drone_from_stats

logger = logging.getLogger(__name__)


class KafkaConsumerService:
    """Consumes Kafka messages from the traffic pipeline and pushes to WebSocket."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics_pattern: str,
        ws_manager: WSManager,
        alert_engine: Any = None,
        influx_client: Any = None,
    ):
        self._bootstrap = bootstrap_servers
        self._group_id = group_id
        self._topics_pattern = topics_pattern
        self._ws = ws_manager
        self._alert_engine = alert_engine
        self._influx = influx_client  # T-102: InfluxDB 写入客户端
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None
        self._running = False

        # Latest state cache: {intersection_id: latest_stats}
        self._latest_stats: dict[str, dict] = {}
        self._latest_system: dict = {}
        self._latest_detections: dict[str, list[dict]] = {}  # ring buffer per intersection
        self._latest_conflicts: dict[str, list[dict]] = {}  # ring buffer per intersection

    @property
    def latest_stats(self) -> dict[str, dict]:
        return self._latest_stats

    @property
    def latest_system(self) -> dict:
        return self._latest_system

    async def start(self):
        """Start the Kafka consumer background task."""
        self._running = True
        self._consumer = await self._create_consumer()

        if self._consumer is None:
            logger.warning("Kafka consumer could not start — running in degraded mode")
            self._task = asyncio.create_task(self._reconnect_loop())
            return

        self._task = asyncio.create_task(self._consume_loop())
        logger.info("Kafka consumer started")

    async def _create_consumer(self) -> AIOKafkaConsumer | None:
        """Create and start an AIOKafkaConsumer. Returns None if broker unavailable."""
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            request_timeout_ms=10000,
            retry_backoff_ms=500,
            max_poll_interval_ms=300000,
        )

        try:
            pattern = re.compile(self._topics_pattern)
            consumer.subscribe(pattern=pattern)
            logger.info(f"Kafka consumer subscribing to pattern: {self._topics_pattern}")
        except Exception:
            topics = ["statistics_1", "statistics_2"]
            consumer.subscribe(topics=topics)
            logger.info(f"Kafka consumer subscribing to topics: {topics}")

        try:
            await asyncio.wait_for(consumer.start(), timeout=15)
            return consumer
        except asyncio.TimeoutError:
            logger.warning("Kafka consumer start timed out (broker may be unavailable)")
            try:
                await consumer.stop()
            except Exception:
                pass
            return None

    async def stop(self):
        """Stop the Kafka consumer."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
        logger.info("Kafka consumer stopped")

    # ── T-403: 指数退避重连 ──

    async def _reconnect_loop(self):
        """指数退避重连循环（降级模式下使用）。"""
        backoff = 5  # 初始退避秒数
        max_backoff = 120  # 最大退避

        while self._running:
            if self._consumer is not None:
                # Consumer 已恢复，切回正常消费循环
                self._task = asyncio.create_task(self._consume_loop())
                return

            logger.info(f"Kafka consumer in degraded mode — reconnecting in {backoff}s")
            await asyncio.sleep(backoff)

            if not self._running:
                break

            consumer = await self._create_consumer()
            if consumer is not None:
                self._consumer = consumer
                logger.info("Kafka consumer reconnected successfully")
                self._task = asyncio.create_task(self._consume_loop())
                return

            backoff = min(backoff * 2, max_backoff)

    async def _consume_loop(self):
        """Main consumption loop with bounded retry."""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self._running:
            if self._consumer is None:
                # T-403: 切到重连循环
                self._task = asyncio.create_task(self._reconnect_loop())
                return

            try:
                async for msg in self._consumer:
                    if not self._running:
                        break
                    try:
                        await self._process_message(msg.value, msg.topic)
                        consecutive_errors = 0
                    except Exception as e:
                        logger.error(f"Error processing Kafka message: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Kafka consumer error ({consecutive_errors}/{max_consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"Kafka consumer: {max_consecutive_errors} consecutive errors — switching to reconnect mode")
                    # 关闭旧 consumer
                    try:
                        await self._consumer.stop()
                    except Exception:
                        pass
                    self._consumer = None
                    self._task = asyncio.create_task(self._reconnect_loop())
                    return
                else:
                    await asyncio.sleep(2)

    async def _process_message(self, data: dict, topic: str):
        """Route a Kafka message to the appropriate handler."""
        msg_type = data.get("msg_type", "stats")
        intersection_id = data.get("intersection_id", self._extract_intersection(topic))

        if msg_type == "stats":
            await self._handle_stats(data, intersection_id)
        elif msg_type == "detections":
            await self._handle_detections(data, intersection_id)
        elif msg_type == "track_complete":
            await self._handle_track_complete(data, intersection_id)
        elif msg_type == "conflict":
            await self._handle_conflict(data, intersection_id)
        elif msg_type == "vlm_analysis":
            await self._handle_vlm(data, intersection_id)
        elif msg_type == "system_metrics":
            await self._handle_system_metrics(data)
        elif msg_type == "telemetry":
            await self._handle_telemetry(data)
        else:
            await self._handle_legacy_stats(data, topic)

    async def _handle_stats(self, data: dict, intersection_id: str):
        """Handle stats message."""
        self._latest_stats[intersection_id] = data

        # Extract drone position from stats and update drone store
        drone_pos = data.get("drone_position")
        if drone_pos:
            update_drone_from_stats(
                intersection_id=intersection_id,
                drone_position=drone_pos,
                is_hovering=data.get("is_hovering", False),
            )

        # Transform lane_stats dict → lanes array for frontend compatibility
        # Skip if KafkaProducerNode already sent unified 'lanes' array
        if "lanes" not in data:
            lane_stats = data.get("lane_stats")
            if lane_stats and isinstance(lane_stats, dict):
                lanes_arr = []
                for lid, v in lane_stats.items():
                    entry = {"lane_id": int(lid), "vehicle_count": v.get("count", 0), **v}
                    cnt = v.get("count", 0)
                    if cnt > 0:
                        entry["headway_sec"] = round(60.0 / cnt, 1)
                    lanes_arr.append(entry)
                data["lanes"] = lanes_arr

        # T-102: 持久化 stats 到 InfluxDB
        if self._influx:
            try:
                self._influx.write_stats(data)
            except Exception as e:
                logger.error(f"InfluxDB write_stats error: {e}")

        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "stats",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

        # Check alert rules
        if self._alert_engine:
            await self._alert_engine.check_stats(intersection_id, data)

    async def _handle_detections(self, data: dict, intersection_id: str):
        """Handle detections message."""
        buf = self._latest_detections.setdefault(intersection_id, [])
        buf.append(data)
        if len(buf) > 5:
            buf.pop(0)

        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "detections",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

    async def _handle_track_complete(self, data: dict, intersection_id: str):
        """Handle track complete message.

        T-102: 新增 InfluxDB 持久化。
        """
        # T-102: 写入 InfluxDB track_events measurement
        if self._influx:
            try:
                self._influx.write_track_event(data)
            except Exception as e:
                logger.error(f"InfluxDB write_track_event error: {e}")

        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "track_complete",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

        # Check anomaly alert
        if self._alert_engine and data.get("is_anomaly"):
            await self._alert_engine.on_anomaly_track(intersection_id, data)

    async def _handle_vlm(self, data: dict, intersection_id: str):
        """Handle VLM analysis message."""
        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "vlm_analysis",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

        if self._alert_engine and (data.get("accident") or data.get("anomaly_detected")):
            await self._alert_engine.on_vlm_alert(intersection_id, data)

    async def _handle_system_metrics(self, data: dict):
        """Handle system metrics message."""
        self._latest_system = data

        ws_msg = {
            "channel": "system",
            "type": "system_metrics",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast("system", ws_msg)

    async def _handle_conflict(self, data: dict, intersection_id: str):
        """Handle conflict event from the detection pipeline.

        T-102: 新增 InfluxDB 持久化。
        """
        # Keep ring buffer of recent conflicts per intersection
        buf = self._latest_conflicts.setdefault(intersection_id, [])
        buf.append(data)
        if len(buf) > 20:
            buf.pop(0)

        # T-102: 写入 InfluxDB conflict_events measurement
        if self._influx:
            try:
                self._influx.write_conflict_event(data)
            except Exception as e:
                logger.error(f"InfluxDB write_conflict_event error: {e}")

        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "conflict",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

        # T-104: 记录冲突事件并检查冲突频率
        if self._alert_engine:
            self._alert_engine.record_conflict(intersection_id)
            await self._alert_engine.check_conflict_rate(intersection_id)

        # Trigger alert for severe conflicts
        if self._alert_engine and data.get("severity") in ("critical", "warning"):
            motor_id = data.get("motor_id", 0)
            non_motor_id = data.get("non_motor_id", 0)
            ttc_val = data.get("ttc_sec", 0)
            dist_val = data.get("distance_m", 0)
            try:
                ttc_val = float(ttc_val)
            except (TypeError, ValueError):
                ttc_val = 0.0
            try:
                dist_val = float(dist_val)
            except (TypeError, ValueError):
                dist_val = 0.0
            await self._alert_engine._create_alert(
                intersection_id,
                alert_type="conflict",
                severity="P1" if data.get("severity") == "critical" else "P2",
                title=f"机非冲突 (TTC={ttc_val:.1f}s)",
                description=(
                    f"路口 {intersection_id} 检测到机动车(id={motor_id})与"
                    f"非机动车(id={non_motor_id})冲突，"
                    f"距离={dist_val:.1f}m，TTC={ttc_val:.1f}s"
                ),
                track_ids=[motor_id, non_motor_id],
            )

    async def _handle_telemetry(self, data: dict):
        """Handle drone telemetry update from the pipeline."""
        drone_id = data.get("drone_id", "")
        if drone_id:
            update_drone_telemetry(drone_id, data)

        ws_msg = {
            "channel": f"telemetry:{drone_id}",
            "type": "telemetry",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"telemetry:{drone_id}", ws_msg)

    async def _handle_legacy_stats(self, data: dict, topic: str):
        """Handle legacy Kafka messages (old format: camera_id, cars, road_1..5)."""
        intersection_id = self._extract_intersection(topic)
        camera_id = data.get("camera_id", "")

        # Convert legacy format to new format
        lanes = []
        for i in range(1, 6):
            val = data.get(f"road_{i}")
            if val is not None:
                lanes.append({
                    "lane_id": i,
                    "flow_veh_per_min": float(val),
                    "vehicle_count": 0,
                    "avg_speed_kmh": 0.0,
                })

        normalized = {
            "msg_type": "stats",
            "intersection_id": intersection_id,
            "timestamp": time.time(),
            "camera_id": camera_id,
            "total_vehicles": data.get("cars", 0),
            "cars": data.get("cars", 0),
            "lanes": lanes,
        }
        for i in range(1, 6):
            normalized[f"road_{i}"] = data.get(f"road_{i}")

        await self._handle_stats(normalized, intersection_id)

    def _extract_intersection(self, topic: str) -> str:
        """Extract intersection ID from topic name."""
        for prefix in ("statistics_", "track_complete_", "conflicts_"):
            if topic.startswith(prefix):
                cam_id = topic[len(prefix):]
                return f"INT_camera_{cam_id}"
        if topic.startswith("telemetry_"):
            return topic.replace("telemetry_", "")
        if "intersection_" in topic:
            return topic.split("intersection_")[-1]
        return topic
