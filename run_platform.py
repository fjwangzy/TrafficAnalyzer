#!/usr/bin/env python3
"""Canonical root entrypoint for the Traffic Platform monolith."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
PLATFORM_ROOT = PROJECT_ROOT / "platform"


def configure_environment() -> None:
    """Apply local-development defaults without overriding deployment values."""
    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("SERVICE_PORT", "8000")

    os.environ.setdefault("DB_HOST", "localhost")
    os.environ.setdefault("DB_PORT", "5432")
    os.environ.setdefault("DB_USER", "traffic")
    os.environ.setdefault("DB_PASSWORD", "traffic123")
    os.environ.setdefault("DB_NAME", "road9")
    os.environ.setdefault("DB_BOOTSTRAP_DATABASE", "postgres")

    os.environ.setdefault("KAFKA_BOOTSTRAP", "localhost:9092")
    os.environ.setdefault("KAFKA_CONSUMER_GROUP", "platform-consumer")
    os.environ.setdefault(
        "KAFKA_TOPICS_PATTERN",
        "(uav_(statistics|track_complete|conflicts|telemetry)_.*|uav_system_metrics)",
    )

    os.environ.setdefault("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")

    os.environ.setdefault("PIPELINE_PROJECT_ROOT", str(PROJECT_ROOT))
    os.environ.setdefault("PIPELINE_PYTHON", sys.executable)
    os.environ.setdefault("PIPELINE_VIDEO_BASE", "http://localhost:8100/video")
    os.environ.setdefault("HLS_OUTPUT_DIR", "/tmp/traffic-hls")
    os.environ.setdefault("GEOJSON_OUTPUT_DIR", "/tmp/traffic-pipeline-output")
    os.environ.setdefault("KAFKA_SPOOL_DIR", "/tmp/traffic-pipeline-spool")
    os.environ.setdefault("CALIBRATION_DB_PATH", "/tmp/traffic-calibration/calibration_db.json")
    os.environ.setdefault(
        "LANE_ANNOTATION_DB_PATH",
        "/tmp/traffic-calibration/lane_annotation_db.json",
    )
    os.environ.setdefault("SURVEY_STORAGE_DIR", "/tmp/traffic-survey-data")

    asset_roots = json.dumps([str(PROJECT_ROOT / "test_videos")])
    os.environ.setdefault("SURVEY_ASSET_ROOTS", asset_roots)
    os.environ.setdefault("UAV_LOCAL_ASSET_ROOTS", asset_roots)


def build_command() -> list[str]:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        os.environ["SERVICE_PORT"],
    ]
    if os.environ.get("DEBUG", "").lower() == "true":
        command.append("--reload")
    return command


def main() -> int:
    configure_environment()
    for directory_var in (
        "HLS_OUTPUT_DIR",
        "GEOJSON_OUTPUT_DIR",
        "KAFKA_SPOOL_DIR",
        "SURVEY_STORAGE_DIR",
    ):
        Path(os.environ[directory_var]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["CALIBRATION_DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    try:
        return subprocess.call(build_command(), cwd=PLATFORM_ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
