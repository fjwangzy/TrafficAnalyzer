"""Publish TCC events only after their actual ShowNode frame exists."""

from __future__ import annotations

import logging
import os
import re
from json import dumps

from kafka import KafkaProducer

from elements.VideoEndBreakElement import VideoEndBreakElement
from nodes.KafkaProducerNode import KafkaProducerNode
from nodes.ReliableKafkaPublisher import ReliableKafkaPublisher
from utils_local.event_evidence import save_conflict_evidence_files


logger = logging.getLogger(__name__)


class TccEvidencePublisherNode:
    """Persist exact event-output pixels and publish the deferred TCC facts."""

    def __init__(self, config: dict, *, publisher=None, storage_root=None) -> None:
        kafka_config = config["kafka_producer_node"]
        camera_id = kafka_config["camera_id"]
        self.conflicts_topic = KafkaProducerNode._canonical_topics(camera_id)[2]
        self.storage_root = storage_root or os.environ.get(
            "SURVEY_STORAGE_DIR", ".runtime/survey"
        )
        self.jpeg_quality = int(
            config.get("video_saver_node", {}).get("conflict_jpeg_quality", 95)
        )
        if publisher is not None:
            self.publisher = publisher
            return

        producer = KafkaProducer(
            bootstrap_servers=kafka_config["bootstrap_servers"],
            value_serializer=lambda value: dumps(value).encode("utf-8"),
            retries=3,
            request_timeout_ms=5000,
        )
        pipeline_id = os.environ.get("PIPELINE_ID")
        spool_name = re.sub(
            r"[^A-Za-z0-9_.-]",
            "_",
            pipeline_id or f"camera-{camera_id}",
        )
        spool_dir = os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool")
        self.publisher = ReliableKafkaPublisher(
            producer,
            os.path.join(spool_dir, f"{spool_name}-tcc-evidence"),
            queue_size=int(kafka_config.get("send_queue_size", 200)),
        )

    def process(self, frame_element):
        if isinstance(frame_element, VideoEndBreakElement):
            final_delivery = self.publisher.close()
            logger.info("TCC evidence publisher closed: %s", final_delivery)
            return frame_element

        pending = list(
            getattr(frame_element, "pending_tcc_envelopes", None) or []
        )
        if not pending:
            return frame_element

        evidence_files = None
        evidence_error = None
        try:
            evidence_files = save_conflict_evidence_files(
                frame_element,
                storage_root=self.storage_root,
                max_width=None,
                jpeg_quality=self.jpeg_quality,
            )
            if not evidence_files:
                evidence_error = "event_output_missing"
        except (OSError, ValueError) as exc:
            evidence_error = "local_write_failed"
            logger.warning("TCC event-output evidence save failed: %s", exc)

        events = list(getattr(frame_element, "conflict_events", None) or [])
        for index, envelope in enumerate(pending):
            data = envelope.setdefault("data", {})
            event = events[index] if index < len(events) else None
            if evidence_files:
                data["evidence_files"] = evidence_files
                data["evidence_status"] = "complete"
                data.pop("evidence_error", None)
                if event is not None:
                    event["evidence_files"] = evidence_files
                    event["evidence_status"] = "complete"
                    event.pop("evidence_error", None)
            else:
                data.pop("evidence_files", None)
                data["evidence_status"] = "incomplete"
                data["evidence_error"] = evidence_error or "event_output_missing"
                if event is not None:
                    event.pop("evidence_files", None)
                    event["evidence_status"] = "incomplete"
                    event["evidence_error"] = data["evidence_error"]
            self.publisher.publish(
                self.conflicts_topic,
                envelope,
                durable=True,
            )
            logger.info(
                "KAFKA enqueued conflict after Show output: severity=%s topic=%s",
                data.get("severity"),
                self.conflicts_topic,
            )

        frame_element.pending_tcc_envelopes = []
        return frame_element

