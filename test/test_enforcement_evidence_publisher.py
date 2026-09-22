import tempfile

import numpy as np

from elements.FrameElement import FrameElement
from nodes.EnforcementEvidencePublisherNode import EnforcementEvidencePublisherNode


class _Publisher:
    def __init__(self):
        self.published = []

    def publish(self, topic, value, durable):
        self.published.append((topic, value, durable))

    def close(self):
        return None


def test_publishes_only_after_managed_source_and_detector_frames_exist():
    frame = FrameElement("test", np.zeros((12, 16, 3), dtype=np.uint8), 1.0, 1, {})
    frame.frame_result = np.full((12, 16, 3), 255, dtype=np.uint8)
    frame.pending_enforcement_envelopes = [{"data": {"source_event_id": "event-1"}}]
    publisher = _Publisher()
    with tempfile.TemporaryDirectory() as root:
        node = EnforcementEvidencePublisherNode(
            {"kafka_producer_node": {"camera_id": 1}, "video_saver_node": {}},
            publisher=publisher, storage_root=root,
        )
        node.process(frame)

    topic, envelope, durable = publisher.published[0]
    assert topic == "uav_enforcement_clues_1"
    assert durable is True
    assert envelope["data"]["evidence_status"] == "complete"
    assert [item["kind"] for item in envelope["data"]["evidence_files"]] == [
        "enforcement_original_frame", "enforcement_detector_frame",
    ]
