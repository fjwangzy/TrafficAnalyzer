"""Alert persistence model."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlertRecord(Base):
    """Persisted alert record for event handling and replay."""

    __tablename__ = "uav_alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    intersection_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="open")
    timestamp: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    track_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    snapshot_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_clip_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vlm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    acknowledged_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    push_logs: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
