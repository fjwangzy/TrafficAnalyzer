"""Trajectory API endpoints."""
from fastapi import APIRouter, Request, Query
from typing import Optional


router = APIRouter(prefix="/trajectories", tags=["trajectories"])


@router.get("/{intersection_id}")
async def get_trajectories(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
    limit: int = Query(500, le=2000),
    class_name: Optional[str] = Query(None),
    turn_behavior: Optional[str] = Query(None),
):
    """Get track events for an intersection."""
    influx = request.app.state.influx
    if influx:
        return influx.query_track_events(
            intersection_id, period, limit, turn_behavior, class_name
        )
    return []


@router.get("/{intersection_id}/heatmap")
async def get_trajectory_heatmap(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get trajectory heatmap data."""
    influx = request.app.state.influx
    if influx:
        tracks = influx.query_track_events(intersection_id, period, limit=2000)
        # Aggregate positions into grid cells
        grid: dict[str, int] = {}
        for t in tracks:
            positions = t.get("positions_bev", "[]")
            if isinstance(positions, str):
                import json
                try:
                    positions = json.loads(positions)
                except Exception:
                    continue
            for pos in positions:
                if len(pos) >= 2:
                    # Grid cell: 1m resolution
                    key = f"{int(pos[0])},{int(pos[1])}"
                    grid[key] = grid.get(key, 0) + 1

        return [
            {"bev_x": float(k.split(",")[0]), "bev_y": float(k.split(",")[1]), "density": v}
            for k, v in sorted(grid.items(), key=lambda x: -x[1])[:200]
        ]
    return []


@router.get("/{intersection_id}/turn-summary")
async def get_turn_summary(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get turn behavior distribution."""
    influx = request.app.state.influx
    if influx:
        return influx.query_turn_summary(intersection_id, period)
    return []


@router.get("/{intersection_id}/lane-change-heatmap")
async def get_lane_change_heatmap(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get lane change position heatmap."""
    influx = request.app.state.influx
    if influx:
        return influx.query_lane_changes(intersection_id, period)
    return []
