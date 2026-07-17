"""Alert engine — rule-based + VLM-based alert detection.

改进点（审查报告 T-104 / S-001）:
  新增 high_avg_speed (P3): avg_speed > 60km/h 持续 3 帧
  新增 multiple_conflicts (P2): conflict_count > 3/min 滑动窗口
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.kafka.ws_manager import WSManager
from app.models.alert import AlertRecord

logger = logging.getLogger(__name__)


class Alert:
    """In-memory alert representation."""

    def __init__(
        self,
        intersection_id: str,
        alert_type: str,
        severity: str,
        title: str,
        description: str | None = None,
        track_ids: list[int] | None = None,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.intersection_id = intersection_id
        self.alert_type = alert_type
        self.severity = severity
        self.title = title
        self.description = description
        self.status = "open"
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.track_ids = track_ids or []
        self.snapshot_url = None
        self.video_clip_url = None
        self.vlm_summary = None
        self.acknowledged_by = None
        self.acknowledged_at = None
        self.push_logs: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intersection_id": self.intersection_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "timestamp": self.timestamp,
            "track_ids": self.track_ids,
            "snapshot_url": self.snapshot_url,
            "video_clip_url": self.video_clip_url,
            "vlm_summary": self.vlm_summary,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
            "push_logs": self.push_logs,
        }

    def acknowledge(self, user: str):
        self.status = "acknowledged"
        self.acknowledged_by = user
        self.acknowledged_at = datetime.now(timezone.utc).isoformat()

    @classmethod
    def from_dict(cls, data: dict) -> "Alert":
        alert = cls(
            intersection_id=data["intersection_id"],
            alert_type=data["alert_type"],
            severity=data["severity"],
            title=data["title"],
            description=data.get("description"),
            track_ids=data.get("track_ids") or [],
        )
        alert.id = data["id"]
        alert.status = data.get("status", "open")
        alert.timestamp = data.get("timestamp") or alert.timestamp
        alert.snapshot_url = data.get("snapshot_url")
        alert.video_clip_url = data.get("video_clip_url")
        alert.vlm_summary = data.get("vlm_summary")
        alert.acknowledged_by = data.get("acknowledged_by")
        alert.acknowledged_at = data.get("acknowledged_at")
        alert.push_logs = data.get("push_logs") or []
        return alert


class SqlAlertStore:
    """SQLAlchemy-backed alert store."""

    def __init__(self, session_maker):
        self._session_maker = session_maker

    async def list_alerts(self) -> list[dict]:
        async with self._session_maker() as session:
            result = await session.execute(select(AlertRecord))
            records = result.scalars().all()
            return [self._record_to_dict(record) for record in records]

    async def save_alert(self, alert: dict):
        async with self._session_maker() as session:
            session.add(self._dict_to_record(alert))
            await session.commit()

    async def update_alert(self, alert: dict):
        async with self._session_maker() as session:
            record = await session.get(AlertRecord, alert["id"])
            if record is None:
                session.add(self._dict_to_record(alert))
            else:
                self._apply_dict(record, alert)
            await session.commit()

    @staticmethod
    def _dict_to_record(alert: dict) -> AlertRecord:
        record = AlertRecord(id=alert["id"])
        SqlAlertStore._apply_dict(record, alert)
        return record

    @staticmethod
    def _apply_dict(record: AlertRecord, alert: dict) -> None:
        record.intersection_id = alert["intersection_id"]
        record.alert_type = alert["alert_type"]
        record.severity = alert["severity"]
        record.title = alert["title"]
        record.description = alert.get("description")
        record.status = alert.get("status", "open")
        record.timestamp = alert["timestamp"]
        record.track_ids = alert.get("track_ids") or []
        record.snapshot_url = alert.get("snapshot_url")
        record.video_clip_url = alert.get("video_clip_url")
        record.vlm_summary = alert.get("vlm_summary")
        record.acknowledged_by = alert.get("acknowledged_by")
        record.acknowledged_at = alert.get("acknowledged_at")
        record.push_logs = alert.get("push_logs") or []
        record.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _record_to_dict(record: AlertRecord) -> dict:
        return {
            "id": record.id,
            "intersection_id": record.intersection_id,
            "alert_type": record.alert_type,
            "severity": record.severity,
            "title": record.title,
            "description": record.description,
            "status": record.status,
            "timestamp": record.timestamp,
            "track_ids": record.track_ids or [],
            "snapshot_url": record.snapshot_url,
            "video_clip_url": record.video_clip_url,
            "vlm_summary": record.vlm_summary,
            "acknowledged_by": record.acknowledged_by,
            "acknowledged_at": record.acknowledged_at,
            "push_logs": record.push_logs or [],
        }


class AlertEngine:
    """Rule-based and VLM-based alert engine."""

    def __init__(
        self,
        ws_manager: WSManager,
        settings: Any = None,
        alert_store: Any = None,
        event_center: Any = None,
    ):
        self._ws = ws_manager
        self._alerts: dict[str, Alert] = {}  # alert_id → Alert
        self._alert_store = alert_store
        self._event_center = event_center
        self._consecutive_congestion: dict[str, int] = {}  # intersection_id → count

        # Thresholds
        self._queue_threshold = getattr(settings, "queue_overflow_threshold_m", 80.0)
        self._congestion_threshold = getattr(settings, "congestion_severe_threshold", 4.0)
        self._calibration_threshold = getattr(settings, "calibration_drift_match_rate", 0.80)
        self._consecutive_frames = getattr(settings, "consecutive_congestion_frames", 30)

        # T-104: high_avg_speed 规则参数
        self._high_speed_threshold_kmh = getattr(settings, "high_avg_speed_threshold_kmh", 60.0)
        self._consecutive_high_speed: dict[str, int] = {}  # intersection_id → count
        self._high_speed_frames = 3  # 连续 N 帧超速才触发

        # T-104: multiple_conflicts 规则参数 — 滑动窗口(60s)
        self._conflict_threshold_per_min = 3
        self._conflict_windows: dict[str, deque] = {}  # intersection_id → deque of timestamps

    @property
    def alerts(self) -> dict[str, Alert]:
        return self._alerts

    async def load_persisted_alerts(self):
        """Load persisted alerts into the in-memory query cache."""
        if not self._alert_store:
            return
        try:
            records = await self._alert_store.list_alerts()
        except Exception as e:
            logger.warning("Alert persistence load failed; using memory cache only: %s", e)
            return
        self._alerts = {
            record["id"]: Alert.from_dict(record)
            for record in records
        }

    def get_alerts_list(
        self,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get filtered alerts list."""
        result = list(self._alerts.values())
        if severity:
            result = [a for a in result if a.severity == severity]
        if status:
            result = [a for a in result if a.status == status]
        result.sort(key=lambda a: a.timestamp, reverse=True)
        return [a.to_dict() for a in result[offset:offset + limit]]

    def get_alert(self, alert_id: str) -> dict | None:
        """Get a single alert by ID."""
        alert = self._alerts.get(alert_id)
        return alert.to_dict() if alert else None

    async def acknowledge_alert(self, alert_id: str, user: str = "admin") -> dict | None:
        """Acknowledge an alert."""
        alert = self._alerts.get(alert_id)
        if alert:
            alert.acknowledge(user)
            payload = alert.to_dict()
            await self._update_persisted_alert(payload)
            return payload
        return None

    async def _save_persisted_alert(self, payload: dict):
        if not self._alert_store:
            return
        try:
            await self._alert_store.save_alert(payload)
        except Exception as e:
            logger.warning("Alert persistence save failed; continuing in memory: %s", e)

    async def _update_persisted_alert(self, payload: dict):
        if not self._alert_store:
            return
        try:
            await self._alert_store.update_alert(payload)
        except Exception as e:
            logger.warning("Alert persistence update failed; continuing in memory: %s", e)

    async def check_stats(self, intersection_id: str, data: dict):
        """Check stats data against alert rules."""
        # Queue overflow check
        max_queue = 0.0
        for lane in data.get("lanes", []):
            q = lane.get("queue_length_m", 0)
            if q > max_queue:
                max_queue = q

        if max_queue > self._queue_threshold:
            await self._create_alert(
                intersection_id,
                alert_type="queue_overflow",
                severity="P2",
                title=f"排队超限预警 ({max_queue:.0f}m)",
                description=f"路口 {intersection_id} 最大排队长度 {max_queue:.0f}m 超过阈值 {self._queue_threshold:.0f}m",
                event_context=data,
            )

        # Congestion index check with consecutive frame counter
        congestion = data.get("congestion_index", 0)
        if congestion > self._congestion_threshold:
            count = self._consecutive_congestion.get(intersection_id, 0) + 1
            self._consecutive_congestion[intersection_id] = count
            if count >= self._consecutive_frames:
                await self._create_alert(
                    intersection_id,
                    alert_type="congestion",
                    severity="P2",
                    title=f"拥堵指数突破阈值 ({congestion:.1f})",
                    description=f"路口 {intersection_id} 连续 {count} 帧拥堵指数 > {self._congestion_threshold}",
                    event_context=data,
                )
                self._consecutive_congestion[intersection_id] = 0
        else:
            self._consecutive_congestion[intersection_id] = 0

        # Calibration drift check
        match_rate = data.get("lane_match_rate", 1.0)
        if match_rate < self._calibration_threshold:
            await self._create_alert(
                intersection_id,
                alert_type="calibration_drift",
                severity="P3",
                title=f"标定漂移预警 (匹配率 {match_rate:.0%})",
                description=f"路口 {intersection_id} 车道匹配率 {match_rate:.0%} 低于阈值 {self._calibration_threshold:.0%}",
                event_context=data,
            )

        # T-104: high_avg_speed check — 连续帧计数
        avg_speed = data.get("avg_speed_kmh", 0)
        if avg_speed and avg_speed > self._high_speed_threshold_kmh:
            count = self._consecutive_high_speed.get(intersection_id, 0) + 1
            self._consecutive_high_speed[intersection_id] = count
            if count >= self._high_speed_frames:
                await self._create_alert(
                    intersection_id,
                    alert_type="high_avg_speed",
                    severity="P3",
                    title=f"路口平均车速过高 ({avg_speed:.0f}km/h)",
                    description=(
                        f"路口 {intersection_id} 连续 {count} 帧平均车速 "
                        f"{avg_speed:.0f}km/h 超过阈值 {self._high_speed_threshold_kmh:.0f}km/h"
                    ),
                    event_context=data,
                )
                self._consecutive_high_speed[intersection_id] = 0
        else:
            self._consecutive_high_speed[intersection_id] = 0

    def record_conflict(self, intersection_id: str):
        """Record a conflict event for the multiple_conflicts rate tracker.

        T-104: 调用此方法记录冲突事件时间戳，用于滑动窗口检测。
        """
        now = time.time()
        window = self._conflict_windows.setdefault(intersection_id, deque(maxlen=100))
        window.append(now)

        # 清理 60s 前的记录
        cutoff = now - 60
        while window and window[0] < cutoff:
            window.popleft()

        return len(window)

    async def check_conflict_rate(self, intersection_id: str):
        """T-104: 检查过去 1 分钟内冲突数是否超过阈值。"""
        window = self._conflict_windows.get(intersection_id, deque())
        now = time.time()
        cutoff = now - 60
        # 只计算最近 60s 的冲突
        recent = sum(1 for t in window if t >= cutoff)
        if recent > self._conflict_threshold_per_min:
            await self._create_alert(
                intersection_id,
                alert_type="multiple_conflicts",
                severity="P2",
                title=f"冲突事件频发 ({recent}次/分钟)",
                description=(
                    f"路口 {intersection_id} 过去 1 分钟内检测到 {recent} 次冲突事件，"
                    f"超过阈值 {self._conflict_threshold_per_min} 次/分钟"
                ),
            )

    async def on_anomaly_track(self, intersection_id: str, data: dict):
        """Handle anomalous track completion (retrograde, illegal parking)."""
        track_id = data.get("track_id", 0)
        await self._create_alert(
            intersection_id,
            alert_type="retrograde",
            severity="P1",
            title="逆行事件",
            description=f"路口 {intersection_id} 检测到逆行车辆 (track_id: {track_id})",
            track_ids=[track_id],
        )

    async def on_vlm_alert(self, intersection_id: str, data: dict):
        """Handle VLM-detected anomaly or accident."""
        if data.get("accident"):
            await self._create_alert(
                intersection_id,
                alert_type="accident",
                severity="P1",
                title="疑似交通事故",
                description=data.get("summary", "VLM 检测到可能的交通事故"),
            )
        elif data.get("anomaly_detected"):
            await self._create_alert(
                intersection_id,
                alert_type="congestion",
                severity="P2",
                title=data.get("anomaly_description", "VLM 异常检测"),
                description=data.get("summary", ""),
            )

    async def _create_alert(
        self,
        intersection_id: str,
        alert_type: str,
        severity: str,
        title: str,
        description: str | None = None,
        track_ids: list[int] | None = None,
        event_context: dict | None = None,
    ):
        """Create a new alert, broadcast via WebSocket."""
        # Deduplicate: don't create duplicate alerts within 60s
        for existing in self._alerts.values():
            if (
                existing.intersection_id == intersection_id
                and existing.alert_type == alert_type
                and existing.status == "open"
            ):
                return

        alert = Alert(
            intersection_id=intersection_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            track_ids=track_ids,
        )
        self._alerts[alert.id] = alert
        payload = alert.to_dict()
        await self._save_persisted_alert(payload)
        if self._event_center:
            try:
                await self._event_center.record_alert(payload, event_context or {})
            except Exception as exc:
                logger.warning("Replayable event persistence failed: %s", exc)

        logger.info(f"Alert created: [{severity}] {title} @ {intersection_id}")

        # Broadcast via WebSocket
        ws_msg = {
            "channel": "uav_alerts",
            "type": "uav_alert_new",
            "data": payload,
            "ts": time.time(),
        }
        await self._ws.broadcast("uav_alerts", ws_msg)

        # Also broadcast to intersection-specific alert channel
        await self._ws.broadcast(f"uav_alerts:{intersection_id}", ws_msg)
