"""Real Kafka -> transactional PG -> replay, while the real four workers are alive."""

import asyncio
import json
import os
from pathlib import Path
import sys
from sqlalchemy import select, func
from app.core.database import async_session_maker, engine
from app.core.config import settings
from app.kafka.consumer import KafkaConsumerService
from app.models.replay_v2 import (
    ReplayV2Mission,
    ReplayV2TrackEvent,
    ReplayV2IngestReceipt,
    ReplayV2TrafficMetricSample,
    ReplayV2InterEvaluation5MinMM,
    ReplayV2DirtyWindow,
)
from app.services.replay_repository import PostgresReplayRepository
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter
from app.services.incremental_replay_jobs import IncrementalReplayJobs
from app.services.trajectory_recovery import TrajectoryRecoveryService
from utils_local.replay_topics import REPLAY_V2_CONSUMER_PATTERN


class WS:
    async def broadcast(self, *args):
        pass


async def main():
    root = Path(__file__).resolve().parents[1]
    output = Path(os.environ["TRAFFIC_FIXTURE_DIR"])
    consumer = KafkaConsumerService(
        settings.kafka_bootstrap,
        "isolated-incremental",
        REPLAY_V2_CONSUMER_PATTERN,
        WS(),
        metric_store=ReplayV2MetricStoreAdapter(async_session_maker),
        dispatch_realtime=False,
        security_options=settings.kafka_security_options,
    )
    jobs = IncrementalReplayJobs(async_session_maker)
    recovery = TrajectoryRecoveryService(
        async_session_maker, settings.kafka_bootstrap, settings.kafka_security_options
    )
    process = None
    report = {
        "before_eof": False,
        "source": "synthetic CPU fixture; no NPU performance claim",
    }
    with (output / "pipeline.log").open("w") as log:
        try:
            await consumer.start()
            assert consumer._consumer is not None
            await jobs.start()
            await recovery.start()
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(root / "test/incremental_pipeline_fixture.py"),
                cwd=root,
                env=os.environ.copy(),
                stdout=log,
                stderr=log,
            )
            deadline = asyncio.get_running_loop().time() + 120
            while asyncio.get_running_loop().time() < deadline:
                async with async_session_maker() as session:
                    count = await session.scalar(
                        select(func.count())
                        .select_from(ReplayV2TrackEvent)
                        .where(ReplayV2TrackEvent.mission_id == "MSN-ISOLATED")
                    )
                if count:
                    assert process.returncode is None, (
                        "trajectory appeared only after process exit"
                    )
                    repo = PostgresReplayRepository(async_session_maker)
                    missions = await repo.list_missions(
                        "INT-ISOLATED", include_incomplete=False
                    )
                    assert len(missions) == 1 and missions[0]["status"] in {
                        "running",
                        "incomplete",
                    }
                    reply = await repo.replay(
                        "INT-ISOLATED",
                        mission_id="MSN-ISOLATED",
                        cursor_ms=8000,
                        window_ms=8000,
                        max_points=5000,
                        page_after=None,
                    )
                    assert reply["tracks"]
                    report["before_eof"] = True
                    break
                if process.returncode is not None:
                    raise AssertionError("pipeline exited before durable departure")
                await asyncio.sleep(0.1)
            assert report["before_eof"], "no departure committed before deadline"
            assert await asyncio.wait_for(process.wait(), 90) == 0
            deadline = asyncio.get_running_loop().time() + 30
            while asyncio.get_running_loop().time() < deadline:
                async with async_session_maker() as session:
                    mission = await session.get(ReplayV2Mission, "MSN-ISOLATED")
                    receipts = await session.scalar(
                        select(func.count()).select_from(ReplayV2IngestReceipt)
                    )
                    typical = await session.scalar(
                        select(func.count())
                        .select_from(ReplayV2InterEvaluation5MinMM)
                        .where(
                            ReplayV2InterEvaluation5MinMM.source_profile_id
                            == "SRC-ISOLATED"
                        )
                    )
                    dirty = await session.scalar(
                        select(func.count())
                        .select_from(ReplayV2DirtyWindow)
                        .where(
                            ReplayV2DirtyWindow.mission_id == "MSN-ISOLATED",
                            ReplayV2DirtyWindow.dirty != 0,
                        )
                    )
                    if mission and mission.status == "sealed" and typical and not dirty:
                        report.update(
                            status="passed",
                            segments=mission.journey_count,
                            receipts=receipts,
                            typical_slots=typical,
                        )
                        assert mission.journey_count >= 2
                        break
                await asyncio.sleep(0.1)
            assert report.get("status") == "passed", (
                "final manifest/aggregation did not converge"
            )
            # Run a second Mission and stop only its parent while a mature target
            # is active. The parent's graceful control plane must drain all workers.
            stop_env = {
                **os.environ,
                "PIPELINE_ID": "pipe-manual-stop",
                "MISSION_ID": "MSN-MANUAL-STOP",
            }
            with (output / "manual-stop-pipeline.log").open("w") as stop_log:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(root / "test/incremental_pipeline_fixture.py"),
                    cwd=root,
                    env=stop_env,
                    stdout=stop_log,
                    stderr=stop_log,
                )
                deadline = asyncio.get_running_loop().time() + 90
                ready = False
                while asyncio.get_running_loop().time() < deadline:
                    async with async_session_maker() as session:
                        mission = await session.get(ReplayV2Mission, "MSN-MANUAL-STOP")
                        sample = await session.scalar(
                            select(ReplayV2TrafficMetricSample)
                            .where(
                                ReplayV2TrafficMetricSample.mission_id
                                == "MSN-MANUAL-STOP",
                                ReplayV2TrafficMetricSample.active_tracks > 0,
                            )
                            .order_by(ReplayV2TrafficMetricSample.sampled_at.desc())
                            .limit(1)
                        )
                    if (
                        mission
                        and sample
                        and (sample.sampled_at - mission.started_at).total_seconds()
                        >= 22
                    ):
                        ready = True
                        break
                    if process.returncode is not None:
                        break
                    await asyncio.sleep(0.1)
                assert ready, (
                    "manual-stop fixture did not reach an active mature target"
                )
                process.terminate()
                assert await asyncio.wait_for(process.wait(), 150) == 0, (
                    "graceful stop failed to drain workers"
                )
                deadline = asyncio.get_running_loop().time() + 30
                stopped = False
                while asyncio.get_running_loop().time() < deadline:
                    async with async_session_maker() as session:
                        mission = await session.get(ReplayV2Mission, "MSN-MANUAL-STOP")
                        interrupted = await session.scalar(
                            select(func.count())
                            .select_from(ReplayV2TrackEvent)
                            .where(
                                ReplayV2TrackEvent.mission_id == "MSN-MANUAL-STOP",
                                ReplayV2TrackEvent.termination_reason == "manual_stop",
                            )
                        )
                    if mission and mission.status == "incomplete" and interrupted:
                        stopped = True
                        break
                    await asyncio.sleep(0.1)
                assert stopped, (
                    "manual stop lost active trajectory or mislabeled Mission as sealed"
                )
                report["manual_stop_preserved"] = True
        finally:
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            await jobs.stop()
            await recovery.stop()
            await consumer.stop()
            await engine.dispose()
    (output / "integration.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
