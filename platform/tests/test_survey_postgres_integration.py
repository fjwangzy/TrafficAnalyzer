"""S3 functional workflow against an explicitly selected disposable road9.

Geometry is a controlled engineering fixture, never approved survey accuracy.
Database changes roll back; evidence uses pytest's temporary object store.
"""
import os
import uuid

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.survey import AuditLog, SurveyCaptureBatch, SurveyFrame, SurveyMeasurement
from app.services.survey_service import SurveyService

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires an explicitly selected disposable road9 database",
)


@pytest.mark.asyncio
async def test_survey_measurement_return_revision_report_and_delivery_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path))
    async with async_session_maker() as session:
        service = SurveyService(session)
        task = await service.create_task(
            {"title": "工程验收测绘夹具", "scene_location": "隔离测试现场"},
            None, "acceptance-fixture", None,
        )
        task_id = task["id"]

        async def transition(action, **payload):
            current = await service.get_task(task_id, None, "admin")
            return await service.transition(
                task_id, action, current["revision"], payload, None, "admin", None,
            )

        await transition("start_precheck")
        prechecked = await transition("complete_precheck", checklist={
            key: True for key in (
                "task_context", "operator_authorized", "site_command_confirmed",
                "device_ready", "storage_ready",
            )
        })
        assert prechecked["status"] == "ready"
        batch = SurveyCaptureBatch(id=uuid.uuid4().hex, task_id=task_id, status="ready")
        session.add(batch)
        await session.flush()
        package = await service._package(task_id)
        encoded, jpeg = cv2.imencode(".jpg", np.full((80, 100, 3), 180, dtype=np.uint8))
        assert encoded
        stored = service.storage.ingest_bytes(jpeg.tobytes())
        evidence = await service._evidence(
            package, task_id, "original_frame", stored, "image/jpeg", {"fixture": True},
        )
        frame = SurveyFrame(
            id=uuid.uuid4().hex, task_id=task_id, batch_id=batch.id,
            frame_number=1, timestamp_sec=0, image_evidence_id=evidence.id,
            bev_evidence_id=evidence.id, image_width=100, image_height=80,
            homography=np.eye(3).tolist(), view_transform=np.eye(3).tolist(),
            quality={"status": "unverified", "fixture": True},
        )
        session.add(frame)
        await session.flush()
        await transition("select_batch", batch_id=batch.id)

        line_data = {"frame_id": frame.id, "geometry_type": "line", "image_geometry": [[0, 0], [3, 4]]}
        line = await service.save_measurement(task_id, line_data, None, "admin", None)
        assert line["values"]["length_m"] == pytest.approx(5)
        area = await service.save_measurement(task_id, {
            "frame_id": frame.id, "geometry_type": "area",
            "image_geometry": [[10, 10], [20, 10], [20, 20], [10, 20]],
        }, None, "admin", None)
        assert area["values"]["area_m2"] == pytest.approx(100)
        assert area["values"]["perimeter_m"] == pytest.approx(40)
        annotation = await service.create_annotation(task_id, {
            "frame_id": frame.id, "category": "vehicle", "image_geometry": [[3, 4]],
        }, None, "admin", None)
        updated = await service.update_annotation(task_id, annotation["id"], {
            "expected_revision": 1, "category": "trace", "image_geometry": [[4, 5]],
        }, None, "admin")
        assert updated["revision"] == 2

        await transition("submit_review")
        returned = await transition("return", return_type="measurement", reason="工程夹具：补充长度")
        assert returned["status"] == "returned"
        replacement = await service.save_measurement(task_id, {
            **line_data, "expected_revision": 1, "image_geometry": [[0, 0], [6, 8]],
        }, None, "admin", None, measurement_id=line["id"])
        assert replacement["revision"] == 2
        assert replacement["values"]["length_m"] == pytest.approx(10)
        versions = (await session.execute(select(SurveyMeasurement).where(
            SurveyMeasurement.measurement_id == line["id"],
        ).order_by(SurveyMeasurement.revision))).scalars().all()
        assert [row.is_current for row in versions] == [False, True]
        await transition("select_batch", batch_id=batch.id)
        await transition("submit_review")
        await transition("approve_review", checklist={key: True for key in (
            "task_and_location", "source_materials", "coordinate_chain",
            "measurements", "edit_history", "quality_status",
        )})
        report = await service.generate_report(task_id, None, "admin", None)
        assert report["delivery_blocked_reason"] == "survey quality thresholds are not approved"
        item_id = report["pdf_url"].split("/")[-2]
        item, pdf_path = await service.evidence_item(item_id, None, "admin")
        assert pdf_path.read_bytes().startswith(b"%PDF")
        assert service._verify_evidence(item)
        actions = (await session.execute(select(AuditLog.action).where(
            AuditLog.target_id.in_([task_id, line["id"], annotation["id"], report["id"]]),
        ))).scalars().all()
        assert {"survey.task.return", "survey.annotation.updated", "survey.report.generated"} <= set(actions)
        with pytest.raises(ValueError, match="quality thresholds are not approved"):
            await service.deliver_report(task_id, report["id"], uuid.uuid4().hex, None, "admin")
        await session.rollback()
