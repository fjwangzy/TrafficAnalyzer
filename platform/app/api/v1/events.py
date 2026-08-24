"""Unified Event Center endpoints."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.survey_service import SurveyService

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


def _actor(request: Request) -> tuple[int | None, str, str]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authenticated event survey identity required")
    try:
        actor_id = int(user.get("sub")) if user.get("sub") is not None else None
    except (TypeError, ValueError):
        actor_id = None
    return actor_id, user.get("username", "unknown"), user.get("role", "viewer")


@router.get("")
async def list_events(
    request: Request,
    event_type: str | None = None,
    inter_id: str | None = None,
    source_profile_id: str | None = None,
    mission_id: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=150, ge=1, le=150),
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


@router.post("/{event_id}/survey", status_code=status.HTTP_201_CREATED)
async def create_event_survey(
    event_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, actor_name, role = _actor(request)
    request_id = idempotency_key or request.headers.get("X-Request-ID")
    if request_id and len(request_id) > 80:
        raise HTTPException(status_code=422, detail="request identifier exceeds 80 characters")
    try:
        event = await _center(request).get_event(event_id)
        return await SurveyService(db).create_from_event(
            event, actor_id, actor_name, role, request_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
        if event["source_kind"] == "replay_v2_conflict":
            raise HTTPException(
                status_code=422,
                detail="Replay V2 conflict review is read-only",
            )
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
