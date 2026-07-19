"""Accident-survey REST interface."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.survey import (
    MeasurementCreate,
    MeasurementUpdate,
    SceneAnnotationCreate,
    SceneAnnotationUpdate,
    SurveyAction,
    SurveyAssetImport,
    SurveyTaskCreate,
)
from app.services.survey_service import SurveyService

router = APIRouter(prefix="/survey-tasks", tags=["survey"])
evidence_router = APIRouter(prefix="/survey-evidence", tags=["survey-evidence"])


def _actor(request: Request) -> tuple[int | None, str, str]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authenticated survey identity required")
    try:
        actor_id = int(user.get("sub")) if user.get("sub") is not None else None
    except (TypeError, ValueError):
        actor_id = None
    return actor_id, user.get("role", "viewer"), user.get("username", "unknown")


def _request_id(request: Request, idempotency_key: str | None = None) -> str | None:
    value = idempotency_key or request.headers.get("X-Request-ID")
    if value and len(value) > 80:
        raise HTTPException(status_code=422, detail="request identifier exceeds 80 characters")
    return value


def _raise_domain_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("")
async def list_survey_tasks(
    request: Request,
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    return await SurveyService(db).list_tasks(actor_id, role, state)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_survey_task(
    payload: SurveyTaskCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, _, actor_name = _actor(request)
    return await SurveyService(db).create_task(payload.model_dump(), actor_id, actor_name, _request_id(request, idempotency_key))


@router.get("/{task_id}")
async def get_survey_task(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).get_task(task_id, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/actions")
async def transition_survey_task(
    task_id: str,
    payload: SurveyAction,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        values = payload.model_dump(exclude={"action", "expected_revision"}, exclude_none=True)
        return await SurveyService(db).transition(
            task_id,
            payload.action,
            payload.expected_revision,
            values,
            actor_id,
            role,
            _request_id(request, idempotency_key),
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/{task_id}/capture-batches")
async def list_capture_batches(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).list_batches(task_id, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/capture-batches/import", status_code=status.HTTP_202_ACCEPTED)
async def import_capture_batch(
    task_id: str,
    payload: SurveyAssetImport,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="administrator capability is required for server asset import")
    try:
        return await SurveyService(db).import_capture_batch(
            task_id,
            payload.video_asset,
            payload.telemetry_asset,
            payload.source_profile_id,
            actor_id,
            role,
            _request_id(request, idempotency_key),
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/{task_id}/annotations")
async def list_scene_annotations(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).list_annotations(task_id, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/annotations", status_code=status.HTTP_201_CREATED)
async def create_scene_annotation(
    task_id: str,
    payload: SceneAnnotationCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).create_annotation(
            task_id, payload.model_dump(), actor_id, role, _request_id(request, idempotency_key)
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.patch("/{task_id}/annotations/{annotation_id}")
async def update_scene_annotation(
    task_id: str,
    annotation_id: str,
    payload: SceneAnnotationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).update_annotation(
            task_id, annotation_id, payload.model_dump(), actor_id, role
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.delete("/{task_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene_annotation(
    task_id: str,
    annotation_id: str,
    request: Request,
    expected_revision: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        await SurveyService(db).delete_annotation(
            task_id, annotation_id, expected_revision, actor_id, role
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/capture-batches/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_capture_batch(
    task_id: str,
    request: Request,
    video: UploadFile = File(...),
    telemetry: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).upload_capture_batch(
            task_id,
            video.file,
            telemetry.file,
            actor_id,
            role,
            _request_id(request, idempotency_key),
            video.filename or "capture.mp4",
            telemetry.filename or "telemetry.srt",
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/{task_id}/frames")
async def list_survey_frames(
    task_id: str,
    request: Request,
    batch_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).list_frames(task_id, actor_id, role, batch_id)
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/{task_id}/measurements")
async def list_measurements(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).list_measurements(task_id, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/measurements", status_code=status.HTTP_201_CREATED)
async def create_measurement(
    task_id: str,
    payload: MeasurementCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).save_measurement(
            task_id,
            payload.model_dump(),
            actor_id,
            role,
            _request_id(request, idempotency_key),
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.patch("/{task_id}/measurements/{measurement_id}")
async def update_measurement(
    task_id: str,
    measurement_id: str,
    payload: MeasurementUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).save_measurement(
            task_id,
            payload.model_dump(),
            actor_id,
            role,
            _request_id(request),
            measurement_id,
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.delete("/{task_id}/measurements/{measurement_id}", status_code=204)
async def delete_measurement(
    task_id: str,
    measurement_id: str,
    request: Request,
    expected_revision: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        await SurveyService(db).delete_measurement(task_id, measurement_id, expected_revision, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/{task_id}/reports")
async def list_reports(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).list_reports(task_id, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/reports", status_code=status.HTTP_201_CREATED)
async def generate_report(
    task_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).generate_report(task_id, actor_id, role, _request_id(request, idempotency_key))
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/{task_id}/reports/{report_id}/deliver")
async def deliver_report(
    task_id: str,
    report_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    actor_id, role, _ = _actor(request)
    try:
        return await SurveyService(db).deliver_report(task_id, report_id, idempotency_key, actor_id, role)
    except Exception as exc:
        _raise_domain_error(exc)


@evidence_router.get("/{evidence_id}/content")
async def survey_evidence_content(evidence_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor_id, role, _ = _actor(request)
    try:
        item, path = await SurveyService(db).evidence_item(evidence_id, actor_id, role)
        return FileResponse(
            path,
            media_type=item.media_type,
            filename=None,
            headers={
                "ETag": f'"{item.sha256}"',
                "X-Content-SHA256": item.sha256,
                "X-Storage-Backend": item.storage_backend,
            },
        )
    except Exception as exc:
        _raise_domain_error(exc)
