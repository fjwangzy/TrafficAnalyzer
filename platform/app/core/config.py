"""Traffic Platform Monolith — unified configuration."""
import time
import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL
from sqlalchemy.dialects import registry

from app.core.pipeline_options import (
    DEFAULT_FRAME_STRIDE,
    MAX_FRAME_STRIDE,
    MIN_FRAME_STRIDE,
)

registry.register("postgresql.highgo_psycopg", "app.core.highgo_dialect", "HighGoPsycopgDialect")


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
    intranet_http_enabled: bool = False
    app_runtime_profile: Literal["live", "replay_v2"] = "live"

    # ── PostgreSQL Database ──
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "traffic"
    db_password: str = "traffic123"
    db_name: str = "road9"
    db_bootstrap_database: str = "postgres"
    db_driver: Literal["asyncpg", "psycopg"] = "asyncpg"
    db_schema: str = "public"
    db_sslmode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    db_auto_migrate: bool = True
    db_timescale_required: bool = True
    road_features_enabled: bool = True

    # ── Legacy offline audit settings (not used by runtime readers) ──
    ycx_db_host: str = ""
    ycx_db_driver: Literal["asyncpg", "psycopg"] = "asyncpg"
    ycx_db_port: int = 5432
    ycx_db_user: str = ""
    ycx_db_password: str = ""
    ycx_db_name: str = "ycx"
    ycx_db_schema: str = "road9"
    ycx_metrics_schema: str = "xianchang"
    ycx_road_version: str = ""
    # Runtime road network and traffic conditions are read only from Doris.
    ycx_metrics_backend: Literal["doris"] = "doris"
    doris_mysql_host: str = ""
    doris_mysql_port: int = 9030
    doris_mysql_user: str = ""
    doris_mysql_password: str = ""
    doris_database: str = "ycx_xc"
    dashboard_situation_cache_ttl_sec: float = 300.0
    dashboard_situation_cache_limit: int = 64

    @property
    def database_url(self) -> str:
        return URL.create(
            "postgresql+highgo_psycopg" if self.db_driver == "psycopg" else "postgresql+asyncpg", username=self.db_user,
            password=self.db_password, host=self.db_host, port=self.db_port,
            database=self.db_name,
            query={"application_schema": self.db_schema} if self.db_driver == "psycopg" else {},
        ).render_as_string(hide_password=False)

    @property
    def database_connect_args(self) -> dict:
        if self.db_driver == "psycopg":
            return {"options": f"-csearch_path={self.db_schema},public", "sslmode": self.db_sslmode}
        return {"server_settings": {"search_path": f"{self.db_schema},public"}}

    @property
    def kafka_security_options(self) -> dict:
        from utils_local.kafka_security import kafka_security_options
        return kafka_security_options({
            "KAFKA_SECURITY_PROTOCOL": self.kafka_security_protocol,
            "KAFKA_SASL_MECHANISM": self.kafka_sasl_mechanism,
            "KAFKA_SASL_USERNAME": self.kafka_sasl_username,
            "KAFKA_SASL_PASSWORD": self.kafka_sasl_password,
        })

    # ── Kafka ──
    kafka_bootstrap: str = "kafka:9092"
    kafka_security_protocol: Literal["PLAINTEXT", "SASL_PLAINTEXT"] = "PLAINTEXT"
    kafka_sasl_mechanism: Literal["PLAIN"] = "PLAIN"
    kafka_sasl_username: str = ""
    kafka_sasl_password: str = ""
    kafka_consumer_group: str = "vision-service"
    kafka_topics_pattern: str = "(uav_(statistics|track_complete|conflicts|telemetry|enforcement_clues)_.*|uav_system_metrics)"

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
    pipeline_ascend_manifest: str = ""
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

    @property
    def control_plane_writes_enabled(self) -> bool:
        return True

    @model_validator(mode="after")
    def reject_insecure_deployment_defaults(self):
        for name in ("db_schema", "ycx_db_schema", "ycx_metrics_schema", "doris_database"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", getattr(self, name)):
                raise ValueError(f"{name.upper()} contains unsupported characters")
        if self.kafka_security_protocol.startswith("SASL") and not (
            self.kafka_sasl_username and self.kafka_sasl_password
        ):
            raise ValueError("SASL Kafka requires username and password")
        if self.app_runtime_profile == "replay_v2":
            if self.deployment_mode == "local" and self.db_name != "road9":
                raise ValueError("replay_v2 must use the canonical road9 database")
            self.kafka_consumer_group = "uav-platform-replay-v2"
            self.kafka_topics_pattern = (
                r"^uav_replay_v2_(?:statistics|track_complete|conflicts|telemetry|mission)_"
                r"[A-Za-z0-9._-]+$"
            )
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
            if not self.media_cookie_secure and not (
                self.deployment_mode == "production" and self.intranet_http_enabled
            ):
                raise ValueError("uat/production requires secure media cookies")
            if not self.cors_origins or any("*" in origin for origin in self.cors_origins):
                raise ValueError("uat/production requires an explicit CORS origin allowlist")
            if "*" in self.uav_rtsp_allowed_hosts:
                raise ValueError("uat/production does not allow wildcard RTSP hosts")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
