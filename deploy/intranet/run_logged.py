#!/usr/bin/env python3
"""Keep container output in bounded host logs as well as Docker stdout."""

import logging
import os
from pathlib import Path
import signal
import subprocess
import sys


def main():
    from utils_local.runtime_logging import RuntimeFormatter, log_level_from_text, rotating_log_handler

    arguments = sys.argv[1:]
    if len(arguments) < 2 or arguments[0] not in {"platform", "init-db", "init-kafka", "preflight", "source-check"}:
        raise SystemExit("Expected platform/init-db/init-kafka/preflight/source-check and a command")
    name, *command = arguments
    directory = Path(os.environ.get("TRAFFIC_LOG_DIR", "/var/log/traffic-analyzer")) / "containers"
    directory.mkdir(parents=True, exist_ok=True)
    handler = rotating_log_handler(directory / f"{name}.log")
    logger = logging.getLogger("container-output")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(RuntimeFormatter())
    logger.addHandler(console)
    logger.info("CONTAINER_START name=%s executable=%s", name, command[0])
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", bufsize=1, start_new_session=True,
                                   env={**os.environ, "PYTHONUNBUFFERED": "1"})
    except Exception:
        logger.exception("CONTAINER_LAUNCH_FAILED name=%s", name)
        handler.close()
        return 1

    def forward(signum, _frame):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, forward)
    try:
        level = logging.INFO
        for line in process.stdout:
            level = log_level_from_text(line, level)
            logger.log(level, "%s", line.rstrip("\n"))
        code = process.wait()
        logger.log(logging.ERROR if code else logging.INFO, "CONTAINER_EXIT name=%s exit_code=%s", name, code)
        return code if code >= 0 else 128 - code
    finally:
        handler.close()


if __name__ == "__main__":
    sys.exit(main())
