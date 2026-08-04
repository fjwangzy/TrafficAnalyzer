import asyncio
from unittest.mock import patch

import pytest

from app.services.pipeline_executor import LocalPipelineExecutor, PipelineLaunchSpec


def _spec(**overrides) -> PipelineLaunchSpec:
    values = {
        "pipeline_id": "pipe-mps-test",
        "video_src": "/project/test_videos/demo.mp4",
        "topic_name": "uav_statistics_10",
        "camera_id": 10,
        "video_port": 8101,
        "drone_id": "UAV-1",
        "intersection_id": "INT-1",
        "inter_id": "INT-1",
        "kafka_bootstrap": "127.0.0.1:9092",
    }
    values.update(overrides)
    return PipelineLaunchSpec(**values)


@pytest.mark.asyncio
async def test_local_executor_forces_configured_mps_device(tmp_path):
    captured = {}

    class EmptyStream:
        async def read(self, _size):
            return b""

    class ReadyStream:
        def __init__(self):
            self.sent = False

        async def read(self, _size):
            if not self.sent:
                self.sent = True
                return b"MJPEG_READY port=8101\n"
            return b""

    class FakeProcess:
        pid = 9001
        returncode = None
        stdout = ReadyStream()
        stderr = EmptyStream()

    async def fake_exec(*command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    executor = LocalPipelineExecutor(
        tmp_path,
        "/project/.venv-mps/bin/python",
        device="mps",
        imgsz=960,
        extra_env={"PYTORCH_ENABLE_MPS_FALLBACK": "1"},
    )
    with patch(
        "app.services.pipeline_executor.asyncio.create_subprocess_exec",
        side_effect=fake_exec,
    ):
        handle = await executor.start(_spec())

    assert handle.pid == 9001
    assert captured["command"][:2] == (
        "/project/.venv-mps/bin/python",
        "main_optimized.py",
    )
    assert "detection_node.device=mps" in captured["command"]
    assert "detection_node.imgsz=960" in captured["command"]
    assert "detection_node.adaptive_imgsz.enabled=true" in captured["command"]
    assert captured["environment"]["KAFKA_BOOTSTRAP"] == "127.0.0.1:9092"
    assert captured["environment"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
    assert captured["cwd"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_local_executor_waits_until_mjpeg_server_is_ready(tmp_path):
    class ControlledStream:
        def __init__(self):
            self.chunks = asyncio.Queue()

        async def read(self, _size):
            return await self.chunks.get()

    stdout = ControlledStream()

    class FakeProcess:
        pid = 9002
        returncode = None
        stderr = ControlledStream()
        native_wait = asyncio.Event()

        async def wait(self):
            await self.native_wait.wait()
            return self.returncode

    process = FakeProcess()
    process.stdout = stdout
    executor = LocalPipelineExecutor(tmp_path, video_ready_timeout_sec=1.0)

    with patch(
        "app.services.pipeline_executor.asyncio.create_subprocess_exec",
        return_value=process,
    ):
        start_task = asyncio.create_task(executor.start(_spec()))
        await asyncio.sleep(0)
        assert not start_task.done()

        await stdout.chunks.put(b"MJPEG_READY port=8101\n")
        handle = await asyncio.wait_for(start_task, timeout=1.0)

    assert handle.pid == 9002
