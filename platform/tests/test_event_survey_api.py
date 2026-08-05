from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import events
from app.core.database import get_db


class _EventCenter:
    async def get_event(self, event_id):
        return {
            "id": event_id,
            "source_kind": "conflict",
            "event_type": "conflict",
            "title": "真实机非冲突",
            "inter_id": "INT-1",
            "source_profile_id": "SRC-1",
            "evidence_refs": [
                {"id": "EVI-ORIGINAL", "kind": "conflict_original_frame"}
            ],
        }


class _SurveyService:
    def __init__(self):
        self.calls = []

    async def create_from_event(
        self, event, actor_id, actor_name, role, request_id
    ):
        self.calls.append((event, actor_id, actor_name, role, request_id))
        return {
            "task": {"id": "SVY-EVENT-1", "status": "measuring"},
            "frame": {"id": "FRM-EVENT-1", "task_id": "SVY-EVENT-1"},
        }


def test_event_survey_endpoint_carries_the_current_event_and_idempotency(monkeypatch):
    app = FastAPI()
    service = _SurveyService()

    @app.middleware("http")
    async def admin(request, call_next):
        request.state.user = {"sub": "7", "username": "admin", "role": "admin"}
        return await call_next(request)

    async def override_db():
        yield object()

    app.state.event_center = _EventCenter()
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(events, "SurveyService", lambda _db: service, raising=False)
    app.include_router(events.router, prefix="/api/v1")

    response = TestClient(app).post(
        "/api/v1/events/EVT-1/survey",
        headers={"Idempotency-Key": "event-survey-EVT-1"},
    )

    assert response.status_code == 201
    assert response.json()["task"]["id"] == "SVY-EVENT-1"
    assert service.calls == [
        (
            {
                "id": "EVT-1",
                "source_kind": "conflict",
                "event_type": "conflict",
                "title": "真实机非冲突",
                "inter_id": "INT-1",
                "source_profile_id": "SRC-1",
                "evidence_refs": [
                    {"id": "EVI-ORIGINAL", "kind": "conflict_original_frame"}
                ],
            },
            7,
            "admin",
            "admin",
            "event-survey-EVT-1",
        )
    ]
