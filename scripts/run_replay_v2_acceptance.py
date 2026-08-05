#!/usr/bin/env python3
"""Run sealed-Mission Replay V2 acceptance without touching live control-plane state."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid
from urllib.parse import urlencode

BOOTSTRAP_V2_PYTHON_DEPS = Path(
    os.environ.get("REPLAY_V2_PYTHON_DEPS", "/private/tmp/traffic-analyzer-replay-v2-python")
)
if BOOTSTRAP_V2_PYTHON_DEPS.is_dir():
    sys.path.insert(0, str(BOOTSTRAP_V2_PYTHON_DEPS))

from kafka import KafkaConsumer, TopicPartition
from kafka.admin import ConfigResource, ConfigResourceType, KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = ROOT / "platform"
for path in (ROOT, PLATFORM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_native_mps_replays import (  # noqa: E402
    PlatformClient,
    _write_json,
    hydra_string,
    source_catalog,
    telemetry_overrides,
    terminate_process_tree,
    validate_source_assets,
    validate_source_time_stride,
    verify_native_mps,
    video_fps,
)
from nodes.KafkaProducerNode import KafkaProducerNode  # noqa: E402
from utils_local.replay_topics import build_replay_v2_topics  # noqa: E402


DEFAULT_SOURCES = (
    "SRC-INTER-XQH-0403-PM",
    "SRC-MP4NEW-HY-0625-AM",
    "SRC-MP4NEW-LS-0625-AM",
    "SRC-MP4NEW-CH-0625-AM",
    "SRC-MP4729-JS-0729-3MS",
)
V2_PYTHON_DEPS = BOOTSTRAP_V2_PYTHON_DEPS


def build_v2_run_identity(source_profile_id: str, *, nonce: str | None = None) -> dict:
    token = nonce or uuid.uuid4().hex[:12]
    topics = build_replay_v2_topics(source_profile_id)
    return {
        "mission_id": f"MSN-RV2-{token}",
        "pipeline_id": f"pipe-rv2-{token}",
        "run_id": f"run-rv2-{token}",
        "topics": [
            topics.statistics,
            topics.track_complete,
            topics.conflicts,
            topics.telemetry,
            topics.mission,
        ],
    }


def parse_args() -> argparse.Namespace:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="repeat to select SourceProfiles")
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--username", default=os.environ.get("PLATFORM_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("PLATFORM_PASSWORD", "admin123"))
    parser.add_argument("--kafka-bootstrap", default="127.0.0.1:9092")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--drain-seconds", type=float, default=8.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(f"/private/tmp/traffic-analyzer-replay-v2-{timestamp}"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def ensure_topics(bootstrap: str, topic_names: list[str]) -> list[str]:
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="replay-v2-acceptance")
    try:
        local_retention = {
            "retention.ms": "21600000",
            "retention.bytes": "268435456",
            "cleanup.policy": "delete",
        }
        existing = set(admin.list_topics())
        missing = [name for name in topic_names if name not in existing]
        if missing:
            try:
                admin.create_topics(
                    [
                        NewTopic(
                            name=name,
                            num_partitions=1,
                            replication_factor=1,
                            topic_configs=local_retention,
                        )
                        for name in missing
                    ],
                    validate_only=False,
                )
            except TopicAlreadyExistsError:
                pass
        admin.alter_configs(
            [
                ConfigResource(
                    ConfigResourceType.TOPIC,
                    name,
                    configs=local_retention,
                )
                for name in topic_names
            ]
        )
        return missing
    finally:
        admin.close()


def topic_end_offsets(bootstrap: str, topic_names: list[str]) -> dict[str, dict[int, int]]:
    """Snapshot only existing topics so a guard never auto-creates canonical names."""

    admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="replay-v2-topic-guard")
    try:
        existing = set(admin.list_topics())
    finally:
        admin.close()
    selected = [name for name in topic_names if name in existing]
    if not selected:
        return {}
    consumer = KafkaConsumer(
        bootstrap_servers=bootstrap,
        enable_auto_commit=False,
        consumer_timeout_ms=1000,
    )
    try:
        result = {}
        for name in selected:
            partitions = consumer.partitions_for_topic(name) or set()
            topic_partitions = [TopicPartition(name, partition) for partition in partitions]
            offsets = consumer.end_offsets(topic_partitions) if topic_partitions else {}
            result[name] = {
                partition.partition: int(offset)
                for partition, offset in offsets.items()
            }
        return result
    finally:
        consumer.close()


def capture_message(buckets: dict[str, list[dict]], message, pipeline_id: str) -> bool:
    payload = message.value
    if not isinstance(payload, dict):
        return False
    data = payload.get("data") or {}
    if data.get("pipeline_id") != pipeline_id:
        return False
    bucket = {
        "uav_stats": "stats",
        "uav_track_complete": "tracks",
        "uav_conflict": "conflicts",
        "uav_telemetry": "telemetry",
        "uav_replay_mission": "missions",
    }.get(payload.get("msg_type"))
    if bucket is None:
        return False
    buckets[bucket].append(payload)
    return True


def aggregate_gate(actual: dict, *, require_road_grains: bool) -> dict:
    """Evaluate the sealed Mission's actual/typical DWS convergence."""

    required = ["intersection_5min", "typical_5min_mm"]
    if require_road_grains:
        required.extend(["link_5min", "lane_5min", "turn_5min"])
    missing = [key for key in required if int(actual.get(key) or 0) <= 0]
    return {
        "passed": not missing,
        "required": required,
        "missing": missing,
        "counts": {key: int(actual.get(key) or 0) for key in required},
    }


async def replay_v2_counts(mission_id: str) -> dict:
    from sqlalchemy import func, select

    from app.core.database import async_session_maker, close_db
    from app.models.replay_v2 import (
        ReplayV2ConflictEvent,
        ReplayV2InterEvaluation5MinMM,
        ReplayV2IntersectionMetric5Min,
        ReplayV2LaneMetric5Min,
        ReplayV2LinkMetric5Min,
        ReplayV2Mission,
        ReplayV2TelemetryMetric,
        ReplayV2TrackEvent,
        ReplayV2TrafficMetricSample,
        ReplayV2TurnMetric5Min,
    )

    try:
        async with async_session_maker() as session:
            mission = await session.scalar(
                select(ReplayV2Mission).where(ReplayV2Mission.id == mission_id)
            )
            counts = {}
            for key, model in (
                ("stats", ReplayV2TrafficMetricSample),
                ("tracks", ReplayV2TrackEvent),
                ("conflicts", ReplayV2ConflictEvent),
                ("telemetry", ReplayV2TelemetryMetric),
            ):
                counts[key] = int(
                    (
                        await session.execute(
                            select(func.count()).select_from(model).where(model.mission_id == mission_id)
                        )
                    ).scalar_one()
                )
            counts["missions"] = 1 if mission is not None else 0
            counts["mission_status"] = mission.status if mission is not None else None
            for key, model in (
                ("intersection_5min", ReplayV2IntersectionMetric5Min),
                ("link_5min", ReplayV2LinkMetric5Min),
                ("lane_5min", ReplayV2LaneMetric5Min),
                ("turn_5min", ReplayV2TurnMetric5Min),
            ):
                counts[key] = int(
                    await session.scalar(
                        select(func.count()).select_from(model).where(
                            model.mission_id == mission_id
                        )
                    )
                    or 0
                )
            counts["typical_5min_mm"] = int(
                await session.scalar(
                    select(func.count()).select_from(ReplayV2InterEvaluation5MinMM).where(
                        ReplayV2InterEvaluation5MinMM.source_profile_id
                        == (mission.source_profile_id if mission is not None else "")
                    )
                )
                or 0
            )
            return counts
    finally:
        await close_db()


async def wait_for_reconciliation(
    mission_id: str,
    expected: dict[str, int],
    *,
    require_road_grains: bool = False,
) -> dict:
    deadline = time.monotonic() + 90.0
    actual = await replay_v2_counts(mission_id)
    while time.monotonic() < deadline:
        if (
            all(actual.get(key) == value for key, value in expected.items())
            and actual.get("mission_status") == "sealed"
            and aggregate_gate(actual, require_road_grains=require_road_grains)["passed"]
        ):
            break
        await asyncio.sleep(1.0)
        actual = await replay_v2_counts(mission_id)
    mismatches = {
        key: {"kafka": value, "road9": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if actual.get("mission_status") != "sealed":
        mismatches["mission_status"] = {"expected": "sealed", "actual": actual.get("mission_status")}
    return {"kafka": expected, "road9": actual, "mismatches": mismatches, "matched": not mismatches}


async def storage_snapshot() -> dict:
    """Measure the isolated and canonical namespaces without reading table rows."""

    from sqlalchemy import text

    from app.core.database import async_session_maker, close_db

    relation_query = text(
        """
        SELECT
          COALESCE(SUM(pg_total_relation_size(c.oid)) FILTER (
            WHERE c.relname LIKE 'uav_replay_v2_%'
          ), 0)::bigint AS replay_v2_bytes,
          COALESCE(SUM(pg_total_relation_size(c.oid)) FILTER (
            WHERE c.relname LIKE 'uav_%'
              AND c.relname NOT LIKE 'uav_replay_v2_%'
          ), 0)::bigint AS canonical_uav_bytes,
          pg_database_size(current_database())::bigint AS database_bytes,
          (SELECT COUNT(*) FROM uav_message_inbox)::bigint AS canonical_inbox_rows,
          (SELECT COUNT(*) FROM uav_track_events)::bigint AS canonical_track_event_rows,
          (SELECT COUNT(*) FROM uav_track_points)::bigint AS canonical_track_point_rows,
          (SELECT COUNT(*) FROM uav_telemetry_metrics)::bigint AS canonical_telemetry_rows,
          (SELECT COUNT(*) FROM uav_traffic_metrics)::bigint AS canonical_traffic_metric_rows,
          (SELECT COUNT(*) FROM uav_conflict_events)::bigint AS canonical_conflict_rows,
          (SELECT COUNT(*) FROM uav_conflict_events WHERE pipeline_id LIKE 'pipe-rv2-%')::bigint
            AS misrouted_replay_v2_conflict_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """
    )
    try:
        async with async_session_maker() as session:
            row = (await session.execute(relation_query)).mappings().one()
            return {key: int(value) for key, value in row.items()}
    finally:
        await close_db()


def _message_size_summary(values: list[dict]) -> dict:
    sizes = [
        len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for value in values
    ]
    if not sizes:
        return {"count": 0, "total_bytes": 0, "median_bytes": None, "p95_bytes": None, "max_bytes": None}
    ordered = sorted(sizes)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "count": len(sizes),
        "total_bytes": sum(sizes),
        "median_bytes": round(statistics.median(sizes), 1),
        "p95_bytes": ordered[p95_index],
        "max_bytes": max(sizes),
    }


def collect_acceptance_metrics(
    client: PlatformClient,
    results: list[dict],
    *,
    output_dir: Path,
    kafka_bootstrap: str,
) -> dict:
    message_sizes: dict[str, list[dict]] = {
        key: [] for key in ("stats", "tracks", "conflicts", "telemetry", "missions")
    }
    replay_query_ms = []
    for result in results:
        source_dir = output_dir / result["source_profile_id"]
        for key in message_sizes:
            path = source_dir / f"{key}.json"
            if path.is_file():
                message_sizes[key].extend(json.loads(path.read_text(encoding="utf-8")))
        query = urlencode(
            {
                "mission_id": result["mission_id"],
                "cursor_sec": 0,
                "window_sec": 30,
                "max_points": 20000,
            }
        )
        for _ in range(3):
            started = time.perf_counter()
            client.request("GET", f"/api/v1/trajectories/{result['inter_id']}/replay?{query}")
            replay_query_ms.append((time.perf_counter() - started) * 1000.0)
    admin = KafkaAdminClient(bootstrap_servers=kafka_bootstrap, client_id="replay-v2-inventory")
    try:
        topics = sorted(admin.list_topics())
    finally:
        admin.close()
    query_ordered = sorted(replay_query_ms)
    reserved_canonical_topics = {
        topic
        for index in range(1, len(DEFAULT_SOURCES) + 1)
        for topic in KafkaProducerNode._canonical_topics(18100 + index)
    }
    return {
        "storage": asyncio.run(storage_snapshot()),
        "message_sizes": {
            key: _message_size_summary(values) for key, values in message_sizes.items()
        },
        "replay_query_latency_ms": {
            "samples": len(query_ordered),
            "median": round(statistics.median(query_ordered), 3) if query_ordered else None,
            "p95": round(query_ordered[min(len(query_ordered) - 1, int(round(0.95 * (len(query_ordered) - 1))))], 3)
            if query_ordered
            else None,
            "max": round(max(query_ordered), 3) if query_ordered else None,
        },
        "topics": {
            "total": len(topics),
            "replay_v2": len([topic for topic in topics if topic.startswith("uav_replay_v2_")]),
            "replay_v2_names": [topic for topic in topics if topic.startswith("uav_replay_v2_")],
            "reserved_canonical_names_present": sorted(
                topic for topic in topics if topic in reserved_canonical_topics
            ),
        },
    }


def validate_archived_tracks(tracks: list[dict]) -> dict:
    alignment_failures = 0
    gap_boundary_count = 0
    source_points = 0
    retained_points = 0
    for envelope in tracks:
        data = envelope.get("data") or {}
        points = data.get("points") or []
        source_points += int(data.get("source_point_count") or 0)
        retained_points += len(points)
        if int(data.get("retained_point_count") or -1) != len(points):
            alignment_failures += 1
        for point in points:
            required = {"offset_ms", "frame_num", "pixel", "enu_m", "gcj02", "speed", "quality"}
            if not required <= set(point):
                alignment_failures += 1
            gap_boundary_count += sum(
                "gap" in str(value) for value in point.get("sampling_boundary") or []
            )
    return {
        "alignment_failures": alignment_failures,
        "source_point_count": source_points,
        "retained_point_count": retained_points,
        "gap_boundary_count": gap_boundary_count,
    }


def run_source(
    client: PlatformClient,
    source: dict,
    *,
    index: int,
    output_dir: Path,
    kafka_bootstrap: str,
    frame_stride: int,
    imgsz: int,
    drain_seconds: float,
) -> dict:
    identity = build_v2_run_identity(source["profile_id"])
    mission_id = identity["mission_id"]
    pipeline_id = identity["pipeline_id"]
    source_dir = output_dir / source["profile_id"]
    source_dir.mkdir(parents=True, exist_ok=True)
    camera_id = 18100 + index
    canonical_topics = list(KafkaProducerNode._canonical_topics(camera_id))
    canonical_before = topic_end_offsets(kafka_bootstrap, canonical_topics)
    created_topics = ensure_topics(kafka_bootstrap, identity["topics"])
    runtime_bundle = client.runtime_bundle(source, required=False)
    consumer = KafkaConsumer(
        *identity["topics"],
        bootstrap_servers=kafka_bootstrap,
        group_id=f"replay-v2-acceptance-{uuid.uuid4().hex}",
        enable_auto_commit=False,
        auto_offset_reset="latest",
        consumer_timeout_ms=1000,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
    )
    deadline = time.monotonic() + 20.0
    while not consumer.assignment() and time.monotonic() < deadline:
        consumer.poll(timeout_ms=500)
    if not consumer.assignment():
        consumer.close()
        raise RuntimeError(f"Kafka topic assignment timed out for {source['profile_id']}")
    consumer.seek_to_end(*consumer.assignment())

    main_assets = Path("/Users/yaoyao/ai/TrafficAnalyzer")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(V2_PYTHON_DEPS), value]
        if (value := env.get("PYTHONPATH"))
        else [str(V2_PYTHON_DEPS)]
    )
    env.update(
        {
            "VIDEO_SRC": str((ROOT / source["video"]).resolve()),
            "CAMERA_ID": str(camera_id),
            "VIDEO_PORT": str(camera_id),
            "KAFKA_BOOTSTRAP": kafka_bootstrap,
            "DRONE_ID": source["drone_id"],
            "INTERSECTION_ID": source["inter_id"],
            "INTER_ID": source["inter_id"],
            "MISSION_ID": mission_id,
            "PIPELINE_ID": pipeline_id,
            "RUN_ID": identity["run_id"],
            "SOURCE_PROFILE_ID": source["profile_id"],
            "TRAJECTORY_STORAGE_PROFILE": "replay_v2",
            "TRAJECTORY_ARCHIVE_SPOOL_DIR": str(output_dir / "spool"),
            "KAFKA_SPOOL_DIR": str(output_dir / "kafka-spool"),
            "SURVEY_STORAGE_DIR": os.environ.get(
                "REPLAY_V2_SURVEY_STORAGE_DIR",
                "/private/tmp/traffic-analyzer-replay-v2-survey",
            ),
            "REPLAY_V2_APPEARANCE_MODEL_PATH": str(main_assets / "weights/yolo11s-visdrone.pt"),
            "REPLAY_V2_APPEARANCE_BATCH_SIZE": "128",
            "REPLAY_V2_APPEARANCE_DEVICE": "mps",
            "REPLAY_V2_APPEARANCE_IMGSZ": "160",
            "ROAD_DATA_VERSION": runtime_bundle["road_data_version"] if runtime_bundle else "",
            "ROAD_CONTEXT_STATUS": "lane_verified" if runtime_bundle else "missing",
            "QUALITY_STATUS": "verified" if runtime_bundle else "degraded",
            "TRACKING_PROFILE": "hover_cruise_v1",
            "FRAME_STRIDE": str(frame_stride),
            "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        }
    )
    if runtime_bundle:
        env["RUNTIME_MAP_BUNDLE_JSON"] = json.dumps(runtime_bundle, ensure_ascii=False, separators=(",", ":"))
    else:
        env.pop("RUNTIME_MAP_BUNDLE_JSON", None)
    command = [
        sys.executable,
        str(ROOT / "main_optimized.py"),
        "hydra/job_logging=disabled",
        "pipeline.show_in_web=false",
        "pipeline.save_video=false",
        "pipeline.send_info_kafka=true",
        "video_saver_node.save_conflict_clips=false",
        "kafka_producer_node.hover_annotation_snapshot_enabled=false",
        "detection_node.device=mps",
        f"detection_node.imgsz={imgsz}",
        "detection_node.adaptive_imgsz.enabled=false",
        f"detection_node.weight_pth={hydra_string(str(main_assets / 'weights/yolo11s-visdrone.pt'))}",
        "tracking_profile=hover_cruise_v1",
    ]
    command.extend(telemetry_overrides(source))
    buckets = {key: [] for key in ("stats", "tracks", "conflicts", "telemetry", "missions")}
    process = None
    started = time.monotonic()
    error = None
    try:
        with (source_dir / "pipeline.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            while process.poll() is None:
                for messages in consumer.poll(timeout_ms=1000, max_records=1000).values():
                    for message in messages:
                        capture_message(buckets, message, pipeline_id)
            quiet_deadline = time.monotonic() + drain_seconds
            while time.monotonic() < quiet_deadline:
                matched = False
                for messages in consumer.poll(timeout_ms=500, max_records=1000).values():
                    for message in messages:
                        matched = capture_message(buckets, message, pipeline_id) or matched
                if matched:
                    quiet_deadline = time.monotonic() + drain_seconds
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        terminate_process_tree(process)
        consumer.close()

    expected = {key: len(buckets[key]) for key in buckets}
    reconciliation = asyncio.run(
        wait_for_reconciliation(
            mission_id,
            expected,
            require_road_grains=bool(runtime_bundle),
        )
    )
    aggregate_validation = aggregate_gate(
        reconciliation["road9"],
        require_road_grains=bool(runtime_bundle),
    )
    track_validation = validate_archived_tracks(buckets["tracks"])
    mission_status = (
        (buckets["missions"][-1].get("data") or {}).get("status")
        if buckets["missions"]
        else None
    )
    stats_have_no_tails = all(
        not any(
            key in (item.get("data") or {})
            for key in ("active_trajectories", "candidate_trajectories", "trajectory_px", "trajectory_gcj02")
        )
        for item in buckets["stats"]
    )
    canonical_after = topic_end_offsets(kafka_bootstrap, canonical_topics)
    canonical_topic_writes = {
        topic: {"before": canonical_before.get(topic), "after": offsets}
        for topic, offsets in canonical_after.items()
        if canonical_before.get(topic) != offsets
    }
    result = {
        **identity,
        "source_profile_id": source["profile_id"],
        "inter_id": source["inter_id"],
        "video": str((ROOT / source["video"]).resolve()),
        "frame_stride": frame_stride,
        "imgsz": imgsz,
        "return_code": process.returncode if process is not None else None,
        "natural_eof": bool(process is not None and process.returncode == 0),
        "elapsed_sec": round(time.monotonic() - started, 3),
        "created_topics": created_topics,
        "message_counts": expected,
        "mission_status": mission_status,
        "stats_have_no_trajectory_tails": stats_have_no_tails,
        "canonical_topic_writes": canonical_topic_writes,
        "track_validation": track_validation,
        "reconciliation": reconciliation,
        "aggregate_validation": aggregate_validation,
        "error": error,
    }
    result["passed"] = bool(
        result["natural_eof"]
        and error is None
        and expected["stats"] > 0
        and expected["tracks"] > 0
        and expected["missions"] == 1
        and mission_status == "sealed"
        and stats_have_no_tails
        and not canonical_topic_writes
        and track_validation["alignment_failures"] == 0
        and reconciliation["matched"]
        and aggregate_validation["passed"]
    )
    for key, values in buckets.items():
        _write_json(source_dir / f"{key}.json", values)
    _write_json(source_dir / "result.json", result)
    return result


def main() -> int:
    args = parse_args()
    catalog = source_catalog()
    selected = args.source or list(DEFAULT_SOURCES)
    unknown = [item for item in selected if item not in catalog]
    if unknown:
        raise SystemExit(f"unknown source profile(s): {', '.join(unknown)}")
    if args.frame_stride < 1:
        raise SystemExit("--frame-stride must be >= 1")
    if not args.skip_preflight:
        verify_native_mps()
    digest_cache = {}
    for profile_id in selected:
        source = catalog[profile_id]
        validate_source_assets(source, digest_cache)
        validate_source_time_stride(args.frame_stride, video_fps(ROOT / source["video"]))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    client = PlatformClient(args.base_url, args.username, args.password)
    results = []
    for index, profile_id in enumerate(selected, start=1):
        result_path = output_dir / profile_id / "result.json"
        if args.resume and result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if existing.get("passed"):
                results.append(existing)
                print(f"[{index}/{len(selected)}] resumed {profile_id}", flush=True)
                continue
        print(f"[{index}/{len(selected)}] running {profile_id}", flush=True)
        result = run_source(
            client,
            catalog[profile_id],
            index=index,
            output_dir=output_dir,
            kafka_bootstrap=args.kafka_bootstrap,
            frame_stride=args.frame_stride,
            imgsz=args.imgsz,
            drain_seconds=args.drain_seconds,
        )
        results.append(result)
        print(
            f"[{index}/{len(selected)}] {'PASS' if result['passed'] else 'FAIL'} "
            f"tracks={result['message_counts']['tracks']} elapsed={result['elapsed_sec']}s",
            flush=True,
        )
        if not result["passed"]:
            break
    summary = {
        "schema_version": "uav.replay-v2-acceptance/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "output_dir": str(output_dir),
        "sources": results,
        "passed": len(results) == len(selected) and all(item["passed"] for item in results),
    }
    if summary["passed"]:
        summary["metrics"] = collect_acceptance_metrics(
            client,
            results,
            output_dir=output_dir,
            kafka_bootstrap=args.kafka_bootstrap,
        )
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "output_dir": str(output_dir)}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
