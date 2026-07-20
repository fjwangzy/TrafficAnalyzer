import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import drones
from app.services.mission_orchestrator import MissionError


class _FakeOrchestrator:
    def __init__(self):
        self.created = None
        self.stopped = None

    async def list_drones(self):
        return [{
            "id": "drone_7", "name": "M300", "model": "M300", "serial_number_masked": "***1234",
            "enabled": True, "default_inter_id": "INT_camera_7", "default_video_source_id": None,
            "default_telemetry_source_id": None, "revision": 1, "created_at": None, "updated_at": None,
        }]

    async def get_drone(self, drone_id):
        return (await self.list_drones())[0]

    async def create_manual_mission(self, body, actor_id=None):
        self.created = (body, actor_id)
        return {
            "id": "MSN-1", "name": body.name, "drone_id": body.drone_id,
            "inter_id": body.inter_id, "status": "running", "pipeline_id": "pipe-mission",
            "pipeline": {"id": "pipe-mission", "observed_status": "running"},
        }

    async def list_missions(self, status=None):
        return [{"id": "MSN-1", "status": status or "running"}]

    async def get_mission(self, mission_id):
        return {"id": mission_id, "status": "running"}

    async def stop_mission(self, mission_id, reason):
        self.stopped = (mission_id, reason)
        return {"id": mission_id, "status": "cancelled", "reason_code": "manual_stop"}


class _FailingOrchestrator(_FakeOrchestrator):
    async def create_manual_mission(self, body, actor_id=None):
        raise MissionError("detector dependency missing", 502, "pipeline_start_failed")


class MissionsApiTest(unittest.TestCase):
    def setUp(self):
        self.orchestrator = _FakeOrchestrator()
        app = FastAPI()
        app.state.mission_orchestrator = self.orchestrator
        app.include_router(drones.router, prefix="/api/v1")
        self.client = TestClient(app)

    def test_legacy_create_mission_is_normalized_by_persistent_interface(self):
        response = self.client.post(
            "/api/v1/missions",
            json={
                "name": "小清河早高峰巡检",
                "drone_id": "drone_7",
                "intersection_id": "INT_camera_7",
                "video_src": "test_videos/inter_xqh/demo.mp4",
                "roads_json": "",
                "telemetry_source": "srt",
                "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "running")
        body, actor_id = self.orchestrator.created
        self.assertEqual(body.inter_id, "INT_camera_7")
        self.assertEqual(body.video_src, "test_videos/inter_xqh/demo.mp4")
        self.assertIsNone(actor_id)

    def test_orchestrator_errors_preserve_status_and_code(self):
        self.client.app.state.mission_orchestrator = _FailingOrchestrator()
        response = self.client.post(
            "/api/v1/missions",
            json={
                "drone_id": "drone_8",
                "intersection_id": "INT_camera_8",
                "video_src": "test_videos/inter_xqh/demo.mp4",
            },
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["code"], "pipeline_start_failed")

    def test_legacy_mission_rejects_lane_annotation_parameters(self):
        response = self.client.post(
            "/api/v1/missions",
            json={
                "drone_id": "drone_8",
                "intersection_id": "INT_camera_8",
                "video_src": "test_videos/inter_xqh/demo.mp4",
                "roads_json": "configs/lanes.json",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_non_admin_cannot_stop_mission(self):
        app = FastAPI()
        app.state.mission_orchestrator = self.orchestrator

        @app.middleware("http")
        async def viewer(request, call_next):
            request.state.user = {"sub": "2", "username": "viewer", "role": "viewer"}
            return await call_next(request)
        app.include_router(drones.router, prefix="/api/v1")
        response = TestClient(app).post("/api/v1/missions/MSN-1/stop", json={"reason": "test"})
        self.assertEqual(response.status_code, 403)

    def test_stop_mission_keeps_mission_and_pipeline_status_separate(self):
        response = self.client.post("/api/v1/missions/MSN-1/stop", json={"reason": "source maintenance"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(self.orchestrator.stopped, ("MSN-1", "source maintenance"))
