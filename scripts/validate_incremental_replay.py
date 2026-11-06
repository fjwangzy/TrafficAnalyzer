#!/usr/bin/env python3
"""Isolated root-Compose PG/Kafka + native synthetic four-worker validation.

Every declared volume is uniquely named. Cleanup removes only manifest-owned,
newly-created volumes with matching Compose labels; never uses down --volumes.
"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    prefix = "traffic_incremental_" + uuid.uuid4().hex[:12]
    env = {
        **os.environ,
        "ROAD9_PASSWORD": secrets.token_hex(20),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_hex(20),
        "CORS_ORIGINS": '["http://localhost:5183"]',
        "AMAP_JS_API_KEY": "isolated-test",
        "ROAD9_PORT": str(port()),
        "KAFKA_HOST_PORT": str(port()),
        "ROAD9_USER": "traffic",
    }
    volume_vars = set(
        re.findall(
            r"\$\{([A-Z0-9_]*VOLUME_NAME)(?::-.*?)?\}",
            (ROOT / "docker-compose.yaml").read_text(),
        )
    )
    names = {key: prefix + "_" + key.lower() for key in volume_vars}
    env.update(names)
    existing = set(
        subprocess.check_output(
            ["docker", "volume", "ls", "--format", "{{.Name}}"], text=True
        ).splitlines()
    )
    assert not existing.intersection(names.values()), "isolated name collision"
    manifest = {
        "project": prefix,
        "volumes": names,
        "ports": {"db": env["ROAD9_PORT"], "kafka": env["KAFKA_HOST_PORT"]},
    }
    (output / "resources.json").write_text(json.dumps(manifest, indent=2))
    compose = [
        "docker",
        "compose",
        "-p",
        prefix,
        "-f",
        str(ROOT / "docker-compose.yaml"),
    ]
    result = {"status": "failed", "project": prefix}
    log = output / "validation.log"
    try:
        with log.open("w") as stream:
            log.chmod(0o600)
            subprocess.run(
                compose
                + ["up", "-d", "--wait", "--wait-timeout", "120", "road9", "kafka"],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=stream,
                check=True,
            )
            env.update(
                DB_HOST="127.0.0.1",
                DB_PORT=env["ROAD9_PORT"],
                DB_USER="traffic",
                DB_PASSWORD=env["ROAD9_PASSWORD"],
                DB_NAME="road9",
                DB_SCHEMA="public",
                DB_DRIVER="asyncpg",
                APP_RUNTIME_PROFILE="replay_v2",
                DEPLOYMENT_MODE="local",
                DB_TIMESCALE_REQUIRED="true",
                ROAD_FEATURES_ENABLED="false",
                PYTHONPATH=str(ROOT / "platform") + os.pathsep + str(ROOT),
                KAFKA_BOOTSTRAP="127.0.0.1:" + env["KAFKA_HOST_PORT"],
                KAFKA_SECURITY_PROTOCOL="PLAINTEXT",
                CAMERA_ID="1",
                TOPIC_NAME="uav_statistics",
                VIDEO_SRC="incremental-fixture",
                GEOJSON_OUTPUT_DIR=str(output / "geojson"),
                KAFKA_TOPIC_PARTITIONS="3",
                KAFKA_TOPIC_REPLICATION_FACTOR="1",
                TRAFFIC_FIXTURE_DIR=str(output),
                KAFKA_SPOOL_DIR=str(output / "spool"),
                TRAJECTORY_ARCHIVE_SPOOL_DIR=str(output / "archive"),
                SURVEY_STORAGE_DIR=str(output / "survey"),
                VIDEO_PORT=str(port()),
                TRAFFIC_SYNTHETIC_VALIDATION="1",
                PIPELINE_EGRESS_ENABLED="true",
                HISTORY_SAMPLING_ENABLED="true",
                TRAJECTORY_STORAGE_PROFILE="replay_v2",
                PIPELINE_ID="pipe-isolated",
                MISSION_ID="MSN-ISOLATED",
                SOURCE_PROFILE_ID="SRC-ISOLATED",
                INTER_ID="INT-ISOLATED",
                INTERSECTION_ID="INT-ISOLATED",
                DEPLOYMENT_ID=prefix,
                OMP_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1",
                VECLIB_MAXIMUM_THREADS="1",
                REPLAY_V2_APPEARANCE_DEVICE="cpu",
            )
            for config in ("alembic.ini", "alembic_replay_v2.ini"):
                subprocess.run(
                    [sys.executable, "-m", "alembic", "-c", config, "upgrade", "head"],
                    cwd=ROOT / "platform",
                    env=env,
                    stdout=stream,
                    stderr=stream,
                    check=True,
                )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/init_fixed_kafka_topics.py"),
                    "--bootstrap",
                    env["KAFKA_BOOTSTRAP"],
                    "--replication-factor",
                    "1",
                ],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=stream,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(ROOT / "test/incremental_replay_integration.py")],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=stream,
                check=True,
                timeout=180,
            )
        result["status"] = "passed"
    finally:
        with log.open("a") as stream:
            subprocess.run(
                compose + ["down"], cwd=ROOT, env=env, stdout=stream, stderr=stream
            )
            # Explicit ownership check, even for our unguessable names.
            for name in names.values():
                inspect = subprocess.run(
                    ["docker", "volume", "inspect", name],
                    capture_output=True,
                    text=True,
                )
                if inspect.returncode:
                    continue
                volume = json.loads(inspect.stdout)[0]
                if (
                    name in existing
                    or (volume.get("Labels") or {}).get("com.docker.compose.project")
                    != prefix
                ):
                    raise RuntimeError("refusing cleanup of unowned volume " + name)
                subprocess.run(
                    ["docker", "volume", "rm", name],
                    stdout=stream,
                    stderr=stream,
                    check=True,
                )
        (output / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == "__main__":
    main()
