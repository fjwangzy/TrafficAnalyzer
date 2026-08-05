import cv2
import numpy as np
from unittest.mock import patch

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from nodes.TccEvidencePublisherNode import TccEvidencePublisherNode


class RecordingPublisher:
    def __init__(self):
        self.records = []
        self.closed = False

    def publish(self, topic, payload, *, durable=False):
        self.records.append((topic, payload, durable))

    def close(self):
        self.closed = True
        return {"durable_pending": 0}


def _config():
    return {
        "kafka_producer_node": {
            "camera_id": 7,
            "bootstrap_servers": ["unused:9092"],
            "send_queue_size": 20,
        },
        "video_saver_node": {"conflict_jpeg_quality": 95},
    }


def _jpeg_roundtrip(frame):
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 95],
    )
    assert ok
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def test_publishes_tcc_only_after_saving_exact_show_output(tmp_path):
    original = np.zeros((120, 180, 3), dtype=np.uint8)
    original[:, :, 0] = np.arange(180, dtype=np.uint8)
    detector_output = original.copy()
    cv2.rectangle(detector_output, (30, 25), (150, 95), (0, 255, 0), 4)
    frame_element = FrameElement("fixture.mp4", original.copy(), 2.0, 1, {})
    frame_element.frame_result = detector_output.copy()
    frame_element.conflict_events = [{
        "motor_id": 82,
        "non_motor_id": 3289,
        "severity": "critical",
        "ttc_sec": 0.2,
    }]
    frame_element.pending_tcc_envelopes = [{
        "message_id": "conflict-output-1",
        "msg_type": "uav_conflict",
        "data": {"motor_id": 82, "non_motor_id": 3289},
    }]
    publisher = RecordingPublisher()
    node = TccEvidencePublisherNode(
        _config(),
        publisher=publisher,
        storage_root=tmp_path,
    )

    node.process(frame_element)

    assert len(publisher.records) == 1
    topic, envelope, durable = publisher.records[0]
    assert topic == "uav_conflicts_7"
    assert durable is True
    assert envelope["data"]["evidence_status"] == "complete"
    assert [item["kind"] for item in envelope["data"]["evidence_files"]] == [
        "conflict_original_frame",
        "conflict_detector_frame",
    ]
    detector = envelope["data"]["evidence_files"][1]
    stored = cv2.imread(str(tmp_path / detector["storage_key"]))
    assert np.array_equal(stored, _jpeg_roundtrip(detector_output))
    assert np.array_equal(frame_element.frame_result, detector_output)


def test_replay_v2_tcc_uses_shadow_conflict_topic(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAJECTORY_STORAGE_PROFILE", "replay_v2")
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-REPLAY-1")

    node = TccEvidencePublisherNode(
        _config(),
        publisher=RecordingPublisher(),
        storage_root=tmp_path,
    )

    assert node.conflicts_topic == "uav_replay_v2_conflicts_SRC-REPLAY-1"


def test_publishes_incomplete_tcc_when_event_output_write_fails(tmp_path):
    frame_element = FrameElement(
        "fixture.mp4",
        np.zeros((20, 20, 3), dtype=np.uint8),
        2.0,
        1,
        {},
    )
    frame_element.frame_result = frame_element.frame.copy()
    frame_element.pending_tcc_envelopes = [{
        "message_id": "conflict-output-failed",
        "msg_type": "uav_conflict",
        "data": {"motor_id": 82, "non_motor_id": 3289},
    }]
    publisher = RecordingPublisher()
    node = TccEvidencePublisherNode(
        _config(),
        publisher=publisher,
        storage_root=tmp_path,
    )

    with patch(
        "nodes.TccEvidencePublisherNode.save_conflict_evidence_files",
        side_effect=OSError("read-only evidence root"),
    ):
        node.process(frame_element)

    _, envelope, durable = publisher.records[0]
    assert durable is True
    assert envelope["data"]["evidence_status"] == "incomplete"
    assert envelope["data"]["evidence_error"] == "local_write_failed"
    assert "evidence_files" not in envelope["data"]


def test_closes_publisher_on_eof(tmp_path):
    publisher = RecordingPublisher()
    node = TccEvidencePublisherNode(
        _config(),
        publisher=publisher,
        storage_root=tmp_path,
    )

    sentinel = VideoEndBreakElement("fixture.mp4", 2.0)
    assert node.process(sentinel) is sentinel
    assert publisher.closed is True
