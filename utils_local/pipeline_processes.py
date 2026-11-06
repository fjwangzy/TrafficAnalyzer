"""Lifecycle-only helpers for pipeline-owned workers and Linux frame segments."""

import logging
from pathlib import Path
import re
import sys
import time
from multiprocessing import shared_memory

LOG = logging.getLogger("pipeline.lifecycle")


def cleanup_frame_segments(prefix):
    if sys.platform != "linux" or not re.fullmatch(r"uavf_[0-9a-f]{12}_", prefix):
        return
    for path in Path("/dev/shm").glob(prefix + "*"):
        try:
            memory = shared_memory.SharedMemory(name=path.name)
            try:
                memory.unlink()
            finally:
                memory.close()
        except FileNotFoundError:
            pass
    LOG.info("SHM_CLEANUP prefix=%s", prefix)


def stop_workers(processes, prefix, grace_sec=20.0):
    deadline = time.monotonic() + grace_sec
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=max(0.0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.kill()
    for process in processes:
        process.join(timeout=5.0)
    cleanup_frame_segments(prefix)
