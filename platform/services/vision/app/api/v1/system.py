"""System metrics API endpoints."""
from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health_check(request: Request):
    """System health check."""
    kafka = request.app.state.kafka_service
    ws = request.app.state.ws_manager

    kafka_healthy = kafka is not None and kafka._running
    return {
        "status": "healthy",
        "service": "vision",
        "kafka_connected": kafka_healthy,
        "ws_connections": ws.total_connections if ws else 0,
        "ws_channels": ws.channel_stats if ws else {},
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
        return {
            "topics": [
                {"name": topic, "partitions": 1, "tps": 0, "lag": 0}
                for topic in ["statistics_1", "statistics_2"]
            ],
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
    return {
        "models": [
            {"name": "yolo11n.pt", "size": "5.4 MB", "type": "nano", "active": True},
            {"name": "yolo11s.pt", "size": "18.5 MB", "type": "small", "active": False},
            {"name": "yolo11m.pt", "size": "38.2 MB", "type": "medium", "active": False},
            {"name": "uav_best.pt", "size": "12.1 MB", "type": "custom", "active": False},
        ],
        "current": "yolo11n.pt",
    }
