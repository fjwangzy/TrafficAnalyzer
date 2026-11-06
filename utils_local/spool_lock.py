"""Bounded POSIX lock shards shared by the publisher and resident recovery."""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path


@contextmanager
def spool_lock(root, name):
    # Fixed 256 shards avoid a new lock inode for every completed trajectory.
    directory = Path(root) / ".delivery-locks"
    directory.mkdir(mode=0o700, exist_ok=True)
    shard = hashlib.sha256(name.encode()).hexdigest()[:2]
    fd = os.open(directory / (shard + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
