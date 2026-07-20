from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1 import video


class _FakePipelineManager:
    def __init__(self, pipelines):
        self._pipelines = pipelines

    def list_pipelines(self):
        return self._pipelines


def _request(pipeline_manager):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pipeline_manager=pipeline_manager))
    )


@pytest.mark.asyncio
async def test_dynamic_camera_proxy_uses_running_pipeline_port(monkeypatch):
    requested = []

    async def fake_stream(source_url):
        requested.append(source_url)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xd9\r\n"

    monkeypatch.setattr(video, "_proxy_mjpeg_stream", fake_stream)
    request = _request(_FakePipelineManager([
        {"camera_id": 17, "video_port": 8127, "status": "running"},
        {"camera_id": 18, "video_port": 8128, "status": "stopped"},
    ]))

    response = await video.proxy_camera_stream(17, request)

    assert isinstance(response, StreamingResponse)
    assert response.status_code == 200
    assert response.media_type == "multipart/x-mixed-replace; boundary=frame"
    assert b"\xff\xd8\xff\xd9" in b"".join([chunk async for chunk in response.body_iterator])
    assert requested == ["http://127.0.0.1:8127/video"]


@pytest.mark.asyncio
async def test_dynamic_camera_proxy_rejects_non_running_camera():
    request = _request(_FakePipelineManager([
        {"camera_id": 18, "video_port": 8128, "status": "stopped"},
    ]))

    response = await video.proxy_camera_stream(18, request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert b"camera_not_running" in response.body


@pytest.mark.asyncio
async def test_hls_start_uses_platform_managed_detector_port(monkeypatch, tmp_path):
    requested = []

    async def fake_audit(*_args, **_kwargs):
        return None

    async def fake_exec(*cmd, **_kwargs):
        requested.append(cmd)
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr(video, "_audit", fake_audit)
    monkeypatch.setattr(video.asyncio, "create_subprocess_exec", fake_exec)
    video._STREAMS.clear()
    request = SimpleNamespace(
        state=SimpleNamespace(user={"username": "admin", "role": "admin"}),
        app=SimpleNamespace(
            state=SimpleNamespace(
                pipeline_manager=_FakePipelineManager([
                    {"camera_id": 17, "video_port": 8127, "status": "running"},
                ]),
                settings=SimpleNamespace(
                    video_max_active_streams=4,
                    hls_output_dir=str(tmp_path),
                ),
            )
        ),
        url=SimpleNamespace(path="/api/v1/video/streams/17/start"),
    )

    response = await video.start_stream("17", request)

    assert response["source_url"] == "http://127.0.0.1:8127/video"
    assert "http://127.0.0.1:8127/video" in requested[0]
    video._STREAMS.clear()
