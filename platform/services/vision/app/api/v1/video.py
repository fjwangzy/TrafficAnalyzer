"""Video stream API endpoints."""
import asyncio
import logging
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])

# Active HLS streams
_STREAMS: dict[str, dict] = {}


@router.get("/streams")
async def list_streams():
    """List active video streams."""
    return list(_STREAMS.values())


@router.post("/streams/{stream_id}/start")
async def start_stream(stream_id: str, request: Request):
    """Start an HLS stream from a pipeline MJPEG source."""
    if stream_id in _STREAMS:
        return _STREAMS[stream_id]

    settings = request.app.state.settings
    source_url = f"{settings.pipeline_video_base}".replace("camera_1", f"camera_{stream_id}")
    output_dir = f"{settings.hls_output_dir}/{stream_id}"

    # Create output directory
    import os
    os.makedirs(output_dir, exist_ok=True)

    # Start FFmpeg process
    hls_time = 2
    hls_list_size = 10
    cmd = [
        "ffmpeg", "-y",
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
            "status": "running",
            "pid": proc.pid,
        }
        _STREAMS[stream_id] = stream_info
        logger.info(f"Started HLS stream: {stream_id} (PID: {proc.pid})")
        return stream_info
    except FileNotFoundError:
        # FFmpeg not available — return mock stream info
        stream_info = {
            "stream_id": stream_id,
            "source_url": source_url,
            "hls_url": f"/hls/{stream_id}/index.m3u8",
            "status": "unavailable",
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
    stream["status"] = "stopped"
    return stream
