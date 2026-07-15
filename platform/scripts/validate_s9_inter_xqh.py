"""Real S9 smoke test using the full inter_xqh MP4 and DJI SRT assets."""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path


PLATFORM_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import async_session_maker, close_db, init_db  # noqa: E402
from app.schemas.mission import DroneCreate, FlightPlanCreate, OnceSchedule, SourceInput, SourcePairCreate  # noqa: E402
from app.services.mission_orchestrator import MissionOrchestrator, PipelineManagerAdapter  # noqa: E402
from app.services.pipeline_manager import PipelineManager  # noqa: E402
from app.services.road_context import FixtureRoadContextAdapter, RoadContext, RoadContextResult  # noqa: E402


VIDEO = "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
SRT = "test_videos/inter_xqh/telemetry.srt"
ROADS = "configs/bak/inter_xqh_lanes.json"
INTER_ID = "INT_camera_1"
ROAD_VERSION = "ROAD-LOCAL-INTER-XQH"


def road_context() -> RoadContext:
    roads_path = PROJECT_ROOT / ROADS
    import hashlib

    fixture = RoadContextResult(
        inter_id=INTER_ID,
        road_data_version=ROAD_VERSION,
        source="inter_xqh_smoke_fixture",
        checksum=hashlib.sha256(roads_path.read_bytes()).hexdigest(),
        coordinate_reference={"metric": "ENU", "display": "GCJ02", "status": "unverified"},
        intersection={"roads_json": ROADS},
        links=(),
        lanes=(),
        visual_bindings=({"roads_json": ROADS, "status": "candidate"},),
        quality_status="unverified",
    )
    return RoadContext(FixtureRoadContextAdapter({(INTER_ID, ROAD_VERSION): fixture}))


def pipeline_manager() -> PipelineManager:
    return PipelineManager(
        project_root=PROJECT_ROOT,
        kafka_bootstrap=os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"),
        pipeline_python=os.environ.get("PIPELINE_PYTHON", sys.executable),
        frame_stride=int(os.environ.get("S9_SMOKE_FRAME_STRIDE", "300")),
    )


async def main() -> dict:
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    suffix = uuid.uuid4().hex[:6].upper()
    drone_id = f"UAV-XQH-{suffix}"
    first_manager = pipeline_manager()
    first = MissionOrchestrator(
        async_session_maker,
        PipelineManagerAdapter(first_manager),
        road_context(),
        poll_sec=5,
    )
    await first.create_drone(
        DroneCreate(
            id=drone_id,
            name=f"inter_xqh 真实验收 {suffix}",
            model="DJI M300 RTK",
            enabled=True,
            default_inter_id=INTER_ID,
        )
    )
    source = await first.create_source_pair(
        drone_id,
        SourcePairCreate(
            mode="local",
            video=SourceInput(source_type="mp4", location=VIDEO),
            telemetry=SourceInput(source_type="srt", location=SRT),
            enabled=True,
            set_default=True,
        ),
    )
    now = datetime.now(UTC)
    mode = os.environ.get("S9_SMOKE_MODE", "recovery_window")
    end_at = now + timedelta(seconds=int(os.environ.get("S9_SMOKE_WINDOW_SEC", "45")))
    plan = await first.create_plan(
        FlightPlanCreate(
            name=f"inter_xqh once 真实验收 {suffix}",
            drone_id=drone_id,
            source_profile_id=source["profile_id"],
            inter_id=INTER_ID,
            road_data_version=ROAD_VERSION,
            timezone="Asia/Shanghai",
            schedule=OnceSchedule(type="once", start_at=now - timedelta(seconds=1), end_at=end_at),
        )
    )
    plan = await first.change_plan_state(plan["id"], plan["revision"], "enable")
    await first.run_once(now)
    mission = next(item for item in await first.list_missions() if item["flight_plan_id"] == plan["id"])
    if mission["status"] != "running" or not mission["pipeline_id"]:
        raise RuntimeError(f"Pipeline failed to start: {mission}")
    original_pipeline_id = mission["pipeline_id"]

    # Simulate a Platform restart: terminate the process without changing the
    # persisted Mission, then construct a fresh runtime manager and recover.
    await first_manager.stop_pipeline(original_pipeline_id)
    second_manager = pipeline_manager()
    second = MissionOrchestrator(
        async_session_maker,
        PipelineManagerAdapter(second_manager),
        road_context(),
        poll_sec=5,
    )

    async def cleanup_runtime() -> None:
        await second_manager.stop_all()
        await first_manager.stop_all()
        await close_db()

    await second.recover()
    recovered = await second.get_mission(mission["id"])
    if recovered["status"] != "running" or recovered["pipeline_id"] == original_pipeline_id:
        await cleanup_runtime()
        raise RuntimeError(f"Mission recovery did not replace the runtime Pipeline: {recovered}")

    runtime_started = time.monotonic()
    if mode == "recovery_eof":
        timeout_sec = int(os.environ.get("S9_SMOKE_TIMEOUT_SEC", "600"))
        deadline = time.monotonic() + timeout_sec
        while True:
            await asyncio.sleep(5)
            await second.run_once(datetime.now(UTC))
            completed = await second.get_mission(mission["id"])
            if completed["status"] in {"completed", "failed", "cancelled", "skipped"}:
                break
            if time.monotonic() >= deadline:
                await cleanup_runtime()
                raise TimeoutError(f"Pipeline did not reach EOF within {timeout_sec}s: {completed}")
        if completed["status"] != "completed" or completed["reason_code"] != "source_eof":
            await cleanup_runtime()
            raise RuntimeError(f"Natural EOF did not complete the Mission: {completed}")
    else:
        await second.run_once(end_at + timedelta(seconds=1))
        completed = await second.get_mission(mission["id"])
    await cleanup_runtime()
    result = {
        "schema_version": "uav.s9-inter-xqh-eof/v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": "isolated_local_non_contract",
        "drone_id": drone_id,
        "source_profile_id": source["profile_id"],
        "flight_plan_id": plan["id"],
        "mission_id": completed["id"],
        "initial_pipeline_id": original_pipeline_id,
        "recovered_pipeline_id": completed["pipeline_id"],
        "mission_status": completed["status"],
        "reason_code": completed["reason_code"],
        "topic_name": completed["pipeline"]["topic_name"],
        "source_validation": source["validation_status"],
        "road_quality": completed["context_snapshot"]["road_context"]["quality_status"],
        "verification_mode": mode,
        "terminal_observation_sec": round(time.monotonic() - runtime_started, 3),
        "passed": True,
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(main())
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
