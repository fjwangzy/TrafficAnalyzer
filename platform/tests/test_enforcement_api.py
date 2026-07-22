from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.v1 import enforcement
from app.services.enforcement_service import EnforcementError


class FakeEnforcementService:
    def __init__(self):
        self.review = None

    async def list_zones(self):
        return [{"id": "ZONE-1", "status": "candidate", "revision": 1}]

    async def create_zone(self, body, actor_id):
        return {"id": "ZONE-2", "status": "candidate", "revision": 1, "actor_id": actor_id}

    async def update_zone(self, zone_id, body, actor_id):
        if body.revision != 1:
            raise EnforcementError(409, "revision_conflict", "stale")
        return {"id": zone_id, "revision": 2}

    async def publish_candidate(self, target, target_id):
        raise EnforcementError(503, "authority_adapter_unavailable", "blocked")

    async def list_rules(self): return []
    async def create_rule(self, body, actor_id): return {"id": "RULE-1", "status": "candidate"}
    async def update_rule(self, rule_id, body, actor_id): return {"id": rule_id, "revision": 2}
    async def list_clues(self, review_status=None, clue_type=None): return []
    async def ingest_clue(self, body, actor_id): return {"id": "CLUE-1", "quality_status": body.quality_status}
    async def get_clue(self, event_id): return {"id": event_id}

    async def review_clue(self, event_id, body, actor_id):
        self.review = (event_id, body.review_status, body.expected_revision, actor_id)
        return {"id": event_id, "review_status": body.review_status, "review_revision": 2}

    async def truck_summary(self): return {"status": "stale", "vehicles": []}


def app_for(role="admin"):
    app = FastAPI()
    service = FakeEnforcementService()
    app.state.enforcement_service = service

    @app.middleware("http")
    async def user(request: Request, call_next):
        request.state.user = {"sub": "7", "role": role}
        return await call_next(request)

    app.include_router(enforcement.router, prefix="/api/v1")
    return app, service


ZONE = {
    "name": "本地候选限行区", "zone_type": "truck_restriction",
    "geometry": {"type": "Polygon", "coordinates": [[[117, 36.7], [117.001, 36.7], [117.001, 36.701], [117, 36.7]]]},
    "coordinate_system": "GCJ02", "road_data_version": "ROAD-TEST",
}


def test_candidate_zone_admin_revision_and_publish_boundary():
    app, _ = app_for()
    with TestClient(app) as client:
        assert client.post("/api/v1/enforcement/zones", json=ZONE).status_code == 201
        conflict = client.patch("/api/v1/enforcement/zones/ZONE-1", json={"revision": 9, "name": "new"})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "revision_conflict"
        blocked = client.post("/api/v1/enforcement/zones/ZONE-1/publish")
        assert blocked.status_code == 503
        assert blocked.json()["detail"]["code"] == "authority_adapter_unavailable"


def test_candidate_rule_update_cannot_declare_approval_or_violation():
    app, _ = app_for()
    with TestClient(app) as client:
        invalid = client.patch(
            "/api/v1/enforcement/rules/RULE-1",
            json={"revision": 1, "definition": {"violation": True}},
        )
        assert invalid.status_code == 422


def test_operator_can_read_but_cannot_write():
    app, _ = app_for("operator")
    with TestClient(app) as client:
        assert client.get("/api/v1/enforcement/zones").status_code == 200
        assert client.post("/api/v1/enforcement/zones", json=ZONE).status_code == 403


def test_radar_cannot_be_faked_and_review_is_technical_only():
    app, service = app_for()
    base = {
        "source_event_id": "s4-api-1", "idempotency_key": "s4-api-1",
        "occurred_at": datetime.now(UTC).isoformat(), "track_id": "7",
        "vehicle_class": "truck", "clue_type": "speed_observation",
        "radar_speed_kmh": 52.0, "radar_device_id": "RADAR-1",
        "radar_metadata": {"calibration_status": "unknown"},
    }
    with TestClient(app) as client:
        invalid = client.post("/api/v1/enforcement/clues", json=base)
        assert invalid.status_code == 422
        reviewed = client.post("/api/v1/enforcement/clues/CLUE-1/review", json={
            "review_status": "reviewed_confirmed", "expected_revision": 1, "reason": "技术事实确认",
        })
        assert reviewed.status_code == 200
        assert reviewed.json()["review_status"] == "reviewed_confirmed"
        assert service.review == ("CLUE-1", "reviewed_confirmed", 1, 7)
