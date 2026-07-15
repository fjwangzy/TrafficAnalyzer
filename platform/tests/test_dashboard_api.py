from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import dashboard


class FakeDashboardReadModel:
    def __init__(self):
        self.intersection_filters = None

    async def overview(self):
        return {"schema_version": "uav.dashboard/v1", "coverage_ratio": None}

    async def intersections(self, **filters):
        self.intersection_filters = filters
        return {"items": [], "isolated": 1, "filters": filters}

    async def intersection(self, inter_id):
        return {"id": inter_id} if inter_id == "INT-1" else None

    async def drones(self):
        return {"items": []}


def app_for(service=True):
    app = FastAPI()
    app.state.dashboard_read_model = FakeDashboardReadModel() if service else None
    app.include_router(dashboard.router, prefix="/api/v1")
    return app


def test_dashboard_read_routes_and_not_found_contract():
    app = app_for()
    with TestClient(app) as client:
        assert client.get("/api/v1/dashboard/overview").json()["coverage_ratio"] is None
        assert client.get("/api/v1/dashboard/intersections").json()["isolated"] == 1
        filtered = client.get(
            "/api/v1/dashboard/intersections",
            params={"risk": "critical", "monitor": "degraded", "quality": "stale", "bbox": "116.9,36.6,117.2,36.8", "q": "INT", "offset": 10, "limit": 20},
        )
        assert filtered.status_code == 200
        assert app.state.dashboard_read_model.intersection_filters == {
            "risk": "critical", "monitor": "degraded", "quality": "stale",
            "bbox": (116.9, 36.6, 117.2, 36.8), "query": "INT", "offset": 10, "limit": 20,
        }
        assert client.get("/api/v1/dashboard/intersections/INT-1").status_code == 200
        missing = client.get("/api/v1/dashboard/intersections/OTHER")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "intersection_not_found"
        assert client.get("/api/v1/dashboard/drones").status_code == 200


def test_dashboard_rejects_invalid_bbox_and_maps_timeout_to_503():
    app = app_for()
    with TestClient(app) as client:
        invalid = client.get("/api/v1/dashboard/intersections", params={"bbox": "117,36,116,37"})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "invalid_bbox"

        async def timeout():
            raise TimeoutError("road9 timeout")

        app.state.dashboard_read_model.overview = timeout
        unavailable = client.get("/api/v1/dashboard/overview")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "dashboard_dependency_unavailable"


def test_dashboard_returns_503_when_road9_read_model_is_unavailable():
    with TestClient(app_for(False)) as client:
        response = client.get("/api/v1/dashboard/overview")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "dashboard_unavailable"


def test_dashboard_maps_database_connection_refusal_to_structured_503():
    app = app_for()

    async def connection_refused():
        raise ConnectionRefusedError("road9 is stopped")

    app.state.dashboard_read_model.overview = connection_refused
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/dashboard/overview")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "dashboard_dependency_unavailable"
