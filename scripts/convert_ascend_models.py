#!/usr/bin/env python3
"""Prepare separately delivered YOLO11 OM resources using CANN 9.0.0 ATC."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils_local.ascend_model_manifest import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    weights = args.weights.resolve(strict=True)
    if weights.suffix != ".pt" or not shutil.which("atc"):
        raise RuntimeError("Local .pt weights and CANN 9.0.0 atc are required")
    if not Path("/usr/local/Ascend/cann-9.0.0").is_dir():
        raise RuntimeError("Use the pinned CANN 9.0.0 model conversion environment")
    import ultralytics
    import torch
    import onnx
    from ultralytics import YOLO
    torch.set_num_threads(1)
    os.environ.setdefault("TE_PARALLEL_COMPILER", "1")
    os.environ.setdefault("MAX_COMPILE_CORE_NUMBER", "1")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    if any(args.output.iterdir()):
        raise FileExistsError("Use a new output directory; do not overwrite an existing resource release")
    manifest = {
        "schema_version": "uav.ascend-model/v1", "cann_version": "9.0.0",
        "soc_version": "Ascend310P3", "input_dtype": "float32",
        "source_name": weights.name, "source_sha256": sha256(weights),
        "ultralytics_version": ultralytics.__version__, "torch_version": torch.__version__,
        "onnx_version": onnx.__version__, "models": {},
        "compiler_environment": {name: os.environ[name] for name in ("TE_PARALLEL_COMPILER", "MAX_COMPILE_CORE_NUMBER")},
    }
    with tempfile.TemporaryDirectory(prefix="traffic-ascend-export-") as temporary:
        source = Path(temporary) / weights.name
        shutil.copy2(weights, source)
        model = YOLO(str(source), task="detect")
        manifest["names"] = model.names
        for size in (640, 960, 1280):
            exported = Path(model.export(format="onnx", imgsz=size, batch=1, dynamic=False,
                                        simplify=False, opset=13, nms=False, device="cpu", half=False))
            onnx = (args.output / f"yolo11-{size}.onnx").resolve()
            shutil.copy2(exported, onnx)
            import onnx as onnx_module
            graph = onnx_module.load(str(onnx))
            input_name = graph.graph.input[0].name
            output_base = (args.output / f"yolo11-{size}").resolve()
            command = ["atc", "--framework=5", f"--model={onnx}", f"--output={output_base}",
                       "--soc_version=Ascend310P3", "--input_format=NCHW",
                       f"--input_shape={input_name}:1,3,{size},{size}", "--output_type=FP32"]
            subprocess.run(command, check=True)
            om = output_base.with_suffix(".om")
            manifest["models"][str(size)] = {
                "path": om.name, "sha256": sha256(om), "onnx_path": onnx.name,
                "onnx_sha256": sha256(onnx), "atc_arguments": command[1:],
            }
    temporary_manifest = args.output / "manifest.json.tmp"
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary_manifest, manifest_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
