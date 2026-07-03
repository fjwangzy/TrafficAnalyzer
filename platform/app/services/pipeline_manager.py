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
    video_port: int = 8100  # MJPEG server port
    status: PipelineStatus = PipelineStatus.PENDING
    process: Any = field(default=None, repr=False)
    started_at: float = 0.0
    stopped_at: float = 0.0
    error_message: str = ""
    stdout_tail: str = field(default="", repr=False)
    stderr_tail: str = field(default="", repr=False)
    io_tasks: list[asyncio.Task] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "drone_id": self.drone_id,
            "intersection_id": self.intersection_id,
            "video_src": self.video_src,
            "roads_json": self.roads_json,
            "topic_name": self.topic_name,
            "camera_id": self.camera_id,
            "video_port": self.video_port,
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
        pipeline_python: str | None = None,
        frame_stride: int | None = None,
    ):
        # Priority: explicit arg > PIPELINE_PROJECT_ROOT env var > fallback
        env_root = os.environ.get("PIPELINE_PROJECT_ROOT")
        if project_root:
            self._root = Path(project_root)
        elif env_root:
            self._root = Path(env_root)
        else:
            self._root = _PROJECT_ROOT
        self._kafka_bootstrap = kafka_bootstrap
        self._pipeline_python = pipeline_python or os.environ.get("PIPELINE_PYTHON") or "python"
        self._frame_stride = frame_stride
        self._pipelines: dict[str, PipelineInstance] = {}
        self._next_camera_id = 10  # start from 10 to avoid collision with static cameras
        self._next_video_port = 8101  # 8100 reserved for manually-started pipelines
        self._monitor_task: asyncio.Task | None = None

    # ── Public API ──

    def register_pipeline(
        self,
        drone_id: str,
        intersection_id: str,
        video_src: str,
        roads_json: str = "configs/entry_exit_lanes.json",
        camera_id: int | None = None,
        video_port: int | None = None,
        topic_name: str | None = None,
    ) -> PipelineInstance:
        """Register an externally-running pipeline (e.g. started locally).

        This allows the Platform to track pipelines that were started
        outside the Platform container (where PyTorch dependencies may
        not be available).
        """
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        cid = camera_id if camera_id is not None else self._next_camera_id
        if camera_id is None:
            self._next_camera_id += 1
        port = video_port if video_port is not None else self._next_video_port
        if video_port is None:
            self._next_video_port += 1
        topic = topic_name or f"statistics_{cid}"

        pipeline = PipelineInstance(
            pipeline_id=pipeline_id,
            drone_id=drone_id,
            intersection_id=intersection_id,
            video_src=video_src,
            roads_json=roads_json,
            topic_name=topic,
            camera_id=cid,
            video_port=port,
            status=PipelineStatus.RUNNING,
            started_at=time.time(),
        )
        self._pipelines[pipeline_id] = pipeline
        assign_drone_to_intersection(drone_id, intersection_id)
        logger.info(
            f"Registered external pipeline {pipeline_id} "
            f"camera={cid} port={port} intersection={intersection_id}"
        )
        return pipeline

    async def start_pipeline(
        self,
        drone_id: str,
        intersection_id: str,
        video_src: str,
        roads_json: str = "configs/entry_exit_lanes.json",
        telemetry_source: str | None = None,
        telemetry_file_path: str | None = None,
        kafka_bootstrap: str | None = None,
    ) -> PipelineInstance:
        """Start a new detection pipeline process.

        Args:
            drone_id: The drone providing the video stream.
            intersection_id: The intersection to monitor.
            video_src: Video source — RTSP URL, file path, or camera index.
            roads_json: Path to the roads polygon JSON file.
            telemetry_source: Optional telemetry source override.
            telemetry_file_path: Optional telemetry file path override.
            kafka_bootstrap: Override Kafka bootstrap servers.

        Returns:
            The created PipelineInstance.
        """
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        camera_id = self._next_camera_id
        self._next_camera_id += 1
        video_port = self._next_video_port
        self._next_video_port += 1
        topic_name = f"statistics_{camera_id}"

        pipeline = PipelineInstance(
            pipeline_id=pipeline_id,
            drone_id=drone_id,
            intersection_id=intersection_id,
            video_src=video_src,
            roads_json=roads_json,
            topic_name=topic_name,
            camera_id=camera_id,
            video_port=video_port,
        )

        # Build environment for the child process
        env = {
            **os.environ,
            "VIDEO_SRC": video_src,
            "ROADS_JSON": str(self._root / roads_json) if roads_json else "",
            "TOPIC_NAME": topic_name,
            "CAMERA_ID": str(camera_id),
            "INTERSECTION_ID": intersection_id,  # pass real intersection ID (e.g. INT_camera_1)
            "VIDEO_PORT": str(video_port),  # unique MJPEG port per pipeline
        }
        if self._frame_stride is not None:
            env["FRAME_STRIDE"] = str(self._frame_stride)
        if kafka_bootstrap:
            env["KAFKA_BOOTSTRAP"] = kafka_bootstrap

        # Spawn the pipeline process
        try:
            cmd = [
                self._pipeline_python,
                "main_optimized.py",
                "pipeline.send_info_kafka=True",
                "hydra/job_logging=disabled",
            ]
            if telemetry_source:
                cmd.extend([
                    "telemetry.enabled=True",
                    f"telemetry.source={telemetry_source}",
                ])
            if telemetry_file_path:
                cmd.append(f"telemetry.file_path={telemetry_file_path}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            pipeline.process = proc
            pipeline.io_tasks = [
                asyncio.create_task(self._drain_stream(proc.stdout, pipeline, "stdout")),
                asyncio.create_task(self._drain_stream(proc.stderr, pipeline, "stderr")),
            ]
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
                try:
                    os.killpg(pipeline.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pipeline.process.terminate()
                try:
                    await asyncio.wait_for(pipeline.process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning(f"Pipeline {pipeline_id} did not exit, sending SIGKILL")
                    try:
                        os.killpg(pipeline.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pipeline.process.kill()
                    await pipeline.process.wait()
            except ProcessLookupError:
                pass  # Already dead
            for task in pipeline.io_tasks:
                task.cancel()

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

    async def _drain_stream(self, stream: Any, pipeline: PipelineInstance, name: str) -> None:
        """Drain child process output so verbose detector logs never block it."""
        if stream is None:
            return
        tail_limit = 4000
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                if name == "stderr":
                    pipeline.stderr_tail = (pipeline.stderr_tail + text)[-tail_limit:]
                else:
                    pipeline.stdout_tail = (pipeline.stdout_tail + text)[-tail_limit:]
        except asyncio.CancelledError:
            pass

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
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    self._handle_process_exit(pipeline, proc.returncode)

    def _handle_process_exit(self, pipeline: PipelineInstance, return_code: int) -> None:
        """Reflect a child process exit in pipeline state."""
        pipeline.stopped_at = time.time()
        if return_code == 0:
            pipeline.status = PipelineStatus.STOPPED
            pipeline.error_message = ""
            logger.info(f"Pipeline {pipeline.pipeline_id} completed normally")
            return

        stderr_msg = pipeline.stderr_tail[-500:]
        pipeline.status = PipelineStatus.ERROR
        pipeline.error_message = (
            f"Process exited with code {return_code}"
            + (f": {stderr_msg}" if stderr_msg else "")
        )
        logger.warning(
            f"Pipeline {pipeline.pipeline_id} exited unexpectedly "
            f"(code={return_code})"
            + (f" stderr: {stderr_msg}" if stderr_msg else "")
        )
