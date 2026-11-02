"""Publish enforcement facts only after an actual source/output frame is saved."""

from __future__ import annotations

import logging
import os
import re
from json import dumps

from kafka import KafkaProducer
from utils_local.kafka_security import kafka_security_options

from elements.VideoEndBreakElement import VideoEndBreakElement
from nodes.KafkaProducerNode import KafkaProducerNode
from nodes.ReliableKafkaPublisher import ReliableKafkaPublisher, kafka_compression_type
from utils_local.event_evidence import save_event_evidence_files

logger = logging.getLogger(__name__)


class EnforcementEvidencePublisherNode:
    def __init__(self, config: dict, *, publisher=None, storage_root=None) -> None:
        kafka_config = config["kafka_producer_node"]
        camera_id = kafka_config["camera_id"]
        profile = os.environ.get("TRAJECTORY_STORAGE_PROFILE", "live")
        source_profile_id = os.environ.get("SOURCE_PROFILE_ID")
        self.topic = KafkaProducerNode._enforcement_topic_for_profile(profile, source_profile_id, camera_id)
        self.storage_root = storage_root or os.environ.get("SURVEY_STORAGE_DIR", ".runtime/survey")
        self.jpeg_quality = int(config.get("video_saver_node", {}).get("conflict_jpeg_quality", 95))
        if publisher is not None:
            self.publisher = publisher
            return
        producer = KafkaProducer(
            bootstrap_servers=kafka_config["bootstrap_servers"],
            **kafka_security_options(),
            value_serializer=lambda value: dumps(value).encode("utf-8"), retries=3,
            request_timeout_ms=5000, compression_type=kafka_compression_type(profile),
        )
        pipeline_id = os.environ.get("PIPELINE_ID")
        spool_name = re.sub(r"[^A-Za-z0-9_.-]", "_", pipeline_id or f"camera-{camera_id}")
        self.publisher = ReliableKafkaPublisher(
            producer, os.path.join(os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool"), f"{spool_name}-enforcement-evidence"),
            queue_size=int(kafka_config.get("send_queue_size", 200)),
        )

    def process(self, frame_element):
        if isinstance(frame_element, VideoEndBreakElement):
            self.publisher.close()
            return frame_element
        pending = list(getattr(frame_element, "pending_enforcement_envelopes", None) or [])
        if not pending:
            return frame_element
        try:
            evidence_files = save_event_evidence_files(
                frame_element, ("enforcement_original_frame", "enforcement_detector_frame"),
                storage_root=self.storage_root, jpeg_quality=self.jpeg_quality,
            )
        except (OSError, ValueError) as exc:
            evidence_files = []
            logger.warning("enforcement evidence save failed: %s", exc)
        for envelope in pending:
            data = envelope["data"]
            if evidence_files:
                data["evidence_files"] = evidence_files
                data["evidence_status"] = "complete"
            else:
                data["evidence_status"] = "incomplete"
                data["evidence_error"] = "event_output_missing"
            self.publisher.publish(self.topic, envelope, durable=True)
        frame_element.pending_enforcement_envelopes = []
        return frame_element
