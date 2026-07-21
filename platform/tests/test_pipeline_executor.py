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

    class FakeProcess:
        pid = 9001
        returncode = None
        stdout = EmptyStream()
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
    assert captured["environment"]["KAFKA_BOOTSTRAP"] == "127.0.0.1:9092"
    assert captured["environment"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
    assert captured["cwd"] == str(tmp_path.resolve())
