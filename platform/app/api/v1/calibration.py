"""Calibration API endpoints."""
import json
import logging
import os
from fastapi import APIRouter, Request


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calibration", tags=["calibration"])


def _load_calibration_db(path: str) -> dict:
    """Load calibration database JSON."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load calibration DB: {e}")
    return {}


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
