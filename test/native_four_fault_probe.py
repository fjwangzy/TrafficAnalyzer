"""Force-kill only a fixture-owned fourth worker; verify failure and SHM cleanup."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

assert sys.platform == "linux"
root = Path("/native")
env = {
    **os.environ,
    "DB_NAME": "ycx_native_validation",
    "TRAJECTORY_STORAGE_PROFILE": "replay_v2",
    "PIPELINE_ID": "fault-verify",
    "SOURCE_PROFILE_ID": "SRC-FAULT",
    "MISSION_ID": "MSN-FAULT",
    "VERIFY_NO_KAFKA": "1",
    "KAFKA_SPOOL_DIR": "/tmp/fault-spool",
    "VIDEO_PORT": "8198",
    "PIPELINE_EGRESS_ENABLED": "true",
    "HISTORY_SAMPLING_ENABLED": "true",
}
process = subprocess.Popen(
    [str(root / "bin/python3"), "/checks/four_process_integration_entry.py"],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
lines = []
writer = None
killed = False
try:
    deadline = time.monotonic() + 60
    for line in process.stdout:
        lines.append(line)
        match = re.search(r"ARCHIVER_READY protocol=1 pid=(\d+)", line)
        if match:
            writer = int(match[1])
        if writer and "STAGE_END stage=egress.journal" in line:
            os.kill(writer, signal.SIGKILL)
            killed = True
            break
        if time.monotonic() > deadline:
            raise AssertionError("fixture startup timed out")
    rest, _ = process.communicate(timeout=40)
    lines.append(rest)
    output = "".join(lines)
    print(output)
    assert killed and process.returncode != 0
    assert "EGRESS_COMPLETE" not in output
    prefix = re.search(r"SHM_CLEANUP prefix=(uavf_[0-9a-f]{12}_)", output)
    assert prefix and not list(Path("/dev/shm").glob(prefix[1] + "*"))
    directory = Path("/tmp/fault-spool/fault-verify/egress")
    assert (directory / "pending.packets").stat().st_size > 8
    assert (
        json.loads((directory / "incomplete.json").read_text())["status"]
        == "incomplete"
    )
    assert list(directory.glob("unconfirmed-*.packets")), (
        "unacknowledged sender packets were not retained"
    )
    print(
        "PASS killed writer => failed pipeline, retained durable journal and unconfirmed sender packets, no false EOF success, no owned SHM"
    )
finally:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
