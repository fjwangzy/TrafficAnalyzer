"""Run with RUN_PG_INTEGRATION=1 DB_NAME=road9_i2_test."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.database import async_session_maker
from app.models.mission import (
    DroneRecord,
    FlightPlanRecord,
    MissionRecord,
    PipelineRecord,
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.schemas.mission import (
    DroneCreate,
    FlightPlanCreate,
    OnceSchedule,
    SourceInput,
    SourcePairCreate,
)
from app.services.mission_orchestrator import MissionError, MissionOrchestrator
from app.services.road_context import FixtureRoadContextAdapter, RoadContext, RoadContextResult

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires an explicitly selected disposable local PostgreSQL database",
)


class FakePipeline:
    def __init__(self):
        self.started = []
        self.running = {}

    async def start(self, **kwargs):
        pipeline_id = f"pipe-{len(self.started) + 1}"
        self.started.append(kwargs)
        result = {
            "pipeline_id": pipeline_id, "status": "running",
            "topic_name": f"uav_statistics_{len(self.started) + 9}",
            "camera_id": len(self.started) + 9, "video_port": 8100 + len(self.started),
            "error_message": "",
        }
        self.running[pipeline_id] = result
        return result

    async def stop(self, pipeline_id):
        result = self.running.get(pipeline_id)
        if result:
            result = {**result, "status": "stopped"}
            self.running[pipeline_id] = result
        return result

    def get(self, pipeline_id):
        return self.running.get(pipeline_id)

    def finish(self, pipeline_id, *, status="stopped", error_message=""):
        self.running[pipeline_id] = {
            **self.running[pipeline_id],
            "status": status,
            "error_message": error_message,
        }


def road_context():
    result = RoadContextResult(
        inter_id="INT_camera_1", road_data_version="ROAD-LOCAL-INTER-XQH",
        source="test_fixture", checksum="a" * 64,
        coordinate_reference={"metric": "ENU", "display": "GCJ02"},
        intersection={}, links=(), lanes=(),
        visual_bindings=({"roads_json": "configs/bak/inter_xqh_lanes.json"},),
        quality_status="unverified",
    )
    return RoadContext(FixtureRoadContextAdapter({(result.inter_id, result.road_data_version): result}))


async def cleanup():
    async with async_session_maker() as session:
        for model in (PipelineRecord, MissionRecord, FlightPlanRecord, TelemetrySourceRecord, VideoSourceRecord, DroneRecord):
            await session.execute(delete(model))
        await session.commit()


@pytest.mark.asyncio
async def test_persistent_plan_concurrency_stop_and_restart_recovery():
    await cleanup()
    pipeline_a = FakePipeline()
    pipeline_b = FakePipeline()
    first = MissionOrchestrator(async_session_maker, pipeline_a, road_context())
    second = MissionOrchestrator(async_session_maker, pipeline_b, road_context())

    await first.create_drone(DroneCreate(id="UAV-I2-1", name="I2 test drone"))
    source = await first.create_source_pair(
        "UAV-I2-1",
        SourcePairCreate(
            mode="local",
            video=SourceInput(
                source_type="mp4",
                location="test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4",
            ),
            telemetry=SourceInput(source_type="srt", location="test_videos/inter_xqh/telemetry.srt"),
            set_default=True,
        ),
    )
    now = datetime.now(UTC)
    plan = await first.create_plan(
        FlightPlanCreate(
            name="I2 once schedule", drone_id="UAV-I2-1", source_profile_id=source["profile_id"],
            inter_id="INT_camera_1", road_data_version="ROAD-LOCAL-INTER-XQH",
            schedule=OnceSchedule(type="once", start_at=now - timedelta(seconds=1), end_at=now + timedelta(minutes=5)),
        )
    )
    enabled = await first.change_plan_state(plan["id"], plan["revision"], "enable")

    await asyncio.gather(first.run_once(now), second.run_once(now))
    missions = await first.list_missions()
    assert len(missions) == 1
    assert missions[0]["status"] == "running"
    assert len(pipeline_a.started) + len(pipeline_b.started) == 1
    started = (pipeline_a.started + pipeline_b.started)[0]
    assert started["roads_json"] == ""
    assert missions[0]["pipeline"]["topic_name"].startswith("uav_statistics_")

    stopped = await first.stop_mission(missions[0]["id"], "integration test")
    assert stopped["status"] == "cancelled"
    assert stopped["pipeline"]["observed_status"] == "stopped"

    # Revision and overlap errors remain observable through the interface.
    with pytest.raises(MissionError) as revision:
        await first.change_plan_state(enabled["id"], enabled["revision"] - 1, "pause")
    assert revision.value.status_code == 409

    await cleanup()


@pytest.mark.asyncio
async def test_scheduler_persists_pipeline_eof_and_error_terminal_states():
    await cleanup()
    pipeline = FakePipeline()
    orchestrator = MissionOrchestrator(async_session_maker, pipeline, road_context())
    await orchestrator.create_drone(DroneCreate(id="UAV-I2-EOF", name="I2 EOF test drone"))
    source = await orchestrator.create_source_pair(
        "UAV-I2-EOF",
        SourcePairCreate(
            mode="local",
            video=SourceInput(
                source_type="mp4",
                location="test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4",
            ),
            telemetry=SourceInput(source_type="srt", location="test_videos/inter_xqh/telemetry.srt"),
            set_default=True,
        ),
    )
    now = datetime.now(UTC)

    async def start_plan(name: str):
        plan = await orchestrator.create_plan(
            FlightPlanCreate(
                name=name,
                drone_id="UAV-I2-EOF",
                source_profile_id=source["profile_id"],
                inter_id="INT_camera_1",
                road_data_version="ROAD-LOCAL-INTER-XQH",
                schedule=OnceSchedule(
                    type="once",
                    start_at=now - timedelta(seconds=1),
                    end_at=now + timedelta(minutes=5),
                ),
            )
        )
        enabled = await orchestrator.change_plan_state(plan["id"], plan["revision"], "enable")
        await orchestrator.run_once(now)
        mission = next(item for item in await orchestrator.list_missions() if item["flight_plan_id"] == plan["id"])
        return enabled, mission

    eof_plan, eof_mission = await start_plan("I2 source EOF")
    pipeline.finish(eof_mission["pipeline_id"], status="stopped")
    await orchestrator.run_once(now + timedelta(seconds=1))
    eof_result = await orchestrator.get_mission(eof_mission["id"])
    assert eof_result["status"] == "completed"
    assert eof_result["reason_code"] == "source_eof"
    assert eof_result["pipeline"]["desired_status"] == "stopped"
    assert eof_result["pipeline"]["observed_status"] == "stopped"
    await orchestrator.change_plan_state(eof_plan["id"], eof_plan["revision"], "retire")

    failed_plan, failed_mission = await start_plan("I2 pipeline error")
    pipeline.finish(failed_mission["pipeline_id"], status="error", error_message="decoder exited")
    await orchestrator.run_once(now + timedelta(seconds=2))
    failed_result = await orchestrator.get_mission(failed_mission["id"])
    assert failed_result["status"] == "failed"
    assert failed_result["reason_code"] == "pipeline_error"
    assert failed_result["error_message"] == "decoder exited"
    assert failed_result["pipeline"]["desired_status"] == "stopped"
    assert failed_result["pipeline"]["observed_status"] == "error"
    assert failed_result["pipeline"]["error_message"] == "decoder exited"
    await orchestrator.change_plan_state(failed_plan["id"], failed_plan["revision"], "retire")

    _, missing_mission = await start_plan("I2 pipeline runtime missing")
    pipeline.running.pop(missing_mission["pipeline_id"])
    await orchestrator.run_once(now + timedelta(seconds=3))
    missing_result = await orchestrator.get_mission(missing_mission["id"])
    assert missing_result["status"] == "failed"
    assert missing_result["reason_code"] == "pipeline_runtime_missing"
    assert missing_result["pipeline"]["desired_status"] == "stopped"
    assert missing_result["pipeline"]["observed_status"] == "error"

    await cleanup()
