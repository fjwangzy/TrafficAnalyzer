import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import alerts, drones, intersections, pipelines, system, trajectories


class _PipelineManager:
    def __init__(self):
        self.pipelines = []

    def list_pipelines(self):
        return self.pipelines

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
        self.traffic_query_args = None
        self.trajectory_analysis_args = None

    async def pipeline_runtime_quality(self, pipeline_ids):
        return {
            pipeline_id: {
                "capabilities": {
                    "trajectory": True,
                    "geo": True,
                    "road": False,
                    "tcc": True,
                },
                "capability_reasons": {
                    "trajectory": [],
                    "geo": [],
                    "road": ["lane_verified_map_required"],
                    "tcc": [],
                },
            }
            for pipeline_id in pipeline_ids
        }

    async def query_tracks(self, *args, **kwargs):
        return []

    async def query_conflicts(self, intersection_id, period="1h", limit=200, **filters):
        self.conflict_query_args = (intersection_id, period, limit, filters)
        return [{
            "motor_id": 96,
            "non_motor_id": 88,
            "prediction_type": "path_intersection",
            "conflict_scene": "suspected_right_turn_mv_nmv",
            "ttc_sec": 1.2,
            "pet_sec": 0.3,
            "evidence": ["hard_ttc_or_pet"],
        }]

    async def query_trajectory_analysis(self, intersection_id, **query):
        self.trajectory_analysis_args = (intersection_id, query)
        return {
            "query": {"intersection_id": intersection_id},
            "quality": {"total_tracks": 2, "returned_tracks": 1, "truncated": False},
            "timeline": [],
            "movement_ranking": [{"movement_key": "entry:3|exit:2", "vehicle_count": 2}],
            "class_summary": {"business": [], "yolo": [], "unknown_yolo_name_count": 0},
            "slice_tracks": [],
            "conflicts": [],
        }

    async def query_traffic(self, *args, **kwargs):
        self.traffic_query_args = (args, kwargs)
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

    def test_pipeline_endpoint_reports_persisted_runtime_capabilities(self):
        self.client.app.state.pipeline_manager.pipelines = [{
            "pipeline_id": "pipe-1",
            "drone_id": "drone-1",
            "intersection_id": "INT-1",
            "video_src": "/redacted/video.mp4",
            "map_version_id": None,
            "topic_name": "uav_statistics_1",
            "camera_id": 1,
            "video_port": 8101,
            "video_stream_url": "http://127.0.0.1:8101/video",
            "capabilities": {
                "trajectory": None,
                "geo": None,
                "road": None,
                "tcc": None,
            },
            "capability_reasons": {
                key: ["runtime_sample_pending"]
                for key in ("trajectory", "geo", "road", "tcc")
            },
            "status": "running",
            "started_at": 1.0,
            "stopped_at": 0.0,
            "error_message": "",
            "uptime_seconds": 1.0,
        }]

        response = self.client.get("/api/v1/pipelines")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]["capabilities"],
            {"trajectory": True, "geo": True, "road": False, "tcc": True},
        )
        self.assertEqual(
            response.json()[0]["capability_reasons"]["road"],
            ["lane_verified_map_required"],
        )

    def test_pipeline_openapi_declares_four_layer_capability_contract(self):
        schema = self.client.get("/openapi.json").json()
        response_schema = schema["components"]["schemas"]["PipelineResponse"]

        self.assertIn("capabilities", response_schema["properties"])
        self.assertIn("capability_reasons", response_schema["properties"])
        self.assertEqual(
            schema["paths"]["/api/v1/pipelines"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]["items"]["$ref"],
            "#/components/schemas/PipelineResponse",
        )

    def test_conflict_history_endpoint_returns_replay_evidence(self):
        response = self.client.get(
            "/api/v1/trajectories/INT_camera_1/conflicts",
            params={
                "period": "30m",
                "limit": 20,
                "source_profile_id": "SRC-1",
                "pipeline_id": "pipe-1",
                "prediction_type": "path_intersection",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["prediction_type"], "path_intersection")
        self.assertEqual(response.json()[0]["evidence"], ["hard_ttc_or_pet"])
        self.assertEqual(
            self.client.app.state.metric_store.conflict_query_args,
            (
                "INT_camera_1", "30m", 20,
                {
                    "source_profile_id": "SRC-1",
                    "pipeline_id": "pipe-1",
                    "prediction_type": "path_intersection",
                },
            ),
        )

    def test_stats_endpoint_forwards_requested_granularity(self):
        response = self.client.get(
            "/api/v1/intersections/INT_camera_1/stats",
            params={"period": "30m", "granularity": "5m", "source_profile_id": "SRC-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.app.state.metric_store.traffic_query_args,
            (("INT_camera_1", "30m"), {
                "grain_type": "intersection",
                "source_profile_id": "SRC-1",
                "granularity": "5m",
            }),
        )

    def test_trajectory_analysis_endpoint_forwards_time_slice_and_raw_class_filters(self):
        response = self.client.get(
            "/api/v1/trajectories/INT_camera_1/analysis",
            params={
                "start_at": "2026-07-21T08:00:00Z",
                "end_at": "2026-07-21T08:30:00Z",
                "slice_start_at": "2026-07-21T08:14:20Z",
                "slice_end_at": "2026-07-21T08:14:30Z",
                "bucket_sec": 10,
                "source_profile_id": "SRC-1",
                "vehicle_class": "motor",
                "yolo_class_id": 3,
                "movement_key": "entry:3|exit:2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["movement_ranking"][0]["vehicle_count"], 2)
        intersection_id, query = self.client.app.state.metric_store.trajectory_analysis_args
        self.assertEqual(intersection_id, "INT_camera_1")
        self.assertEqual(query["bucket_sec"], 10)
        self.assertEqual(query["source_profile_id"], "SRC-1")
        self.assertEqual(query["vehicle_class"], "motor")
        self.assertEqual(query["yolo_class_id"], 3)
        self.assertEqual(query["movement_key"], "entry:3|exit:2")

    def test_trajectory_analysis_can_discover_the_complete_data_window(self):
        response = self.client.get(
            "/api/v1/trajectories/INT_camera_1/analysis",
            params={"period": "all", "bucket_sec": 10},
        )

        self.assertEqual(response.status_code, 200)
        _, query = self.client.app.state.metric_store.trajectory_analysis_args
        self.assertEqual(query["period"], "all")
        self.assertIsNone(query["start_at"])
        self.assertIsNone(query["slice_start_at"])


if __name__ == "__main__":
    unittest.main()
