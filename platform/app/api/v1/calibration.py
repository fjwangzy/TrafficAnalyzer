"""Calibration API endpoints."""
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calibration", tags=["calibration"])


class LanePayload(BaseModel):
    lane_id: str | None = None
    name: str | None = None
    direction: str | None = None
    polygon: list[float] = Field(min_length=6)


class SaveLaneAnnotationPayload(BaseModel):
    lanes: list[LanePayload] = Field(min_length=1)
    roads: dict[str, Any] | None = None


def _load_calibration_db(path: str) -> dict:
    """Load calibration database JSON."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load calibration DB: {e}")
    return {}


def _lane_store(request: Request):
    store = getattr(request.app.state, "lane_annotation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="lane annotation store unavailable")
    return store


@router.get("/summary")
async def get_calibration_summary(request: Request):
    """Get calibration summary."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, list):
        total = len(records)
        ok_count = sum(1 for r in records if r.get("quality", {}).get("score", 0) > 0.9)
        return {"total": total, "ok": ok_count, "degraded": total - ok_count}

    return {
        "total": len(records) if isinstance(records, dict) else 0,
        "records_count": len(records) if isinstance(records, dict) else 0,
    }


@router.get("/records")
async def list_calibration_records(request: Request):
    """List all calibration records."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, dict):
        return [{"key": k, **v} if isinstance(v, dict) else {"key": k, "value": v} for k, v in records.items()]
    elif isinstance(records, list):
        return records
    return []


@router.get("/records/{calib_key}")
async def get_calibration_record(calib_key: str, request: Request):
    """Get a specific calibration record."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, dict):
        record = records.get(calib_key)
        if record:
            return {"key": calib_key, **record} if isinstance(record, dict) else record
    return {"error": "not_found", "key": calib_key}


@router.get("/coverage/{intersection_id}")
async def get_coverage(intersection_id: str, request: Request):
    """Get calibration coverage heatmap data."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    coverage = []
    if isinstance(records, dict):
        for key, val in records.items():
            if intersection_id in key:
                if isinstance(val, dict):
                    quality = val.get("quality", {})
                    coverage.append({
                        "key": key,
                        "altitude": val.get("altitude_agl", 0),
                        "pitch": val.get("gimbal_pitch", 0),
                        "quality": "ok" if quality.get("score", 0) > 0.9 else "degraded",
                    })

    return coverage


@router.get("/lane-tasks")
async def list_lane_annotation_tasks(request: Request):
    """List hover-created lane annotation tasks."""
    return _lane_store(request).list_tasks()


@router.get("/lane-annotations")
async def list_lane_annotations(request: Request):
    """List saved lane annotation parameters."""
    return _lane_store(request).list_annotations()


@router.get("/lane-annotations/{intersection_id}")
async def get_lane_annotation(intersection_id: str, request: Request):
    """Get reusable lane parameters for one intersection."""
    annotation = _lane_store(request).get_annotation(intersection_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="lane annotation not found")
    return annotation


@router.post("/lane-tasks/{task_id}/annotation")
async def save_lane_annotation(
    task_id: str,
    payload: SaveLaneAnnotationPayload,
    request: Request,
):
    """Save a task's manual lane annotation as reusable pipeline parameters."""
    try:
        return _lane_store(request).save_annotation(task_id, payload.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="lane annotation task not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
