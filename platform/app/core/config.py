"""Traffic Platform Monolith — unified configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


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

    # ── PostgreSQL Database ──
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "traffic"
    db_password: str = "traffic123"
    db_name: str = "traffic_platform"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ── Kafka ──
    kafka_bootstrap: str = "kafka:9092"
    kafka_consumer_group: str = "vision-service"
    kafka_topics_pattern: str = "((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)"

    # ── InfluxDB ──
    influx_host: str = "influxdb"
    influx_port: int = 8086
    influx_db: str = "traffic"
    influx_user: str = ""
    influx_pass: str = ""

    # ── JWT ──
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # ── Alert Rules ──
    queue_overflow_threshold_m: float = 80.0
    congestion_severe_threshold: float = 4.0
    calibration_drift_match_rate: float = 0.80
    consecutive_congestion_frames: int = 30

    # ── Video ──
    hls_output_dir: str = "/hls"
    pipeline_video_base: str = "http://traffic_analyzer_camera_1:8100/video"
    pipeline_python: str = "python"
    pipeline_frame_stride: int | None = None

    # ── Calibration ──
    calibration_db_path: str = "/calibration/calibration_db.json"
    lane_annotation_db_path: str = "/calibration/lane_annotation_db.json"
    lane_annotation_hover_seconds: float = 30.0
    lane_annotation_hover_radius_m: float = 1.5


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
