"""S8 project dashboard read-only aggregation endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _service(request: Request):
    service = getattr(request.app.state, "dashboard_read_model", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "dashboard_unavailable", "message": "road9 聚合读模型不可用"})
    return service


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        result = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_bbox", "message": "bbox 必须为 min_lon,min_lat,max_lon,max_lat"}) from exc
    if len(result) != 4:
        raise HTTPException(status_code=422, detail={"code": "invalid_bbox", "message": "bbox 必须包含 4 个坐标值"})
    min_lon, min_lat, max_lon, max_lat = result
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise HTTPException(status_code=422, detail={"code": "invalid_bbox", "message": "bbox 坐标范围或顺序无效"})
    return result


async def _invoke(awaitable):
    try:
        return await awaitable
    except (TimeoutError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "dashboard_dependency_unavailable", "message": "road9 聚合依赖暂不可用，请保留当前页面并重试"},
        ) from exc


@router.get("/overview")
async def overview(request: Request):
    return await _invoke(_service(request).overview())


@router.get("/intersections")
async def intersections(
    request: Request,
    risk: Literal["critical", "warning", "unknown"] | None = None,
    monitor: Literal["running", "degraded", "standby"] | None = None,
    quality: Literal["verified", "stale", "unverified"] | None = None,
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat (WGS84)"),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return await _invoke(_service(request).intersections(
        risk=risk,
        monitor=monitor,
        quality=quality,
        bbox=_parse_bbox(bbox),
        query=q,
        offset=offset,
        limit=limit,
    ))


@router.get("/intersections/{inter_id}")
async def intersection(inter_id: str, request: Request):
    result = await _invoke(_service(request).intersection(inter_id))
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "intersection_not_found", "message": "路口不在当前授权项目范围"})
    return result


@router.get("/drones")
async def drones(request: Request):
    return await _invoke(_service(request).drones())
