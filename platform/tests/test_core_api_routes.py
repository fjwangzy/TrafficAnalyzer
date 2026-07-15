import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import alerts, drones, intersections, pipelines, system, trajectories


class _PipelineManager:
    def list_pipelines(self):
        return []

    def get_active_count(self):
        return 0


class _MissionOrchestrator:
    async def list_drones(self):
        return []


class _KafkaService:
    _running = True
    _group_id = "test"

    def __init__(self):
        self.latest_stats = {}
        self.latest_system = {}


class _WsManager:
    total_connections = 0
    channel_stats = {}


class _AlertEngine:
    alerts = {}

    def get_alerts_list(self, severity=None, status=None, limit=50, offset=0):
        return []


class _MetricStore:
    def __init__(self):
        self.conflict_query_args = None

    async def query_tracks(self, *args, **kwargs):
        return []

    async def query_conflicts(self, intersection_id, period="1h", limit=200):
        self.conflict_query_args = (intersection_id, period, limit)
        return [{
            "motor_id": 96,
            "non_motor_id": 88,
            "prediction_type": "path_intersection",
            "conflict_scene": "suspected_right_turn_mv_nmv",
            "ttc_sec": 1.2,
            "pet_sec": 0.3,
            "evidence": ["hard_ttc_or_pet"],
        }]

    async def query_traffic(self, *args, **kwargs):
        return []

    async def query_system_metrics(self, *args, **kwargs):
        return []


class CoreApiRoutesTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.state.pipeline_manager = _PipelineManager()
        app.state.mission_orchestrator = _MissionOrchestrator()
        app.state.kafka_service = _KafkaService()
        app.state.ws_manager = _WsManager()
        app.state.alert_engine = _AlertEngine()
        app.state.metric_store = _MetricStore()

        app.include_router(pipelines.router, prefix="/api/v1")
        app.include_router(intersections.router, prefix="/api/v1")
        app.include_router(drones.router, prefix="/api/v1")
        app.include_router(drones.telemetry_router, prefix="/api/v1")
        app.include_router(trajectories.router, prefix="/api/v1")
        app.include_router(alerts.router, prefix="/api/v1")
        app.include_router(system.router, prefix="/api/v1")
        self.client = TestClient(app)

    def test_tcc_core_api_endpoints_are_reachable(self):
        endpoints = [
            "/api/v1/pipelines",
            "/api/v1/pipelines/summary",
            "/api/v1/intersections",
            "/api/v1/intersections/summary",
            "/api/v1/drones",
            "/api/v1/trajectories/INT_camera_1",
            "/api/v1/trajectories/INT_camera_1/conflicts",
            "/api/v1/alerts",
            "/api/v1/system/health",
        ]

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200)

    def test_conflict_history_endpoint_returns_replay_evidence(self):
        response = self.client.get(
            "/api/v1/trajectories/INT_camera_1/conflicts",
            params={"period": "30m", "limit": 20},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["prediction_type"], "path_intersection")
        self.assertEqual(response.json()[0]["evidence"], ["hard_ttc_or_pet"])
        self.assertEqual(
            self.client.app.state.metric_store.conflict_query_args,
            ("INT_camera_1", "30m", 20),
        )


if __name__ == "__main__":
    unittest.main()
