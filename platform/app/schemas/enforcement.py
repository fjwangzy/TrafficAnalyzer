"""Validated S4 request contracts. All outputs remain AI clues, never violations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ZoneType = Literal["truck_restriction", "no_parking", "speed_observation", "dwell", "occupation"]
ClueType = Literal["truck_restriction", "speed_observation", "no_parking", "dwell", "occupation"]
VehicleClass = Literal["truck", "non_truck", "unknown"]


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    zone_type: ZoneType
    geometry: dict
    coordinate_system: Literal["ENU", "GCJ02", "WGS84"]
    road_data_version: str | None = Field(default=None, max_length=100)
    schedule: dict = Field(default_factory=dict)

    @field_validator("geometry")
    @classmethod
    def valid_polygon(cls, value: dict):
        if value.get("type") != "Polygon":
            raise ValueError("geometry must be a GeoJSON Polygon")
        coordinates = value.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates or len(coordinates[0]) < 4:
            raise ValueError("polygon must contain a closed ring with at least four positions")
        if coordinates[0][0] != coordinates[0][-1]:
            raise ValueError("polygon ring must be closed")
        return value


class ZoneUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    zone_type: ZoneType | None = None
    geometry: dict | None = None
    coordinate_system: Literal["ENU", "GCJ02", "WGS84"] | None = None
    road_data_version: str | None = Field(default=None, max_length=100)
    schedule: dict | None = None
    status: Literal["candidate", "retired"] | None = None

    @field_validator("geometry")
    @classmethod
    def valid_polygon(cls, value: dict | None):
        if value is None:
            return value
        return ZoneCreate.valid_polygon(value)


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    zone_id: str | None = Field(default=None, max_length=40)
    clue_type: ClueType
    definition: dict

    @field_validator("definition")
    @classmethod
    def candidate_facts_only(cls, value: dict):
        forbidden = {"approved", "legal_threshold", "penalty", "violation"}
        if forbidden.intersection(value):
            raise ValueError("local candidate rules cannot declare approval, penalty, or violation")
        return value


class RuleUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    zone_id: str | None = Field(default=None, max_length=40)
    definition: dict | None = None
    status: Literal["candidate", "retired"] | None = None

    @field_validator("definition")
    @classmethod
    def candidate_facts_only(cls, value: dict | None):
        if value is None:
            return value
        return RuleCreate.candidate_facts_only(value)


class EvidenceReference(BaseModel):
    kind: Literal["original_video", "telemetry", "frame", "clip", "trajectory", "rule_snapshot"]
    storage_key: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=0)
    metadata: dict = Field(default_factory=dict)


class ClueIngest(BaseModel):
    source_event_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    inter_id: str | None = Field(default=None, max_length=100)
    road_data_version: str | None = Field(default=None, max_length=100)
    track_id: str = Field(min_length=1, max_length=80)
    vehicle_class: VehicleClass
    class_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_model_version: str | None = Field(default=None, max_length=120)
    clue_type: ClueType
    zone_id: str | None = Field(default=None, max_length=40)
    zone_version: str | None = Field(default=None, max_length=40)
    rule_id: str | None = Field(default=None, max_length=40)
    rule_version: str | None = Field(default=None, max_length=40)
    matched_facts: dict = Field(default_factory=dict)
    exclusion_result: dict = Field(default_factory=dict)
    video_speed_kmh: float | None = Field(default=None, ge=0)
    video_speed_method: str | None = Field(default=None, max_length=80)
    video_speed_quality: Literal["verified", "degraded", "unverified"] | None = None
    video_speed_uncertainty: float | None = Field(default=None, ge=0)
    radar_speed_kmh: float | None = Field(default=None, ge=0)
    radar_device_id: str | None = Field(default=None, max_length=80)
    radar_metadata: dict = Field(default_factory=dict)
    fused_speed_kmh: float | None = Field(default=None, ge=0)
    fusion_method: str | None = Field(default=None, max_length=80)
    quality_status: Literal["unverified", "degraded"] = "unverified"
    validation_fixture: bool = False
    evidence: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def source_and_quality_boundaries(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if self.video_speed_kmh is not None and not self.video_speed_method:
            raise ValueError("video_speed_method is required with video_speed_kmh")
        if self.radar_speed_kmh is not None:
            if not self.radar_device_id:
                raise ValueError("radar_device_id is required with radar_speed_kmh")
            if self.radar_metadata.get("calibration_status") != "valid":
                raise ValueError("radar calibration_status must be valid")
        elif self.radar_device_id or self.radar_metadata:
            raise ValueError("radar metadata is not allowed without a radar measurement")
        if self.fused_speed_kmh is not None:
            if self.video_speed_kmh is None or self.radar_speed_kmh is None or not self.fusion_method:
                raise ValueError("fusion requires independent video and radar measurements plus fusion_method")
        return self


class ClueReview(BaseModel):
    review_status: Literal["reviewed_confirmed", "reviewed_rejected"]
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
