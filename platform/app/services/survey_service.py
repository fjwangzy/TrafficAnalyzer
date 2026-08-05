"""Deep accident-survey module: state, evidence, geometry, reports, and audit."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mission import TelemetrySourceRecord, VideoSourceRecord
from app.models.survey import (
    AiEvent,
    AuditLog,
    CaptureIngestionJob,
    EventOutbox,
    EvidenceItem,
    EvidencePackage,
    RuleVersion,
    SceneAnnotation,
    SurveyCaptureBatch,
    SurveyFrame,
    SurveyMeasurement,
    SurveyReport,
    SurveyTask,
)
from app.services.survey_capture import process_event_keyframe, process_mp4_telemetry
from app.services.survey_geometry import calculate_measurement
from app.services.survey_storage import (
    ContentAddressedStore,
    StoredObject,
    resolve_allowlisted_asset,
)

TERMINAL_STATES = {"completed", "cancelled", "error"}


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _task_dict(task: SurveyTask) -> dict:
    return {
        "id": task.id,
        "external_task_id": task.external_task_id,
        "title": task.title,
        "source": task.source,
        "location": task.scene_location,
        "inter_id": task.inter_id,
        "road_data_version": task.road_data_version,
        "assignee_user_id": task.assignee_user_id,
        "owner": task.owner_name,
        "status": task.state,
        "quality": task.quality_status,
        "delivery": task.delivery_status,
        "precheck": task.precheck,
        "selected_batch_id": task.selected_batch_id,
        "version": f"v{task.version}",
        "revision": task.version,
        "last_return_type": task.last_return_type,
        "last_return_reason": task.last_return_reason,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _batch_dict(batch: SurveyCaptureBatch) -> dict:
    return {
        "id": batch.id,
        "task_id": batch.task_id,
        "status": batch.status,
        "source_type": batch.source_type,
        "source_profile_id": batch.source_profile_id,
        "duration_sec": batch.duration_sec,
        "fps": batch.fps,
        "frame_count": batch.frame_count,
        "telemetry_coverage": batch.telemetry_coverage,
        "quality_checks": batch.quality_checks,
        "calibration": batch.calibration,
        "error_message": batch.error_message,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _frame_dict(frame: SurveyFrame) -> dict:
    metric_transform = None
    if frame.homography is not None:
        try:
            homography = np.asarray(frame.homography, dtype=np.float64)
            view_transform = np.asarray(frame.view_transform, dtype=np.float64)
            transform = homography @ np.linalg.inv(view_transform)
            if transform.shape == (3, 3) and np.all(np.isfinite(transform)):
                metric_transform = transform.tolist()
        except (TypeError, ValueError, np.linalg.LinAlgError):
            metric_transform = None
    return {
        "id": frame.id,
        "task_id": frame.task_id,
        "batch_id": frame.batch_id,
        "frame_number": frame.frame_number,
        "timestamp_sec": frame.timestamp_sec,
        "image_width": frame.image_width,
        "image_height": frame.image_height,
        "has_metric_transform": frame.homography is not None,
        "metric_transform": metric_transform,
        "telemetry": frame.telemetry,
        "quality": frame.quality,
        "selected": frame.selected,
        "image_url": f"/api/v1/survey-evidence/{frame.image_evidence_id}/content",
        "bev_url": f"/api/v1/survey-evidence/{frame.bev_evidence_id}/content",
    }


def _annotation_dict(annotation: SceneAnnotation) -> dict:
    return {
        "id": annotation.id,
        "task_id": annotation.task_id,
        "frame_id": annotation.frame_id,
        "category": annotation.category,
        "image_geometry": annotation.image_geometry,
        "source": annotation.source,
        "confidence": annotation.confidence,
        "review_state": annotation.review_state,
        "revision": annotation.version,
        "created_at": annotation.created_at.isoformat() if annotation.created_at else None,
    }


def _measurement_dict(measurement: SurveyMeasurement) -> dict:
    values = measurement.computed_values or {}
    if "length_m" in values:
        display_value = f"{values['length_m']:.2f}m"
    elif "area_m2" in values:
        display_value = f"{values['area_m2']:.2f}m² · 周长 {values.get('perimeter_m', 0):.2f}m"
    elif "easting_m" in values:
        display_value = f"E {values['easting_m']:.2f}m / N {values['northing_m']:.2f}m"
    else:
        display_value = "不可量算"
    return {
        "id": measurement.measurement_id,
        "row_id": measurement.row_id,
        "task_id": measurement.task_id,
        "frame_id": measurement.frame_id,
        "revision": measurement.revision,
        "geometry_type": measurement.geometry_type,
        "category": measurement.category,
        "image_geometry": measurement.image_geometry,
        "metric_geometry": measurement.metric_geometry,
        "values": values,
        "display_value": display_value,
        "error_estimate": measurement.error_estimate,
        "quality_status": measurement.quality_status,
        "source": measurement.source,
        "created_at": measurement.created_at.isoformat() if measurement.created_at else None,
    }


class SurveyService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.storage = ContentAddressedStore(settings.survey_storage_dir)

    def _resolve_evidence_path(self, item: EvidenceItem) -> Path:
        if item.storage_backend == "server_asset":
            platform_dir = Path(__file__).resolve().parents[2]
            return resolve_allowlisted_asset(item.storage_key, settings.survey_asset_roots, platform_dir)
        return self.storage.resolve(item.storage_key)

    def _verify_evidence(self, item: EvidenceItem) -> bool:
        try:
            path = self._resolve_evidence_path(item)
            digest, size = ContentAddressedStore._hash_file(path)
        except (FileNotFoundError, ValueError, OSError):
            return False
        return digest == item.sha256 and size == item.size_bytes

    def _evidence_reference_status(self, item: EvidenceItem) -> str:
        try:
            path = self._resolve_evidence_path(item)
            stat = path.stat()
        except FileNotFoundError:
            return "missing"
        except (ValueError, OSError):
            return "unavailable"
        if stat.st_size != item.size_bytes:
            return "hash_mismatch"
        metadata = item.item_metadata or {}
        fingerprint = metadata.get("source_fingerprint") or {}
        current_fingerprint = {
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        }
        if item.storage_backend == "server_asset" and fingerprint == current_fingerprint:
            return "verified"
        try:
            digest, size = ContentAddressedStore._hash_file(path)
        except OSError:
            return "unavailable"
        if digest != item.sha256 or size != item.size_bytes:
            return "hash_mismatch"
        if item.storage_backend == "server_asset":
            item.item_metadata = {**metadata, "source_fingerprint": current_fingerprint}
        return "verified"

    async def _batch_details(self, batch: SurveyCaptureBatch) -> dict:
        result = _batch_dict(batch)
        video = await self.session.get(EvidenceItem, batch.video_evidence_id)
        telemetry = await self.session.get(EvidenceItem, batch.telemetry_evidence_id)
        telemetry_metadata = telemetry.item_metadata if telemetry else {}
        result.update(
            {
                "telemetry_type": telemetry_metadata.get("telemetry_type", "srt"),
                "sync_config": telemetry_metadata.get("config") or {},
                "original_materials": {
                    "video": {
                        "evidence_id": video.id,
                        "storage_backend": video.storage_backend,
                        "asset_key": (video.item_metadata or {}).get("asset_key"),
                        "sha256": video.sha256,
                        "size_bytes": video.size_bytes,
                        "reference_status": self._evidence_reference_status(video),
                    }
                    if video
                    else {"reference_status": "missing"},
                    "telemetry": {
                        "evidence_id": telemetry.id,
                        "storage_backend": telemetry.storage_backend,
                        "asset_key": telemetry_metadata.get("asset_key"),
                        "sha256": telemetry.sha256,
                        "size_bytes": telemetry.size_bytes,
                        "reference_status": self._evidence_reference_status(telemetry),
                    }
                    if telemetry
                    else {"reference_status": "missing"},
                },
            }
        )
        return result

    async def _audit(
        self,
        actor_id: int | None,
        action: str,
        target_type: str,
        target_id: str,
        before: dict | None = None,
        after: dict | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_value=before,
                after_value=after,
                reason=reason,
                request_id=request_id,
            )
        )

    async def _prior(self, action: str, request_id: str | None) -> dict | None:
        if not request_id:
            return None
        row = (
            await self.session.execute(
                select(AuditLog).where(AuditLog.action == action, AuditLog.request_id == request_id)
            )
        ).scalar_one_or_none()
        return row.after_value if row else None

    async def _task(self, task_id: str, actor_id: int | None, role: str) -> SurveyTask:
        task = await self.session.get(SurveyTask, task_id)
        if task is None:
            raise LookupError("survey task not found")
        if role != "admin" and task.assignee_user_id not in (None, actor_id):
            raise PermissionError("survey task is outside the current assignment")
        return task

    async def list_tasks(self, actor_id: int | None, role: str, state: str | None = None) -> list[dict]:
        query = select(SurveyTask).order_by(SurveyTask.updated_at.desc())
        if role != "admin":
            query = query.where(SurveyTask.assignee_user_id.in_([actor_id, None]))
        if state:
            query = query.where(SurveyTask.state == state)
        rows = (await self.session.execute(query)).scalars().all()
        return [_task_dict(row) for row in rows]

    async def create_task(self, data: dict, actor_id: int | None, actor_name: str, request_id: str | None) -> dict:
        if prior := await self._prior("survey.task.created", request_id):
            return prior
        today = datetime.now(UTC).strftime("%Y%m%d")
        suffix = uuid.uuid4().hex[:6].upper()
        task = SurveyTask(
            id=f"SVY-{today}-{suffix}",
            external_task_id=data.get("external_task_id"),
            title=data["title"],
            source=data.get("source", "local"),
            scene_location=data["scene_location"],
            inter_id=data.get("inter_id"),
            road_data_version=data.get("road_data_version"),
            assignee_user_id=data.get("assignee_user_id") or actor_id,
            owner_name=data.get("owner_name") or actor_name,
            created_by=actor_id,
        )
        self.session.add(task)
        await self.session.flush()
        await self._audit(actor_id, "survey.task.created", "survey_task", task.id, after=_task_dict(task), request_id=request_id)
        return _task_dict(task)

    async def create_from_event(
        self,
        event: dict,
        actor_id: int | None,
        actor_name: str,
        role: str,
        request_id: str | None,
    ) -> dict:
        if prior := await self._prior("survey.task.created_from_event", request_id):
            return prior
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            raise ValueError("event id is required")
        existing = (
            await self.session.execute(
                select(SurveyTask).where(
                    SurveyTask.external_task_id == event_id,
                    SurveyTask.source == "event",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if role != "admin" and existing.assignee_user_id not in (None, actor_id):
                raise PermissionError("event survey is outside the current assignment")
            batch = await self.session.get(SurveyCaptureBatch, existing.selected_batch_id)
            frame = (
                await self.session.execute(
                    select(SurveyFrame)
                    .where(SurveyFrame.task_id == existing.id)
                    .order_by(SurveyFrame.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if batch is None or frame is None:
                raise RuntimeError("existing event survey is incomplete")
            return {"task": _task_dict(existing), "batch": _batch_dict(batch), "frame": _frame_dict(frame)}

        references = event.get("evidence_refs") or []
        priority = ("conflict_original_frame", "conflict_keyframe")
        reference = next(
            (item for kind in priority for item in references if item.get("kind") == kind),
            None,
        )
        if reference is None or not reference.get("id"):
            raise ValueError("event has no reusable original keyframe evidence")
        original = await self.session.get(EvidenceItem, reference["id"])
        if original is None or not str(original.media_type).startswith("image/"):
            raise LookupError("event keyframe evidence not found")
        evidence_status = self._evidence_reference_status(original)
        if evidence_status != "verified":
            raise ValueError(f"event keyframe evidence is {evidence_status}")
        metadata = original.item_metadata or {}
        timestamp_sec = metadata.get("frame_timestamp_sec")
        if timestamp_sec is None:
            raise ValueError("event keyframe timestamp is missing")
        source_profile_id = event.get("source_profile_id")
        if not source_profile_id:
            raise ValueError("event source profile is missing")
        telemetry_source = (
            await self.session.execute(
                select(TelemetrySourceRecord).where(
                    TelemetrySourceRecord.profile_id == source_profile_id
                )
            )
        ).scalar_one_or_none()
        if telemetry_source is None or telemetry_source.mode != "local" or not telemetry_source.enabled:
            raise ValueError("event telemetry source is unavailable")
        telemetry_config = telemetry_source.config or {}
        telemetry_type = telemetry_source.source_type
        if telemetry_type == "file":
            telemetry_type = telemetry_config.get("format") or "dji_cloud_json"
        evidence_frame_number = metadata.get("frame_number")
        if evidence_frame_number is None:
            source_manifest = telemetry_config.get("source_manifest") or {}
            video_fps = float(source_manifest.get("video_fps") or 0)
            evidence_frame_number = round(float(timestamp_sec) * video_fps) if video_fps > 0 else 0
        platform_dir = Path(__file__).resolve().parents[2]
        telemetry_asset = telemetry_source.location.removeprefix("test_videos/")
        telemetry_path = resolve_allowlisted_asset(
            telemetry_asset,
            [*settings.survey_asset_roots, settings.survey_storage_dir],
            platform_dir,
        )
        source_image = await asyncio.to_thread(self._resolve_evidence_path(original).read_bytes)
        processed = await asyncio.to_thread(
            process_event_keyframe,
            source_image,
            telemetry_path,
            float(timestamp_sec),
            telemetry_type=telemetry_type,
            time_offset_sec=float(telemetry_config.get("time_offset_sec") or 0),
            sync_tolerance_sec=float(telemetry_config.get("sync_tolerance_sec") or 0.5),
            frame_number=int(evidence_frame_number),
        )

        task = SurveyTask(
            id=f"SVY-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            external_task_id=event_id,
            title=f"{event.get('title') or event.get('event_type') or 'AI 事件'}事件测绘",
            source="event",
            scene_location=event.get("inter_id") or "事件现场",
            inter_id=event.get("inter_id"),
            road_data_version=event.get("road_data_version"),
            assignee_user_id=actor_id,
            owner_name=actor_name,
            state="measuring",
            quality_status="unverified",
            delivery_status="not_generated",
            precheck={
                "mode": "event_evidence_reuse",
                "source_event_id": event_id,
                "checked_at": _now_iso(),
                "checked_by": actor_id,
            },
            version=1,
            created_by=actor_id,
        )
        self.session.add(task)
        await self.session.flush()
        package = EvidencePackage(
            id=_identifier("EVP"),
            task_id=task.id,
            owner_type="survey_task",
            owner_id=task.id,
            source_event_id=event_id,
            version=1,
            integrity_status="unverified",
        )
        self.session.add(package)
        await self.session.flush()
        linked_original = EvidenceItem(
            id=_identifier("EVI"),
            package_id=package.id,
            task_id=task.id,
            kind="event_original_frame",
            storage_backend=original.storage_backend,
            storage_key=original.storage_key,
            sha256=original.sha256,
            media_type=original.media_type,
            size_bytes=original.size_bytes,
            item_metadata={
                **metadata,
                "source_event_id": event_id,
                "source_evidence_id": original.id,
                "mission_id": event.get("mission_id"),
                "pipeline_id": event.get("pipeline_id"),
                "source_profile_id": source_profile_id,
            },
            derived_from_id=original.id,
        )
        self.session.add(linked_original)
        await self.session.flush()
        bev_stored = await asyncio.to_thread(self.storage.ingest_bytes, processed.bev)
        bev_item = await self._evidence(
            package,
            task.id,
            "event_bev_frame",
            bev_stored,
            "image/jpeg",
            {
                "source_event_id": event_id,
                "source_evidence_id": original.id,
                "frame_timestamp_sec": processed.timestamp_sec,
                "width": processed.image_width,
                "height": processed.image_height,
            },
            derived_from_id=original.id,
        )
        batch = SurveyCaptureBatch(
            id=_identifier("BATCH"),
            task_id=task.id,
            status="selected",
            source_type="event_keyframe",
            source_profile_id=source_profile_id,
            video_evidence_id=linked_original.id,
            telemetry_evidence_id=None,
            duration_sec=0,
            frame_count=1,
            telemetry_coverage=1.0,
            quality_checks={
                "status": "unverified",
                "keyframes_extracted": 1,
                "homography_available": 1,
                "source": "event_keyframe",
            },
            calibration={"status": "unverified", "method": "event_frame_telemetry"},
        )
        self.session.add(batch)
        await self.session.flush()
        frame = SurveyFrame(
            id=_identifier("FRM"),
            task_id=task.id,
            batch_id=batch.id,
            frame_number=processed.frame_number,
            timestamp_sec=processed.timestamp_sec,
            image_evidence_id=linked_original.id,
            bev_evidence_id=bev_item.id,
            image_width=processed.image_width,
            image_height=processed.image_height,
            homography=processed.homography,
            view_transform=processed.view_transform,
            telemetry=processed.telemetry,
            quality=processed.quality,
            selected=True,
        )
        self.session.add(frame)
        task.selected_batch_id = batch.id
        await self.session.flush()
        result = {"task": _task_dict(task), "batch": _batch_dict(batch), "frame": _frame_dict(frame)}
        await self._audit(
            actor_id,
            "survey.task.created_from_event",
            "survey_task",
            task.id,
            after=result,
            request_id=request_id,
        )
        return result

    async def get_task(self, task_id: str, actor_id: int | None, role: str) -> dict:
        return _task_dict(await self._task(task_id, actor_id, role))

    async def transition(
        self,
        task_id: str,
        action: str,
        expected_revision: int,
        payload: dict,
        actor_id: int | None,
        role: str,
        request_id: str | None,
    ) -> dict:
        audit_action = f"survey.task.{action}"
        if prior := await self._prior(audit_action, request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.version != expected_revision:
            raise RuntimeError("survey task revision conflict")
        before = _task_dict(task)
        if task.state in TERMINAL_STATES and action != "cancel":
            raise ValueError("terminal survey task cannot transition")

        if action == "start_precheck" and task.state in {"created", "precheck_failed"}:
            task.state = "prechecking"
        elif action == "complete_precheck" and task.state == "prechecking":
            checklist = payload.get("checklist") or {}
            required = ["task_context", "operator_authorized", "site_command_confirmed", "device_ready", "storage_ready"]
            task.precheck = {**checklist, "checked_at": _now_iso(), "checked_by": actor_id}
            task.state = "ready" if all(checklist.get(key) is True for key in required) else "precheck_failed"
        elif action == "select_batch" and task.state in {"ready", "collecting", "returned", "measuring"}:
            batch_id = payload.get("batch_id")
            batch = await self.session.get(SurveyCaptureBatch, batch_id)
            if batch is None or batch.task_id != task.id or batch.status not in {"ready", "degraded", "selected"}:
                raise ValueError("capture batch is not selectable")
            await self.session.execute(
                update(SurveyCaptureBatch)
                .where(
                    SurveyCaptureBatch.task_id == task.id,
                    SurveyCaptureBatch.status == "selected",
                )
                .values(status="ready")
            )
            batch.status = "selected"
            task.selected_batch_id = batch.id
            task.state = "measuring"
        elif action == "submit_review" and task.state == "measuring":
            count = await self.session.scalar(
                select(func.count()).select_from(SurveyMeasurement).where(
                    SurveyMeasurement.task_id == task.id,
                    SurveyMeasurement.is_current.is_(True),
                    SurveyMeasurement.metric_geometry.is_not(None),
                )
            )
            if not count:
                raise ValueError("at least one metric measurement is required")
            task.state = "pending_review"
        elif action == "return" and task.state == "pending_review":
            return_type, reason = payload.get("return_type"), (payload.get("reason") or "").strip()
            if return_type not in {"capture", "measurement"} or not reason:
                raise ValueError("return_type and reason are required")
            task.state = "returned"
            task.last_return_type, task.last_return_reason = return_type, reason
        elif action == "approve_review" and task.state == "pending_review":
            checklist = payload.get("checklist") or {}
            required_review = {
                "task_and_location",
                "source_materials",
                "coordinate_chain",
                "measurements",
                "edit_history",
                "quality_status",
            }
            if set(checklist) != required_review or not all(
                checklist.get(key) is True for key in required_review
            ):
                raise ValueError("review checklist must contain exactly six true items")
            task.state = "technical_reviewed"
        elif action == "cancel" and task.state not in TERMINAL_STATES:
            reason = (payload.get("reason") or "").strip()
            if not reason:
                raise ValueError("cancellation reason is required")
            task.state = "cancelled"
            task.last_return_reason = reason
        else:
            raise ValueError(f"action {action} is invalid from state {task.state}")
        task.version += 1
        await self.session.flush()
        after = _task_dict(task)
        audit_after = (
            {**after, "review_checklist": dict(payload["checklist"])}
            if action == "approve_review"
            else after
        )
        await self._audit(actor_id, audit_action, "survey_task", task.id, before, audit_after, payload.get("reason"), request_id)
        return after

    async def _package(self, task_id: str) -> EvidencePackage:
        package = (
            await self.session.execute(
                select(EvidencePackage).where(EvidencePackage.task_id == task_id, EvidencePackage.version == 1)
            )
        ).scalar_one_or_none()
        if package is None:
            package = EvidencePackage(id=_identifier("EVP"), task_id=task_id, version=1)
            self.session.add(package)
            await self.session.flush()
        return package

    async def _evidence(
        self,
        package: EvidencePackage,
        task_id: str,
        kind: str,
        stored,
        media_type: str,
        metadata: dict | None = None,
        derived_from_id: str | None = None,
    ) -> EvidenceItem:
        item_metadata = dict(metadata or {})
        if stored.storage_backend == "server_asset" and stored.source_fingerprint:
            item_metadata["source_fingerprint"] = stored.source_fingerprint
        item = EvidenceItem(
            id=_identifier("EVI"),
            package_id=package.id,
            task_id=task_id,
            kind=kind,
            storage_backend=stored.storage_backend,
            storage_key=stored.storage_key,
            sha256=stored.sha256,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            item_metadata=item_metadata,
            derived_from_id=derived_from_id,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def import_capture_batch(
        self,
        task_id: str,
        video_asset: str | None,
        telemetry_asset: str | None,
        source_profile_id: str | None,
        actor_id: int | None,
        role: str,
        request_id: str | None,
    ) -> dict:
        if prior := await self._prior("survey.capture.enqueued", request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"ready", "collecting", "returned"}:
            raise ValueError("task must pass precheck before capture ingestion")
        platform_dir = Path(__file__).resolve().parents[2]
        telemetry_type = "srt"
        telemetry_config: dict = {}
        validation_status = "unknown"
        if source_profile_id:
            video_source = (
                await self.session.execute(
                    select(VideoSourceRecord).where(VideoSourceRecord.profile_id == source_profile_id)
                )
            ).scalar_one_or_none()
            telemetry_source = (
                await self.session.execute(
                    select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == source_profile_id)
                )
            ).scalar_one_or_none()
            if video_source is None or telemetry_source is None:
                raise LookupError("source profile is incomplete or missing")
            if video_source.mode != "local" or telemetry_source.mode != "local":
                raise ValueError("survey server import requires a local source profile")
            if not video_source.enabled or not telemetry_source.enabled:
                raise ValueError("source profile is disabled")
            video_asset = video_source.location.removeprefix("test_videos/")
            telemetry_asset = telemetry_source.location.removeprefix("test_videos/")
            telemetry_type = telemetry_source.source_type
            telemetry_config = telemetry_source.config or {}
            if telemetry_source.source_type == "file":
                telemetry_type = telemetry_config.get("format") or "dji_cloud_json"
            validation_status = telemetry_source.validation_status
        if not video_asset or not telemetry_asset:
            raise ValueError("source_profile_id or both video_asset and telemetry_asset are required")
        source_roots = [*settings.survey_asset_roots, settings.survey_storage_dir]
        video_path = resolve_allowlisted_asset(video_asset, source_roots, platform_dir)
        telemetry_path = resolve_allowlisted_asset(telemetry_asset, source_roots, platform_dir)
        package = await self._package(task.id)
        video_stored, telemetry_stored = await asyncio.gather(
            asyncio.to_thread(self.storage.reference_path, video_path, video_asset),
            asyncio.to_thread(self.storage.reference_path, telemetry_path, telemetry_asset),
        )
        result = await self.enqueue_capture_batch(
            task,
            package,
            video_stored,
            telemetry_stored,
            actor_id,
            request_id,
            {
                "asset_key": video_asset,
                "ingest": "server_asset_reference",
                "source_profile_id": source_profile_id,
                "validation_status": validation_status,
            },
            {
                "asset_key": telemetry_asset,
                "ingest": "server_asset_reference",
                "source_profile_id": source_profile_id,
                "telemetry_type": telemetry_type,
                "config": telemetry_config,
                "validation_status": validation_status,
            },
            source_profile_id=source_profile_id,
            source_type=f"mp4_{telemetry_type}",
        )
        batch = await self.session.get(SurveyCaptureBatch, result["id"])
        return await self._batch_details(batch)

    async def upload_capture_batch(
        self,
        task_id: str,
        video_file,
        telemetry_file,
        actor_id: int | None,
        role: str,
        request_id: str | None,
        video_name: str,
        telemetry_name: str,
    ) -> dict:
        if prior := await self._prior("survey.capture.enqueued", request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"ready", "collecting", "returned"}:
            raise ValueError("task must pass precheck before capture ingestion")
        if not video_name.lower().endswith(".mp4") or not telemetry_name.lower().endswith(".srt"):
            raise ValueError("survey upload requires one MP4 video and one SRT telemetry file")
        package = await self._package(task.id)
        max_bytes = int(settings.survey_upload_max_bytes)
        video_stored = await asyncio.to_thread(self.storage.ingest_fileobj, video_file, max_bytes)
        telemetry_stored = await asyncio.to_thread(self.storage.ingest_fileobj, telemetry_file, max_bytes)
        return await self.enqueue_capture_batch(
            task,
            package,
            video_stored,
            telemetry_stored,
            actor_id,
            request_id,
            {"filename": video_name, "ingest": "upload"},
            {"filename": telemetry_name, "ingest": "upload"},
        )

    async def enqueue_capture_batch(
        self,
        task: SurveyTask,
        package: EvidencePackage,
        video_stored: StoredObject,
        telemetry_stored: StoredObject,
        actor_id: int | None,
        request_id: str | None,
        video_metadata: dict,
        telemetry_metadata: dict,
        source_profile_id: str | None = None,
        source_type: str = "mp4_srt",
    ) -> dict:
        video_item = await self._evidence(package, task.id, "original_video", video_stored, "video/mp4", video_metadata)
        telemetry_media_type = (
            "application/x-subrip" if telemetry_metadata.get("telemetry_type", "srt") == "srt" else "application/json"
        )
        telemetry_item = await self._evidence(
            package, task.id, "original_telemetry", telemetry_stored, telemetry_media_type, telemetry_metadata
        )
        batch = SurveyCaptureBatch(
            id=_identifier("BATCH"),
            task_id=task.id,
            status="queued",
            source_type=source_type,
            source_profile_id=source_profile_id,
            video_evidence_id=video_item.id,
            telemetry_evidence_id=telemetry_item.id,
        )
        self.session.add(batch)
        await self.session.flush()
        self.session.add(
            CaptureIngestionJob(
                id=_identifier("JOB"),
                task_id=task.id,
                batch_id=batch.id,
                status="pending",
            )
        )
        task.state = "collecting"
        task.version += 1
        await self.session.flush()
        result = _batch_dict(batch)
        await self._audit(actor_id, "survey.capture.enqueued", "capture_batch", batch.id, after=result, request_id=request_id)
        return result

    async def process_capture_batch(self, batch_id: str) -> dict:
        job = (
            await self.session.execute(
                select(CaptureIngestionJob).where(CaptureIngestionJob.batch_id == batch_id).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            raise LookupError("capture ingestion job not found")
        batch = await self.session.get(SurveyCaptureBatch, batch_id)
        if batch is None:
            raise LookupError("capture batch not found")
        if job.status == "completed":
            return _batch_dict(batch)
        if job.attempt_count >= job.max_attempts:
            raise ValueError("capture ingestion retry limit reached")
        video_item = await self.session.get(EvidenceItem, batch.video_evidence_id)
        telemetry_item = await self.session.get(EvidenceItem, batch.telemetry_evidence_id)
        if video_item is None or telemetry_item is None:
            raise ValueError("capture source evidence is incomplete")
        source_statuses = {
            "video": self._evidence_reference_status(video_item),
            "telemetry": self._evidence_reference_status(telemetry_item),
        }
        if any(status != "verified" for status in source_statuses.values()):
            batch.status = "error"
            batch.error_message = "/".join(f"{kind}:{value}" for kind, value in source_statuses.items())
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            job.last_error = batch.error_message
            await self.session.flush()
            await self._audit(None, "survey.capture.source_invalid", "capture_batch", batch.id, after=await self._batch_details(batch))
            return await self._batch_details(batch)
        package = await self._package(batch.task_id)
        job.status = "processing"
        job.attempt_count += 1
        job.locked_at = datetime.now(UTC)
        batch.status = "processing"
        await self.session.flush()
        try:
            telemetry_metadata = telemetry_item.item_metadata or {}
            telemetry_config = telemetry_metadata.get("config") or {}
            processed = await asyncio.to_thread(
                process_mp4_telemetry,
                self._resolve_evidence_path(video_item),
                self._resolve_evidence_path(telemetry_item),
                settings.survey_keyframe_count,
                telemetry_metadata.get("telemetry_type", "srt"),
                float(telemetry_config.get("time_offset_sec", 0)),
                float(telemetry_config.get("sync_tolerance_sec", 0.5)),
            )
            batch.duration_sec = processed.duration_sec
            batch.fps = processed.fps
            batch.frame_count = processed.frame_count
            batch.telemetry_coverage = processed.telemetry_coverage
            batch.quality_checks = processed.quality_checks
            declared_degraded = telemetry_metadata.get("validation_status") == "degraded"
            batch.status = "degraded" if processed.frames and declared_degraded else ("ready" if processed.frames else "error")
            batch.error_message = None
            for index, frame in enumerate(processed.frames):
                source_stored = await asyncio.to_thread(self.storage.ingest_bytes, frame.image)
                bev_stored = await asyncio.to_thread(self.storage.ingest_bytes, frame.bev)
                source_item = await self._evidence(
                    package,
                    batch.task_id,
                    "source_frame",
                    source_stored,
                    "image/jpeg",
                    {"frame_number": frame.frame_number, "timestamp_sec": frame.timestamp_sec},
                    video_item.id,
                )
                bev_item = await self._evidence(
                    package,
                    batch.task_id,
                    "bev_frame",
                    bev_stored,
                    "image/jpeg",
                    {"frame_number": frame.frame_number, "timestamp_sec": frame.timestamp_sec},
                    source_item.id,
                )
                self.session.add(
                    SurveyFrame(
                        id=_identifier("FRM"),
                        task_id=batch.task_id,
                        batch_id=batch.id,
                        frame_number=frame.frame_number,
                        timestamp_sec=frame.timestamp_sec,
                        image_evidence_id=source_item.id,
                        bev_evidence_id=bev_item.id,
                        image_width=frame.image_width,
                        image_height=frame.image_height,
                        homography=frame.homography,
                        view_transform=frame.view_transform,
                        telemetry=frame.telemetry,
                        quality=frame.quality,
                        selected=index == 0,
                    )
                )
            job.status = "completed" if processed.frames else "failed"
            job.finished_at = datetime.now(UTC)
            job.last_error = None if processed.frames else "no usable keyframes"
        except Exception as exc:
            batch.status = "error"
            batch.error_message = str(exc)
            job.last_error = str(exc)
            job.status = "retry" if job.attempt_count < job.max_attempts else "failed"
            job.finished_at = datetime.now(UTC) if job.status == "failed" else None
            await self.session.flush()
            return _batch_dict(batch)
        await self.session.flush()
        await self._audit(None, "survey.capture.processed", "capture_batch", batch.id, after=_batch_dict(batch))
        return await self._batch_details(batch)

    async def list_batches(self, task_id: str, actor_id: int | None, role: str) -> list[dict]:
        await self._task(task_id, actor_id, role)
        rows = (
            await self.session.execute(
                select(SurveyCaptureBatch).where(SurveyCaptureBatch.task_id == task_id).order_by(SurveyCaptureBatch.created_at.desc())
            )
        ).scalars().all()
        return [await self._batch_details(row) for row in rows]

    async def list_frames(self, task_id: str, actor_id: int | None, role: str, batch_id: str | None = None) -> list[dict]:
        task = await self._task(task_id, actor_id, role)
        selected_batch = batch_id or task.selected_batch_id
        query = select(SurveyFrame).where(SurveyFrame.task_id == task_id)
        if selected_batch:
            query = query.where(SurveyFrame.batch_id == selected_batch)
        rows = (await self.session.execute(query.order_by(SurveyFrame.frame_number.asc()))).scalars().all()
        return [_frame_dict(row) for row in rows]

    async def list_measurements(self, task_id: str, actor_id: int | None, role: str) -> list[dict]:
        await self._task(task_id, actor_id, role)
        rows = (
            await self.session.execute(
                select(SurveyMeasurement).where(
                    SurveyMeasurement.task_id == task_id,
                    SurveyMeasurement.is_current.is_(True),
                ).order_by(SurveyMeasurement.created_at.asc())
            )
        ).scalars().all()
        return [_measurement_dict(row) for row in rows]

    async def save_measurement(
        self,
        task_id: str,
        data: dict,
        actor_id: int | None,
        role: str,
        request_id: str | None,
        measurement_id: str | None = None,
    ) -> dict:
        if prior := await self._prior("survey.measurement.saved", request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"measuring", "returned"}:
            raise ValueError("task is not in a measurement-editable state")
        frame = await self.session.get(SurveyFrame, data["frame_id"])
        if frame is None or frame.task_id != task.id:
            raise LookupError("survey frame not found")
        if frame.homography is None:
            raise ValueError("selected frame has no valid metric transform")
        image_to_view = np.asarray(frame.view_transform, dtype=np.float64)
        pixel_to_metric = np.asarray(frame.homography, dtype=np.float64) @ np.linalg.inv(image_to_view)
        metric_geometry, values = calculate_measurement(data["geometry_type"], data["image_geometry"], pixel_to_metric)

        logical_id = measurement_id or f"M-{uuid.uuid4().hex[:8].upper()}"
        current = (
            await self.session.execute(
                select(SurveyMeasurement).where(
                    SurveyMeasurement.task_id == task.id,
                    SurveyMeasurement.measurement_id == logical_id,
                    SurveyMeasurement.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        revision = 1
        before = None
        if current is not None:
            expected = data.get("expected_revision")
            if expected is None or expected != current.revision:
                raise RuntimeError("measurement revision conflict")
            before = _measurement_dict(current)
            current.is_current = False
            revision = current.revision + 1
        measurement = SurveyMeasurement(
            row_id=_identifier("MSR"),
            measurement_id=logical_id,
            task_id=task.id,
            frame_id=frame.id,
            revision=revision,
            geometry_type=data["geometry_type"],
            category=data.get("category"),
            image_geometry=data["image_geometry"],
            metric_geometry=metric_geometry,
            computed_values=values,
            error_estimate={"status": "unverified", "reason": "survey thresholds not approved"},
            quality_status="unverified",
            source="manual",
            created_by=actor_id,
        )
        self.session.add(measurement)
        await self.session.flush()
        result = _measurement_dict(measurement)
        await self._audit(actor_id, "survey.measurement.saved", "survey_measurement", logical_id, before, result, request_id=request_id)
        return result

    async def delete_measurement(self, task_id: str, measurement_id: str, expected_revision: int, actor_id: int | None, role: str) -> None:
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"measuring", "returned"}:
            raise ValueError("task is not in a measurement-editable state")
        current = (
            await self.session.execute(
                select(SurveyMeasurement).where(
                    SurveyMeasurement.task_id == task.id,
                    SurveyMeasurement.measurement_id == measurement_id,
                    SurveyMeasurement.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        if current is None:
            raise LookupError("measurement not found")
        if current.revision != expected_revision:
            raise RuntimeError("measurement revision conflict")
        current.is_current = False
        await self._audit(actor_id, "survey.measurement.deleted", "survey_measurement", measurement_id, before=_measurement_dict(current))

    async def list_annotations(self, task_id: str, actor_id: int | None, role: str) -> list[dict]:
        await self._task(task_id, actor_id, role)
        rows = (
            await self.session.execute(
                select(SceneAnnotation)
                .where(SceneAnnotation.task_id == task_id)
                .order_by(SceneAnnotation.created_at.asc())
            )
        ).scalars().all()
        return [_annotation_dict(row) for row in rows]

    async def create_annotation(
        self,
        task_id: str,
        data: dict,
        actor_id: int | None,
        role: str,
        request_id: str | None,
    ) -> dict:
        if prior := await self._prior("survey.annotation.created", request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"measuring", "returned", "pending_review"}:
            raise ValueError("task is not in an annotation-editable state")
        frame = await self.session.get(SurveyFrame, data["frame_id"])
        if frame is None or frame.task_id != task_id:
            raise LookupError("survey frame not found")
        annotation = SceneAnnotation(
            id=_identifier("ANN"),
            task_id=task_id,
            frame_id=frame.id,
            category=data["category"],
            image_geometry=data["image_geometry"],
            source=data.get("source", "manual"),
            confidence=data.get("confidence"),
            review_state="draft",
            version=1,
        )
        self.session.add(annotation)
        await self.session.flush()
        result = _annotation_dict(annotation)
        await self._audit(actor_id, "survey.annotation.created", "scene_annotation", annotation.id, after=result, request_id=request_id)
        return result

    async def update_annotation(
        self, task_id: str, annotation_id: str, data: dict, actor_id: int | None, role: str
    ) -> dict:
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"measuring", "returned", "pending_review"}:
            raise ValueError("task is not in an annotation-editable state")
        annotation = await self.session.get(SceneAnnotation, annotation_id)
        if annotation is None or annotation.task_id != task_id:
            raise LookupError("scene annotation not found")
        if annotation.version != data["expected_revision"]:
            raise RuntimeError("scene annotation revision conflict")
        before = _annotation_dict(annotation)
        annotation.category = data["category"]
        annotation.image_geometry = data["image_geometry"]
        annotation.review_state = data.get("review_state", "draft")
        annotation.version += 1
        await self.session.flush()
        result = _annotation_dict(annotation)
        await self._audit(actor_id, "survey.annotation.updated", "scene_annotation", annotation.id, before, result)
        return result

    async def delete_annotation(
        self, task_id: str, annotation_id: str, expected_revision: int, actor_id: int | None, role: str
    ) -> None:
        task = await self._task(task_id, actor_id, role)
        if task.state not in {"measuring", "returned", "pending_review"}:
            raise ValueError("task is not in an annotation-editable state")
        annotation = await self.session.get(SceneAnnotation, annotation_id)
        if annotation is None or annotation.task_id != task_id:
            raise LookupError("scene annotation not found")
        if annotation.version != expected_revision:
            raise RuntimeError("scene annotation revision conflict")
        before = _annotation_dict(annotation)
        await self.session.delete(annotation)
        await self._audit(actor_id, "survey.annotation.deleted", "scene_annotation", annotation_id, before=before)

    async def evidence_item(self, evidence_id: str, actor_id: int | None, role: str) -> tuple[EvidenceItem, Path]:
        item = await self.session.get(EvidenceItem, evidence_id)
        if item is None:
            raise LookupError("evidence item not found")
        if item.task_id:
            await self._task(item.task_id, actor_id, role)
        status = self._evidence_reference_status(item)
        if status != "verified":
            raise RuntimeError(f"evidence reference is {status}")
        return item, self._resolve_evidence_path(item)

    @staticmethod
    def _annotated_bev(source: bytes, measurements: list[dict]) -> bytes:
        image = cv2.imdecode(np.frombuffer(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("BEV evidence is not a readable image")
        overlay = image.copy()
        for measurement in measurements:
            points = np.rint(np.asarray(measurement.get("image_geometry") or [], dtype=np.float64)).astype(np.int32)
            if len(points) == 0:
                continue
            geometry_type = measurement.get("geometry_type")
            closed = geometry_type in {"area", "object"} and len(points) > 2
            color = (216, 200, 32)
            if closed:
                cv2.fillPoly(overlay, [points], color)
            if len(points) > 1:
                cv2.polylines(image, [points], closed, color, 3, cv2.LINE_AA)
            for point in points:
                cv2.circle(image, tuple(point), 5, color, -1, cv2.LINE_AA)

            metric_points = np.asarray(measurement.get("metric_geometry") or [], dtype=np.float64)
            segments = list(zip(points[:-1], points[1:], strict=False))
            metric_segments = list(zip(metric_points[:-1], metric_points[1:], strict=False))
            if closed:
                segments.append((points[-1], points[0]))
                if len(metric_points) == len(points):
                    metric_segments.append((metric_points[-1], metric_points[0]))
            for index, (start, end) in enumerate(segments):
                if index >= len(metric_segments):
                    continue
                metric_start, metric_end = metric_segments[index]
                label = f"{np.linalg.norm(metric_end - metric_start):.2f} m"
                midpoint = np.rint((start + end) / 2).astype(int)
                (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                x = int(midpoint[0] - text_width / 2)
                y = int(midpoint[1] + text_height / 2)
                cv2.rectangle(
                    image,
                    (x - 5, y - text_height - 5),
                    (x + text_width + 5, y + baseline + 5),
                    (6, 13, 24),
                    -1,
                )
                cv2.rectangle(
                    image,
                    (x - 5, y - text_height - 5),
                    (x + text_width + 5, y + baseline + 5),
                    color,
                    1,
                )
                cv2.putText(image, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        image = cv2.addWeighted(overlay, 0.15, image, 0.85, 0)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("annotated BEV encoding failed")
        return encoded.tobytes()

    @staticmethod
    def _report_pdf(payload: dict, annotated_images: list[bytes] | None = None) -> bytes:
        buffer = io.BytesIO()
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        document = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        document.setTitle(f"无人机辅助事故现场测绘报告 {payload['task']['id']}")
        document.setFont("STSong-Light", 18)
        document.drawString(48, height - 56, "无人机辅助事故现场测绘报告")
        document.setFont("STSong-Light", 9)
        document.drawString(48, height - 76, "技术复核成果 · 不替代法定事故责任认定、人工签章或案件归档")
        y = height - 112
        for label, value in [
            ("任务", payload["task"]["id"]),
            ("位置", payload["task"]["location"]),
            ("成果版本", payload["task"]["version"]),
            ("质量状态", payload["task"]["quality"]),
            ("生成时间", payload["generated_at"]),
        ]:
            document.setFont("STSong-Light", 10)
            document.drawString(48, y, f"{label}：{value}")
            y -= 18
        for index, annotated_image in enumerate(annotated_images or [], start=1):
            image = ImageReader(io.BytesIO(annotated_image))
            image_width, image_height = image.getSize()
            target_width = width - 96
            target_height = min(260, target_width * image_height / image_width)
            if y - target_height < 80:
                document.showPage()
                document.setFont("STSong-Light", 13)
                y = height - 56
            document.setFont("STSong-Light", 12)
            document.drawString(48, y, f"测绘标注图 {index}")
            y -= 16
            document.drawImage(
                image,
                48,
                y - target_height,
                width=target_width,
                height=target_height,
                preserveAspectRatio=True,
                anchor="c",
            )
            y -= target_height + 22
        y -= 10
        document.setFont("STSong-Light", 13)
        document.drawString(48, y, "量算清单")
        y -= 24
        document.setFont("STSong-Light", 9)
        for item in payload["measurements"]:
            line = f"{item['id']}  {item.get('category') or item['geometry_type']}  {item['display_value']}  {item['quality_status']}"
            document.drawString(58, y, line[:88])
            y -= 16
            if y < 72:
                document.showPage()
                document.setFont("STSong-Light", 9)
                y = height - 56
        document.setFont("STSong-Light", 8)
        document.drawString(48, 44, "schema uav.survey-result.v1 · event_type survey_result · quality thresholds unverified")
        document.save()
        return buffer.getvalue()

    async def generate_report(self, task_id: str, actor_id: int | None, role: str, request_id: str | None) -> dict:
        if prior := await self._prior("survey.report.generated", request_id):
            return prior
        task = await self._task(task_id, actor_id, role)
        if task.state != "technical_reviewed":
            raise ValueError("technical review is required before report generation")
        measurements = await self.list_measurements(task.id, actor_id, role)
        if not measurements:
            raise ValueError("report requires at least one measurement")
        package = await self._package(task.id)
        evidence_rows = (
            await self.session.execute(select(EvidenceItem).where(EvidenceItem.task_id == task.id))
        ).scalars().all()
        integrity_checks = await asyncio.gather(
            *(asyncio.to_thread(self._verify_evidence, item) for item in evidence_rows)
        )
        if not evidence_rows or not all(integrity_checks):
            raise ValueError("evidence integrity check failed")
        report_version = int(
            await self.session.scalar(
                select(func.coalesce(func.max(SurveyReport.version), 0)).where(SurveyReport.task_id == task.id)
            )
        ) + 1
        measurement_frame_ids = {item["frame_id"] for item in measurements}
        frames = (
            await self.session.execute(
                select(SurveyFrame)
                .where(SurveyFrame.task_id == task.id, SurveyFrame.id.in_(measurement_frame_ids))
                .order_by(SurveyFrame.frame_number)
            )
        ).scalars().all()
        annotated_images: list[bytes] = []
        annotated_refs: list[dict] = []
        for frame in frames:
            frame_measurements = [item for item in measurements if item["frame_id"] == frame.id]
            bev_item = await self.session.get(EvidenceItem, frame.bev_evidence_id)
            if bev_item is None or not await asyncio.to_thread(self._verify_evidence, bev_item):
                raise ValueError(f"BEV evidence integrity check failed for frame {frame.id}")
            bev_source = await asyncio.to_thread(self._resolve_evidence_path(bev_item).read_bytes)
            annotated = await asyncio.to_thread(self._annotated_bev, bev_source, frame_measurements)
            annotated_stored = await asyncio.to_thread(self.storage.ingest_bytes, annotated)
            annotated_item = await self._evidence(
                package,
                task.id,
                "survey_report_annotated_image",
                annotated_stored,
                "image/jpeg",
                {
                    "version": report_version,
                    "frame_id": frame.id,
                    "frame_number": frame.frame_number,
                    "measurement_count": len(frame_measurements),
                },
                derived_from_id=frame.bev_evidence_id,
            )
            annotated_images.append(annotated)
            annotated_refs.append(
                {
                    "frame_id": frame.id,
                    "frame_number": frame.frame_number,
                    "measurement_count": len(frame_measurements),
                    "evidence_id": annotated_item.id,
                    "url": f"/api/v1/survey-evidence/{annotated_item.id}/content",
                    "sha256": annotated_item.sha256,
                }
            )
        payload = {
            "schema_version": "uav.survey-result.v1",
            "event_type": "survey_result",
            "source_system": "uav_traffic_analyzer_ai",
            "generated_at": _now_iso(),
            "task": _task_dict(task),
            "measurements": measurements,
            "annotated_images": annotated_refs,
            "evidence": [{"id": item.id, "kind": item.kind, "sha256": item.sha256} for item in evidence_rows],
            "quality_statement": "unverified: S3 measurement thresholds are not approved",
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
        content_hash = hashlib.sha256(canonical).hexdigest()
        pdf_stored = await asyncio.to_thread(self.storage.ingest_bytes, self._report_pdf(payload, annotated_images))
        json_stored = await asyncio.to_thread(self.storage.ingest_bytes, canonical)
        def geojson_coordinates(item: dict):
            coordinates = item["metric_geometry"]
            if item["geometry_type"] == "point":
                return coordinates[0]
            if item["geometry_type"] in {"area", "object"} and coordinates and coordinates[0] != coordinates[-1]:
                return coordinates + [coordinates[0]]
            return coordinates

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": item["id"],
                    "geometry": {
                        "type": "Polygon" if item["geometry_type"] in {"area", "object"} else "LineString" if item["geometry_type"] in {"line", "polyline"} else "Point",
                        "coordinates": [geojson_coordinates(item)] if item["geometry_type"] in {"area", "object"} else geojson_coordinates(item),
                    },
                    "properties": {"category": item.get("category"), "quality_status": item["quality_status"], **item["values"]},
                }
                for item in measurements
            ],
        }
        geojson_stored = await asyncio.to_thread(
            self.storage.ingest_bytes,
            json.dumps(geojson, ensure_ascii=False, sort_keys=True).encode(),
        )
        pdf_item = await self._evidence(package, task.id, "survey_report_pdf", pdf_stored, "application/pdf", {"version": report_version})
        json_item = await self._evidence(
            package, task.id, "survey_report_json", json_stored, "application/json", {"version": report_version}
        )
        geojson_item = await self._evidence(
            package,
            task.id,
            "survey_report_geojson",
            geojson_stored,
            "application/geo+json",
            {"version": report_version},
        )
        report = SurveyReport(
            id=_identifier("RPT"),
            task_id=task.id,
            version=report_version,
            payload=payload,
            content_hash=content_hash,
            pdf_evidence_id=pdf_item.id,
            created_by=actor_id,
        )
        self.session.add(report)
        batch = (
            await self.session.get(SurveyCaptureBatch, task.selected_batch_id)
            if task.selected_batch_id
            else None
        )
        event_payload = {
            **payload,
            "title": f"事故测绘成果 · {task.scene_location}",
            "description": "真实视频与遥测生成的技术测绘成果",
            "severity": "P3",
            "status": "generated",
            "report_id": report.id,
            "source_profile_id": batch.source_profile_id if batch else None,
            "evidence_refs": [
                {
                    "id": pdf_item.id,
                    "kind": "survey_report_pdf",
                    "url": f"/api/v1/survey-evidence/{pdf_item.id}/content",
                    "sha256": pdf_item.sha256,
                },
                {
                    "id": json_item.id,
                    "kind": "survey_report_json",
                    "url": f"/api/v1/survey-evidence/{json_item.id}/content",
                    "sha256": json_item.sha256,
                },
                {
                    "id": geojson_item.id,
                    "kind": "survey_report_geojson",
                    "url": f"/api/v1/survey-evidence/{geojson_item.id}/content",
                    "sha256": geojson_item.sha256,
                },
                *[
                    {
                        "id": item["evidence_id"],
                        "kind": "survey_report_annotated_image",
                        "url": item["url"],
                        "sha256": item["sha256"],
                    }
                    for item in annotated_refs
                ],
            ],
            "delivery_blocked_reason": "survey quality thresholds are not approved",
        }
        self.session.add(AiEvent(
            id=_identifier("EVT"),
            source_event_id=report.id,
            idempotency_key=f"survey-report:{report.id}",
            event_type="survey_result",
            task_id=task.id,
            review_status="technical_reviewed",
            occurred_at=datetime.now(UTC),
            inter_id=task.inter_id,
            road_data_version=task.road_data_version,
            quality_status=task.quality_status,
            payload_hash=content_hash,
            delivery_status="blocked",
            payload=event_payload,
        ))
        task.delivery_status = "generated"
        task.version += 1
        package.integrity_status = "unverified"
        package.manifest_hash = content_hash
        await self.session.flush()
        result = {
            "id": report.id,
            "task_id": task.id,
            "version": report.version,
            "status": report.status,
            "schema_version": report.schema_version,
            "content_hash": report.content_hash,
            "payload": report.payload,
            "pdf_url": f"/api/v1/survey-evidence/{pdf_item.id}/content",
            "json_url": f"/api/v1/survey-evidence/{json_item.id}/content",
            "geojson_url": f"/api/v1/survey-evidence/{geojson_item.id}/content",
            "annotated_images": annotated_refs,
            "delivery_blocked_reason": "survey quality thresholds are not approved",
        }
        await self._audit(actor_id, "survey.report.generated", "survey_report", report.id, after=result, request_id=request_id)
        return result

    async def list_reports(self, task_id: str, actor_id: int | None, role: str) -> list[dict]:
        await self._task(task_id, actor_id, role)
        approved_policy = (
            await self.session.execute(
                select(RuleVersion.id).where(
                    RuleVersion.rule_type == "survey_quality",
                    RuleVersion.status == "approved",
                ).limit(1)
            )
        ).scalar_one_or_none()
        if approved_policy is None:
            blocked_reason = "survey quality thresholds are not approved"
        elif not settings.survey_delivery_url:
            blocked_reason = "survey delivery URL is not configured"
        else:
            blocked_reason = None
        rows = (
            await self.session.execute(
                select(SurveyReport).where(SurveyReport.task_id == task_id).order_by(SurveyReport.version.desc())
            )
        ).scalars().all()
        report_evidence = (
            await self.session.execute(
                select(EvidenceItem).where(
                    EvidenceItem.task_id == task_id,
                    EvidenceItem.kind.in_(
                        ["survey_report_pdf", "survey_report_json", "survey_report_geojson"]
                    ),
                )
            )
        ).scalars().all()
        evidence_by_version_kind = {
            (int((item.item_metadata or {}).get("version", 0)), item.kind): item.id
            for item in report_evidence
        }

        def evidence_url(version: int, kind: str) -> str | None:
            evidence_id = evidence_by_version_kind.get((version, kind))
            return f"/api/v1/survey-evidence/{evidence_id}/content" if evidence_id else None

        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "version": row.version,
                "status": row.status,
                "schema_version": row.schema_version,
                "content_hash": row.content_hash,
                "payload": row.payload,
                "pdf_url": f"/api/v1/survey-evidence/{row.pdf_evidence_id}/content" if row.pdf_evidence_id else None,
                "json_url": evidence_url(row.version, "survey_report_json"),
                "geojson_url": evidence_url(row.version, "survey_report_geojson"),
                "annotated_images": (row.payload or {}).get("annotated_images", []),
                "delivery_blocked_reason": blocked_reason if row.status == "generated" else None,
            }
            for row in rows
        ]

    async def deliver_report(self, task_id: str, report_id: str, idempotency_key: str, actor_id: int | None, role: str) -> dict:
        if role != "admin":
            raise PermissionError("administrator capability is required for delivery")
        task = await self._task(task_id, actor_id, role)
        report = await self.session.get(SurveyReport, report_id)
        if report is None or report.task_id != task.id:
            raise LookupError("survey report not found")
        approved_policy = (
            await self.session.execute(
                select(RuleVersion).where(
                    RuleVersion.rule_type == "survey_quality",
                    RuleVersion.status == "approved",
                )
            )
        ).scalar_one_or_none()
        if approved_policy is None:
            raise ValueError("survey quality thresholds are not approved")
        if not settings.survey_delivery_url:
            raise ValueError("survey delivery destination is not configured")
        existing = (
            await self.session.execute(
                select(EventOutbox).where(
                    EventOutbox.idempotency_key == idempotency_key,
                    EventOutbox.destination == settings.survey_delivery_url,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return {"status": existing.status, "idempotency_key": idempotency_key}
        event = (
            await self.session.execute(
                select(AiEvent).where(
                    AiEvent.source_system == "uav_traffic_analyzer_ai",
                    AiEvent.source_event_id == report.id,
                )
            )
        ).scalar_one_or_none()
        if event is None:
            event = AiEvent(
                id=_identifier("EVT"),
                source_event_id=report.id,
                idempotency_key=f"survey-report:{report.id}",
                event_type="survey_result",
                task_id=task.id,
                payload=report.payload,
            )
            self.session.add(event)
        event.delivery_status = "pending"
        self.session.add(
            EventOutbox(
                id=_identifier("OUT"),
                event_id=event.id,
                destination=settings.survey_delivery_url,
                idempotency_key=idempotency_key,
                payload_hash=report.content_hash,
                payload=report.payload,
            )
        )
        report.status = "delivering"
        task.delivery_status = "delivering"
        task.version += 1
        await self.session.flush()
        return {"status": "delivering", "idempotency_key": idempotency_key}
