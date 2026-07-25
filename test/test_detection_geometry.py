from types import SimpleNamespace

import numpy as np

from elements.FrameElement import FrameElement
from nodes.DetectionNode import DetectionNode
from utils_local.detection_geometry import (
    configure_safe_mps_box_clipping,
    extract_valid_detections,
)


class _TensorLike:
    def __init__(self, value):
        self._value = np.asarray(value)

    def cpu(self):
        return self

    def numpy(self):
        return self._value


def _boxes(xyxy, conf, cls):
    return SimpleNamespace(
        xyxy=_TensorLike(xyxy),
        conf=_TensorLike(conf),
        cls=_TensorLike(cls),
    )


def test_extract_valid_detections_rejects_invalid_geometry_and_keeps_arrays_aligned():
    result = extract_valid_detections(
        _boxes(
            [
                [10.0, 20.0, 30.0, 40.0],
                [100.0, 20.0, 100.0, 40.0],
                [np.nan, 10.0, 20.0, 30.0],
                [-5.0, 5.0, 15.0, 25.0],
            ],
            [0.9, 0.8, 0.7, 0.6],
            [3, 4, 5, 6],
        ),
        class_names={3: "car", 4: "van", 5: "truck", 6: "bus"},
        frame_shape=(80, 120, 3),
    )

    assert result.xyxy == [[10.0, 20.0, 30.0, 40.0], [0.0, 5.0, 15.0, 25.0]]
    assert result.confidences == [0.9, 0.6]
    assert result.class_ids == [3, 6]
    assert result.class_names == ["car", "bus"]
    assert result.diagnostics == {
        "raw_detection_count": 4,
        "valid_detection_count": 2,
        "invalid_geometry_count": 2,
        "invalid_geometry_reasons": {
            "non_finite": 1,
            "non_positive_extent": 1,
        },
    }


def test_extract_valid_detections_rejects_misaligned_model_output():
    result = extract_valid_detections(
        _boxes([[10.0, 20.0, 30.0, 40.0]], [0.9, 0.8], [3]),
        class_names={3: "car"},
        frame_shape=(80, 120, 3),
    )

    assert result.xyxy == []
    assert result.diagnostics["invalid_geometry_count"] == 1
    assert result.diagnostics["invalid_geometry_reasons"] == {
        "unaligned_model_output": 1
    }


def test_configure_safe_mps_box_clipping_disables_in_place_ultralytics_path():
    fake_ops = SimpleNamespace(NOT_MACOS14=True)

    enabled = configure_safe_mps_box_clipping("mps", ops_module=fake_ops)

    assert enabled is True
    assert fake_ops.NOT_MACOS14 is False


def test_configure_safe_mps_box_clipping_leaves_cpu_path_unchanged():
    fake_ops = SimpleNamespace(NOT_MACOS14=True)

    enabled = configure_safe_mps_box_clipping("cpu", ops_module=fake_ops)

    assert enabled is False
    assert fake_ops.NOT_MACOS14 is True


def test_detection_node_publishes_only_valid_rows_and_geometry_diagnostics():
    node = object.__new__(DetectionNode)
    node.model = SimpleNamespace(
        predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=_boxes(
            [[10.0, 20.0, 30.0, 40.0], [120.0, 10.0, 120.0, 30.0]],
            [0.9, 0.8],
            [3, 4],
        ))]
    )
    node.imgsz = 960
    node.conf = 0.05
    node.iou = 0.4
    node.classes_to_detect = [3, 4]
    node.device = "cpu"
    node.half = False
    node.classes = {3: "car", 4: "van"}
    node.yolo_model_id = "test-model"
    node.safe_mps_box_clipping = False
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=0.0,
        frame_num=0,
        roads_info={},
    )

    result = node.process(frame)

    assert result.detected_xyxy == [[10.0, 20.0, 30.0, 40.0]]
    assert result.detected_conf == [0.9]
    assert result.detected_cls_ids == [3]
    assert result.detected_cls == ["car"]
    assert result.detection_diagnostics["invalid_geometry_count"] == 1
    assert result.detection_diagnostics["safe_mps_box_clipping"] is False
