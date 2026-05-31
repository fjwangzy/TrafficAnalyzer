"""Pipeline lifecycle manager — starts/stops detection pipeline processes.

The PipelineManager bridges the gap between the platform (FastAPI) and
the detection pipeline (main_optimized.py).  It spawns pipeline
processes as child processes with the correct environment variables,
monitors their health, and can stop them gracefully.

Architecture note
-----------------
The detection pipeline is a **separate process** (not a thread or async
task) because it uses GPU-bound PyTorch inference which would block the
FastAPI asyncio event loop.  Communication is one-way: the pipeline
publishes results to Kafka, which the platform's KafkaConsumerService
picks up.

Deployment modes
----------------
1. **Local / dev**: spawns ``python main_optimized.py`` as a subprocess.
2. **Docker** (future): uses the Docker API to start/stop containers.
   This module currently supports mode 1 only.
"""
import asyncio
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.models.drone_store import assign_drone_to_intersection

logger = logging.getLogger(__name__)

# Path to the TrafficAnalyzer root (parent of platform/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class PipelineInstance:
    """Represents a single running detection pipeline."""

    pipeline_id: str
    drone_id: str
    intersection_id: str
    video_src: str
    roads_json: str
    topic_name: str
    camera_id: int
    status: PipelineStatus = PipelineStatus.PENDING
    process: Any = field(default=None, repr=False)
    started_at: float = 0.0
    stopped_at: float = 0.0
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "drone_id": self.drone_id,
            "intersection_id": self.intersection_id,
            "video_src": self.video_src,
            "roads_json": self.roads_json,
            "topic_name": self.topic_name,
            "camera_id": self.camera_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "error_message": self.error_message,
            "uptime_seconds": (
                (self.stopped_at or time.time()) - self.started_at
                if self.started_at
                else 0
            ),
        }


class PipelineManager:
    """Manages the lifecycle of detection pipeline processes.

    Usage::

        pm = PipelineManager()
        pipeline = await pm.start_pipeline(
            drone_id="drone_001",
            intersection_id="INT_camera_1",
            video_src="rtsp://192.168.1.100:554/stream",
            roads_json="configs/inter1_lanes.json",
        )
        # ... later ...
        await pm.stop_pipeline(pipeline.pipeline_id)
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        kafka_bootstrap: str = "kafka:9092",
    ):
        self._root = Path(project_root) if project_root else _PROJECT_ROOT
        self._kafka_bootstrap = kafka_bootstrap
        self._pipelines: dict[str, PipelineInstance] = {}
        self._next_camera_id = 10  # start from 10 to avoid collision with static cameras
        self._monitor_task: asyncio.Task | None = None

    # ── Public API ──

    async def start_pipeline(
        self,
        drone_id: str,
        intersection_id: str,
        video_src: str,
        roads_json: str = "configs/entry_exit_lanes.json",
        kafka_bootstrap: str | None = None,
    ) -> PipelineInstance:
        """Start a new detection pipeline process.

        Args:
            drone_id: The drone providing the video stream.
            intersection_id: The intersection to monitor.
            video_src: Video source — RTSP URL, file path, or camera index.
            roads_json: Path to the roads polygon JSON file.
            kafka_bootstrap: Override Kafka bootstrap servers.

        Returns:
            The created PipelineInstance.
        """
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        camera_id = self._next_camera_id
        self._next_camera_id += 1
        topic_name = f"statistics_{camera_id}"

        pipeline = PipelineInstance(
            pipeline_id=pipeline_id,
            drone_id=drone_id,
            intersection_id=intersection_id,
            video_src=video_src,
            roads_json=roads_json,
            topic_name=topic_name,
            camera_id=camera_id,
        )

        # Build environment for the child process
        env = {
            **os.environ,
            "VIDEO_SRC": video_src,
            "ROADS_JSON": str(self._root / roads_json),
            "TOPIC_NAME": topic_name,
            "CAMERA_ID": str(camera_id),
            "INTERSECTION_ID": intersection_id,  # pass real intersection ID (e.g. INT_camera_1)
        }
        if kafka_bootstrap:
            env["KAFKA_BOOTSTRAP"] = kafka_bootstrap

        # Spawn the pipeline process
        try:
            cmd = ["python", "main_optimized.py", "pipeline.send_info_kafka=True"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pipeline.process = proc
            pipeline.status = PipelineStatus.RUNNING
            pipeline.started_at = time.time()
            logger.info(
                f"Pipeline {pipeline_id} started (PID={proc.pid}) "
                f"drone={drone_id} intersection={intersection_id}"
            )
        except Exception as e:
            pipeline.status = PipelineStatus.ERROR
            pipeline.error_message = str(e)
            logger.error(f"Failed to start pipeline {pipeline_id}: {e}")

        self._pipelines[pipeline_id] = pipeline

        # Register drone-intersection mapping
        assign_drone_to_intersection(drone_id, intersection_id)

        # Start monitor task if not running
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

        return pipeline

    async def stop_pipeline(self, pipeline_id: str) -> PipelineInstance | None:
        """Gracefully stop a pipeline process.

        Sends SIGTERM, waits up to 10 seconds, then sends SIGKILL if
        the process is still alive.
        """
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            return None

        if pipeline.process and pipeline.process.returncode is None:
            logger.info(f"Stopping pipeline {pipeline_id} (PID={pipeline.process.pid})")
            try:
                pipeline.process.terminate()
                try:
                    await asyncio.wait_for(pipeline.process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning(f"Pipeline {pipeline_id} did not exit, sending SIGKILL")
                    pipeline.process.kill()
                    await pipeline.process.wait()
            except ProcessLookupError:
                pass  # Already dead

        pipeline.status = PipelineStatus.STOPPED
        pipeline.stopped_at = time.time()
        logger.info(f"Pipeline {pipeline_id} stopped")
        return pipeline

    async def stop_all(self) -> None:
        """Stop all running pipelines."""
        for pid in list(self._pipelines.keys()):
            await self.stop_pipeline(pid)
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

    def get_pipeline(self, pipeline_id: str) -> PipelineInstance | None:
        return self._pipelines.get(pipeline_id)

    def list_pipelines(self) -> list[dict]:
        return [p.to_dict() for p in self._pipelines.values()]

    def get_active_count(self) -> int:
        return sum(
            1 for p in self._pipelines.values()
            if p.status == PipelineStatus.RUNNING
        )

    # ── Internal ──

    async def _monitor_loop(self) -> None:
        """Background task: poll pipeline processes for unexpected exits."""
        while True:
            await asyncio.sleep(5)
            for pipeline in self._pipelines.values():
                if pipeline.status != PipelineStatus.RUNNING:
                    continue
                proc = pipeline.process
                if proc is None:
                    continue
                if proc.returncode is not None:
                    # Process exited unexpectedly
                    pipeline.status = PipelineStatus.ERROR
                    pipeline.stopped_at = time.time()
                    pipeline.error_message = f"Process exited with code {proc.returncode}"
                    logger.warning(
                        f"Pipeline {pipeline.pipeline_id} exited unexpectedly "
                        f"(code={proc.returncode})"
                    )
