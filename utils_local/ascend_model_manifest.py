"""Standard-library validation shared by build hosts and the detector runtime."""

import hashlib
import json
import re
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != "uav.ascend-model/v1":
        raise ValueError("Unsupported Ascend model manifest")
    if manifest.get("cann_version") != "9.0.0" or manifest.get("soc_version") != "Ascend310P3":
        raise ValueError("Ascend models must target CANN 9.0.0 / Ascend310P3")
    if manifest.get("input_dtype") != "float32" or not isinstance(manifest.get("names"), dict) or not manifest["names"]:
        raise ValueError("Ascend model requires float32 NCHW input and class names")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("source_sha256", "")):
        raise ValueError("Ascend model manifest requires its source weight SHA-256")
    for size in (640, 960, 1280):
        item = manifest["models"][str(size)]
        model_path = (path.parent / item["path"]).resolve()
        if not model_path.is_relative_to(path.parent) or not model_path.is_file():
            raise ValueError(f"Missing or unsafe Ascend model path for {size}")
        if sha256(model_path) != item["sha256"]:
            raise ValueError(f"Ascend model checksum mismatch for {size}")
    return manifest, path.parent
