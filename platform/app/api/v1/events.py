"""Unified Event Center endpoints."""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/events", tags=["events"])


class EventReviewRequest(BaseModel):
    review_status: str
    expected_revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


def _center(request: Request):
    center = getattr(request.app.state, "event_center", None)
    if center is None:
        raise HTTPException(status_code=503, detail="EventCenter unavailable")
    return center


@router.get("")
async def list_events(
    request: Request,
    event_type: str | None = None,
    inter_id: str | None = None,
    source_profile_id: str | None = None,
    mission_id: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    return await _center(request).list_events(
        event_type=event_type,
        inter_id=inter_id,
        source_profile_id=source_profile_id,
        mission_id=mission_id,
        review_status=review_status,
        limit=limit,
    )


@router.get("/{event_id}")
async def get_event(event_id: str, request: Request):
    try:
        return await _center(request).get_event(event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{event_id}/review")
async def review_event(event_id: str, body: EventReviewRequest, request: Request):
    user = getattr(request.state, "user", None)
    if user is not None and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    reviewed_by = None
    if user:
        try:
            reviewed_by = int(user.get("sub"))
        except (TypeError, ValueError):
            pass
    try:
        event = await _center(request).get_event(event_id)
        if event["source_kind"] == "conflict":
            metric_store = getattr(request.app.state, "metric_store", None)
            if metric_store is None:
                raise HTTPException(status_code=503, detail="MetricStore unavailable")
            return await metric_store.review_conflict(
                event["inter_id"], event_id, body.review_status,
                body.expected_revision, reviewed_by, body.reason,
            )
        return await _center(request).review_ai_event(
            event_id, body.review_status, body.expected_revision, reviewed_by, body.reason
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
