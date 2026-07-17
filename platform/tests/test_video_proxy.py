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
