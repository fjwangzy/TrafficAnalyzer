"""Recoverable capture-ingestion and report-delivery worker for survey jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.survey import (
    AiEvent,
    CaptureIngestionJob,
    DeadLetter,
    EventDeliveryAttempt,
    EventOutbox,
    SurveyReport,
    SurveyTask,
)
from app.services.survey_service import SurveyService, _identifier


logger = logging.getLogger(__name__)


class SurveyWorker:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="uav-survey-worker")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        while self._running:
            try:
                progressed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Survey worker iteration failed")
                progressed = False
            await asyncio.sleep(settings.survey_worker_poll_sec)

    async def run_once(self) -> bool:
        if await self._process_one_capture():
            return True
        return await self._deliver_one_event()

    async def _process_one_capture(self) -> bool:
        async with async_session_maker() as session:
            job = (
                await session.execute(
                    select(CaptureIngestionJob)
                    .where(CaptureIngestionJob.status.in_(["pending", "retry"]))
                    .order_by(CaptureIngestionJob.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if job is None:
                return False
            await SurveyService(session).process_capture_batch(job.batch_id)
            await session.commit()
            return True

    async def _deliver_one_event(self) -> bool:
        async with async_session_maker() as session:
            outbox = (
                await session.execute(
                    select(EventOutbox)
                    .where(EventOutbox.status.in_(["pending", "retry"]))
                    .order_by(EventOutbox.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if outbox is None:
                return False
            response_status = None
            error = None
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        outbox.destination,
                        json=outbox.payload,
                        headers={"Idempotency-Key": outbox.idempotency_key},
                    )
                response_status = response.status_code
                response.raise_for_status()
            except Exception as exc:
                error = str(exc)[:1000]

            outbox.attempt_count += 1
            success = error is None
            session.add(
                EventDeliveryAttempt(
                    outbox_id=outbox.id,
                    success=success,
                    response_status=response_status,
                    error_summary=error,
                )
            )
            event = await session.get(AiEvent, outbox.event_id)
            report = await session.get(SurveyReport, event.source_event_id) if event else None
            task = await session.get(SurveyTask, report.task_id) if report else None
            if success:
                outbox.status = "delivered"
                outbox.delivered_at = datetime.now(UTC)
                if report:
                    report.status = "delivered"
                if task:
                    task.delivery_status = "delivered"
                    task.state = "completed"
                    task.version += 1
            else:
                outbox.last_error = error
                if outbox.attempt_count >= settings.survey_delivery_max_attempts:
                    outbox.status = "dead_letter"
                    session.add(DeadLetter(id=_identifier("DLQ"), outbox_id=outbox.id, reason=error or "delivery failed"))
                    if report:
                        report.status = "delivery_failed"
                    if task:
                        task.delivery_status = "failed"
                else:
                    outbox.status = "retry"
            await session.commit()
            return True
