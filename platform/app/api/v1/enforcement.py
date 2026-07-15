"""S4 enforcement AI-clue API. It never returns legal violation dispositions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.enforcement import ClueIngest, ClueReview, RuleCreate, RuleUpdate, ZoneCreate, ZoneUpdate
from app.services.enforcement_service import EnforcementError, EnforcementService


router = APIRouter(prefix="/enforcement", tags=["enforcement"])


def _service(request: Request) -> EnforcementService:
    service = getattr(request.app.state, "enforcement_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "enforcement_service_unavailable", "message": "EnforcementService unavailable"})
    return service


def _admin(request: Request) -> int | None:
    user = getattr(request.state, "user", None)
    if user is None:  # Isolated API tests may omit production auth middleware.
        return None
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    try:
        return int(user.get("sub"))
    except (TypeError, ValueError):
        return None


async def _call(awaitable):
    try:
        return await awaitable
    except EnforcementError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc


@router.get("/zones")
async def list_zones(request: Request):
    return await _call(_service(request).list_zones())


@router.post("/zones", status_code=status.HTTP_201_CREATED)
async def create_zone(body: ZoneCreate, request: Request):
    return await _call(_service(request).create_zone(body, _admin(request)))


@router.patch("/zones/{zone_id}")
async def update_zone(zone_id: str, body: ZoneUpdate, request: Request):
    return await _call(_service(request).update_zone(zone_id, body, _admin(request)))


@router.post("/zones/{zone_id}/publish")
async def publish_zone(zone_id: str, request: Request):
    _admin(request)
    return await _call(_service(request).publish_candidate("zone", zone_id))


@router.get("/rules")
async def list_rules(request: Request):
    return await _call(_service(request).list_rules())


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(body: RuleCreate, request: Request):
    return await _call(_service(request).create_rule(body, _admin(request)))


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdate, request: Request):
    return await _call(_service(request).update_rule(rule_id, body, _admin(request)))


@router.post("/rules/{rule_id}/publish")
async def publish_rule(rule_id: str, request: Request):
    _admin(request)
    return await _call(_service(request).publish_candidate("rule", rule_id))


@router.get("/clues")
async def list_clues(
    request: Request,
    review_status: str | None = Query(default=None),
    clue_type: str | None = Query(default=None),
):
    return await _call(_service(request).list_clues(review_status, clue_type))


@router.post("/clues", status_code=status.HTTP_201_CREATED)
async def ingest_clue(body: ClueIngest, request: Request):
    return await _call(_service(request).ingest_clue(body, _admin(request)))


@router.get("/clues/{event_id}")
async def get_clue(event_id: str, request: Request):
    return await _call(_service(request).get_clue(event_id))


@router.post("/clues/{event_id}/review")
async def review_clue(event_id: str, body: ClueReview, request: Request):
    return await _call(_service(request).review_clue(event_id, body, _admin(request)))


@router.get("/truck-summary")
async def truck_summary(request: Request):
    return await _call(_service(request).truck_summary())
