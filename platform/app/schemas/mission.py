"""S9 request contracts. FlightPlan and Mission are intentionally separate."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DroneCreate(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=160)
    enabled: bool = True
    default_inter_id: str | None = Field(default=None, max_length=100)


class DroneUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    default_inter_id: str | None = Field(default=None, max_length=100)
    default_video_source_id: str | None = Field(default=None, max_length=40)
    default_telemetry_source_id: str | None = Field(default=None, max_length=40)


class SourceInput(BaseModel):
    source_type: Literal["mp4", "rtsp", "srt", "file", "mqtt"]
    location: str = Field(min_length=1, max_length=2000)
    credential_ref: str | None = Field(default=None, max_length=300)
    time_offset_sec: float | None = Field(default=None, ge=-86400, le=86400)
    sync_tolerance_sec: float | None = Field(default=None, gt=0, le=60)


class SourcePairCreate(BaseModel):
    profile_id: str | None = Field(default=None, max_length=40)
    mode: Literal["local", "realtime"]
    video: SourceInput
    telemetry: SourceInput
    enabled: bool = True
    set_default: bool = False

    @model_validator(mode="after")
    def validate_pair(self):
        actual = (self.video.source_type, self.telemetry.source_type)
        if self.mode == "local" and actual not in {("mp4", "srt"), ("mp4", "file")}:
            raise ValueError("local source pair must be mp4+srt or mp4+file")
        if self.mode == "realtime" and actual != ("rtsp", "mqtt"):
            raise ValueError("realtime source pair must be rtsp+mqtt")
        return self


class SourcePairUpdate(BaseModel):
    revision: int = Field(ge=1)
    enabled: bool | None = None
    set_default: bool = False
    video: SourceInput | None = None
    telemetry: SourceInput | None = None


class OnceSchedule(BaseModel):
    type: Literal["once"]
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def valid_window(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("once schedule timestamps must include a timezone")
        if self.end_at <= self.start_at:
            raise ValueError("once schedule end_at must be after start_at")
        return self


class WeeklySchedule(BaseModel):
    type: Literal["weekly"]
    weekdays: list[int] = Field(min_length=1)
    local_start: time
    local_end: time
    effective_from: date
    effective_to: date | None = None
    exceptions: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_days(self):
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must use Monday=0 through Sunday=6")
        self.weekdays = sorted(set(self.weekdays))
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


Schedule = OnceSchedule | WeeklySchedule


class FlightPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    drone_id: str = Field(min_length=1, max_length=40)
    source_profile_id: str = Field(min_length=1, max_length=40)
    inter_id: str = Field(min_length=1, max_length=100)
    road_data_version: str = Field(min_length=1, max_length=100)
    ai_mode: str = Field(default="traffic_monitoring", max_length=40)
    tracking_profile: Literal["hover_cruise_v1", "hover_only_legacy"] = "hover_cruise_v1"
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    schedule: Schedule = Field(discriminator="type")


class FlightPlanUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_profile_id: str | None = Field(default=None, max_length=40)
    inter_id: str | None = Field(default=None, max_length=100)
    road_data_version: str | None = Field(default=None, max_length=100)
    ai_mode: str | None = Field(default=None, max_length=40)
    tracking_profile: Literal["hover_cruise_v1", "hover_only_legacy"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    schedule: Schedule | None = Field(default=None, discriminator="type")


class RevisionAction(BaseModel):
    revision: int = Field(ge=1)


class MissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    drone_id: str = Field(min_length=1, max_length=40)
    source_profile_id: str | None = Field(default=None, max_length=40)
    inter_id: str | None = Field(default=None, max_length=100)
    road_data_version: str | None = Field(default=None, max_length=100)
    map_version_id: str | None = Field(default=None, max_length=40)
    scheduled_end_at: datetime | None = None

    @model_validator(mode="after")
    def valid_shape(self):
        if not self.inter_id:
            raise ValueError("inter_id is required")
        if not self.source_profile_id:
            raise ValueError("source_profile_id is required")
        return self


class MissionAction(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
