"""REST schemas for the S3 accident-survey module."""

from typing import Literal

from pydantic import BaseModel, Field


class SurveyTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    scene_location: str = Field(min_length=2, max_length=300)
    source: str = Field(default="local", max_length=40)
    external_task_id: str | None = Field(default=None, max_length=100)
    inter_id: str | None = Field(default=None, max_length=100)
    road_data_version: str | None = Field(default=None, max_length=100)
    assignee_user_id: int | None = None
    owner_name: str | None = Field(default=None, max_length=120)


class SurveyAction(BaseModel):
    action: Literal[
        "start_precheck",
        "complete_precheck",
        "select_batch",
        "submit_review",
        "return",
        "approve_review",
        "cancel",
    ]
    expected_revision: int = Field(ge=1)
    checklist: dict[str, bool] | None = None
    batch_id: str | None = None
    return_type: Literal["capture", "measurement"] | None = None
    reason: str | None = Field(default=None, max_length=1000)


class SurveyAssetImport(BaseModel):
    video_asset: str = Field(min_length=1, max_length=500)
    telemetry_asset: str = Field(min_length=1, max_length=500)


class MeasurementCreate(BaseModel):
    frame_id: str
    geometry_type: Literal["point", "line", "polyline", "area", "object"]
    category: str | None = Field(default=None, max_length=80)
    image_geometry: list[list[float]] = Field(min_length=1)


class MeasurementUpdate(MeasurementCreate):
    expected_revision: int = Field(ge=1)
