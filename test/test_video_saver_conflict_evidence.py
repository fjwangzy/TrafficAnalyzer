from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from elements.FrameElement import FrameElement
from nodes.VideoSaverNode import VideoSaverNode
from utils_local.event_evidence import save_conflict_evidence_files


def _jpeg_roundtrip(frame, quality=95):
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    assert ok
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def test_tcc_evidence_uses_show_output_pixels_without_redrawing(tmp_path):
    original = np.zeros((120, 180, 3), dtype=np.uint8)
    original[:, :, 0] = np.arange(180, dtype=np.uint8)
    detector_output = original.copy()
    cv2.rectangle(detector_output, (30, 25), (150, 95), (0, 255, 0), 4)
    cv2.putText(
        detector_output,
        "ACTUAL SHOW OUTPUT",
        (10, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    frame_element = SimpleNamespace(
        frame=original.copy(),
        frame_result=detector_output.copy(),
    )

    descriptors = save_conflict_evidence_files(
        frame_element,
        {"motor_id": 82, "non_motor_id": 3289, "ttc_sec": 0.2},
        storage_root=tmp_path,
        max_width=180,
        jpeg_quality=95,
    )

    detector_descriptor = next(
        item for item in descriptors if item["kind"] == "conflict_detector_frame"
    )
    stored = cv2.imread(str(tmp_path / detector_descriptor["storage_key"]))
    assert np.array_equal(stored, _jpeg_roundtrip(detector_output))
    assert np.array_equal(frame_element.frame_result, detector_output)


def test_video_saver_keeps_existing_detector_conflict_output(tmp_path):
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    cv2.rectangle(frame, (8, 6), (52, 34), (20, 180, 240), 3)
    frame_element = FrameElement("test.mp4", frame, 2.0, 1, {})
    frame_element.frame_result = frame.copy()
    frame_element.conflict_events = [{
        "motor_id": 101,
        "non_motor_id": 202,
        "severity": "critical",
        "ttc_sec": 1.2,
        "evidence_status": "complete",
        "evidence_files": [{
            "kind": "conflict_detector_frame",
            "storage_backend": "managed",
            "storage_key": f"objects/aa/{'a' * 64}",
        }],
    }]
    saver = VideoSaverNode({
        "fps": 24,
        "out_folder": str(tmp_path),
        "save_conflict_clips": True,
    })

    saver.process(frame_element, save_video=False)

    saved = list(Path(tmp_path).glob("conflict_*.jpg"))
    assert len(saved) == 1
    assert np.array_equal(cv2.imread(str(saved[0])), _jpeg_roundtrip(frame))
