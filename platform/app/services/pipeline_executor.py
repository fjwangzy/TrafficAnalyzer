"""Detection pipeline process execution.

The Platform owns pipeline business lifecycle while this module owns the local
child-process boundary. macOS development and Linux production use the same
start/inspect/stop contract with environment-specific device configuration.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from utils_local.runtime_logging import RuntimeFormatter, log_level_from_text, redact_log_text, rotating_log_handler, runtime_log_dir

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
    enforcement_snapshot: dict | None = None
    frame_stride: int | None = None
    kafka_bootstrap: str = "kafka:9092"
    telemetry_source: str | None = None
    telemetry_file_path: str | None = None
    telemetry_time_offset_sec: float | None = None
    telemetry_sync_tolerance_sec: float | None = None
    telemetry_camera_lens_policy: str | None = None


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
    output_logger: Any = field(default=None, repr=False)
    exit_logged: bool = False


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
        adaptive_imgsz: bool = True,
        extra_env: dict[str, str] | None = None,
        extra_overrides: tuple[str, ...] = (),
        video_ready_timeout_sec: float = 45.0,
    ) -> None:
        self._root = Path(project_root).resolve()
        self._pipeline_python = pipeline_python
        self._device = device
        self._imgsz = imgsz
        self._adaptive_imgsz = bool(adaptive_imgsz)
        self._extra_env = dict(extra_env or {})
        self._extra_overrides = tuple(extra_overrides)
        self._video_ready_timeout_sec = max(float(video_ready_timeout_sec), 0.1)

    def _command(self, spec: PipelineLaunchSpec) -> list[str]:
        command = [
            self._pipeline_python,
            "-u",
            "main_optimized.py",
            "pipeline.send_info_kafka=True",
            "hydra/job_logging=stdout",  # Re-enable pre-imported loggers, including MJPEG_READY.
        ]
        if self._device:
            command.append(f"detection_node.device={self._device}")
        if self._imgsz is not None:
            command.append(f"detection_node.imgsz={self._imgsz}")
        command.append(
            "detection_node.adaptive_imgsz.enabled="
            f"{'true' if self._adaptive_imgsz else 'false'}"
        )
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
        if spec.telemetry_camera_lens_policy is not None:
            command.append(
                "telemetry.camera_lens_policy="
                f"{spec.telemetry_camera_lens_policy}"
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
            "PYTHONUNBUFFERED": "1",
            "PYTHONFAULTHANDLER": "1",
        }
        if spec.frame_stride is not None:
            environment["FRAME_STRIDE"] = str(spec.frame_stride)
        if spec.runtime_map_bundle is not None:
            environment["RUNTIME_MAP_BUNDLE_JSON"] = json.dumps(
                spec.runtime_map_bundle, ensure_ascii=False, separators=(",", ":")
            )
        else:
            environment.pop("RUNTIME_MAP_BUNDLE_JSON", None)
        if spec.enforcement_snapshot is not None:
            environment["ENFORCEMENT_RUNTIME_SNAPSHOT_JSON"] = json.dumps(
                spec.enforcement_snapshot, ensure_ascii=False, separators=(",", ":")
            )
        else:
            environment.pop("ENFORCEMENT_RUNTIME_SNAPSHOT_JSON", None)
        environment.pop("RUNTIME_GEO_REGISTRATION_JSON", None)
        return environment

    async def start(self, spec: PipelineLaunchSpec) -> ExecutionHandle:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", spec.pipeline_id):
            raise ValueError("pipeline_id contains unsupported log path characters")
        output_logger = logging.Logger(f"detector.{spec.pipeline_id}", logging.INFO)
        output_logger.addHandler(rotating_log_handler(
            runtime_log_dir(self._root) / "pipelines" / f"{spec.pipeline_id}.log",
            pipeline_id=spec.pipeline_id,
        ))
        console = logging.StreamHandler()
        console.setFormatter(RuntimeFormatter(spec.pipeline_id))
        output_logger.addHandler(console)
        output_logger.info(
            "PIPELINE_LAUNCH startup_contract=20261019.3 device=%s imgsz=%s adaptive_imgsz=%s frame_stride=%s source_kind=%s tracking_profile=%s",
            self._device or "auto", self._imgsz, self._adaptive_imgsz, spec.frame_stride,
            "stream" if "://" in spec.video_src else "file", spec.tracking_profile,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command(spec),
                cwd=str(self._root),
                env=self._environment(spec),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except Exception:
            output_logger.exception("PIPELINE_LAUNCH_FAILED")
            for handler in output_logger.handlers:
                handler.close()
            raise
        handle = ExecutionHandle(
            execution_id=spec.pipeline_id,
            pid=process.pid,
            native_process=process,
            output_logger=output_logger,
        )
        handle.io_tasks = [
            asyncio.create_task(self._drain_stream(process.stdout, handle, "stdout")),
            asyncio.create_task(self._drain_stream(process.stderr, handle, "stderr")),
        ]
        try:
            await self._wait_until_video_ready(handle)
            return handle
        except Exception:
            output_logger.exception("PIPELINE_START_FAILED pid=%s", process.pid)
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
            if handle.returncode is not None:
                await self._finish_output(handle)
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
        await self._finish_output(handle)
        return handle

    @staticmethod
    async def _finish_output(handle: ExecutionHandle) -> None:
        if handle.exit_logged:
            return
        if handle.io_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*handle.io_tasks), timeout=2.0)
            except TimeoutError:
                for task in handle.io_tasks:
                    task.cancel()
        handle.exit_logged = True
        if handle.output_logger is not None:
            def finish_log():
                handle.output_logger.log(
                    logging.INFO if handle.returncode == 0 else logging.ERROR,
                    "PIPELINE_EXIT child_pid=%s returncode=%s", handle.pid, handle.returncode,
                )
                for handler in handle.output_logger.handlers:
                    handler.close()
                handle.output_logger.handlers.clear()
            try:
                await asyncio.wait_for(asyncio.to_thread(finish_log), timeout=2.0)
            except TimeoutError:
                # A stalled host log disk must not hold the pipeline lifecycle open.
                pass

    @staticmethod
    async def _drain_stream(
        stream: Any,
        handle: ExecutionHandle,
        name: str,
    ) -> None:
        if stream is None:
            return
        tail_limit = 4000
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        dropping_oversized_line = False
        line_level = logging.WARNING if name == "stderr" else logging.INFO

        async def emit(value):
            safe = redact_log_text(value)
            if name == "stderr":
                handle.stderr_tail = (handle.stderr_tail + safe)[-tail_limit:]
            else:
                combined = handle.stdout_tail + safe
                if VIDEO_READY_MARKER in combined:
                    handle.video_ready.set()
                handle.stdout_tail = combined[-tail_limit:]
            if handle.output_logger is not None and safe.strip():
                def write_lines():
                    nonlocal line_level
                    for line in safe.splitlines():
                        line_level = log_level_from_text(line, line_level)
                        if not handle.output_logger.isEnabledFor(line_level):
                            continue
                        record = handle.output_logger.makeRecord(
                            f"detector.{handle.execution_id}.{name}", line_level, "", 0, line, (), None,
                        )
                        record.process = handle.pid
                        handle.output_logger.handle(record)
                await asyncio.to_thread(write_lines)

        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                decoded = decoder.decode(chunk)
                if dropping_oversized_line:
                    boundary = decoded.find("\n")
                    if boundary < 0:
                        continue
                    dropping_oversized_line = False
                    decoded = decoded[boundary + 1:]
                pending += decoded
                boundary = pending.rfind("\n")
                if boundary >= 0:
                    await emit(pending[:boundary + 1])
                    pending = pending[boundary + 1:]
                elif len(pending) > 65536:
                    await emit("WARNING OUTPUT_LINE_TRUNCATED limit_chars=65536\n")
                    pending = ""
                    dropping_oversized_line = True
            pending += decoder.decode(b"", final=True)
            if pending:
                await emit(pending)
        except Exception:
            logging.getLogger(__name__).exception("Detector output drain failed pipeline=%s stream=%s", handle.execution_id, name)
