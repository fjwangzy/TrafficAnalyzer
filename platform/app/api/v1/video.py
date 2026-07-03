"""Video stream API endpoints."""
import asyncio
import logging
import os
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])

# Active HLS streams
_STREAMS: dict[str, dict] = {}


@router.get("/streams")
async def list_streams():
    """List active video streams."""
    return list(_STREAMS.values())


async def _proxy_mjpeg_stream(source_url: str):
    """Stream MJPEG bytes from a detector process reachable inside Platform."""
    timeout = httpx.Timeout(connect=2.0, read=None, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", source_url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk


@router.get("/camera/{camera_id}")
async def proxy_camera_stream(camera_id: int, request: Request):
    """Proxy a running PipelineManager MJPEG stream by camera ID.

    The detector subprocess runs inside the Platform container and binds its
    MJPEG server to an internal localhost port. Browser/dev-server clients
    cannot reach that port directly, so Platform performs the container-local
    hop and exposes a stable HTTP endpoint.
    """
    pm = getattr(request.app.state, "pipeline_manager", None)
    if pm is None:
        return JSONResponse({"error": "pipeline_manager_unavailable"}, status_code=503)

    pipeline = next(
        (
            item for item in pm.list_pipelines()
            if item["camera_id"] == camera_id and item["status"] == "running"
        ),
        None,
    )
    if pipeline is None:
        return JSONResponse({"error": "camera_not_running", "camera_id": camera_id}, status_code=404)

    source_url = f"http://127.0.0.1:{pipeline['video_port']}/video"
    return StreamingResponse(
        _proxy_mjpeg_stream(source_url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/streams/{stream_id}/start")
async def start_stream(stream_id: str, request: Request):
    """Start an HLS stream from a pipeline MJPEG source.

    stream_id corresponds to the camera suffix: '1' -> traffic_analyzer_camera_1:8100
    """
    if stream_id in _STREAMS and _STREAMS[stream_id]["status"] == "running":
        return _STREAMS[stream_id]

    settings = request.app.state.settings
    # Build source URL: http://traffic_analyzer_camera_{stream_id}:8100/video
    source_url = f"http://traffic_analyzer_camera_{stream_id}:8100/video"
    output_dir = f"{settings.hls_output_dir}/{stream_id}"

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Start FFmpeg process
    hls_time = 2
    hls_list_size = 10
    cmd = [
        "ffmpeg", "-y",
        "-use_wallclock_as_timestamps", "1",
        "-i", source_url,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-g", str(hls_time * 15),
        "-f", "hls",
        "-hls_time", str(hls_time),
        "-hls_list_size", str(hls_list_size),
        "-hls_flags", "delete_segments+append_list",
        "-hls_segment_filename", f"{output_dir}/seg_%04d.ts",
        f"{output_dir}/index.m3u8",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        stream_info = {
            "stream_id": stream_id,
            "source_url": source_url,
            "hls_url": f"/hls/{stream_id}/index.m3u8",
            "mjpeg_url": f"/camera_{stream_id}",
            "status": "running",
            "pid": proc.pid,
        }
        _STREAMS[stream_id] = stream_info
        logger.info(f"Started HLS stream: {stream_id} (PID: {proc.pid}) src={source_url}")
        return stream_info
    except FileNotFoundError:
        # FFmpeg not available — return MJPEG-only info
        stream_info = {
            "stream_id": stream_id,
            "source_url": source_url,
            "hls_url": None,
            "mjpeg_url": f"/camera_{stream_id}",
            "status": "mjpeg_only",
            "error": "ffmpeg_not_found",
        }
        _STREAMS[stream_id] = stream_info
        return stream_info


@router.post("/streams/{stream_id}/stop")
async def stop_stream(stream_id: str):
    """Stop an active HLS stream."""
    stream = _STREAMS.pop(stream_id, None)
    if not stream:
        return {"error": "not_found", "stream_id": stream_id}
    # Kill ffmpeg process if running
    pid = stream.get("pid")
    if pid:
        try:
            os.kill(pid, 15)  # SIGTERM
        except OSError:
            pass
    stream["status"] = "stopped"
    return stream


@router.get("/streams/{stream_id}/snapshot")
async def get_snapshot(stream_id: str, request: Request):
    """Return a single JPEG snapshot from the camera MJPEG stream.

    Useful for thumbnail / preview without starting full HLS.
    """
    settings = request.app.state.settings
    source_url = f"http://traffic_analyzer_camera_{stream_id}:8100/video"
    output_path = f"{settings.hls_output_dir}/{stream_id}/snapshot.jpg"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", source_url,
        "-frames:v", "1",
        "-q:v", "3",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
        if os.path.exists(output_path):
            return FileResponse(output_path, media_type="image/jpeg")
        return JSONResponse({"error": "snapshot_failed"}, status_code=500)
    except (FileNotFoundError, asyncio.TimeoutError) as e:
        return JSONResponse({"error": str(e)}, status_code=500)
