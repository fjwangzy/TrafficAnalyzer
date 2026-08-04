"""Traffic Platform Monolith — unified configuration."""
import time
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.pipeline_options import (
    DEFAULT_FRAME_STRIDE,
    MAX_FRAME_STRIDE,
    MIN_FRAME_STRIDE,
)


class Settings(BaseSettings):
    """Unified application settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──
    app_name: str = "Traffic Platform"
    debug: bool = False
    api_prefix: str = "/api/v1"
    service_port: int = 8000
    cors_origins: list[str] = ["*"]
    deployment_mode: Literal["local", "uat", "production"] = "local"

    # ── PostgreSQL Database ──
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "traffic"
    db_password: str = "traffic123"
    db_name: str = "road9"
    db_bootstrap_database: str = "postgres"

    # ── External YCX road network (strictly read-only) ──
    ycx_db_host: str = ""
    ycx_db_port: int = 5432
    ycx_db_user: str = ""
    ycx_db_password: str = ""
    ycx_db_name: str = "ycx"
    ycx_db_schema: str = "road9"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ── Kafka ──
    kafka_bootstrap: str = "kafka:9092"
    kafka_consumer_group: str = "vision-service"
    kafka_topics_pattern: str = "(uav_(statistics|track_complete|conflicts|telemetry)_.*|uav_system_metrics)"

    # ── JWT ──
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    media_cookie_name: str = "uav_media_session"
    media_cookie_secure: bool = False
    media_cookie_samesite: Literal["strict"] = "strict"
    media_cookie_path: str = "/"
    bootstrap_admin_password: str = "admin123"

    # ── Alert Rules ──
    queue_overflow_threshold_m: float = 80.0
    congestion_severe_threshold: float = 4.0
    calibration_drift_match_rate: float = 0.80
    consecutive_congestion_frames: int = 30

    # ── Video ──
    hls_output_dir: str = "/hls"
    pipeline_video_base: str = "http://127.0.0.1:{video_port}/video"
    pipeline_python: str = "python"
    pipeline_video_ready_timeout_sec: float = 45.0
    pipeline_frame_stride: int = Field(
        default=DEFAULT_FRAME_STRIDE,
        ge=MIN_FRAME_STRIDE,
        le=MAX_FRAME_STRIDE,
    )
    pipeline_max_active: int = 4
    pipeline_device: str | None = None
    pipeline_imgsz: int | None = None
    # Dynamic detector camera IDs scope canonical Kafka topics. Seed each
    # Platform runtime uniquely so a recovered Mission cannot publish behind
    # an older replay backlog on a reused uav_statistics_10 topic.
    pipeline_camera_id_start: int = int(time.time())
    mission_pipeline_missing_grace_sec: float = 15.0
    video_max_active_streams: int = 4
    uav_rtsp_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]

    # ── S9 Mission orchestration ──
    uav_local_asset_roots: list[str] = ["test_videos", "/app/test_videos"]
    mission_scheduler_poll_sec: float = 5.0
    # ── Calibration ──
    calibration_db_path: str = "/calibration/calibration_db.json"
    lane_annotation_db_path: str = "/calibration/lane_annotation_db.json"
    lane_annotation_auto_tasks_enabled: bool = False
    lane_annotation_hover_seconds: float = 30.0
    lane_annotation_hover_radius_m: float = 1.5
    calibration_media_roots: list[str] = [
        "/calibration",
        "/tmp/traffic-survey-data",
        ".runtime/calibration",
        "test_videos",
        "/app/test_videos",
    ]

    # ── Accident survey ──
    survey_storage_dir: str = "/tmp/traffic-survey-data"
    survey_asset_roots: list[str] = ["test_videos", "/app/test_videos"]
    survey_max_upload_mb: int = 8192
    survey_keyframe_count: int = 6
    survey_report_font_path: str = ""
    survey_delivery_url: str = ""
    survey_worker_poll_sec: float = 1.0
    survey_delivery_max_attempts: int = 5

    @property
    def survey_upload_max_bytes(self) -> int:
        return self.survey_max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def reject_insecure_deployment_defaults(self):
        if self.deployment_mode in {"uat", "production"}:
            insecure_jwt = {
                "",
                "your-secret-key-change-in-production",
                "local-road9-target-change-before-production",
            }
            if self.db_password in {"", "traffic123"}:
                raise ValueError("uat/production requires a non-default DB password")
            if self.jwt_secret_key in insecure_jwt:
                raise ValueError("uat/production requires a non-default JWT secret")
            if self.bootstrap_admin_password in {"", "admin123"}:
                raise ValueError("uat/production requires a non-default bootstrap admin password")
            if not self.media_cookie_secure:
                raise ValueError("uat/production requires secure media cookies")
            if "*" in self.cors_origins:
                raise ValueError("uat/production requires an explicit CORS origin allowlist")
            if "*" in self.uav_rtsp_allowed_hosts:
                raise ValueError("uat/production does not allow wildcard RTSP hosts")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
