"""Kafka consumer service — consumes pipeline messages and broadcasts via WebSocket."""
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
    ):
        self._bootstrap = bootstrap_servers
        self._group_id = group_id
        self._topics_pattern = topics_pattern
        self._ws = ws_manager
        self._alert_engine = alert_engine
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
        self._consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            # 限流：避免GroupCoordinatorNotAvailableError导致无限重试阻塞事件循环
            request_timeout_ms=10000,
            retry_backoff_ms=500,
            max_poll_interval_ms=300000,
        )

        try:
            # Try pattern-based subscription first
            pattern = re.compile(self._topics_pattern)
            self._consumer.subscribe(pattern=pattern)
            logger.info(f"Kafka consumer subscribing to pattern: {self._topics_pattern}")
        except Exception:
            # Fallback: subscribe to specific known topics
            topics = ["statistics_1", "statistics_2"]
            self._consumer.subscribe(topics=topics)
            logger.info(f"Kafka consumer subscribing to topics: {topics}")

        try:
            await asyncio.wait_for(self._consumer.start(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("Kafka consumer start timed out (broker may be unavailable) — running in degraded mode")
            self._consumer = None
            return

        self._task = asyncio.create_task(self._consume_loop())
        logger.info("Kafka consumer started")

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

    async def _consume_loop(self):
        """Main consumption loop with bounded retry."""
        consecutive_errors = 0
        max_consecutive_errors = 10  # 最多连续错误次数，超过后暂停消费

        while self._running:
            if self._consumer is None:
                # 降级模式：Kafka不可用，等待重连
                logger.info("Kafka consumer in degraded mode — waiting for reconnect")
                await asyncio.sleep(30)
                continue

            try:
                async for msg in self._consumer:
                    if not self._running:
                        break
                    try:
                        await self._process_message(msg.value, msg.topic)
                        consecutive_errors = 0  # 成功处理后重置错误计数
                    except Exception as e:
                        logger.error(f"Error processing Kafka message: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Kafka consumer error ({consecutive_errors}/{max_consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"Kafka consumer: {max_consecutive_errors} consecutive errors — pausing for 60s")
                    await asyncio.sleep(60)
                    consecutive_errors = 0
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
            # Legacy format (old KafkaProducerNode): treat as stats
            await self._handle_legacy_stats(data, topic)

    async def _handle_stats(self, data: dict, intersection_id: str):
        """Handle stats message."""
        self._latest_stats[intersection_id] = data

        # Extract drone position from stats and update drone store
        drone_pos = data.get("drone_position")
        if drone_pos:
            # Stats messages carry drone position — use it to update drone state
            update_drone_from_stats(
                intersection_id=intersection_id,
                drone_position=drone_pos,
                is_hovering=data.get("is_hovering", False),
            )

        # Transform lane_stats dict → lanes array for frontend compatibility
        # KafkaProducerNode sends: {"lane_stats": {"1": {"count": 3, "avg_speed_kmh": 25, ...}, ...}}
        # Frontend expects:       {"lanes": [{"lane_id": 1, "vehicle_count": 3, "avg_speed_kmh": 25, ...}, ...]}
        lane_stats = data.get("lane_stats")
        if lane_stats and isinstance(lane_stats, dict):
            lanes_arr = []
            for lid, v in lane_stats.items():
                entry = {"lane_id": int(lid), "vehicle_count": v.get("count", 0), **v}
                # Compute headway from vehicle count (60s window / count)
                cnt = v.get("count", 0)
                if cnt > 0:
                    entry["headway_sec"] = round(60.0 / cnt, 1)
                lanes_arr.append(entry)
            data["lanes"] = lanes_arr

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
        # Keep ring buffer of last 5 frames
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
        """Handle track complete message."""
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

        # Check VLM alert
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
        """Handle conflict event from the detection pipeline."""
        # Keep ring buffer of recent conflicts per intersection
        buf = self._latest_conflicts.setdefault(intersection_id, [])
        buf.append(data)
        if len(buf) > 20:
            buf.pop(0)

        ws_msg = {
            "channel": f"intersection:{intersection_id}",
            "type": "conflict",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"intersection:{intersection_id}", ws_msg)

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
        # Preserve raw road_N fields
        for i in range(1, 6):
            normalized[f"road_{i}"] = data.get(f"road_{i}")

        await self._handle_stats(normalized, intersection_id)

    def _extract_intersection(self, topic: str) -> str:
        """Extract intersection ID from topic name."""
        # statistics_1 → INT_camera_1
        # track_complete_1 → INT_camera_1
        # conflicts_1 → INT_camera_1
        # telemetry_drone_001 → drone_001
        for prefix in ("statistics_", "track_complete_", "conflicts_"):
            if topic.startswith(prefix):
                cam_id = topic[len(prefix):]
                return f"INT_camera_{cam_id}"
        if topic.startswith("telemetry_"):
            return topic.replace("telemetry_", "")
        if "intersection_" in topic:
            return topic.split("intersection_")[-1]
        return topic
