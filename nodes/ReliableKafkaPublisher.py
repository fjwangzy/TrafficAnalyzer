"""Reliable Kafka publishing behind a small ``publish/snapshot/close`` interface.

Completed tracks and real conflicts are business facts.  They are written as
atomic files in a persistent spool before Kafka delivery.  This is deliberately
not a second database: road9 remains the only business database and the
canonical path remains detector -> Kafka -> Platform transaction -> road9.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any

from kafka.codec import has_zstd


logger = logging.getLogger(__name__)


def kafka_compression_type(storage_profile: str) -> str | None:
    """Return the canonical codec and fail before a video-only false runtime starts."""
    if storage_profile != "replay_v2":
        return None
    if not has_zstd():
        raise RuntimeError(
            "Replay V2 Kafka compression requires the 'zstandard' dependency"
        )
    return "zstd"


class ReliableKafkaPublisher:
    """Publish Kafka records without leaking retry/spool complexity to callers."""

    def __init__(
        self,
        producer: Any,
        spool_path: str | Path,
        *,
        queue_size: int = 200,
        delivery_timeout_sec: float = 10.0,
        retry_interval_sec: float = 1.0,
    ) -> None:
        self._producer = producer
        self._spool_dir = Path(spool_path)
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        self._spool_lock = threading.Lock()
        self._transient: Queue[tuple[str, dict]] = Queue(maxsize=queue_size)
        self._delivery_timeout_sec = delivery_timeout_sec
        self._retry_interval_sec = retry_interval_sec
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._metrics_lock = threading.Lock()
        recovered = len(self._pending_files())
        self._expected = recovered
        self._actual = 0
        self._dropped = 0
        self._last_drop_reason: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="reliable_kafka_publisher",
            daemon=True,
        )
        self._thread.start()

    def publish(self, topic: str, payload: dict, *, durable: bool = False) -> str | None:
        """Accept one record; durable records return their spool identifier.

        A durable atomic-file write is part of the interface contract and
        therefore raises on failure. Best-effort queue pressure is measured.
        """
        with self._metrics_lock:
            self._expected += 1
        if durable:
            message_id = str(payload.get("message_id") or uuid.uuid4())
            digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()
            target = self._spool_dir / f"{digest}.json"
            record = {"id": message_id, "topic": topic, "payload": payload}
            encoded = json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            temporary = self._spool_dir / f".{digest}.{uuid.uuid4().hex}.tmp"
            try:
                with self._spool_lock:
                    if not target.exists():
                        with temporary.open("xb") as handle:
                            handle.write(encoded)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, target)
            except OSError:
                temporary.unlink(missing_ok=True)
                logger.exception("durable Kafka spool write failed")
                raise
            self._wake.set()
            return message_id

        try:
            self._transient.put_nowait((topic, payload))
            self._wake.set()
        except Full:
            self._record_drop("best_effort_queue_full")
        return None

    def snapshot(self) -> dict[str, Any]:
        """Return delivery measurements suitable for persisted stats facts."""
        with self._metrics_lock:
            expected, actual, dropped = self._expected, self._actual, self._dropped
            drop_reason = self._last_drop_reason
        pending = len(self._pending_files())
        coverage = actual / expected if expected else 1.0
        return {
            "expected_samples": expected,
            "actual_samples": actual,
            "dropped_samples": dropped,
            "coverage_ratio": round(coverage, 6),
            "drop_reason": drop_reason,
            "durable_pending": pending,
        }

    def close(self, timeout_sec: float = 10.0) -> dict[str, Any]:
        """Stop the worker after a bounded drain and return its final snapshot."""
        deadline = time.monotonic() + max(timeout_sec, 0.0)
        while time.monotonic() < deadline:
            if self._transient.empty() and not self._pending_files():
                break
            self._wake.set()
            time.sleep(0.05)
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=max(deadline - time.monotonic(), 0.1))
        try:
            self._producer.flush(timeout=max(timeout_sec, 0.1))
        except Exception:
            logger.warning("Kafka producer flush failed during close", exc_info=True)
        return self.snapshot()

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._deliver_durable():
                continue
            try:
                topic, payload = self._transient.get_nowait()
            except Empty:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            try:
                self._send(topic, payload)
                self._record_actual()
            except Exception as exc:
                logger.warning("best-effort Kafka delivery failed: %s", exc)
                self._record_drop("best_effort_delivery_failed")

    def _deliver_durable(self) -> bool:
        pending = self._pending_files()
        if not pending:
            return False
        path = pending[0]
        try:
            with path.open("r", encoding="utf-8") as handle:
                record = json.load(handle)
            self._send(record["topic"], record["payload"])
            with self._spool_lock:
                path.unlink(missing_ok=True)
            self._record_actual()
        except Exception as exc:
            logger.warning("durable Kafka delivery deferred: %s", exc)
            self._wake.wait(timeout=self._retry_interval_sec)
            self._wake.clear()
        return True

    def _pending_files(self) -> list[Path]:
        with self._spool_lock:
            return sorted(self._spool_dir.glob("*.json"), key=lambda path: (path.stat().st_mtime_ns, path.name))

    def _send(self, topic: str, payload: dict) -> None:
        future = self._producer.send(topic, value=payload)
        if hasattr(future, "get"):
            future.get(timeout=self._delivery_timeout_sec)

    def _record_actual(self) -> None:
        with self._metrics_lock:
            self._actual += 1

    def _record_drop(self, reason: str) -> None:
        with self._metrics_lock:
            self._dropped += 1
            self._last_drop_reason = reason
