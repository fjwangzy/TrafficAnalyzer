"""Kafka consumer with transactionally durable PostgreSQL/TimescaleDB writes."""
import asyncio
import json
import logging
import re
import time
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import OffsetAndMetadata

from app.kafka.ws_manager import WSManager
from app.models.drone_store import update_drone_from_stats, update_drone_telemetry
from app.services.metric_store import MessageEnvelope, MetricContractError, MetricStorePort

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
        lane_annotation_store: Any = None,
        metric_store: MetricStorePort | None = None,
        dispatch_realtime: bool = True,
    ):
        self._bootstrap = bootstrap_servers
        self._group_id = group_id
        self._topics_pattern = topics_pattern
        self._ws = ws_manager
        self._alert_engine = alert_engine
        self._lane_annotation_store = lane_annotation_store
        self._metric_store = metric_store
        self._dispatch_realtime = dispatch_realtime
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
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            request_timeout_ms=10000,
            retry_backoff_ms=500,
            metadata_max_age_ms=5000,
            # One canonical stats record can fan out into many Timescale rows.
            # Keep delivery strictly one-at-a-time and allow a slow durable
            # commit to finish without expiring group membership and replaying
            # the same partition after a rebalance.
            max_poll_records=1,
            max_poll_interval_ms=1800000,
        )

        try:
            pattern = re.compile(self._topics_pattern)
            consumer.subscribe(pattern=pattern)
            logger.info(f"Kafka consumer subscribing to pattern: {self._topics_pattern}")
        except Exception:
            topics = ["uav_statistics_1", "uav_statistics_2"]
            consumer.subscribe(topics=topics)
            logger.info(f"Kafka consumer subscribing to topics: {topics}")

        try:
            await asyncio.wait_for(consumer.start(), timeout=15)
            return consumer
        except TimeoutError:
            logger.warning("Kafka consumer start timed out (broker may be unavailable)")
            try:
                await consumer.stop()
            except Exception:
                pass
            return None
        except Exception as e:
            logger.warning(f"Kafka consumer start failed (broker may be unavailable): {e}")
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
            self._consumer = None
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
                        await self._process_message(msg.value, msg.topic, msg.partition, msg.offset)
                        await self._consumer.commit({
                            TopicPartition(msg.topic, msg.partition): OffsetAndMetadata(msg.offset + 1, "")
                        })
                        consecutive_errors = 0
                    except Exception as e:
                        logger.error(f"Error processing Kafka message: {e}")
                        # Do not advance past a failed record: a later successful
                        # commit would otherwise skip this offset permanently.
                        self._consumer.seek(TopicPartition(msg.topic, msg.partition), msg.offset)
                        await asyncio.sleep(1)
                        break
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

    async def _process_message(self, data: dict, topic: str, partition: int = -1, offset: int = -1):
        """Persist first, then route one non-duplicate canonical message."""
        if self._metric_store is None:
            raise RuntimeError("MetricStore is required before Kafka consumption")
        envelope = MessageEnvelope(data, topic, partition, offset)
        try:
            result = await self._metric_store.persist(envelope)
        except MetricContractError as error:
            dead_letter_id = await self._metric_store.quarantine(envelope, error)
            logger.error(
                "Kafka record quarantined: dead_letter_id=%s topic=%s partition=%s offset=%s reason=%s",
                dead_letter_id,
                topic,
                partition,
                offset,
                type(error).__name__,
            )
            return
        if result.dispatch_status == "dispatched":
            return
        normalized = result.normalized_payload
        if not self._dispatch_realtime:
            await self._metric_store.mark_dispatched(
                normalized.get("source_system", "uav_traffic_analyzer_ai"),
                result.message_id,
            )
            return
        business_data = normalized.get("data")
        if isinstance(business_data, dict):
            data = {
                **business_data,
                "msg_type": result.msg_type,
                "message_id": result.message_id,
                "intersection_id": normalized.get("intersection_id") or business_data.get("intersection_id"),
                "inter_id": normalized.get("inter_id") or business_data.get("inter_id"),
                "road_data_version": normalized.get("road_data_version") or business_data.get("road_data_version"),
                "road_context_status": normalized.get("road_context_status") or business_data.get("road_context_status"),
                "quality_status": normalized.get("quality_status") or business_data.get("quality_status"),
                "time_quality": normalized.get("time_quality") or business_data.get("time_quality"),
            }
        msg_type = result.msg_type
        intersection_id = data.get("inter_id") or data.get("intersection_id")
        if not intersection_id and msg_type != "uav_replay_mission":
            intersection_id = self._extract_intersection(topic)

        try:
            if msg_type == "uav_stats":
                await self._handle_stats(data, intersection_id)
            elif msg_type == "uav_detections":
                await self._handle_detections(data, intersection_id)
            elif msg_type == "uav_track_complete":
                await self._handle_track_complete(data, intersection_id)
            elif msg_type == "uav_conflict":
                await self._handle_conflict(data, intersection_id)
            elif msg_type == "uav_vlm_analysis":
                await self._handle_vlm(data, intersection_id)
            elif msg_type == "uav_system_metrics":
                await self._handle_system_metrics(data)
            elif msg_type == "uav_telemetry":
                await self._handle_telemetry(data)
            elif msg_type == "uav_replay_mission":
                # Mission lifecycle messages are durable control-plane facts.
                # They intentionally have no realtime monitoring projection.
                pass
            else:
                raise ValueError(f"Unsupported persisted msg_type: {msg_type}")
        except Exception as error:
            await self._metric_store.mark_dispatch_failed(
                normalized["source_system"], result.message_id, error
            )
            raise
        await self._metric_store.mark_dispatched(
            normalized["source_system"], result.message_id
        )

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

        if self._lane_annotation_store:
            try:
                task = self._lane_annotation_store.observe_stats(intersection_id, data)
            except Exception as e:
                logger.warning("Lane annotation observe_stats failed for %s: %s", intersection_id, e)
            else:
                if task:
                    data["lane_annotation_task_id"] = task["task_id"]
                    await self._ws.broadcast(
                        "uav_calibration",
                        {
                            "channel": "uav_calibration",
                            "type": "uav_lane_annotation_task",
                            "data": task,
                            "ts": time.time(),
                        },
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

        ws_msg = {
            "channel": f"uav_intersection:{intersection_id}",
            "type": "uav_stats",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_intersection:{intersection_id}", ws_msg)

        # Check alert rules
        if self._alert_engine:
            try:
                await self._alert_engine.check_stats(intersection_id, data)
            except Exception as error:
                # Alerts are a side effect of a canonical stats record. A rule
                # failure must not pin the Kafka partition and stop realtime
                # trajectory delivery for every later record.
                logger.warning(
                    "Alert evaluation failed for %s; continuing realtime stats dispatch: %s",
                    intersection_id,
                    error,
                )

    async def _handle_detections(self, data: dict, intersection_id: str):
        """Handle detections message."""
        buf = self._latest_detections.setdefault(intersection_id, [])
        buf.append(data)
        if len(buf) > 5:
            buf.pop(0)

        ws_msg = {
            "channel": f"uav_intersection:{intersection_id}",
            "type": "uav_detections",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_intersection:{intersection_id}", ws_msg)

    async def _handle_track_complete(self, data: dict, intersection_id: str):
        """Handle a track already committed by MetricStore."""
        ws_msg = {
            "channel": f"uav_intersection:{intersection_id}",
            "type": "uav_track_complete",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_intersection:{intersection_id}", ws_msg)

        # Check anomaly alert
        if self._alert_engine and data.get("is_anomaly"):
            await self._alert_engine.on_anomaly_track(intersection_id, data)

    async def _handle_vlm(self, data: dict, intersection_id: str):
        """Handle VLM analysis message."""
        ws_msg = {
            "channel": f"uav_intersection:{intersection_id}",
            "type": "uav_vlm_analysis",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_intersection:{intersection_id}", ws_msg)

        if self._alert_engine and (data.get("accident") or data.get("anomaly_detected")):
            await self._alert_engine.on_vlm_alert(intersection_id, data)

    async def _handle_system_metrics(self, data: dict):
        """Handle system metrics message."""
        self._latest_system = data

        ws_msg = {
            "channel": "uav_system",
            "type": "uav_system_metrics",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast("uav_system", ws_msg)

    async def _handle_conflict(self, data: dict, intersection_id: str):
        """Handle a conflict already committed by MetricStore."""
        # Keep one visible event per motor/non_motor pair. Duplicate same-severity
        # messages are dropped; a warning can still upgrade to critical.
        if not self._upsert_latest_conflict(data, intersection_id):
            return

        ws_msg = {
            "channel": f"uav_intersection:{intersection_id}",
            "type": "uav_conflict",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_intersection:{intersection_id}", ws_msg)

        # T-104: 记录冲突事件并检查冲突频率
        if self._alert_engine:
            self._alert_engine.record_conflict(intersection_id, data.get("message_id"))
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
                event_context=data,
                event_id=data.get("message_id"),
            )

    @staticmethod
    def _conflict_pair_key(data: dict) -> tuple[str, str] | None:
        motor_id = data.get("motor_id")
        non_motor_id = data.get("non_motor_id")
        if motor_id is None or non_motor_id is None:
            return None
        return str(motor_id), str(non_motor_id)

    @staticmethod
    def _conflict_severity_rank(data: dict) -> int:
        return {"warning": 1, "critical": 2}.get(str(data.get("severity")), 0)

    def _upsert_latest_conflict(self, data: dict, intersection_id: str) -> bool:
        """Return True when this conflict should be broadcast/persisted."""
        buf = self._latest_conflicts.setdefault(intersection_id, [])
        pair_key = self._conflict_pair_key(data)
        if pair_key is None:
            buf.append(data)
            if len(buf) > 20:
                buf.pop(0)
            return True

        for idx, existing in enumerate(buf):
            if self._conflict_pair_key(existing) != pair_key:
                continue
            if data.get("message_id") and existing.get("message_id") == data.get("message_id"):
                return True
            if self._conflict_severity_rank(data) <= self._conflict_severity_rank(existing):
                return False
            buf[idx] = data
            return True

        buf.append(data)
        if len(buf) > 20:
            buf.pop(0)
        return True

    async def _handle_telemetry(self, data: dict):
        """Handle drone telemetry update from the pipeline."""
        drone_id = data.get("drone_id", "")
        if drone_id:
            update_drone_telemetry(drone_id, data)

        ws_msg = {
            "channel": f"uav_telemetry:{drone_id}",
            "type": "uav_telemetry",
            "data": data,
            "ts": time.time(),
        }
        await self._ws.broadcast(f"uav_telemetry:{drone_id}", ws_msg)

    def _extract_intersection(self, topic: str) -> str:
        """Extract intersection ID from topic name."""
        for prefix in (
            "uav_statistics_", "uav_track_complete_", "uav_conflicts_",
        ):
            if topic.startswith(prefix):
                cam_id = topic[len(prefix):]
                return f"INT_camera_{cam_id}"
        for prefix in ("uav_telemetry_",):
            if topic.startswith(prefix):
                return topic[len(prefix):]
        if topic == "uav_system_metrics":
            return "uav_system"
        raise ValueError(f"unsupported canonical topic: {topic}")
