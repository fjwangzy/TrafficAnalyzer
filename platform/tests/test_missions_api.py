import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import drones
from app.models.drone_store import DRONES, MISSIONS


class _FakePipeline:
    def __init__(self):
        self.pipeline_id = "pipe-mission"

    def to_dict(self):
        return {
            "pipeline_id": self.pipeline_id,
            "drone_id": "drone_7",
            "intersection_id": "INT_camera_7",
            "video_src": "test_videos/inter_xqh/demo.mp4",
            "roads_json": "",
            "topic_name": "statistics_10",
            "camera_id": 10,
            "video_port": 8101,
            "status": "running",
            "started_at": 1.0,
            "stopped_at": 0.0,
            "error_message": "",
            "uptime_seconds": 0.0,
        }


class _FakePipelineManager:
    def __init__(self):
        self.started_with = None

    async def start_pipeline(self, **kwargs):
        self.started_with = kwargs
        return _FakePipeline()


class _FailingPipelineManager:
    async def start_pipeline(self, **kwargs):
        raise RuntimeError("detector dependency missing")


class MissionsApiTest(unittest.TestCase):
    def setUp(self):
        DRONES.clear()
        MISSIONS.clear()
        self.pipeline_manager = _FakePipelineManager()
        app = FastAPI()
        app.state.pipeline_manager = self.pipeline_manager
        app.include_router(drones.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self):
        DRONES.clear()
        MISSIONS.clear()

    def test_create_mission_starts_pipeline_and_records_binding(self):
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
        payload = response.json()
        self.assertEqual(payload["name"], "小清河早高峰巡检")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["pipeline_id"], "pipe-mission")
        self.assertEqual(payload["pipeline"]["status"], "running")
        self.assertIn(payload["id"], MISSIONS)
        self.assertEqual(MISSIONS[payload["id"]]["pipeline_id"], "pipe-mission")
        self.assertEqual(DRONES["drone_7"]["current_intersection_id"], "INT_camera_7")
        self.assertEqual(
            self.pipeline_manager.started_with,
            {
                "drone_id": "drone_7",
                "intersection_id": "INT_camera_7",
                "video_src": "test_videos/inter_xqh/demo.mp4",
                "roads_json": "",
                "telemetry_source": "srt",
                "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt",
            },
        )

    def test_create_mission_marks_error_when_pipeline_start_raises(self):
        self.client.app.state.pipeline_manager = _FailingPipelineManager()

        response = self.client.post(
            "/api/v1/missions",
            json={
                "name": "异常启动任务",
                "drone_id": "drone_8",
                "intersection_id": "INT_camera_8",
                "video_src": "test_videos/inter_xqh/demo.mp4",
            },
        )

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(payload["detail"], "detector dependency missing")
        self.assertEqual(len(MISSIONS), 1)
        mission = next(iter(MISSIONS.values()))
        self.assertEqual(mission["status"], "error")
        self.assertEqual(mission["error_message"], "detector dependency missing")
        self.assertIsNone(mission["pipeline_id"])


if __name__ == "__main__":
    unittest.main()
