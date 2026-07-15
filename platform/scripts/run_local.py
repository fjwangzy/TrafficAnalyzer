#!/usr/bin/env python3
"""Local development startup script for Traffic Platform monolith."""
import os
import sys
import subprocess


def main():
    """Start the Traffic Platform monolith locally."""
    print("🚀 Starting Traffic Platform (monolith)...")
    print()

    # Set default environment variables for local development
    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("SERVICE_PORT", "8000")

    # Database (local PostgreSQL)
    os.environ.setdefault("DB_HOST", "localhost")
    os.environ.setdefault("DB_PORT", "5432")
    os.environ.setdefault("DB_USER", "traffic")
    os.environ.setdefault("DB_PASSWORD", "traffic123")
    os.environ.setdefault("DB_NAME", "road9")

    # Kafka (local)
    os.environ.setdefault("KAFKA_BOOTSTRAP", "localhost:9092")
    os.environ.setdefault("KAFKA_CONSUMER_GROUP", "platform-consumer")
    os.environ.setdefault("KAFKA_TOPICS_PATTERN", "((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)")

    # InfluxDB (local)
    os.environ.setdefault("INFLUX_HOST", "localhost")
    os.environ.setdefault("INFLUX_PORT", "8086")
    os.environ.setdefault("INFLUX_DB", "traffic")

    # JWT
    os.environ.setdefault("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")

    # Video
    os.environ.setdefault("HLS_OUTPUT_DIR", "/tmp/hls")
    os.environ.setdefault("PIPELINE_VIDEO_BASE", "http://localhost:8100/video")

    # Calibration
    os.environ.setdefault("CALIBRATION_DB_PATH", "../../configs/calibration_db.json")
    os.environ.setdefault("SURVEY_STORAGE_DIR", "/tmp/traffic-survey-data")
    os.environ.setdefault("SURVEY_ASSET_ROOTS", '["../test_videos"]')

    print("Environment:")
    print(f"  - Database: {os.environ['DB_HOST']}:{os.environ['DB_PORT']}")
    print(f"  - Kafka: {os.environ['KAFKA_BOOTSTRAP']}")
    print(f"  - InfluxDB: {os.environ['INFLUX_HOST']}:{os.environ['INFLUX_PORT']}")
    print(f"  - Port: {os.environ['SERVICE_PORT']}")
    print()

    # Create HLS output directory
    os.makedirs(os.environ["HLS_OUTPUT_DIR"], exist_ok=True)

    # Start uvicorn
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", os.environ["SERVICE_PORT"],
    ]
    if os.environ.get("DEBUG") == "true":
        cmd.append("--reload")

    print(f"Running: {' '.join(cmd)}")
    print()

    try:
        subprocess.run(cmd, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
