import importlib.util
from pathlib import Path

import httpx
import pytest


spec = importlib.util.spec_from_file_location(
    'live_diagnostics', Path(__file__).resolve().parents[1] / 'deploy/intranet/diagnose_live.py',
)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


@pytest.mark.asyncio
async def test_video_probe_counts_complete_changed_frames_across_chunks(monkeypatch):
    jpeg_a = b'\xff\xd8first\xff\xd9'
    jpeg_b = b'\xff\xd8second\xff\xd9'
    wire = b'header\r\n' + jpeg_a + b'\r\nheader\r\n' + jpeg_a + jpeg_b

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(0, len(wire), 3):
                yield wire[index:index + 3]

    real_client = httpx.AsyncClient

    def make_client(**kwargs):
        assert kwargs['trust_env'] is False
        return real_client(**kwargs, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Chunks()),
        ))

    monkeypatch.setattr(httpx, 'AsyncClient', make_client)
    report = await diagnostics.sample_mjpeg(8102)
    assert report['frames_received'] == 3
    assert report['distinct_frames'] == 2
    assert report['status'] == 'stream_ended'


@pytest.mark.asyncio
async def test_video_probe_reports_connection_failure_without_leaking_error_or_image(monkeypatch):
    class Client:
        async def __aenter__(self):
            raise httpx.ConnectError('private-password')

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_: Client())
    report = await diagnostics.sample_mjpeg(8102)
    assert report['status'] == 'ConnectError'
    assert report['frames_received'] == 0
    assert 'private-password' not in str(report)
    assert (await diagnostics.sample_mjpeg(None))['status'] == 'video_port_missing'
