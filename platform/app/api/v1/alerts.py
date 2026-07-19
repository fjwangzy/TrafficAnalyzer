"""Alert API endpoints."""

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    request: Request,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List alerts with optional filters."""
    engine = request.app.state.alert_engine
    return engine.get_alerts_list(severity=severity, status=status, limit=limit, offset=offset)


@router.get("/{alert_id}")
async def get_alert(alert_id: str, request: Request):
    """Get a single alert by ID."""
    engine = request.app.state.alert_engine
    alert = engine.get_alert(alert_id)
    if not alert:
        return {"error": "not_found", "id": alert_id}
    return alert


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: Request):
    """Acknowledge an alert."""
    engine = request.app.state.alert_engine
    user = "admin"
    if hasattr(request.state, "user") and request.state.user:
        identity = request.state.user
        user = identity.get("username", "admin") if isinstance(identity, dict) else getattr(identity, "username", "admin")
    alert = await engine.acknowledge_alert(alert_id, user)
    if not alert:
        return {"error": "not_found", "id": alert_id}
    return alert


@router.get("/{alert_id}/push-logs")
async def get_push_logs(alert_id: str, request: Request):
    """Get webhook push logs for an alert."""
    engine = request.app.state.alert_engine
    alert = engine.get_alert(alert_id)
    if not alert:
        return {"error": "not_found", "id": alert_id}
    return alert.get("push_logs", [])
