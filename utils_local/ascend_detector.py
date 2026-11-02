"""Static YOLO11 OM inference through CANN pyACL; imported only for Ascend."""

from __future__ import annotations

import atexit
from types import SimpleNamespace

import cv2
import numpy as np

from utils_local.ascend_model_manifest import load_manifest, sha256
from utils_local.runtime_logging import run_stage, stage


def letterbox(frame, size):
    height, width = frame.shape[:2]
    ratio = min(size / height, size / width)
    resized = (round(width * ratio), round(height * ratio))
    dw, dh = (size - resized[0]) / 2, (size - resized[1]) / 2
    image = cv2.resize(frame, resized, interpolation=cv2.INTER_LINEAR)
    image = cv2.copyMakeBorder(
        image, round(dh - 0.1), round(dh + 0.1), round(dw - 0.1), round(dw + 0.1),
        cv2.BORDER_CONSTANT, value=(114, 114, 114),
    )
    image = np.ascontiguousarray(image[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32)
    image /= 255.0
    return image, ratio, (dw, dh)


def check(ret, operation):
    if ret != 0:
        raise RuntimeError(f"Ascend {operation} failed (code={ret})")


class AclModel:
    def __init__(self, acl, path, size, class_count):
        self.acl = acl
        self.model_id = None
        self.desc = None
        self.datasets = []
        self.allocations = []
        try:
            with stage("ascend.om_load", imgsz=size):
                model_id, ret = acl.mdl.load_from_file(str(path))
            check(ret, "load model")
            self.model_id = model_id
            self.desc = acl.mdl.create_desc()
            if self.desc is None:
                raise RuntimeError("Ascend failed to allocate a model descriptor")
            check(acl.mdl.get_desc(self.desc, self.model_id), "describe model")
            if acl.mdl.get_num_inputs(self.desc) != 1 or acl.mdl.get_num_outputs(self.desc) != 1:
                raise ValueError("Expected a single-input/single-output YOLO11 OM")
            dims, ret = acl.mdl.get_input_dims(self.desc, 0)
            check(ret, "input dimensions")
            if list(dims["dims"]) != [1, 3, size, size] or acl.mdl.get_input_data_type(self.desc, 0) != 0:
                raise ValueError("OM input must be static float32 NCHW")
            dims, ret = acl.mdl.get_output_dims(self.desc, 0)
            check(ret, "output dimensions")
            self.output_shape = tuple(dims["dims"])
            if (len(self.output_shape) != 3 or self.output_shape[0] != 1
                    or self.output_shape[1] != 4 + class_count):
                raise ValueError("OM output must be YOLO11 [1,4+classes,anchors], without NMS")
            dtype = acl.mdl.get_output_data_type(self.desc, 0)
            if dtype not in {0, 1}:
                raise ValueError("OM output must be float32 or float16")
            self.output_dtype = np.float32 if dtype == 0 else np.float16
            for nbytes in (
                acl.mdl.get_input_size_by_index(self.desc, 0),
                acl.mdl.get_output_size_by_index(self.desc, 0),
            ):
                dataset = acl.mdl.create_dataset()
                if dataset is None:
                    raise RuntimeError("Ascend failed to create a dataset")
                self.datasets.append(dataset)
                pointer, ret = acl.rt.malloc(nbytes, 2)
                check(ret, "allocate device memory")
                self.allocations.append((pointer, nbytes, None))
                buffer = acl.create_data_buffer(pointer, nbytes)
                if buffer is None:
                    raise RuntimeError("Ascend failed to create a data buffer")
                self.allocations[-1] = (pointer, nbytes, buffer)
                _, ret = acl.mdl.add_dataset_buffer(dataset, buffer)
                check(ret, "attach data buffer")
        except Exception:
            self.close()
            raise

    def infer(self, image):
        acl = self.acl
        pointer, size, _ = self.allocations[0]
        if image.nbytes != size:
            raise ValueError("OM input byte size mismatch")
        with stage("ascend.copy_input", bytes=image.nbytes):
            check(acl.rt.memcpy(pointer, size, image.ctypes.data, image.nbytes, 1), "copy input")
        with stage("ascend.om_execute", input_shape=image.shape):
            check(acl.mdl.execute(self.model_id, *self.datasets), "execute")
        pointer, size, _ = self.allocations[1]
        output = np.empty(self.output_shape, dtype=self.output_dtype)
        if output.nbytes != size:
            raise ValueError("OM output byte size mismatch")
        with stage("ascend.copy_output", bytes=output.nbytes):
            check(acl.rt.memcpy(output.ctypes.data, output.nbytes, pointer, size, 2), "copy output")
        return output.astype(np.float32, copy=False)

    def close(self):
        for dataset in self.datasets:
            self.acl.mdl.destroy_dataset(dataset)
        self.datasets.clear()
        for pointer, _, buffer in self.allocations:
            if buffer is not None:
                self.acl.destroy_data_buffer(buffer)
            self.acl.rt.free(pointer)
        self.allocations.clear()
        if self.desc is not None:
            self.acl.mdl.destroy_desc(self.desc)
            self.desc = None
        if self.model_id is not None:
            self.acl.mdl.unload(self.model_id)
            self.model_id = None


class AscendDetector:
    def __init__(self, manifest_path, device_id=0):
        self.manifest, self.root = run_stage("ascend.manifest_validate", load_manifest, manifest_path)
        self.names = {int(k): v for k, v in self.manifest["names"].items()}
        if sorted(self.names) != list(range(len(self.names))):
            raise ValueError("Model class ids must be contiguous from zero")
        import acl
        self.acl = acl
        self.device_id = device_id
        self.models = {}
        self.context = None
        self.initialized = False
        self.device_set = False
        try:
            check(run_stage("ascend.acl_init", acl.init), "initialize")
            self.initialized = True
            check(run_stage("ascend.set_device", acl.rt.set_device, device_id), "set device")
            self.device_set = True
            self.context, ret = run_stage("ascend.create_context", acl.rt.create_context, device_id)
            check(ret, "create context")
            # Load every tier before reporting a task as running.
            for size in (640, 960, 1280):
                with stage("ascend.model_initialize", imgsz=size, device_id=device_id):
                    self.models[size] = AclModel(
                        acl, self.root / self.manifest["models"][str(size)]["path"], size, len(self.names),
                    )
        except Exception:
            self.close()
            raise
        atexit.register(self.close)

    def predict(self, frame, *, imgsz, conf, iou, classes, **_):
        import torch
        from ultralytics.utils.nms import non_max_suppression

        if imgsz not in self.models:
            raise ValueError(f"No Ascend model for input size {imgsz}")
        with stage("ascend.preprocess", imgsz=imgsz, frame_shape=frame.shape):
            image, ratio, (dw, dh) = letterbox(frame, imgsz)
        output = run_stage("ascend.infer", self.models[imgsz].infer, image)
        if not np.isfinite(output).all():
            raise RuntimeError("Non-finite Ascend model output")
        with stage("ascend.cpu_nms", output_shape=output.shape, confidence=conf, iou=iou):
            rows = non_max_suppression(
                torch.from_numpy(output), conf_thres=conf, iou_thres=iou,
                classes=classes, agnostic=False, nc=len(self.names),
            )[0]
        rows[:, [0, 2]] = (rows[:, [0, 2]] - dw) / ratio
        rows[:, [1, 3]] = (rows[:, [1, 3]] - dh) / ratio
        return [SimpleNamespace(boxes=SimpleNamespace(xyxy=rows[:, :4], conf=rows[:, 4], cls=rows[:, 5]))]

    def close(self):
        for model in self.models.values():
            model.close()
        self.models.clear()
        if self.context is not None:
            self.acl.rt.destroy_context(self.context)
            self.context = None
        if self.device_set:
            self.acl.rt.reset_device(self.device_id)
            self.device_set = False
        if self.initialized:
            self.acl.finalize()
            self.initialized = False
