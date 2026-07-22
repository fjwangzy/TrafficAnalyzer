#!/usr/bin/env python3
"""Finalize passed GCJ-02 demo replays as traceable Mission batches.

The native MPS acceptance runner is intentionally external to Platform.  This
script creates one durable completed Mission per passed source result and links
only facts carrying that result's ``pipeline_id``.  Raw Kafka payloads remain
verbatim; input hashes and runtime provenance live in ``context_snapshot``.

The command is dry-run by default.  Mutation requires both ``--execute`` and
the fixed confirmation phrase so an incomplete replay cannot be finalized by
accident.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.metrics import (  # noqa: E402
    ConflictEvent,
    TelemetryMetric,
    TrackEvent,
    TrackPoint,
    TrafficMetric,
)
from app.models.mission import (  # noqa: E402
    ChannelizedMapVersion,
    MissionRecord,
    PipelineRecord,
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.models.survey import AuditLog  # noqa: E402
from scripts.bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402


CONFIRMATION = "FINALIZE_GCJ02_DEMO_REPLAY"
MODEL_PATH = ROOT / "weights/uav_best.pt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog() -> dict[str, dict]:
    flattened: dict[str, dict] = {}
    for intersection in LOCAL_REPLAY_CATALOG:
        for source in intersection["sources"]:
            flattened[source["profile_id"]] = {
                **source,
                "inter_id": intersection["inter_id"],
                "drone_id": intersection["drone_id"],
            }
    return flattened


def _mission_id(profile_id: str) -> str:
    suffix = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:20]
    return f"MIS-GCJ02-DEMO-{suffix}"


def _run_started_at(run_id: str) -> datetime:
    prefix = "native-mps-"
    stamp = run_id.removeprefix(prefix).split("-SRC-", 1)[0]
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _load_results(
    output_dir: Path,
    profile_ids: set[str] | None = None,
) -> list[tuple[dict, dict]]:
    catalog = _catalog()
    selected = profile_ids or set(catalog)
    unknown = selected - set(catalog)
    if unknown:
        raise RuntimeError(f"unknown replay sources: {', '.join(sorted(unknown))}")
    results: list[tuple[dict, dict]] = []
    missing: list[str] = []
    for profile_id, source in catalog.items():
        if profile_id not in selected:
            continue
        result_path = output_dir / profile_id / "result.json"
        if not result_path.is_file():
            missing.append(profile_id)
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("passed"):
            raise RuntimeError(f"replay result is not passed: {profile_id}")
        if result.get("profile_id") != profile_id:
            raise RuntimeError(f"result/profile mismatch: {profile_id}")
        results.append((source, result))
    if missing:
        raise RuntimeError(f"missing replay results: {', '.join(missing)}")
    return results


async def finalize(
    output_dir: Path,
    *,
    execute: bool,
    profile_ids: set[str] | None = None,
) -> dict:
    results = _load_results(output_dir, profile_ids)
    model_hash = _sha256(MODEL_PATH)
    report: list[dict] = []
    async with async_session_maker() as session:
        for source, result in results:
            profile_id = result["profile_id"]
            video_source = (
                await session.execute(
                    select(VideoSourceRecord).where(VideoSourceRecord.profile_id == profile_id)
                )
            ).scalar_one()
            telemetry_source = (
                await session.execute(
                    select(TelemetrySourceRecord).where(
                        TelemetrySourceRecord.profile_id == profile_id
                    )
                )
            ).scalar_one()
            map_version = await session.get(ChannelizedMapVersion, result["map_version_id"])
            if map_version is None or map_version.status != "lane_verified":
                raise RuntimeError(f"lane_verified map unavailable for {profile_id}")

            track_count = int((await session.execute(
                select(func.count(TrackEvent.id)).where(
                    TrackEvent.pipeline_id == result["pipeline_id"],
                    TrackEvent.source_profile_id == profile_id,
                )
            )).scalar_one())
            if track_count != int(result["trajectory_count"]):
                raise RuntimeError(
                    f"Kafka/DB trajectory mismatch for {profile_id}: "
                    f"capture={result['trajectory_count']} db={track_count}"
                )

            video_path = ROOT / source["video"]
            telemetry_path = ROOT / source["telemetry"]
            started_at = _run_started_at(result["run_id"])
            ended_at = started_at + timedelta(seconds=float(result["elapsed_sec"]))
            mission_id = _mission_id(profile_id)
            context_snapshot = {
                "schema_version": "uav.replay-batch-provenance/v1",
                "replay_batch_id": result["run_id"],
                "pipeline_id": result["pipeline_id"],
                "source_profile_id": profile_id,
                "input_files": {
                    "video": {
                        "path": source["video"],
                        "sha256": _sha256(video_path),
                        "size_bytes": video_path.stat().st_size,
                    },
                    "telemetry": {
                        "path": source["telemetry"],
                        "sha256": _sha256(telemetry_path),
                        "size_bytes": telemetry_path.stat().st_size,
                    },
                },
                "model": {
                    "path": str(MODEL_PATH.relative_to(ROOT)),
                    "sha256": model_hash,
                },
                "runtime_map": {
                    "map_version_id": map_version.id,
                    "road_data_version": map_version.road_data_version,
                    "coordinate_system": map_version.coordinate_system,
                    "coordinate_transform_version": map_version.coordinate_transform_version,
                    "quality": map_version.quality,
                },
                "sampling": {
                    "input_fps": result.get("input_fps"),
                    "sample_fps": result.get("sample_fps"),
                    "frame_stride": result["frame_stride"],
                    "imgsz": result["imgsz"],
                },
                "acceptance_artifact": str(
                    (output_dir / profile_id / "result.json").relative_to(ROOT)
                ),
            }
            report.append({
                "profile_id": profile_id,
                "mission_id": mission_id,
                "pipeline_id": result["pipeline_id"],
                "map_version_id": map_version.id,
                "trajectory_count": track_count,
                "video_sha256": context_snapshot["input_files"]["video"]["sha256"],
                "telemetry_sha256": context_snapshot["input_files"]["telemetry"]["sha256"],
                "model_sha256": model_hash,
            })
            if not execute:
                continue

            mission = await session.get(MissionRecord, mission_id)
            if mission is None:
                mission = MissionRecord(
                    id=mission_id,
                    name=f"GCJ-02 演示重跑 · {profile_id}",
                    flight_plan_id=None,
                    parent_mission_id=None,
                    retry_index=0,
                    trigger_type="manual",
                    drone_id=source["drone_id"],
                    video_source_id=video_source.id,
                    telemetry_source_id=telemetry_source.id,
                    inter_id=source["inter_id"],
                    road_data_version=map_version.road_data_version,
                    scheduled_start_at=started_at,
                    scheduled_end_at=ended_at,
                    actual_start_at=started_at,
                    actual_end_at=ended_at,
                    status="completed",
                    reason_code="gcj02_demo_replay_passed",
                    pipeline_id=result["pipeline_id"],
                    context_snapshot=context_snapshot,
                )
                session.add(mission)
                session.add(AuditLog(
                    actor_id=None,
                    action="gcj02.replay_batch.finalized",
                    target_type="mission",
                    target_id=mission_id,
                    after_value={
                        "pipeline_id": result["pipeline_id"],
                        "source_profile_id": profile_id,
                        "map_version_id": map_version.id,
                        "trajectory_count": track_count,
                        "video_sha256": context_snapshot["input_files"]["video"]["sha256"],
                        "telemetry_sha256": context_snapshot["input_files"]["telemetry"]["sha256"],
                        "model_sha256": model_hash,
                    },
                    reason="GCJ-02 two-stage demo replay passed EOF and Kafka/DB reconciliation",
                    request_id=f"gcj02-demo-finalize-{mission_id}",
                ))
            else:
                mission.name = f"GCJ-02 演示重跑 · {profile_id}"
                mission.status = "completed"
                mission.reason_code = "gcj02_demo_replay_passed"
                mission.pipeline_id = result["pipeline_id"]
                mission.actual_start_at = started_at
                mission.actual_end_at = ended_at
                mission.context_snapshot = context_snapshot
            await session.flush()

            pipeline = await session.get(PipelineRecord, result["pipeline_id"])
            if pipeline is None:
                pipeline = PipelineRecord(
                    id=result["pipeline_id"],
                    mission_id=mission_id,
                    desired_status="stopped",
                    observed_status="stopped",
                    topic_name=f"uav_statistics_{result['camera_id']}",
                    camera_id=result["camera_id"],
                    video_port=15700 + (int(result["camera_id"]) - 5700),
                    started_at=started_at,
                    stopped_at=ended_at,
                    error_message=None,
                )
                session.add(pipeline)
            else:
                pipeline.mission_id = mission_id
                pipeline.desired_status = "stopped"
                pipeline.observed_status = "stopped"
                pipeline.started_at = started_at
                pipeline.stopped_at = ended_at
                pipeline.error_message = None
            await session.flush()

            for model in (TrackEvent, TrackPoint, TrafficMetric, ConflictEvent, TelemetryMetric):
                await session.execute(
                    update(model)
                    .where(
                        model.pipeline_id == result["pipeline_id"],
                        model.source_profile_id == profile_id,
                    )
                    .values(mission_id=mission_id)
                )
        if execute:
            await session.commit()
        else:
            await session.rollback()

    return {
        "mode": "execute" if execute else "dry-run",
        "schema_version": "uav.replay-finalization-report/v1",
        "output_dir": str(output_dir.relative_to(ROOT)),
        "completed_missions": len(report),
        "trajectory_count": sum(item["trajectory_count"] for item in report),
        "items": report,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output/native-mps/gcj02-demo-20260721",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help="Finalize only this completed SourceProfile; repeat for multiple sources.",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.execute and args.confirm != CONFIRMATION:
        raise SystemExit(f"--execute requires --confirm {CONFIRMATION}")
    try:
        report = await finalize(
            output_dir,
            execute=args.execute,
            profile_ids=set(args.sources) if args.sources else None,
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
