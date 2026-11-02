import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from utils_local.ascend_detector import AscendDetector, AclModel, letterbox, load_manifest


def test_manifest_checks_all_tiers_and_rejects_corruption(tmp_path):
    models = {}
    for size in (640, 960, 1280):
        file = tmp_path / f"{size}.om"
        file.write_bytes(f"model-{size}".encode())
        models[str(size)] = {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    manifest = {"schema_version": "uav.ascend-model/v1", "cann_version": "9.0.0",
                "soc_version": "Ascend310P3", "input_dtype": "float32", "source_sha256": "a" * 64,
                "names": {"0": "car"}, "models": models}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert load_manifest(path)[0]["soc_version"] == "Ascend310P3"
    (tmp_path / "1280.om").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_manifest(path)


def test_letterbox_and_postprocess_restore_original_non_square_coordinates():
    image, ratio, padding = letterbox(np.zeros((320, 640, 3), np.uint8), 640)
    assert image.shape == (1, 3, 640, 640)
    assert ratio == 1 and padding == (0, 160)
    output = np.zeros((1, 5, 2), dtype=np.float32)
    output[0, :4, :] = np.array([[200, 200], [260, 260], [100, 100], [100, 100]])
    output[0, 4, :] = [0.9, 0.8]
    detector = AscendDetector.__new__(AscendDetector)
    detector.names = {0: "car"}
    detector.models = {640: SimpleNamespace(infer=lambda _: output)}
    boxes = detector.predict(np.zeros((320, 640, 3), np.uint8), imgsz=640, conf=0.05, iou=0.4, classes=[0])[0].boxes
    assert boxes.xyxy.tolist() == [[150, 50, 250, 150]]
    assert boxes.cls.tolist() == [0]
    with pytest.raises(ValueError, match="No Ascend model"):
        detector.predict(np.zeros((320, 640, 3), np.uint8), imgsz=800, conf=0.05, iou=0.4, classes=None)


def test_acl_partial_allocation_failure_releases_created_resources():
    events = []
    mdl = SimpleNamespace(
        load_from_file=lambda _: (1, 0), create_desc=lambda: 2, get_desc=lambda *_: 0,
        get_num_inputs=lambda _: 1, get_num_outputs=lambda _: 1,
        get_input_dims=lambda *_: ({"dims": [1, 3, 640, 640]}, 0),
        get_input_data_type=lambda *_: 0,
        get_output_dims=lambda *_: ({"dims": [1, 5, 8400]}, 0), get_output_data_type=lambda *_: 0,
        get_input_size_by_index=lambda *_: 16, get_output_size_by_index=lambda *_: 16,
        create_dataset=lambda: 3, destroy_dataset=lambda _: events.append("dataset"),
        destroy_desc=lambda _: events.append("descriptor"), unload=lambda _: events.append("model"),
    )
    acl = SimpleNamespace(mdl=mdl, rt=SimpleNamespace(malloc=lambda *_: (0, 7)))
    with pytest.raises(RuntimeError, match="allocate device memory"):
        AclModel(acl, "test.om", 640, 1)
    assert events == ["dataset", "descriptor", "model"]


def test_explicit_ascend_model_failure_never_falls_back_to_cpu_yolo(tmp_path, monkeypatch):
    import importlib
    detection = importlib.import_module('nodes.DetectionNode')
    weight = tmp_path / 'model.pt'
    weight.write_bytes(b'fixture')
    monkeypatch.setenv('ASCEND_MODEL_MANIFEST', str(tmp_path / 'manifest.json'))
    calls = []

    def unavailable(*_args):
        raise RuntimeError('Ascend fixture model load failed')

    monkeypatch.setattr('utils_local.ascend_detector.AscendDetector', unavailable)
    monkeypatch.setattr(detection, 'YOLO', lambda *_args, **_kwargs: calls.append('cpu'))
    with pytest.raises(RuntimeError, match='Ascend fixture model load failed'):
        detection.DetectionNode({'detection_node': {'device': 'ascend', 'weight_pth': str(weight)}})
    assert calls == []
