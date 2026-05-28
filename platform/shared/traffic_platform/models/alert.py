"""Alert domain models"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


class AlertType(str, Enum):
    """告警类型"""
    RETROGRADE = "retrograde"  # 逆行
    QUEUE_OVERFLOW = "queue_overflow"  # 排队溢出
    CONGESTION = "congestion"  # 拥堵
    CALIBRATION_DRIFT = "calibration_drift"  # 标定漂移
    ACCIDENT = "accident"  # 事故
    ILLEGAL_PARKING = "illegal_parking"  # 违停


class AlertSeverity(str, Enum):
    """告警严重等级"""
    P1 = "P1"  # 严重（立即处理）
    P2 = "P2"  # 警告（尽快处理）
    P3 = "P3"  # 提示（可延后处理）


class AlertStatus(str, Enum):
    """告警状态"""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(BaseModel):
    """告警模型"""
    id: str  # UUID
    intersection_id: str
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN
    title: str
    description: Optional[str] = None
    snapshot_url: Optional[str] = None  # 告警截图
    video_clip_url: Optional[str] = None  # 前后30s视频
    vlm_summary: Optional[str] = None  # Qwen-VL 分析
    track_ids: list[int] = []  # 关联轨迹
    acknowledged_by: Optional[int] = None  # 确认人 user_id
    acknowledged_at: Optional[datetime] = None
    created_at: datetime
