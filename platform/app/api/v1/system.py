"""System metrics API endpoints."""
import os
from pathlib import Path

from fastapi import APIRouter, Request, Query


router = APIRouter(prefix="/system", tags=["system"])


def list_model_files(weights_dir: str | Path) -> list[dict]:
    """Return model files present on disk."""
    path = Path(weights_dir)
    if not path.exists():
        return []
    models = []
    for file_path in sorted(path.glob("*.pt")):
        stat = file_path.stat()
        models.append({
            "name": file_path.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 1),
            "type": "custom" if "best" in file_path.name else "yolo",
        })
    return models


@router.get("/health")
async def health_check(request: Request):
    """System health check."""
    kafka = request.app.state.kafka_service
    ws = request.app.state.ws_manager
    pm = getattr(request.app.state, "pipeline_manager", None)

    kafka_healthy = kafka is not None and kafka._running
    return {
        "status": "healthy",
        "service": "platform",
        "kafka_connected": kafka_healthy,
        "ws_connections": ws.total_connections if ws else 0,
        "ws_channels": ws.channel_stats if ws else {},
        "pipelines_active": pm.get_active_count() if pm else 0,
    }


@router.get("/gpu")
async def get_gpu_metrics(request: Request):
    """Get latest GPU metrics from Kafka cache."""
    kafka = request.app.state.kafka_service
    if kafka:
        sys = kafka.latest_system
        return {
            "gpu_util_pct": sys.get("gpu_util_pct", sys.get("gpu_utilization", 0)),
            "gpu_vram_used_mb": sys.get("gpu_vram_used_mb", sys.get("gpu_memory_used_mb", 0)),
            "gpu_vram_total_mb": sys.get("gpu_vram_total_mb", sys.get("gpu_memory_total_mb", 8192)),
            "gpu_temp_c": sys.get("gpu_temp_c", sys.get("gpu_temperature", 0)),
            "fps": sys.get("fps", 0),
            "inference_ms": sys.get("inference_ms", 0),
            "tracking_ms": sys.get("tracking_ms", 0),
        }
    return {"error": "no_data"}


@router.get("/gpu/history")
async def get_gpu_history(
    request: Request,
    period: str = Query("30m"),
    granularity: str = Query("5s"),
):
    """Get GPU metrics history from InfluxDB."""
    influx = request.app.state.influx
    if influx:
        return influx.query_system_metrics(period, granularity)
    return []


@router.get("/kafka/topics")
async def get_kafka_topics(request: Request):
    """Get Kafka topic statistics."""
    kafka = request.app.state.kafka_service
    if kafka:
        latest = getattr(kafka, "latest_stats", {})
        topics = []
        for data in latest.values():
            camera_id = str(data.get("camera_id", "")).replace("id_", "")
            if camera_id:
                topics.append({"name": f"statistics_{camera_id}", "partitions": 1, "tps": 0, "lag": 0})
        return {
            "topics": topics,
            "consumer_group": kafka._group_id,
        }
    return {"topics": [], "consumer_group": "none"}


@router.get("/kafka/consumers")
async def get_kafka_consumers(request: Request):
    """Get Kafka consumer group status."""
    kafka = request.app.state.kafka_service
    if kafka:
        return {
            "group_id": kafka._group_id,
            "state": "Stable" if kafka._running else "Dead",
            "members": 1 if kafka._running else 0,
        }
    return {"group_id": "none", "state": "Dead", "members": 0}


@router.get("/models")
async def list_models():
    """List available YOLO models."""
    project_root = Path(os.environ.get("PIPELINE_PROJECT_ROOT", Path.cwd().parent))
    models = list_model_files(project_root / "weights")
    current = models[0]["name"] if models else None
    return {"models": models, "current": current}
