"""Trajectory API endpoints."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.metric_store import MessageIdentityConflict, MetricContractError

router = APIRouter(prefix="/trajectories", tags=["trajectories"])


class ConflictReviewRequest(BaseModel):
    review_status: str
    expected_revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


@router.get("/{intersection_id}/replay-missions")
async def get_replay_missions(
    intersection_id: str,
    request: Request,
    include_incomplete: bool = Query(False),
):
    """List sealed replay-v2 Missions; incomplete runs are diagnostic-only."""
    if include_incomplete:
        user = getattr(request.state, "user", None)
        if not user or user.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Administrator role required for incomplete Mission diagnostics",
            )
    repository = getattr(request.app.state, "replay_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="ReplayRepository unavailable")
    items = await repository.list_missions(
        intersection_id,
        include_incomplete=include_incomplete,
    )
    return {"schema_version": "uav.replay-missions/v1", "items": items}


@router.get("/{intersection_id}/replay")
async def get_trajectory_replay(
    intersection_id: str,
    request: Request,
    mission_id: str = Query(..., min_length=1),
    cursor_sec: float = Query(0.0, ge=0.0),
    window_sec: float = Query(10.0, gt=0.0, le=300.0),
    max_points: int = Query(5000, ge=1, le=20000),
    page_after: str | None = Query(None),
    track_id: str | None = Query(None),
    behavior: str | None = Query(None),
    vehicle_class: str | None = None,
    yolo_class_id: int | None = None,
    turn_behavior: str | None = None,
    movement_key: str | None = None,
):
    """Return event-faithful points on one sealed Mission-relative clock."""
    repository = getattr(request.app.state, "replay_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="ReplayRepository unavailable")
    try:
        return await repository.replay(
            intersection_id,
            mission_id=mission_id,
            cursor_ms=round(cursor_sec * 1000),
            window_ms=round(window_sec * 1000),
            max_points=max_points,
            page_after=page_after,
            track_id=track_id,
            behavior=behavior,
            vehicle_class=vehicle_class,
            yolo_class_id=yolo_class_id,
            turn_behavior=turn_behavior,
            movement_key=movement_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{intersection_id}")
async def get_trajectories(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
    limit: int = Query(500, le=2000),
    class_name: str | None = Query(None),
    turn_behavior: str | None = Query(None),
    mission_id: str | None = Query(None),
    source_profile_id: str | None = Query(None),
    quality_status: str | None = Query(None),
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    spatial_ready: bool = Query(False),
    min_gcj02_points: int = Query(2, ge=2, le=10000),
):
    """Get track events for an intersection."""
    metric_store = getattr(request.app.state, "metric_store", None)
    return await metric_store.query_tracks(
        intersection_id,
        period,
        limit,
        class_name=class_name,
        turn_behavior=turn_behavior,
        mission_id=mission_id,
        source_profile_id=source_profile_id,
        quality_status=quality_status,
        start_at=start_at,
        end_at=end_at,
        spatial_ready=spatial_ready,
        min_gcj02_points=min_gcj02_points,
    ) if metric_store else []


@router.get("/{intersection_id}/analysis")
async def get_trajectory_analysis(
    intersection_id: str,
    request: Request,
    period: str = Query("all"),
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    slice_start_at: datetime | None = Query(None),
    slice_end_at: datetime | None = Query(None),
    bucket_sec: int = Query(10, ge=1, le=300),
    mission_id: str | None = Query(None),
    source_profile_id: str | None = Query(None),
    vehicle_class: str | None = Query(None),
    yolo_class_id: int | None = Query(None),
    yolo_class_name: str | None = Query(None),
    turn_behavior: str | None = Query(None),
    quality_status: str | None = Query(None),
    movement_key: str | None = Query(None),
    track_limit: int = Query(500, ge=1, le=2000),
):
    """Aggregate a bounded trajectory-analysis window and return its replay slice."""
    if (start_at is None) != (end_at is None):
        raise HTTPException(status_code=422, detail="start_at and end_at must be provided together")
    if (slice_start_at is None) != (slice_end_at is None):
        raise HTTPException(
            status_code=422, detail="slice_start_at and slice_end_at must be provided together"
        )
    if start_at is not None and end_at is not None and start_at >= end_at:
        raise HTTPException(status_code=422, detail="start_at must be earlier than end_at")
    if slice_start_at is not None and slice_end_at is not None and slice_start_at >= slice_end_at:
        raise HTTPException(status_code=422, detail="slice_start_at must be earlier than slice_end_at")
    if (
        start_at is not None and end_at is not None
        and slice_start_at is not None and slice_end_at is not None
        and (slice_start_at < start_at or slice_end_at > end_at)
    ):
        raise HTTPException(status_code=422, detail="time slice must be contained in the analysis window")

    metric_store = getattr(request.app.state, "metric_store", None)
    if not metric_store:
        raise HTTPException(status_code=503, detail="MetricStore unavailable")
    return await metric_store.query_trajectory_analysis(
        intersection_id,
        period=period,
        start_at=start_at,
        end_at=end_at,
        slice_start_at=slice_start_at,
        slice_end_at=slice_end_at,
        bucket_sec=bucket_sec,
        mission_id=mission_id,
        source_profile_id=source_profile_id,
        vehicle_class=vehicle_class,
        yolo_class_id=yolo_class_id,
        yolo_class_name=yolo_class_name,
        turn_behavior=turn_behavior,
        quality_status=quality_status,
        movement_key=movement_key,
        track_limit=track_limit,
    )


@router.get("/{intersection_id}/conflicts")
async def get_conflict_history(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
    limit: int = Query(200, le=2000),
    source_profile_id: str | None = Query(None),
    pipeline_id: str | None = Query(None),
    prediction_type: str | None = Query(None),
):
    """Get historical conflict events for an intersection."""
    metric_store = getattr(request.app.state, "metric_store", None)
    return await metric_store.query_conflicts(
        intersection_id,
        period,
        limit,
        source_profile_id=source_profile_id,
        pipeline_id=pipeline_id,
        prediction_type=prediction_type,
    ) if metric_store else []


@router.post("/{intersection_id}/conflicts/{event_id}/review")
async def review_conflict(
    intersection_id: str,
    event_id: str,
    payload: ConflictReviewRequest,
    request: Request,
):
    """Persist a technical AI-result review; it is not a police disposition."""
    user = getattr(request.state, "user", None)
    if user is not None and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    reviewed_by = None
    if user:
        try:
            reviewed_by = int(user.get("sub"))
        except (TypeError, ValueError):
            pass
    metric_store = getattr(request.app.state, "metric_store", None)
    if not metric_store:
        raise HTTPException(status_code=503, detail="MetricStore unavailable")
    try:
        return await metric_store.review_conflict(
            intersection_id, event_id, payload.review_status,
            payload.expected_revision, reviewed_by, payload.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MessageIdentityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MetricContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{intersection_id}/heatmap")
async def get_trajectory_heatmap(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get trajectory heatmap data."""
    metric_store = getattr(request.app.state, "metric_store", None)
    tracks = await metric_store.query_tracks(intersection_id, period, 2000) if metric_store else []
    grid: dict[str, int] = {}
    for track in tracks:
        positions = track.get("trajectory_gcj02") or []
        for position in positions if isinstance(positions, list) else []:
            if isinstance(position, list) and len(position) >= 2:
                key = f"{int(position[0])},{int(position[1])}"
                grid[key] = grid.get(key, 0) + 1
    return [
        {"bev_x": float(key.split(",")[0]), "bev_y": float(key.split(",")[1]), "density": density}
        for key, density in sorted(grid.items(), key=lambda item: -item[1])[:200]
    ]


@router.get("/{intersection_id}/turn-summary")
async def get_turn_summary(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get turn behavior distribution."""
    metric_store = getattr(request.app.state, "metric_store", None)
    tracks = await metric_store.query_tracks(intersection_id, period, 2000) if metric_store else []
    counts: dict[str, int] = {}
    for track in tracks:
        behavior = str(track.get("turn_behavior") or "unknown")
        counts[behavior] = counts.get(behavior, 0) + 1
    return [{"turn_behavior": behavior, "count": count} for behavior, count in sorted(counts.items())]


@router.get("/{intersection_id}/lane-change-heatmap")
async def get_lane_change_heatmap(
    intersection_id: str,
    request: Request,
    period: str = Query("1h"),
):
    """Get lane change position heatmap."""
    metric_store = getattr(request.app.state, "metric_store", None)
    tracks = await metric_store.query_tracks(intersection_id, period, 2000) if metric_store else []
    changes = []
    for track in tracks:
        for change in track.get("lane_changes") or []:
            if isinstance(change, dict):
                changes.append(change)
    return changes
