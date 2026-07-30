"""Detection pipeline process execution.

The Platform owns pipeline business lifecycle while this module owns the local
child-process boundary. macOS development and Linux production use the same
start/inspect/stop contract with environment-specific device configuration.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

VIDEO_READY_MARKER = "MJPEG_READY"


def hydra_string(value: str) -> str:
    """Quote one Hydra string override, including paths with spaces/CJK."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


@dataclass(frozen=True)
class PipelineLaunchSpec:
    pipeline_id: str
    video_src: str
    topic_name: str
    camera_id: int
    video_port: int
    drone_id: str
    intersection_id: str
    inter_id: str
    mission_id: str = ""
    source_profile_id: str = ""
    road_data_version: str = ""
    road_context_status: str = "missing"
    quality_status: str = "unverified"
    tracking_profile: str = "hover_cruise_v1"
    runtime_map_bundle: dict | None = None
    frame_stride: int | None = None
    kafka_bootstrap: str = "kafka:9092"
    telemetry_source: str | None = None
    telemetry_file_path: str | None = None
    telemetry_time_offset_sec: float | None = None
    telemetry_sync_tolerance_sec: float | None = None


@dataclass
class ExecutionHandle:
    execution_id: str
    pid: int | None
    returncode: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    native_process: Any = field(default=None, repr=False)
    io_tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    video_ready: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class PipelineExecutor(Protocol):
    """Small interface at the detector-process execution seam."""

    async def start(self, spec: PipelineLaunchSpec) -> ExecutionHandle: ...

    async def inspect(self, handle: ExecutionHandle) -> ExecutionHandle: ...

    async def stop(self, handle: ExecutionHandle) -> ExecutionHandle: ...


class LocalPipelineExecutor:
    """Run detector processes in the same OS environment as Platform."""

    def __init__(
        self,
        project_root: str | Path,
        pipeline_python: str = "python",
        *,
        device: str | None = None,
        imgsz: int | None = None,
        extra_env: dict[str, str] | None = None,
        extra_overrides: tuple[str, ...] = (),
        video_ready_timeout_sec: float = 45.0,
    ) -> None:
        self._root = Path(project_root).resolve()
        self._pipeline_python = pipeline_python
        self._device = device
        self._imgsz = imgsz
        self._extra_env = dict(extra_env or {})
        self._extra_overrides = tuple(extra_overrides)
        self._video_ready_timeout_sec = max(float(video_ready_timeout_sec), 0.1)

    def _command(self, spec: PipelineLaunchSpec) -> list[str]:
        command = [
            self._pipeline_python,
            "main_optimized.py",
            "pipeline.send_info_kafka=True",
            "hydra/job_logging=disabled",
        ]
        if self._device:
            command.append(f"detection_node.device={self._device}")
        if self._imgsz is not None:
            command.append(f"detection_node.imgsz={self._imgsz}")
        command.extend(self._extra_overrides)
        if spec.telemetry_source:
            command.extend(
                [
                    "telemetry.enabled=True",
                    f"telemetry.source={spec.telemetry_source}",
                ]
            )
        if spec.telemetry_file_path:
            command.append(
                f"telemetry.file_path={hydra_string(spec.telemetry_file_path)}"
            )
        if spec.telemetry_time_offset_sec is not None:
            command.append(
                f"telemetry.time_offset_sec={spec.telemetry_time_offset_sec}"
            )
        if spec.telemetry_sync_tolerance_sec is not None:
            command.append(
                "telemetry.sync_tolerance_sec="
                f"{spec.telemetry_sync_tolerance_sec}"
            )
        return command

    def _environment(self, spec: PipelineLaunchSpec) -> dict[str, str]:
        environment = {
            **os.environ,
            **self._extra_env,
            "VIDEO_SRC": spec.video_src,
            "TOPIC_NAME": spec.topic_name,
            "CAMERA_ID": str(spec.camera_id),
            "DRONE_ID": spec.drone_id,
            "INTERSECTION_ID": spec.intersection_id,
            "INTER_ID": spec.inter_id,
            "MISSION_ID": spec.mission_id,
            "PIPELINE_ID": spec.pipeline_id,
            "RUN_ID": spec.pipeline_id,
            "SOURCE_PROFILE_ID": spec.source_profile_id,
            "ROAD_DATA_VERSION": spec.road_data_version,
            "ROAD_CONTEXT_STATUS": spec.road_context_status,
            "QUALITY_STATUS": spec.quality_status,
            "TRACKING_PROFILE": spec.tracking_profile,
            "VIDEO_PORT": str(spec.video_port),
            "KAFKA_BOOTSTRAP": spec.kafka_bootstrap,
        }
        if spec.frame_stride is not None:
            environment["FRAME_STRIDE"] = str(spec.frame_stride)
        if spec.runtime_map_bundle is not None:
            environment["RUNTIME_MAP_BUNDLE_JSON"] = json.dumps(
                spec.runtime_map_bundle, ensure_ascii=False, separators=(",", ":")
            )
        else:
            environment.pop("RUNTIME_MAP_BUNDLE_JSON", None)
        environment.pop("RUNTIME_GEO_REGISTRATION_JSON", None)
        return environment

    async def start(self, spec: PipelineLaunchSpec) -> ExecutionHandle:
        process = await asyncio.create_subprocess_exec(
            *self._command(spec),
            cwd=str(self._root),
            env=self._environment(spec),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        handle = ExecutionHandle(
            execution_id=spec.pipeline_id,
            pid=process.pid,
            native_process=process,
        )
        handle.io_tasks = [
            asyncio.create_task(self._drain_stream(process.stdout, handle, "stdout")),
            asyncio.create_task(self._drain_stream(process.stderr, handle, "stderr")),
        ]
        try:
            await self._wait_until_video_ready(handle)
            return handle
        except Exception:
            await self.stop(handle)
            raise

    async def _wait_until_video_ready(self, handle: ExecutionHandle) -> None:
        """Do not expose a running pipeline before its MJPEG socket is bound."""
        process = handle.native_process
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._video_ready_timeout_sec
        while not handle.video_ready.is_set():
            if process is not None and process.returncode is not None:
                handle.returncode = process.returncode
                raise RuntimeError(
                    "detector exited before the MJPEG server became ready "
                    f"(returncode={process.returncode}): {handle.stderr_tail[-1000:]}"
                )
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    "detector MJPEG server did not become ready within "
                    f"{self._video_ready_timeout_sec:g}s"
                )
            try:
                await asyncio.wait_for(
                    handle.video_ready.wait(),
                    timeout=min(remaining, 0.1),
                )
            except TimeoutError:
                continue

    async def inspect(self, handle: ExecutionHandle) -> ExecutionHandle:
        process = handle.native_process
        if process is not None:
            handle.returncode = process.returncode
        return handle

    async def stop(self, handle: ExecutionHandle) -> ExecutionHandle:
        process = handle.native_process
        if process is not None and process.returncode is None:
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        process.kill()
                    await process.wait()
            except ProcessLookupError:
                pass
        if process is not None:
            handle.returncode = process.returncode
        for task in handle.io_tasks:
            task.cancel()
        return handle

    @staticmethod
    async def _drain_stream(
        stream: Any,
        handle: ExecutionHandle,
        name: str,
    ) -> None:
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
                    handle.stderr_tail = (handle.stderr_tail + text)[-tail_limit:]
                else:
                    handle.stdout_tail = (handle.stdout_tail + text)[-tail_limit:]
                    if VIDEO_READY_MARKER in handle.stdout_tail:
                        handle.video_ready.set()
        except asyncio.CancelledError:
            pass
