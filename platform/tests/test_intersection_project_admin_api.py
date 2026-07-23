from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import calibration
from app.core.database import get_db


class _NoDatabaseAccess:
    async def execute(self, _statement):
        raise AssertionError("authorization must run before database access")


def _client(role: str):
    app = FastAPI()

    @app.middleware("http")
    async def user(request, call_next):
        request.state.user = {"sub": "9", "username": role, "role": role}
        return await call_next(request)

    async def database():
        yield _NoDatabaseAccess()

    app.dependency_overrides[get_db] = database
    app.include_router(calibration.router, prefix="/api/v1")
    return TestClient(app)


def test_non_admin_cannot_read_projects_or_start_video_ingestion():
    client = _client("viewer")

    assert client.get("/api/v1/calibration/intersection-projects").status_code == 403
    assert client.post("/api/v1/calibration/video-ingestions", json={}).status_code == 403

