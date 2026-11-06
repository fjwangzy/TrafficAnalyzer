"""Runtime reuse retains image/migration gates and never aliases writable files."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from build_host_platform import copy_verified_runtime


def package(tmp_path):
    source = tmp_path/"old"
    (source/"runtime").mkdir(parents=True)
    (source/"runtime/lib").write_bytes(b"immutable runtime")
    baseline = {"requirements": b"original"}
    image = {"id": "sha256:fixture"}
    (source/"HOST_RELEASE.json").write_text(json.dumps({"runtime_image": image, "runtime_baseline": {"requirements": hashlib.sha256(b"original").hexdigest()}}))
    (source/"SHA256SUMS").write_text(hashlib.sha256(b"immutable runtime").hexdigest()+"  runtime/lib\n")
    return source, image, baseline


def test_copy_is_independent(tmp_path):
    source, image, baseline = package(tmp_path)
    target = tmp_path/"new"
    assert copy_verified_runtime(source, target, image, baseline)["runtime_files_verified"] == 1
    (target/"lib").write_bytes(b"changed new file")
    assert (source/"runtime/lib").read_bytes() == b"immutable runtime"


@pytest.mark.parametrize("change", ["image", "baseline", "bytes", "extra", "symlink"])
def test_reuse_rejects_inconsistent_runtime(tmp_path, change):
    source, image, baseline = package(tmp_path)
    if change == "image":
        image = {"id": "different"}
    elif change == "baseline":
        baseline["requirements"] = b"different"
    elif change == "bytes":
        (source/"runtime/lib").write_bytes(b"corrupt")
    elif change == "extra":
        (source/"runtime/extra").write_bytes(b"unlisted")
    else:
        outside = tmp_path/"outside"
        outside.mkdir()
        (source/"runtime/escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        copy_verified_runtime(source, tmp_path/"new", image, baseline)
