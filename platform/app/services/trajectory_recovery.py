"""Resident, bounded replay of durable facts lacking a database commit receipt."""

import asyncio
import json
import logging
import os
from pathlib import Path

from aiokafka import AIOKafkaProducer
from sqlalchemy import select

from app.models.replay_v2 import ReplayV2IngestReceipt
from app.services.replay_v2_metric_store import _hash

LOG = logging.getLogger(__name__)


class TrajectoryRecoveryService:
    def __init__(self, session_maker, bootstrap, security):
        self.sessions = session_maker
        self.bootstrap, self.security = bootstrap, security
        self.producer = AIOKafkaProducer(bootstrap_servers=bootstrap, **security)
        self.task = None
        self.root = Path(os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool"))

    async def start(self):
        self.task = asyncio.create_task(self.run(), name="trajectory-recovery")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.producer.stop()

    async def run(self):
        while True:
            try:
                from utils_local.kafka_topic_preflight import check_fixed_topics

                await asyncio.to_thread(check_fixed_topics, self.bootstrap, self.security)
                await self.producer.start()
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.warning("TRAJECTORY_RECOVERY_CONNECT_WAIT", exc_info=True)
                await asyncio.sleep(5)
        while True:
            try:
                await self.publish_receipts()
                # Scandir iterators do not retain every completed trajectory in RAM.
                for pipeline in self.root.iterdir() if self.root.exists() else ():
                    if not pipeline.is_dir():
                        continue
                    for subdir in (pipeline, pipeline / "awaiting-receipt"):
                        if not subdir.exists():
                            continue
                        batch = 0
                        for path in subdir.glob("*.json"):
                            try:
                                await self.reconcile(path)
                            except FileNotFoundError:
                                continue
                            except (ValueError, KeyError, TypeError):
                                destination = pipeline / "quarantine"
                                destination.mkdir(exist_ok=True)
                                try:
                                    await asyncio.to_thread(
                                        os.replace, path, destination / path.name
                                    )
                                except FileNotFoundError:
                                    pass
                                LOG.exception("TRAJECTORY_SPOOL_INVALID file=%s", path.name)
                            batch += 1
                            if batch % 32 == 0:
                                await asyncio.sleep(0.1)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.warning("TRAJECTORY_RECOVERY_DEFERRED", exc_info=True)
                await asyncio.sleep(5)

    async def publish_receipts(self):
        async with self.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(ReplayV2IngestReceipt)
                        .where(ReplayV2IngestReceipt.status == "pending")
                        .with_for_update(skip_locked=True)
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                payload = {
                    "msg_type": "uav_ingest_receipt",
                    "schema_version": "uav_ingest_receipt/v1",
                    "deployment_id": row.deployment_id,
                    "message_id": row.message_id,
                    "message_hash": row.message_hash,
                    "status": "db_committed",
                    "committed_at": row.committed_at.isoformat(),
                }
                await self.producer.send_and_wait(
                    "uav_ingest_receipts",
                    json.dumps(payload).encode(),
                    key=row.deployment_id.encode(),
                )
                row.status = "published"
            await session.commit()

    async def reconcile(self, path):
        from utils_local.spool_lock import spool_lock

        root = path.parent.parent if path.parent.name == "awaiting-receipt" else path.parent
        with spool_lock(root, path.name) as acquired:
            if acquired:
                await self._reconcile_locked(path)

    async def _reconcile_locked(self, path):
        record = json.loads(await asyncio.to_thread(path.read_text))
        payload = record.get("payload") or {}
        if payload.get("transport_version") != "uav-fixed/v2":
            return
        if payload.get("msg_type") not in {
            "uav_track_complete",
            "uav_track_chunk",
            "uav_track_relation",
            "uav_replay_mission",
        }:
            return
        from utils_local.message_identity import validate_payload
        from utils_local.replay_topics import FIXED_TOPICS

        validate_payload(payload)
        expected = (
            "uav_track_complete"
            if payload["msg_type"] == "uav_track_chunk"
            else FIXED_TOPICS[payload["msg_type"]]
        )
        if record.get("id") != payload.get("message_id") or record.get("topic") != expected:
            raise ValueError("durable trajectory routing/identity conflict")
        # The resident service takes ownership only after P4's broker ACK rename.
        if path.parent.name != "awaiting-receipt":
            import time

            if time.time() - path.stat().st_mtime < 10:
                return
            # Immutable retries may race the live publisher; DB identity handles this.
            await self.producer.send_and_wait(
                record["topic"],
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
                key=str(
                    (payload.get("data") or {}).get("mission_id") or payload.get("camera_id")
                ).encode(),
            )
            waiting = path.parent / "awaiting-receipt"
            waiting.mkdir(exist_ok=True)
            try:
                await asyncio.to_thread(os.replace, path, waiting / path.name)
            except FileNotFoundError:
                pass
            return
        digest = _hash(payload)
        async with self.sessions() as session:
            receipt = await session.get(ReplayV2IngestReceipt, payload["message_id"])
            if receipt:
                if receipt.status == "quarantined":
                    quarantine = path.parent.parent / "quarantine"
                    quarantine.mkdir(exist_ok=True)
                    await asyncio.to_thread(os.replace, path, quarantine / path.name)
                    LOG.error("TRAJECTORY_CONTRACT_QUARANTINED id=%s", payload["message_id"])
                    return
                if receipt.status not in {"pending", "published"}:
                    LOG.warning(
                        "TRAJECTORY_RECEIPT_NOT_COMMITTED id=%s status=%s",
                        payload["message_id"],
                        receipt.status,
                    )
                    return
                if receipt.message_hash != digest or receipt.deployment_id != payload.get(
                    "deployment_id", "local"
                ):
                    quarantine = path.parent.parent / "quarantine"
                    quarantine.mkdir(exist_ok=True)
                    await asyncio.to_thread(os.replace, path, quarantine / path.name)
                    LOG.error("TRAJECTORY_IDENTITY_QUARANTINED id=%s", payload["message_id"])
                    return
                await asyncio.to_thread(path.unlink, missing_ok=True)
                return
        # Immutable retry; broker delivery never substitutes for a database ACK.
        data = payload.get("data") or {}
        await self.producer.send_and_wait(
            record["topic"],
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            key=str(data.get("mission_id") or payload.get("camera_id")).encode(),
        )
