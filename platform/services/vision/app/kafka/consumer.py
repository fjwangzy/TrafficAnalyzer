"""Kafka consumer service — consumes pipeline messages and broadcasts via WebSocket."""
import asyncio
import json
import logging
import re
import time
from typing import Any

from aiokafka import AIOKafkaConsumer

from .ws_manager import WSManager

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

        await self._consumer.start()
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
        """Main consumption loop."""
        while self._running:
            try:
                async for msg in self._consumer:
                    if not self._running:
                        break
                    try:
                        await self._process_message(msg.value, msg.topic)
                    except Exception as e:
                        logger.error(f"Error processing Kafka message: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Kafka consumer error: {e}")
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
        elif msg_type == "vlm_analysis":
            await self._handle_vlm(data, intersection_id)
        elif msg_type == "system_metrics":
            await self._handle_system_metrics(data)
        else:
            # Legacy format (old KafkaProducerNode): treat as stats
            await self._handle_legacy_stats(data, topic)

    async def _handle_stats(self, data: dict, intersection_id: str):
        """Handle stats message."""
        self._latest_stats[intersection_id] = data

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
        # drone_001_intersection_INT_xx → INT_xx
        if topic.startswith("statistics_"):
            cam_id = topic.replace("statistics_", "")
            return f"INT_camera_{cam_id}"
        if "intersection_" in topic:
            return topic.split("intersection_")[-1]
        return topic
