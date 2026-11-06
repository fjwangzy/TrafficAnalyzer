#!/usr/bin/env python3
"""Hardware-independent native runtime check; no business messages or database writes."""

import json
import multiprocessing as mp
from multiprocessing import shared_memory
import os
from pathlib import Path
import subprocess
import sys


def worker(queue, name):
    import numpy as np

    memory = shared_memory.SharedMemory(name=name)
    try:
        queue.put(
            {
                "python": sys.executable,
                "affinity": sorted(os.sched_getaffinity(0))
                if hasattr(os, "sched_getaffinity")
                else None,
                "value": int(np.ndarray((1,), dtype="int64", buffer=memory.buf)[0]),
            }
        )
    finally:
        memory.close()


def main():
    import numpy as np
    import scipy
    import torch
    import cv2
    import cython_bbox  # noqa: F401 - deliberately verify native module loading
    import lap  # noqa: F401 - deliberately verify native module loading
    import main_optimized  # noqa: F401 - deliberately verify native module loading
    import app.main  # noqa: F401 - deliberately verify native module loading
    import psycopg

    root = Path(__file__).resolve().parent
    worker_count = int(
        json.loads((root / "HOST_RELEASE.json").read_text()).get("pipeline_workers", 3)
    )
    memory = shared_memory.SharedMemory(create=True, size=8)
    np.ndarray((1,), dtype="int64", buffer=memory.buf)[0] = 314159
    children = []
    try:
        contexts = ["spawn"] + (["fork"] if sys.platform == "linux" else [])
        parent_affinity = (
            sorted(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else None
        )
        for method in contexts:
            context = mp.get_context(method)
            queue = context.Queue()
            group = []
            for _ in range(worker_count):
                child = context.Process(target=worker, args=(queue, memory.name))
                child.start()
                children.append(child)
                group.append(child)
            try:
                records = [queue.get(timeout=45) for _ in group]
                for child in group:
                    child.join(timeout=10)
                    assert child.exitcode == 0, child.exitcode
                assert all(
                    r["value"] == 314159 and r["python"] == sys.executable
                    for r in records
                ), records
                assert all(r["affinity"] == parent_affinity for r in records), (
                    method,
                    parent_affinity,
                    records,
                )
            finally:
                queue.close()
                queue.join_thread()
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        memory.close()
        memory.unlink()
    root = Path(__file__).resolve().parent
    for tool in ("ffmpeg", "ffprobe"):
        subprocess.run(
            [str(root / "bin" / tool), "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    subprocess.run(
        [sys.executable, "-c", 'import numpy,torch; print("NATIVE_CHILD_OK")'],
        check=True,
    )
    print(
        json.dumps(
            {
                "result": "passed",
                "spawn_workers": worker_count,
                "fork_workers": worker_count if sys.platform == "linux" else 0,
                "affinity_preserved": True,
                "shared_memory": "passed",
                "python": sys.version,
                "executable": sys.executable,
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "torch": torch.__version__,
                "opencv": cv2.__version__,
                "libpq": psycopg.pq.version(),
                "npu": "not_evaluated",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
