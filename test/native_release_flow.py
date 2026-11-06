"""Run only inside the isolated ARM64 validator; never against a site database."""

import base64
import hashlib
import json
import os
import re
import statistics
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(os.environ["NATIVE_PACKAGE"])
sys.path.insert(0, str(ROOT))


def run(script, *arguments, expected=0, env=None):
    result = subprocess.run(
        [
            str(ROOT / "bin/python3"),
            str(ROOT / "app/deploy/intranet" / script),
            *arguments,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode(errors="replace")
    if result.returncode != expected:
        print(output)
        raise AssertionError((script, result.returncode, expected))
    return output


def request(path, data=None, cookie=None, bearer=None):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(
        "http://console2:8080" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            req, timeout=10
        ) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def websocket(cookie):
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        "GET /ws/realtime HTTP/1.1\r\nHost: console2:8080\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "
        + key
        + "\r\n"
        "Origin: http://console2:8080\r\nCookie: " + cookie + "\r\n\r\n"
    )
    with socket.create_connection(("console2", 8080), timeout=5) as stream:
        stream.sendall(handshake.encode())
        result = b""
        while b"\r\n\r\n" not in result:
            result += stream.recv(4096)
        assert b"101 Switching Protocols" in result, result[:200]
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        )
        assert accept.lower() in result.lower()


def main():
    assert os.environ["DB_NAME"] == "ycx_native_validation", "isolated database only"
    assert "native_verify_" in os.environ["KAFKA_CONSUMER_GROUP"], (
        "isolated consumer group only"
    )
    empty = run("source_check.py", "--database", expected=1)
    assert "MIGRATION" in empty.upper() or "SCHEMA" in empty.upper(), empty[-1000:]
    print("PASS empty database rejected without automatic migration", flush=True)
    run("init_db.py")
    run("source_check.py", "--database")
    print("PASS explicit init-db and both installed heads", flush=True)
    wrong = {**os.environ, "DB_SCHEMA": "missing_schema"}
    run("source_check.py", "--database", expected=1, env=wrong)
    print("PASS wrong schema rejected", flush=True)
    run("init_kafka.py", "--replication-factor", "1")
    print("PASS explicit fixed Topic initialization before readonly preflight", flush=True)
    result = run(
        "runtime_check.py",
        "--connections-only",
        env={**os.environ, "TRAFFIC_NATIVE_OWNER": str(ROOT)},
    )
    assert "KAFKA_ADVERTISED_UNREACHABLE" not in result
    print(
        "PASS private vendor libpq, database identity/permissions and Kafka metadata endpoints",
        flush=True,
    )
    # Exercise the real supervisor and child Uvicorn; only retained-container lookup is stubbed
    # because this minimal tool image intentionally has no Docker CLI/socket.
    Path(os.environ["HLS_OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
    (Path(os.environ["HLS_OUTPUT_DIR"]) / "proxy-check.m3u8").write_text("#EXTM3U\n")
    state = {"environment": dict(os.environ), "bind_address": "0.0.0.0"}
    Path("/native/state/site.json").write_text(json.dumps(state))
    code = 'import sys;sys.path.insert(0,"/native");import json,native_platform as n;n.service=lambda *a,**k:{"State":{"Running":False}};raise SystemExit(n.supervise(json.load(open("/native/state/site.json"))))'
    with open("/tmp/supervisor.log", "w") as log:
        supervisor = subprocess.Popen(
            [str(ROOT / "bin/python3"), "-c", code],
            stdout=log,
            stderr=subprocess.STDOUT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT) + ":" + os.environ["PYTHONPATH"],
            },
        )
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    if request("/ready")[0] == 200:
                        break
                except OSError:
                    pass
                if supervisor.poll() is not None:
                    raise AssertionError(
                        Path("/tmp/supervisor.log").read_text()[-6000:]
                    )
                time.sleep(0.5)
            else:
                raise AssertionError(
                    "proxy /ready timeout: "
                    + Path("/tmp/supervisor.log").read_text()[-6000:]
                )
            assert request("/api/v1/auth/me")[0] == 401
            status, headers, body = request(
                "/api/v1/auth/login",
                {
                    "username": "admin",
                    "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"],
                },
            )
            assert status == 200, body[:300]
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            assert request("/api/v1/auth/media-session", cookie=cookie)[0] == 200
            assert (
                request("/api/v1/auth/me", bearer=json.loads(body)["access_token"])[0]
                == 200
            )
            assert request("/hls/proxy-check.m3u8")[0] == 401
            status, _, media = request("/hls/proxy-check.m3u8", cookie=cookie)
            assert status == 200 and media == b"#EXTM3U\n", (status, media[:100])
            websocket(cookie)
            print(
                "PASS real native Uvicorn /ready, Console API/cookie/media-session/WebSocket proxy",
                flush=True,
            )

            if (ROOT / "console/html/index.html").is_file():
                status, _, served = request("/")
                assert (
                    status == 200
                    and served == (ROOT / "console/html/index.html").read_bytes()
                )
                assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', served.decode())
                assert assets
                for asset in assets:
                    status, _, content = request(asset)
                    assert (
                        status == 200
                        and content
                        == (ROOT / "console/html" / asset.lstrip("/")).read_bytes()
                    )
                print(
                    "PASS bundled current Console HTML and hashed JS/CSS served by retained container",
                    flush=True,
                )
            if os.environ.get("VERIFY_FOUR_PROCESS") == "1":
                env = {
                    **os.environ,
                    "PIPELINE_EGRESS_ENABLED": "true",
                    "HISTORY_SAMPLING_ENABLED": "true",
                    "TRAJECTORY_STORAGE_PROFILE": "replay_v2",
                    "SOURCE_PROFILE_ID": "SRC-VERIFY-FOUR",
                    "MISSION_ID": "MSN-VERIFY-FOUR",
                    "PIPELINE_ID": "pipe-verify-four",
                    "RUN_ID": "pipe-verify-four",
                    "INTERSECTION_ID": "INT-VERIFY",
                    "INTER_ID": "INT-VERIFY",
                    "DRONE_ID": "UAV-VERIFY",
                    "CAMERA_ID": "1",
                    "TOPIC_NAME": "uav_statistics_1",
                    "VIDEO_PORT": "8199",
                    "VIDEO_BIND_HOST": "127.0.0.1",
                    "KAFKA_SPOOL_DIR": "/tmp/four-spool",
                    "TRAJECTORY_ARCHIVE_SPOOL_DIR": "/tmp/four-archive",
                    "GEOJSON_OUTPUT_DIR": "/tmp/four-geo",
                }
                result = subprocess.run(
                    [
                        str(ROOT / "bin/python3"),
                        "/checks/four_process_integration_entry.py",
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                )
                if result.returncode:
                    print(result.stdout.decode(errors="replace")[-12000:])
                    raise AssertionError("real four-process contract fixture failed")
                output = result.stdout.decode(errors="replace")
                assert "EGRESS_COMPLETE" in output and "ARCHIVER_READY" in output
                measured = {}
                for name, elapsed, cpu in re.findall(
                    r"STAGE_END stage=(\S+) elapsed_ms=([0-9.]+) cpu_ms=([0-9.]+)",
                    output,
                ):
                    if name.startswith(("tracker.", "show.", "egress.", "queue.")):
                        measured.setdefault(name, []).append(
                            (float(elapsed), float(cpu))
                        )
                assert all(
                    name in measured
                    for name in (
                        "tracker.info",
                        "tracker.egress_delta",
                        "egress.journal",
                        "egress.seal",
                        "show.render",
                    )
                )
                print(
                    "SYNTHETIC_STAGE_TIMINGS "
                    + json.dumps(
                        {
                            name: {
                                "logged_samples": len(values),
                                "wall_median_ms": statistics.median(
                                    v[0] for v in values
                                ),
                                "cpu_median_ms": statistics.median(
                                    v[1] for v in values
                                ),
                                "wall_max_ms": max(v[0] for v in values),
                            }
                            for name, values in sorted(measured.items())
                        }
                    ),
                    flush=True,
                )
                from app.core.database import engine
                from sqlalchemy import text
                import asyncio

                async def check_ingestion():
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        async with engine.connect() as connection:
                            row = (
                                await connection.execute(
                                    text(
                                        "SELECT status,journey_count,source_point_count,retained_point_count FROM uav_replay_v2_missions WHERE id='MSN-VERIFY-FOUR'"
                                    )
                                )
                            ).one_or_none()
                            count = await connection.scalar(
                                text(
                                    "SELECT count(*) FROM uav_replay_v2_track_events WHERE mission_id='MSN-VERIFY-FOUR'"
                                )
                            )
                            if (
                                row
                                and row[0] == "sealed"
                                and count == row[1]
                                and count > 0
                            ):
                                assert row[2] > row[3] and row[2] >= 90, tuple(row)
                                sampling = await connection.scalar(
                                    text(
                                        "SELECT sampling FROM uav_replay_v2_track_events WHERE mission_id='MSN-VERIFY-FOUR' LIMIT 1"
                                    )
                                )
                                assert (
                                    sampling["algorithm_version"] == "event-faithful/v2"
                                )
                                assert (
                                    sampling["full_sequence_summary"][
                                        "speed_sample_count"
                                    ]
                                    > 0
                                )
                                expected = {
                                    w["window_start"]: w
                                    for w in sampling["full_sequence_summary"][
                                        "windows"
                                    ]
                                }
                                facts = (
                                    await connection.execute(
                                        text(
                                            "SELECT window_start,avg_speed_kmh,p85_speed_kmh FROM uav_replay_v2_intersection_metrics_5min WHERE mission_id='MSN-VERIFY-FOUR'"
                                        )
                                    )
                                ).all()
                                if len(facts) != len(expected):
                                    await asyncio.sleep(0.2)
                                    continue
                                for stamp, average, p85 in facts:
                                    window = expected[stamp.isoformat()]
                                    assert (
                                        abs(
                                            float(average)
                                            - window["sum_milli"]
                                            / window["count"]
                                            / 1000
                                        )
                                        <= 0.000001
                                    )
                                    cumulative = 0
                                    rank = (85 * window["count"] + 99) // 100
                                    for speed, frequency in window["histogram"]:
                                        cumulative += frequency
                                        if cumulative >= rank:
                                            assert float(p85) == speed / 1000
                                            break
                                from utils_local.track_message_codec import unpack_track_message
                                envelopes = [
                                    unpack_track_message(json.loads(path.read_text()))
                                    for path in sorted(Path("/tmp/four-archive/MSN-VERIFY-FOUR/incremental").glob("*.json"))
                                ]
                                assert len(envelopes) == row[1], "incremental segment count differs from committed mission"
                                assert sum(item["data"]["source_point_count"] for item in envelopes) == row[2]
                                assert sum(item["data"]["retained_point_count"] for item in envelopes) == row[3]
                                journeys = [item["data"] for item in envelopes if item["data"]["sampling"] == sampling]
                                assert journeys, "stored summary has no matching immutable archive segment"
                                sealed = {"journeys": journeys}
                                speeds = [
                                    point["speed"]["ema_kmh"]
                                    for point in sealed["journeys"][0]["points"]
                                    if point["speed"]["ema_kmh"] is not None
                                ]
                                total = sum(w["count"] for w in expected.values())
                                full_mean = (
                                    sum(w["sum_milli"] for w in expected.values())
                                    / total
                                    / 1000
                                )
                                assert (
                                    abs(sum(speeds) / len(speeds) - full_mean) > 0.01
                                ), (
                                    "fixture must distinguish full and sampled speed means"
                                )
                                print(
                                    "PASS stored five-minute mean/P85 use full-sequence histograms, not sampled geometry",
                                    flush=True,
                                )
                                print(
                                    "PASS real four-process deltas, compact archive, Kafka and Postgres ingestion counts="
                                    + str(tuple(row[1:])),
                                    flush=True,
                                )
                                return
                        await asyncio.sleep(0.5)
                    async with engine.connect() as connection:
                        errors = (
                            await connection.execute(
                                text(
                                    "SELECT reason_code,reason_detail FROM uav_replay_v2_message_dead_letters"
                                )
                            )
                        ).all()
                        print(
                            "INGEST_DEBUG row="
                            + str(row)
                            + " event_count="
                            + str(count)
                            + " dead_letters="
                            + str(errors),
                            flush=True,
                        )
                    diagnostic = Path("/tmp/logs/containers/platform.log")
                    if diagnostic.exists():
                        print(diagnostic.read_text()[-10000:], flush=True)
                    raise AssertionError(
                        "four-process replay ingestion did not converge"
                    )

                async def verify_and_close():
                    try:
                        await check_ingestion()
                    finally:
                        await engine.dispose()

                asyncio.run(verify_and_close())

            # Create an owned process tree with detached grandchildren to test orphan cleanup.
            detached = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(300)"],start_new_session=True);time.sleep(300)'
            orphan = subprocess.Popen(
                [str(ROOT / "bin/python3"), "-c", detached],
                env={**os.environ, "TRAFFIC_NATIVE_OWNER": str(ROOT)},
                start_new_session=True,
            )
            time.sleep(1)
            orphan.kill()
            orphan.wait()
        finally:
            supervisor.send_signal(signal.SIGTERM)
            supervisor.wait(timeout=45)
            if supervisor.returncode != 0:
                print(Path("/tmp/supervisor.log").read_text()[-6000:])
                raise AssertionError(("supervisor exit", supervisor.returncode))
    import native_platform

    assert not native_platform.owned_children(), "detached worker remains"
    print("PASS graceful supervisor shutdown and detached orphan cleanup", flush=True)
    print("SITE_UOS_NPU_FPS=not_evaluated", flush=True)


if __name__ == "__main__":
    main()
