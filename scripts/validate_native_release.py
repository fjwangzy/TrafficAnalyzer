#!/usr/bin/env python3
"""Validate an unpacked native release with isolated services derived from root Compose."""

import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--four-process", action="store_true")
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--controller", type=Path)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    project = "native_verify_" + secrets.token_hex(4)
    with tempfile.TemporaryDirectory(
        prefix=project, dir=ROOT / ".runtime"
    ) as temporary:
        work = Path(temporary)
        data = work / "data"
        data.mkdir()
        assets = work / "assets"
        assets.mkdir()
        for name in ("weights", "videos"):
            (assets / name).mkdir()
        for name in (
            "postgres",
            "hls",
            "output",
            "spool",
            "calibration",
            "survey",
            "trajectory-archive",
            "logs",
        ):
            (data / name).mkdir()
        private = {
            "COMPOSE_PROJECT_NAME": project,
            "DATA_ROOT": str(data),
            "ASSET_ROOT": str(assets),
            "ROAD9_PASSWORD": secrets.token_hex(16),
            "JWT_SECRET_KEY": secrets.token_hex(32),
            "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_hex(16),
            "KAFKA_SASL_PASSWORD": secrets.token_hex(16),
            "CORS_ORIGINS": '["http://console2:8080"]',
            "AMAP_JS_API_KEY": "validation",
            "MINEMAP_KEY": "validation",
            "DB_NAME": "ycx_native_validation",
            "DB_SCHEMA": "drone",
            "DB_USER": "sysdba",
            "DB_HOST": "road9",
            "DB_PORT": "5432",
            "DB_TIMESCALE_REQUIRED": "true",
            "PLATFORM_IMAGE": "traffic-analyzer-platform:2026.10.19-intranet.1-arm64",
            "CONSOLE_IMAGE": "traffic-analyzer-console:2026.10.19-intranet.1-arm64",
            "DATABASE_IMAGE": "traffic-analyzer-database:2026.10.19-intranet.1-arm64",
        }
        envfile = work / ".env"
        envfile.write_text("\n".join(k + "=" + v for k, v in private.items()) + "\n")
        envfile.chmod(0o600)
        render = [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(envfile),
            "-p",
            project,
            "-f",
            str(ROOT / "docker-compose.yaml"),
            "-f",
            str(ROOT / "deploy/intranet/compose.yaml"),
            "-f",
            str(ROOT / "deploy/intranet/compose.postgres.yaml"),
            "--profile",
            "bundled-infra",
            "config",
            "--format",
            "json",
        ]
        model = json.loads(subprocess.check_output(render))
        model["services"] = {
            k: v
            for k, v in model["services"].items()
            if k in {"road9", "kafka", "platform", "console2"}
        }
        for service in model["services"].values():
            for key in ("build", "ports", "profiles", "depends_on", "restart"):
                service.pop(key, None)
        kafka = model["services"]["kafka"]
        kafka["environment"]["KAFKA_HEAP_OPTS"] = "-Xmx256m -Xms256m"
        platform = model["services"]["platform"]
        env = platform["environment"]
        env.update(
            KAFKA_BOOTSTRAP="kafka:29092",
            KAFKA_SECURITY_PROTOCOL="PLAINTEXT",
            KAFKA_SASL_USERNAME="",
            KAFKA_SASL_PASSWORD="",
            KAFKA_CONSUMER_GROUP=project,
            KAFKA_REPLAY_V2_CONSUMER_GROUP=project + "_replay",
            YCX_METRICS_BACKEND="doris",
            DORIS_MYSQL_HOST="",
            ROAD_FEATURES_ENABLED="false",
            TRAFFIC_LOG_DIR="/tmp/logs",
            GEOJSON_OUTPUT_DIR="/tmp/output",
            HLS_OUTPUT_DIR="/tmp/hls",
            KAFKA_SPOOL_DIR="/tmp/spool",
            TRAJECTORY_ARCHIVE_SPOOL_DIR="/tmp/archive",
            SURVEY_STORAGE_DIR="/tmp/survey",
            CALIBRATION_DB_PATH="/tmp/calibration/calibration_db.json",
            LANE_ANNOTATION_DB_PATH="/tmp/calibration/lanes.json",
            YOLO_CONFIG_DIR="/tmp/ultralytics",
            MPLCONFIGDIR="/tmp/matplotlib",
            PIPELINE_PYTHON="/native/bin/python3",
            PIPELINE_PROJECT_ROOT="/native/app",
            NATIVE_PACKAGE="/native",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
        )
        env["VERIFY_FOUR_PROCESS"] = (
            "1"
            if args.four_process
            or "event-faithful/v2"
            in json.loads((package / "HOST_RELEASE.json").read_text()).get(
                "sampling_versions", []
            )
            else "0"
        )
        env.pop("LD_PRELOAD", None)
        platform.update(
            image="nginx:1.27-alpine",
            entrypoint=["/native/bin/python3"],
            command=["/checks/native_release_flow.py"],
            read_only=True,
            volumes=[
                {
                    "type": "bind",
                    "source": str(package),
                    "target": "/native",
                    "read_only": True,
                },
                {
                    "type": "bind",
                    "source": str(ROOT / "test"),
                    "target": "/checks",
                    "read_only": True,
                },
            ],
            tmpfs=["/tmp:rw,size=512m", "/native/state:rw,size=16m"],
        )
        if args.app_root:
            platform["volumes"].append(
                {
                    "type": "bind",
                    "source": str(args.app_root.resolve(strict=True)),
                    "target": "/native/app",
                    "read_only": True,
                }
            )
        if args.controller:
            platform["volumes"].append(
                {
                    "type": "bind",
                    "source": str(args.controller.resolve(strict=True)),
                    "target": "/native/native_platform.py",
                    "read_only": True,
                }
            )
        platform.pop("devices", None)
        platform.pop("healthcheck", None)
        # Actual retained Console image and its existing proxy configuration, no test web server.
        if (package / "console/html/index.html").is_file():
            console = model["services"]["console2"]
            console["volumes"] = [
                m
                for m in console.get("volumes", [])
                if not m.get("target", "").startswith("/opt/traffic-console")
            ]
            console["volumes"].append(
                {
                    "type": "bind",
                    "source": str(package / "console"),
                    "target": "/opt/traffic-console",
                    "read_only": True,
                }
            )
            proxy = work / "console-nginx.conf"
            proxy.write_text((package / "console/nginx.conf").read_text())
            proxy.chmod(0o644)
            console["volumes"].append(
                {
                    "type": "bind",
                    "source": str(proxy),
                    "target": "/opt/traffic-console/nginx.conf",
                    "read_only": True,
                }
            )
            console["entrypoint"] = ["/bin/sh", "/opt/traffic-console/entrypoint.sh"]
            console["command"] = []
        composefile = work / "compose.json"
        composefile.write_text(json.dumps(model))
        composefile.chmod(0o600)
        cli = ["docker", "compose", "-p", project, "-f", str(composefile)]
        try:
            command(
                cli
                + [
                    "up",
                    "-d",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "road9",
                    "kafka",
                ]
            )
            command(cli + ["up", "-d", "--pull", "never", "platform", "console2"])
            cid = subprocess.check_output(
                cli + ["ps", "-a", "-q", "platform"], text=True
            ).strip()
            result = subprocess.check_output(
                ["docker", "wait", cid], timeout=360, text=True
            ).strip()
            command(["docker", "logs", cid])
            if result != "0":
                raise RuntimeError(
                    "Native integration validation failed; exit=" + result
                )
        finally:
            command(cli + ["down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    main()
