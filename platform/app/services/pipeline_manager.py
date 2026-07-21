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
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings
from app.models.drone_store import assign_drone_to_intersection
from app.services.pipeline_executor import (
    LocalPipelineExecutor,
    PipelineExecutor,
    PipelineLaunchSpec,
)

logger = logging.getLogger(__name__)

# Path to the TrafficAnalyzer root (parent of platform/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def redact_video_source(value: str) -> str:
    """Return a client/audit-safe source without RTSP credentials or query secrets."""
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{port}{parsed.path}"


def detector_video_stream_url(video_port: int, base_url: str | None = None) -> str:
    """Build the browser-reachable detector MJPEG URL registered at launch."""
    template = (base_url or settings.pipeline_video_base).strip()
    if not template:
        raise ValueError("pipeline_video_base must not be empty")
    candidate = template.replace("{video_port}", str(video_port))
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("pipeline video stream URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("pipeline video stream URL must not contain credentials, query, or fragment")
    if "{video_port}" not in template:
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        candidate = urlunsplit(
            (parsed.scheme, f"{host}:{video_port}", parsed.path or "/video", "", "")
        )
        parsed = urlsplit(candidate)
    if not parsed.path or parsed.path == "/":
        candidate = urlunsplit((parsed.scheme, parsed.netloc, "/video", "", ""))
    return candidate


def validate_detector_video_stream_url(value: str) -> str:
    """Validate an explicitly registered external detector address."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("video_stream_url must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("video_stream_url must not contain credentials, query, or fragment")
    return value.strip()


class PipelineStatus(StrEnum):
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
    video_stream_url: str = ""
    mission_id: str | None = None
    source_profile_id: str | None = None
    inter_id: str | None = None
    road_data_version: str | None = None
    road_context_status: str = "missing"
    quality_status: str = "unverified"
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
            "video_src": redact_video_source(self.video_src),
            "roads_json": self.roads_json,
            "topic_name": self.topic_name,
            "camera_id": self.camera_id,
            "video_port": self.video_port,
            "video_stream_url": self.video_stream_url,
            "mission_id": self.mission_id,
            "source_profile_id": self.source_profile_id,
            "inter_id": self.inter_id,
            "road_data_version": self.road_data_version,
            "road_context_status": self.road_context_status,
            "quality_status": self.quality_status,
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
            roads_json="",
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
        executor: PipelineExecutor | None = None,
        video_public_base: str | None = None,
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
        self._video_public_base = video_public_base or settings.pipeline_video_base
        self._executor = executor or LocalPipelineExecutor(
            self._root,
            self._pipeline_python,
            device=settings.pipeline_device,
            imgsz=settings.pipeline_imgsz,
            extra_env=(
                {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}
                if settings.pipeline_device == "mps"
                else None
            ),
        )
        self._pipelines: dict[str, PipelineInstance] = {}
        self._next_camera_id = 10  # start from 10 to avoid collision with static cameras
        self._next_video_port = 8101  # 8100 reserved for manually-started pipelines
        self._monitor_task: asyncio.Task | None = None

    def _resolve_local_asset(self, value: str, *, roots: tuple[Path, ...]) -> str:
        candidate = Path(value)
        resolved = (self._root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if not any(root == resolved or root in resolved.parents for root in roots):
            raise ValueError("pipeline source path is outside the configured allowlist")
        if not resolved.is_file() or not os.access(resolved, os.R_OK):
            raise ValueError("pipeline source file is missing or unreadable")
        return str(resolved)

    def _asset_roots(self) -> tuple[Path, ...]:
        return tuple(
            (self._root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
            for value in settings.uav_local_asset_roots
        )

    def _roads_roots(self) -> tuple[Path, ...]:
        return tuple(
            (self._root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
            for value in settings.pipeline_roads_roots
        )

    def _validate_video_source(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme:
            if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
                raise ValueError("video source must be an allowlisted local file or rtsp/rtsps URL")
            allowed_hosts = {host.lower() for host in settings.uav_rtsp_allowed_hosts}
            if parsed.hostname.lower() not in allowed_hosts:
                raise ValueError("RTSP host is outside the configured allowlist")
            return value
        return self._resolve_local_asset(value, roots=self._asset_roots())

    def _validate_support_file(self, value: str | None, suffixes: tuple[str, ...], *, roots: tuple[Path, ...]) -> str | None:
        if not value:
            return value
        resolved = self._resolve_local_asset(value, roots=roots)
        if Path(resolved).suffix.lower() not in suffixes:
            raise ValueError(f"pipeline support file must use one of: {', '.join(suffixes)}")
        return resolved

    def _ensure_capacity(self) -> None:
        if self.get_active_count() >= settings.pipeline_max_active:
            raise ValueError("pipeline concurrency limit reached")

    # ── Public API ──

    def register_pipeline(
        self,
        drone_id: str,
        intersection_id: str,
        video_src: str,
        roads_json: str = "",
        camera_id: int | None = None,
        video_port: int | None = None,
        topic_name: str | None = None,
        video_stream_url: str | None = None,
    ) -> PipelineInstance:
        """Register an externally-running pipeline (e.g. started locally).

        This allows the Platform to track pipelines that were started
        outside the Platform container (where PyTorch dependencies may
        not be available).
        """
        self._ensure_capacity()
        video_src = self._validate_video_source(video_src)
        if roads_json:
            raise ValueError("road/lane annotation parameters are disabled; roads_json must be empty")
        if camera_id is not None and not 1 <= camera_id <= 65535:
            raise ValueError("camera_id must be between 1 and 65535")
        if video_port is not None and not 1024 <= video_port <= 65535:
            raise ValueError("video_port must be between 1024 and 65535")
        if topic_name is not None and not re.fullmatch(r"uav_statistics_[A-Za-z0-9._-]+", topic_name):
            raise ValueError("topic_name must be a canonical uav_statistics topic")
        if any(
            (camera_id is not None and item.camera_id == camera_id)
            or (video_port is not None and item.video_port == video_port)
            for item in self._pipelines.values()
            if item.status == PipelineStatus.RUNNING
        ):
            raise ValueError("camera_id or video_port is already registered")
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        cid = camera_id if camera_id is not None else self._next_camera_id
        if camera_id is None:
            self._next_camera_id += 1
        port = video_port if video_port is not None else self._next_video_port
        if video_port is None:
            self._next_video_port += 1
        topic = topic_name or f"uav_statistics_{cid}"
        registered_stream_url = (
            validate_detector_video_stream_url(video_stream_url)
            if video_stream_url
            else detector_video_stream_url(port, self._video_public_base)
        )

        pipeline = PipelineInstance(
            pipeline_id=pipeline_id,
            drone_id=drone_id,
            intersection_id=intersection_id,
            video_src=video_src,
            roads_json=roads_json,
            topic_name=topic,
            camera_id=cid,
            video_port=port,
            video_stream_url=registered_stream_url,
            status=PipelineStatus.RUNNING,
            started_at=time.time(),
        )
        self._pipelines[pipeline_id] = pipeline
        assign_drone_to_intersection(drone_id, intersection_id)
        logger.info(
            f"Registered external pipeline {pipeline_id} "
            f"camera={cid} port={port} stream={registered_stream_url} intersection={intersection_id}"
        )
        return pipeline

    async def start_pipeline(
        self,
        drone_id: str,
        intersection_id: str,
        video_src: str,
        roads_json: str = "",
        telemetry_source: str | None = None,
        telemetry_file_path: str | None = None,
        telemetry_time_offset_sec: float | None = None,
        telemetry_sync_tolerance_sec: float | None = None,
        kafka_bootstrap: str | None = None,
        topic_name: str | None = None,
        mission_id: str | None = None,
        source_profile_id: str | None = None,
        inter_id: str | None = None,
        road_data_version: str | None = None,
        road_context_status: str = "missing",
        quality_status: str = "unverified",
    ) -> PipelineInstance:
        """Start a new detection pipeline process.

        Args:
            drone_id: The drone providing the video stream.
            intersection_id: The intersection to monitor.
            video_src: Video source — RTSP URL, file path, or camera index.
            roads_json: Must be empty; video sources always start without road/lane annotations.
            telemetry_source: Optional telemetry source override.
            telemetry_file_path: Optional telemetry file path override.
            kafka_bootstrap: Override Kafka bootstrap servers.

        Returns:
            The created PipelineInstance.
        """
        self._ensure_capacity()
        video_src = self._validate_video_source(video_src)
        if roads_json:
            raise ValueError("road/lane annotation parameters are disabled; roads_json must be empty")
        telemetry_file_path = self._validate_support_file(
            telemetry_file_path,
            (".srt", ".json", ".txt"),
            roots=self._asset_roots(),
        )
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        camera_id = self._next_camera_id
        self._next_camera_id += 1
        video_port = self._next_video_port
        self._next_video_port += 1
        topic_name = topic_name or f"uav_statistics_{camera_id}"
        video_stream_url = detector_video_stream_url(video_port, self._video_public_base)

        pipeline = PipelineInstance(
            pipeline_id=pipeline_id,
            drone_id=drone_id,
            intersection_id=intersection_id,
            video_src=video_src,
            roads_json=roads_json,
            topic_name=topic_name,
            camera_id=camera_id,
            video_port=video_port,
            video_stream_url=video_stream_url,
            mission_id=mission_id,
            source_profile_id=source_profile_id,
            inter_id=inter_id or intersection_id,
            road_data_version=road_data_version,
            road_context_status=road_context_status,
            quality_status=quality_status,
        )

        launch = PipelineLaunchSpec(
            pipeline_id=pipeline_id,
            video_src=video_src,
            topic_name=topic_name,
            camera_id=camera_id,
            video_port=video_port,
            drone_id=drone_id,
            intersection_id=intersection_id,
            inter_id=inter_id or intersection_id,
            mission_id=mission_id or "",
            source_profile_id=source_profile_id or "",
            road_data_version=road_data_version or "",
            road_context_status=road_context_status,
            quality_status=quality_status,
            frame_stride=self._frame_stride,
            kafka_bootstrap=kafka_bootstrap or self._kafka_bootstrap,
            telemetry_source=telemetry_source,
            telemetry_file_path=telemetry_file_path,
            telemetry_time_offset_sec=telemetry_time_offset_sec,
            telemetry_sync_tolerance_sec=telemetry_sync_tolerance_sec,
        )

        try:
            execution = await self._executor.start(launch)
            pipeline.process = execution
            pipeline.status = PipelineStatus.RUNNING
            pipeline.started_at = time.time()
            logger.info(
                f"Pipeline {pipeline_id} started (PID={execution.pid}) "
                f"drone={drone_id} intersection={intersection_id} stream={video_stream_url}"
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
            await self._executor.stop(pipeline.process)
            self._sync_execution_output(pipeline)

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
                try:
                    await self._executor.inspect(proc)
                except Exception as exc:
                    logger.warning(
                        "Pipeline %s executor status unavailable: %s",
                        pipeline.pipeline_id,
                        exc,
                    )
                    continue
                self._sync_execution_output(pipeline)
                if proc.returncode is not None:
                    self._handle_process_exit(pipeline, proc.returncode)

    @staticmethod
    def _sync_execution_output(pipeline: PipelineInstance) -> None:
        if pipeline.process is None:
            return
        pipeline.stdout_tail = pipeline.process.stdout_tail
        pipeline.stderr_tail = pipeline.process.stderr_tail

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
