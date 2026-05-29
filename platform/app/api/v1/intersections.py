"""Intersection API endpoints."""
from fastapi import APIRouter, Request, Query
from typing import Optional


router = APIRouter(prefix="/intersections", tags=["intersections"])


# In-memory intersection registry (populated from Kafka + config)
_INTERSECTIONS: dict[str, dict] = {
    "INT_camera_1": {
        "id": "INT_camera_1",
        "name": "路口 1 (Camera 1)",
        "center_lat": 36.7029,
        "center_lon": 117.0223,
        "lane_count": 5,
        "status": "active",
        "current_drone_id": None,
        "lanes": [
            {"id": i, "name": f"车道 {i}", "direction": "inbound", "compass": d}
            for i, d in enumerate(["north", "east", "south", "west", "north"], 1)
        ],
    },
    "INT_camera_2": {
        "id": "INT_camera_2",
        "name": "路口 2 (Camera 2)",
        "center_lat": 36.7050,
        "center_lon": 117.0250,
        "lane_count": 5,
        "status": "active",
        "current_drone_id": None,
        "lanes": [
            {"id": i, "name": f"车道 {i}", "direction": "inbound", "compass": d}
            for i, d in enumerate(["north", "east", "south", "west", "north"], 1)
        ],
    },
}


def update_intersection(int_id: str, data: dict):
    """Update intersection state from Kafka data."""
    if int_id not in _INTERSECTIONS:
        _INTERSECTIONS[int_id] = {
            "id": int_id,
            "name": f"路口 ({int_id})",
            "center_lat": 0.0,
            "center_lon": 0.0,
            "lane_count": len(data.get("lanes", [])) or 5,
            "status": "active",
            "current_drone_id": None,
            "lanes": [],
        }
    _INTERSECTIONS[int_id]["status"] = "active"


@router.get("")
async def list_intersections():
    """List all known intersections."""
    return list(_INTERSECTIONS.values())


@router.get("/summary")
async def get_summary(request: Request):
    """Get system-wide summary for dashboard KPIs."""
    kafka = request.app.state.kafka_service
    latest = kafka.latest_stats if kafka else {}

    total_flow = 0
    max_congestion = 0.0
    active_count = 0

    for int_id, stats in latest.items():
        cars = stats.get("cars", stats.get("total_vehicles", 0))
        total_flow += int(cars) if cars else 0
        cong = stats.get("congestion_index", 0)
        if cong > max_congestion:
            max_congestion = cong
        active_count += 1

    alert_engine = request.app.state.alert_engine
    open_alerts = len([
        a for a in alert_engine.alerts.values()
        if a.status == "open"
    ]) if alert_engine else 0

    sys_metrics = kafka.latest_system if kafka else {}

    return {
        "total_intersections": len(_INTERSECTIONS),
        "active_intersections": active_count,
        "total_flow": total_flow,
        "congestion_index": round(max_congestion, 2),
        "anomalies": open_alerts,
        "drones_online": 0,
        "gpu_pct": sys_metrics.get("gpu_util_pct", sys_metrics.get("gpu_utilization", 0)),
        "latency_ms": sys_metrics.get("kafka_lag", 0) * 33 + 42,
    }


@router.get("/{intersection_id}")
async def get_intersection(intersection_id: str):
    """Get a single intersection by ID."""
    data = _INTERSECTIONS.get(intersection_id)
    if not data:
        return {"error": "not_found", "id": intersection_id}
    return data


@router.get("/{intersection_id}/stats")
async def get_stats(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
    granularity: str = Query("1m"),
):
    """Get historical stats from InfluxDB."""
    influx = request.app.state.influx
    if influx:
        return influx.query_stats(intersection_id, period, granularity)
    # Fallback: return latest from Kafka cache
    kafka = request.app.state.kafka_service
    if kafka:
        latest = kafka.latest_stats.get(intersection_id)
        return [latest] if latest else []
    return []


@router.get("/{intersection_id}/lane-stats")
async def get_lane_stats(
    intersection_id: str,
    request: Request,
    period: str = Query("10m"),
    granularity: str = Query("1s"),
):
    """Get lane-level stats from InfluxDB."""
    influx = request.app.state.influx
    if influx:
        return influx.query_lane_stats(intersection_id, period, granularity)
    return []
