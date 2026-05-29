"""Alert engine — rule-based + VLM-based alert detection."""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.kafka.ws_manager import WSManager

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


class AlertEngine:
    """Rule-based and VLM-based alert engine."""

    def __init__(self, ws_manager: WSManager, settings: Any = None):
        self._ws = ws_manager
        self._alerts: dict[str, Alert] = {}  # alert_id → Alert
        self._consecutive_congestion: dict[str, int] = {}  # intersection_id → count

        # Thresholds
        self._queue_threshold = getattr(settings, "queue_overflow_threshold_m", 80.0)
        self._congestion_threshold = getattr(settings, "congestion_severe_threshold", 4.0)
        self._calibration_threshold = getattr(settings, "calibration_drift_match_rate", 0.80)
        self._consecutive_frames = getattr(settings, "consecutive_congestion_frames", 30)

    @property
    def alerts(self) -> dict[str, Alert]:
        return self._alerts

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
        # Sort by timestamp descending
        result.sort(key=lambda a: a.timestamp, reverse=True)
        return [a.to_dict() for a in result[offset:offset + limit]]

    def get_alert(self, alert_id: str) -> dict | None:
        """Get a single alert by ID."""
        alert = self._alerts.get(alert_id)
        return alert.to_dict() if alert else None

    def acknowledge_alert(self, alert_id: str, user: str = "admin") -> dict | None:
        """Acknowledge an alert."""
        alert = self._alerts.get(alert_id)
        if alert:
            alert.acknowledge(user)
            return alert.to_dict()
        return None

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

        logger.info(f"Alert created: [{severity}] {title} @ {intersection_id}")

        # Broadcast via WebSocket
        ws_msg = {
            "channel": "alerts",
            "type": "alert_new",
            "data": alert.to_dict(),
            "ts": time.time(),
        }
        await self._ws.broadcast("alerts", ws_msg)

        # Also broadcast to intersection-specific alert channel
        await self._ws.broadcast(f"alerts:{intersection_id}", ws_msg)
