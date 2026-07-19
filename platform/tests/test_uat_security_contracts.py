from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import video
from app.core.config import Settings
from app.main import app
from app.models.survey import AuditLog, SurveyTask
from app.services.audit_service import AuditService
from app.services.survey_service import SurveyService

REVIEW_CHECKLIST = {
    "task_and_location": True,
    "source_materials": True,
    "coordinate_chain": True,
    "measurements": True,
    "edit_history": True,
    "quality_status": True,
}


class _Session:
    def __init__(self, task):
        self.task = task
        self.added = []

    async def get(self, model, identifier):
        return self.task if model is SurveyTask and identifier == self.task.id else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _AuditSession:
    def __init__(self):
        self.added = []

    def begin(self):
        return _AsyncContext()

    def add(self, value):
        self.added.append(value)


class _AuditSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return _AsyncContext(self.session)


def _task():
    now = datetime.now(UTC)
    return SimpleNamespace(
        id="SVY-1", external_task_id=None, title="test", source="local",
        scene_location="site", inter_id="INT-1", road_data_version="v1",
        assignee_user_id=1, owner_name="owner", state="pending_review",
        quality_status="verified", delivery_status="not_delivered", precheck={},
        selected_batch_id="B-1", version=1, last_return_type=None,
        last_return_reason=None, created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_approve_review_requires_exact_six_true_items_and_audits_them():
    task = _task()
    session = _Session(task)
    service = SurveyService(session)
    with pytest.raises(ValueError, match="review checklist"):
        await service.transition("SVY-1", "approve_review", 1, {"checklist": {**REVIEW_CHECKLIST, "quality_status": False}}, 1, "admin", "bad")

    result = await service.transition("SVY-1", "approve_review", 1, {"checklist": REVIEW_CHECKLIST}, 1, "admin", "ok")
    assert result["status"] == "technical_reviewed"
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.after_value["review_checklist"] == REVIEW_CHECKLIST


def test_uat_settings_reject_insecure_defaults():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, deployment_mode="uat")


def test_uat_settings_reject_wildcard_cors_even_with_secure_secrets():
    with pytest.raises(ValidationError, match="CORS"):
        Settings(
            _env_file=None,
            deployment_mode="uat",
            db_password="not-default-db-password",
            jwt_secret_key="not-default-jwt-secret-with-entropy",
            bootstrap_admin_password="not-default-admin-password",
            media_cookie_secure=True,
            cors_origins=["*"],
        )


def test_uat_settings_accept_explicit_secure_values():
    value = Settings(
        _env_file=None,
        deployment_mode="uat",
        db_password="not-default-db-password",
        jwt_secret_key="not-default-jwt-secret-with-entropy",
        bootstrap_admin_password="not-default-admin-password",
        media_cookie_secure=True,
        cors_origins=["https://uat.example.test"],
    )
    assert value.deployment_mode == "uat"


@pytest.mark.asyncio
async def test_video_stream_concurrency_limit_is_enforced_before_ffmpeg_spawn():
    request = SimpleNamespace(
        state=SimpleNamespace(user={"sub": "1", "username": "operator", "role": "operator"}),
        app=SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(video_max_active_streams=1, hls_output_dir="/tmp/hls"),
        )),
        url=SimpleNamespace(path="/api/v1/video/streams/2/start"),
    )
    video._STREAMS.clear()
    video._STREAMS["1"] = {"status": "running"}
    try:
        with pytest.raises(HTTPException) as exc:
            await video.start_stream("2", request)
        assert exc.value.status_code == 409
    finally:
        video._STREAMS.clear()


@pytest.mark.asyncio
async def test_sensitive_operation_audit_is_written_as_uav_audit_log():
    session = _AuditSession()
    service = AuditService(_AuditSessionFactory(session))

    await service.record(
        actor={"sub": "9", "username": "operator", "role": "operator"},
        action="pipeline.start",
        target_type="pipeline",
        target_id="INT-1",
        after_value={"video_src": "rtsp://camera.uat.internal/live"},
    )

    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, AuditLog)
    assert row.__tablename__ == "uav_audit_logs"
    assert row.actor_id == 9
    assert row.action == "pipeline.start"


def test_hls_static_route_is_mounted_on_platform():
    assert any(getattr(route, "path", None) == "/hls" for route in app.routes)
