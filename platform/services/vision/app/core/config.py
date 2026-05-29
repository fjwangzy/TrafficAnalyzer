"""Vision Service configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionSettings(BaseSettings):
    """Vision service settings."""
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env")

    service_name: str = "vision"
    service_port: int = 8002
    debug: bool = False

    # Kafka
    kafka_bootstrap: str = "kafka:9092"
    kafka_consumer_group: str = "vision-service"
    kafka_topics_pattern: str = "statistics_.*"

    # InfluxDB
    influx_host: str = "influxdb"
    influx_port: int = 8086
    influx_db: str = "influx"
    influx_user: str = ""
    influx_pass: str = ""

    # CORS
    cors_origins: list[str] = ["*"]

    # Alert rules
    queue_overflow_threshold_m: float = 80.0
    congestion_severe_threshold: float = 4.0
    calibration_drift_match_rate: float = 0.80
    consecutive_congestion_frames: int = 30

    # Video
    hls_output_dir: str = "/hls"
    pipeline_video_base: str = "http://traffic_analyzer_camera_1:8100/video"

    # Calibration
    calibration_db_path: str = "/calibration/calibration_db.json"


settings = VisionSettings()
