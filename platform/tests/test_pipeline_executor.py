import asyncio
from pathlib import Path
import re
import sys
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
    assert captured["command"][:3] == (
        "/project/.venv-mps/bin/python",
        "-u",
        "main_optimized.py",
    )
    assert "detection_node.device=mps" in captured["command"]
    assert "detection_node.imgsz=960" in captured["command"]
    assert "detection_node.adaptive_imgsz.enabled=true" in captured["command"]
    assert captured["environment"]["KAFKA_BOOTSTRAP"] == "127.0.0.1:9092"
    assert captured["environment"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
    assert captured["environment"]["PYTHONUNBUFFERED"] == "1"
    assert captured["environment"]["PYTHONFAULTHANDLER"] == "1"
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


@pytest.mark.asyncio
@pytest.mark.parametrize("job_logging", ["stdout", "disabled"])
async def test_hydra_fork_worker_announces_real_mjpeg_listener(tmp_path, unused_tcp_port, job_logging):
    import httpx

    root = Path(__file__).resolve().parents[2]
    # Import the node before Hydra; disabled also covers a parent retaining its old launch command.
    (tmp_path / "main_optimized.py").write_text(f'''
import multiprocessing
import hydra
from nodes.FlaskServerVideoNode import VideoServer
from utils_local.runtime_logging import configure_runtime_logging

def worker():
    configure_runtime_logging()
    server = VideoServer({{"video_server_node": {{
        "host_ip": "127.0.0.1", "port": 0, "index_page": "unused.html",
        "template_folder": ".", "output_size": (32, 24),
    }}}})
    server.app_thread.join()

@hydra.main(version_base=None, config_path={str(root / 'configs')!r}, config_name="app_config")
def main(config):
    configure_runtime_logging()
    process = multiprocessing.get_context("fork").Process(target=worker)
    process.start()
    process.join()

if __name__ == "__main__":
    main()
''')
    executor = LocalPipelineExecutor(
        tmp_path, sys.executable, extra_env={"PYTHONPATH": str(root)},
        extra_overrides=(f"hydra/job_logging={job_logging}",),
        video_ready_timeout_sec=10,
    )
    handle = await executor.start(_spec(video_port=unused_tcp_port))
    try:
        match = re.search(r"MJPEG_READY port=(\d+)", handle.stdout_tail)
        assert match, handle.stdout_tail
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            async with client.stream("GET", f"http://127.0.0.1:{match[1]}/video") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
                data = b""
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if b"\xff\xd9" in data:
                        break
                assert b"Content-Type: image/jpeg" in data
                assert b"\xff\xd8" in data
    finally:
        await executor.stop(handle)


def test_production_executor_forwards_ascend_om_selection(tmp_path):
    executor = LocalPipelineExecutor(
        tmp_path, '/usr/bin/python3', device='ascend',
        extra_env={'ASCEND_MODEL_MANIFEST': '/app/weights/ascend/manifest.json', 'ASCEND_DEVICE_ID': '0'},
    )
    command = executor._command(_spec())
    environment = executor._environment(_spec())
    assert 'detection_node.device=ascend' in command
    assert 'detection_node.device=cpu' not in command
    assert environment['ASCEND_MODEL_MANIFEST'] == '/app/weights/ascend/manifest.json'
    assert environment['ASCEND_DEVICE_ID'] == '0'


@pytest.mark.asyncio
async def test_detector_output_persists_redacted_split_chunks_and_keeps_ready_contract(tmp_path, monkeypatch):
    from app.services.pipeline_executor import ExecutionHandle
    from utils_local.runtime_logging import rotating_log_handler
    import logging

    chunks = iter([
        b'MJPEG_RE', b'ADY port=8101\nrtsp://pilot:camera-',
        b'private@example.test/live\n',
        b'2026-10-18T08:00:00.100Z DEBUG pid=45 pipeline=pipe-fixture stage noisy-debug\n',
        b'2026-10-18 08:00:00,100 WARNING pid=45 pipeline=pipe-fixture stage slow\n',
        b'Traceback (most recent call last):\n  password=db-private\n', b'',
    ])

    class Stream:
        async def read(self, _size):
            return next(chunks)

    log = logging.Logger("fixture.detector", logging.INFO)
    handler = rotating_log_handler(tmp_path / "pipe-fixture.log", pipeline_id="pipe-fixture")
    log.addHandler(handler)
    handle = ExecutionHandle(execution_id="pipe-fixture", pid=1234, output_logger=log)
    try:
        await LocalPipelineExecutor._drain_stream(Stream(), handle, "stdout")
        assert handle.video_ready.is_set()
        assert "MJPEG_READY port=8101" in handle.stdout_tail
        assert "camera-private" not in handle.stdout_tail
        assert "db-private" not in handle.stdout_tail
        output = (tmp_path / "pipe-fixture.log").read_text()
        assert "pid=1234" in output
        assert "example.test/live" in output
        assert "camera-private" not in output
        assert "db-private" not in output
        assert "noisy-debug" not in output
        assert any("WARNING pid=" in line and "stage slow" in line for line in output.splitlines())
        assert any("ERROR pid=" in line and "Traceback" in line for line in output.splitlines())
        assert any("ERROR pid=" in line and "password=[redacted]" in line for line in output.splitlines())
    finally:
        handler.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [False, True])
async def test_ready_marker_is_detected_before_a_burst_truncates_the_output_tail(ready):
    from app.services.pipeline_executor import ExecutionHandle

    prefix = b"2026-10-19T10:35:00.000Z INFO pid=564 pipeline=pipe-fixture nodes.FlaskServerVideoNode "
    marker = b"MJPEG_READY port=8101\n" if ready else b"initialization still running\n"
    chunks = iter([prefix, marker + b"x" * (4096 - len(marker) - 1) + b"\n", b""])

    class Stream:
        async def read(self, _size):
            return next(chunks)

    handle = ExecutionHandle("pipe-burst", 564)
    await LocalPipelineExecutor._drain_stream(Stream(), handle, "stdout")
    assert len(handle.stdout_tail) == 4000
    assert "MJPEG_READY" not in handle.stdout_tail
    assert handle.video_ready.is_set() is ready


@pytest.mark.asyncio
async def test_inspect_persists_exit_code_once(tmp_path):
    from app.services.pipeline_executor import ExecutionHandle
    from utils_local.runtime_logging import rotating_log_handler
    from types import SimpleNamespace
    import logging

    log = logging.Logger("fixture.detector", logging.INFO)
    log.addHandler(rotating_log_handler(tmp_path / "exit.log"))
    handle = ExecutionHandle("pipe-exit", 5678, native_process=SimpleNamespace(returncode=7), output_logger=log)
    executor = LocalPipelineExecutor(tmp_path)
    await executor.inspect(handle)
    await executor.inspect(handle)
    output = (tmp_path / "exit.log").read_text()
    assert output.count("PIPELINE_EXIT") == 1
    assert "returncode=7" in output
    assert not log.handlers


@pytest.mark.asyncio
async def test_cancelled_output_drain_never_starts_a_disk_write():
    from app.services.pipeline_executor import ExecutionHandle
    from unittest.mock import AsyncMock

    waiting = asyncio.Event()

    class Stream:
        sent = False

        async def read(self, _size):
            if not self.sent:
                self.sent = True
                return b"unfinished line without newline"
            waiting.set()
            await asyncio.Event().wait()

    handle = ExecutionHandle("pipe-cancel", 123, output_logger=object())
    with patch("app.services.pipeline_executor.asyncio.to_thread", new_callable=AsyncMock) as write:
        task = asyncio.create_task(LocalPipelineExecutor._drain_stream(Stream(), handle, "stderr"))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
        write.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_unterminated_output_drops_whole_line_without_leaking_partial_secret():
    from app.services.pipeline_executor import ExecutionHandle

    data = b"rtsp://pilot:" + b"private-password" * 5000 + b"@example.test/live\nMJPEG_READY port=8101\n"
    chunks = iter([data[index:index + 4096] for index in range(0, len(data), 4096)] + [b""])

    class Stream:
        async def read(self, _size):
            return next(chunks)

    handle = ExecutionHandle("pipe-large", 123)
    await LocalPipelineExecutor._drain_stream(Stream(), handle, "stdout")
    assert "OUTPUT_LINE_TRUNCATED" in handle.stdout_tail
    assert "private-password" not in handle.stdout_tail
    assert handle.video_ready.is_set()
