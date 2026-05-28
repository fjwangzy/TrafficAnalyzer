"""Webhook domain models"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


class WebhookChannel(str, Enum):
    """Webhook 推送渠道"""
    WECOM = "wecom"  # 企业微信
    DINGTALK = "dingtalk"  # 钉钉
    HTTP_POST = "http_post"  # 通用 HTTP POST
    SMS = "sms"  # 短信


class Webhook(BaseModel):
    """Webhook 配置"""
    id: str  # UUID
    intersection_id: Optional[str] = None  # 关联路口（None 表示全局）
    channel: WebhookChannel
    url: str
    token: Optional[str] = None
    enabled: bool = True
    severity_filter: list[str] = ["P1", "P2"]  # 只推送这些等级的告警
    rate_limit_sec: int = 300  # 推送频率限制（秒）
    created_at: datetime
    updated_at: datetime


class AlertPushLog(BaseModel):
    """告警推送日志"""
    id: str  # UUID
    alert_id: str
    webhook_id: str
    channel: WebhookChannel
    status: str  # success/failed
    response_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    pushed_at: datetime
