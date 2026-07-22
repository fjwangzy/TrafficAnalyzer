from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from utils_local.coordinates import enu_to_gcj02

from app.api.v1 import calibration
from app.core.database import get_db
from app.models.mission import RoadContextSnapshot
from app.models.survey import SurveyCaptureBatch, SurveyFrame, SurveyTask


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _Session:
    def __init__(self, *, inter_id="INT-1"):
        self.results = [
            SimpleNamespace(
                profile_id="SRC-1",
                drone_id="UAV-1",
                enabled=True,
                mode="local",
                validation_status="valid",
            ),
            SimpleNamespace(
                road_data_version="ROAD-1",
                payload={"intersection": {"name": "小清河北路 × 水屯路"}},
            ),
        ]
        self.drone = SimpleNamespace(
            id="UAV-1", default_inter_id=inter_id, enabled=True
        )

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    async def get(self, _model, _identifier):
        return self.drone


class _SurveyService:
    def __init__(self):
        self.calls = []

    async def create_task(self, data, actor_id, actor_name, request_id):
        self.calls.append(("create", data, actor_id, actor_name, request_id))
        return {"id": "SVY-CAL-1", "revision": 1}

    async def transition(
        self, task_id, action, revision, payload, actor_id, role, request_id
    ):
        self.calls.append(
            ("transition", task_id, action, revision, payload, actor_id, role, request_id)
        )
        return {"id": task_id, "revision": revision + 1}

    async def import_capture_batch(
        self, task_id, video, telemetry, source_profile_id, actor_id, role, request_id
    ):
        self.calls.append(
            (
                "import",
                task_id,
                video,
                telemetry,
                source_profile_id,
                actor_id,
                role,
                request_id,
            )
        )
        return {"id": "BATCH-CAL-1", "status": "queued", "source_profile_id": source_profile_id}

    async def get_task(self, task_id, _actor_id, _role):
        return {"id": task_id, "status": "collecting", "revision": 4, "inter_id": "INT-1"}


def _client(monkeypatch, session, service):
    app = FastAPI()

    @app.middleware("http")
    async def admin(request, call_next):
        request.state.user = {"sub": "7", "username": "admin", "role": "admin"}
        return await call_next(request)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(calibration, "SurveyService", lambda _db: service)
    app.include_router(calibration.router, prefix="/api/v1")
    return TestClient(app)


def _payload():
    return {
        "inter_id": "INT-1",
        "source_profile_id": "SRC-1",
        "checklist": {
            "task_context": True,
            "operator_authorized": True,
            "site_command_confirmed": True,
            "device_ready": True,
            "storage_ready": True,
        },
    }


def test_lane_keyframe_extraction_reuses_survey_precheck_and_capture_queue(monkeypatch):
    service = _SurveyService()
    response = _client(monkeypatch, _Session(), service).post(
        "/api/v1/calibration/lane-keyframe-extractions",
        json=_payload(),
        headers={"Idempotency-Key": "lane-extract-test"},
    )

    assert response.status_code == 201
    assert response.json()["task"]["status"] == "collecting"
    assert response.json()["batch"]["status"] == "queued"
    assert [call[0] for call in service.calls] == [
        "create",
        "transition",
        "transition",
        "import",
    ]
    created = service.calls[0]
    assert created[1]["source"] == "lane_calibration"
    assert created[1]["road_data_version"] == "ROAD-1"
    assert created[-1] == "lane-extract-test"
    assert service.calls[1][2:4] == ("start_precheck", 1)
    assert service.calls[2][2:4] == ("complete_precheck", 2)


def test_lane_keyframe_extraction_rejects_source_from_another_intersection(monkeypatch):
    service = _SurveyService()
    response = _client(monkeypatch, _Session(inter_id="INT-OTHER"), service).post(
        "/api/v1/calibration/lane-keyframe-extractions", json=_payload()
    )

    assert response.status_code == 422
    assert "not registered" in response.json()["detail"]
    assert service.calls == []


def test_lane_task_homography_is_aligned_to_the_loaded_channelized_map(monkeypatch, tmp_path):
    anchor = [117.028285, 36.703222]
    longitude, latitude = enu_to_gcj02(12, -8, anchor)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"jpeg")
    frame = SimpleNamespace(
        id="FRM-1", task_id="SVY-1", batch_id="BATCH-1", image_evidence_id="EVI-1",
        image_width=3840, image_height=2160,
        homography=[[0.05, 0, -96], [0, -0.05, 54], [0, 0, 1]],
        view_transform=[[2, 0, 10], [0, 2, 20], [0, 0, 1]],
        telemetry={"position_gcj02": {"longitude": longitude, "latitude": latitude}},
    )
    task = SimpleNamespace(id="SVY-1", inter_id="INT-1")
    batch = SimpleNamespace(id="BATCH-1", source_profile_id="SRC-1")
    context = SimpleNamespace(payload={"intersection": {"name": "测试路口"}})
    map_version = SimpleNamespace(id="CMV-1", anchor_gcj02=anchor)

    class Session:
        async def get(self, model, identifier):
            return {
                (SurveyFrame, "FRM-1"): frame,
                (SurveyTask, "SVY-1"): task,
                (SurveyCaptureBatch, "BATCH-1"): batch,
            }.get((model, identifier))

        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            return _Result(context if entity is RoadContextSnapshot else map_version)

    class EvidenceService:
        async def evidence_item(self, *_args):
            return {}, image_path

    class LaneStore:
        def __init__(self):
            self.kwargs = None

        def ensure_task_from_snapshot(self, *args, **kwargs):
            self.kwargs = kwargs
            return {"task_id": "lane-1", **kwargs}

    session = Session()
    lane_store = LaneStore()
    app = FastAPI()

    @app.middleware("http")
    async def admin(request, call_next):
        request.state.user = {"sub": "7", "username": "admin", "role": "admin"}
        return await call_next(request)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(calibration, "SurveyService", lambda _db: EvidenceService())
    monkeypatch.setattr(calibration, "_lane_store", lambda _request: lane_store)
    app.include_router(calibration.router, prefix="/api/v1")

    response = TestClient(app).post(
        "/api/v1/calibration/lane-tasks/from-survey-frame", json={"frame_id": "FRM-1"}
    )

    assert response.status_code == 201
    assert np.allclose(
        lane_store.kwargs["homography_pixel_to_enu"],
        [[0.05, 0, -84], [0, -0.05, 46], [0, 0, 1]],
        atol=1e-6,
    )
    assert lane_store.kwargs["map_version_id"] == "CMV-1"
    assert lane_store.kwargs["map_anchor_gcj02"] == anchor
    assert lane_store.kwargs["homography_coordinate_frame"] == "map_enu"
