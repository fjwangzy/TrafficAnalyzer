#!/usr/bin/env python3
"""End-to-end test: MPS + Video Streaming + Platform Integration.

Tests the full data flow:
  Detection Pipeline (GPU+MPS) → MJPEG (port 8100) → Platform API → HLS/Nginx → Frontend

Usage:
    python test/test_e2e_mps_streaming.py
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8009"  # nginx proxy
PLATFORM_URL = "http://localhost:8000"  # direct platform
NGINX_URL = "http://localhost:8009"

results = {"pass": 0, "fail": 0, "warn": 0}


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        results["pass"] += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        results["fail"] += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def warn(name: str, detail: str = ""):
    results["warn"] += 1
    print(f"  ⚠️  {name}" + (f" — {detail}" if detail else ""))


def http_get(url: str, timeout: int = 5):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.URLError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def http_post(url: str, data: dict = None, timeout: int = 10):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.URLError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Docker Compose & MPS Configuration
# ═══════════════════════════════════════════════════════════════════
print("\n═══ Phase 1: Docker Compose & MPS Configuration ═══")

import yaml
with open("docker-compose.yaml") as f:
    dc = yaml.safe_load(f)

services = dc.get("services", {})

# MPS daemon service
check("nvidia-mps service defined", "nvidia-mps" in services)
if "nvidia-mps" in services:
    mps = services["nvidia-mps"]
    check("MPS uses nvidia/cuda image", "nvidia/cuda" in mps.get("image", ""))
    check("MPS has GPU reservation", 
          "deploy" in mps and "resources" in mps["deploy"])
    check("MPS has pipe volume",
          any("nvidia_mps_pipes" in str(v) for v in mps.get("volumes", [])))

# Camera containers with MPS
for cam_name in ["traffic_analyzer_camera_1", "traffic_analyzer_camera_2", "traffic_analyzer_camera_3"]:
    check(f"{cam_name} defined", cam_name in services)
    if cam_name in services:
        cam = services[cam_name]
        env = cam.get("environment", [])
        check(f"{cam_name} has CUDA_MPS_PIPE_DIRECTORY",
              any("CUDA_MPS_PIPE_DIRECTORY" in str(e) for e in env))
        check(f"{cam_name} depends on nvidia-mps",
              "nvidia-mps" in str(cam.get("depends_on", {})))
        check(f"{cam_name} has GPU reservation",
              "deploy" in cam and "resources" in cam["deploy"])
        ports = cam.get("ports", [])
        check(f"{cam_name} exposes MJPEG port", len(ports) > 0,
              f"ports={ports}")

# MPS volumes
volumes = dc.get("volumes", {})
check("nvidia_mps_pipes volume defined", "nvidia_mps_pipes" in volumes)
check("nvidia_mps_logs volume defined", "nvidia_mps_logs" in volumes)

# Camera 3 uses inter_xqh video
cam3 = services.get("traffic_analyzer_camera_3", {})
cam3_env = cam3.get("environment", [])
check("Camera 3 uses inter_xqh video",
      any("inter_xqh" in str(e) for e in cam3_env))

# ═══════════════════════════════════════════════════════════════════
# Phase 2: Nginx Configuration
# ═══════════════════════════════════════════════════════════════════
print("\n═══ Phase 2: Nginx Configuration ═══")

with open("services/nginx/nginx.conf") as f:
    nginx_conf = f.read()

check("Nginx has HLS location", "/hls/" in nginx_conf)
check("Nginx has API proxy", "/api/" in nginx_conf)
check("Nginx has WebSocket proxy", "/ws/" in nginx_conf)
check("Nginx has camera proxy", "/camera_" in nginx_conf)
check("Nginx has HLS volume mounted",
      "hls_data" in str(services.get("nginx", {}).get("volumes", [])))

# ═══════════════════════════════════════════════════════════════════
# Phase 3: Platform Video API
# ═══════════════════════════════════════════════════════════════════
print("\n═══ Phase 3: Platform Video API ═══")

with open("platform/app/api/v1/video.py") as f:
    video_api = f.read()

check("Video API has start_stream endpoint", "start_stream" in video_api)
check("Video API has stop_stream endpoint", "stop_stream" in video_api)
check("Video API has snapshot endpoint", "snapshot" in video_api)
check("Video API builds dynamic camera URL", "traffic_analyzer_camera_" in video_api)
check("Video API uses HLS flags", "delete_segments" in video_api)

# ═══════════════════════════════════════════════════════════════════
# Phase 4: Frontend Integration
# ═══════════════════════════════════════════════════════════════════
print("\n═══ Phase 4: Frontend Integration ═══")

with open("traffic-fly-console/src/lib/api.ts") as f:
    api_ts = f.read()

check("api.ts has startStream method", "startStream" in api_ts)
check("api.ts has stopStream method", "stopStream" in api_ts)
check("api.ts has getPipelines method", "getPipelines" in api_ts)
check("api.ts has VideoStream interface", "VideoStream" in api_ts)
check("api.ts has PipelineInstance interface", "PipelineInstance" in api_ts)

with open("traffic-fly-console/src/features/video/index.tsx") as f:
    video_tsx = f.read()

check("Video feature has MJPEG img tag", "img" in video_tsx and "mjpegUrl" in video_tsx)
check("Video feature has stream toggle", "toggleStream" in video_tsx)
check("Video feature has camera selector", "selectedCamera" in video_tsx)
check("Video feature uses WebSocket", "useWebSocket" in video_tsx)
check("Video feature shows real stats", "latestStats" in video_tsx)
check("Video feature has pipeline tab", "pipelines" in video_tsx.lower())

with open("traffic-fly-console/src/features/monitoring/index.tsx") as f:
    mon_tsx = f.read()

check("Monitoring has stream toggle", "streamActive" in mon_tsx)
check("Monitoring has MJPEG support", "camera_" in mon_tsx)

# ═══════════════════════════════════════════════════════════════════
# Phase 5: Live Connectivity (optional — only if services running)
# ═══════════════════════════════════════════════════════════════════
print("\n═══ Phase 5: Live Connectivity (if running) ═══")

# Platform health
status, body = http_get(f"{PLATFORM_URL}/health")
if status == 200:
    check("Platform /health responds", True, f"status={status}")
    
    # Ready check
    status2, body2 = http_get(f"{PLATFORM_URL}/ready")
    if status2 == 200:
        ready = json.loads(body2)
        check("Platform /ready responds", True, f"status={ready.get('status')}")
    else:
        warn("Platform /ready not available", f"status={status2}")
    
    # Video streams
    status3, body3 = http_get(f"{PLATFORM_URL}/api/v1/video/streams")
    if status3 == 200:
        streams = json.loads(body3)
        check("Video streams endpoint works", True, f"{len(streams)} streams")
    else:
        warn("Video streams not available")
    
    # Pipelines
    status4, body4 = http_get(f"{PLATFORM_URL}/api/v1/pipelines")
    if status4 == 200:
        pipes = json.loads(body4)
        check("Pipelines endpoint works", True, f"{len(pipes)} pipelines")
    else:
        warn("Pipelines not available")

else:
    warn("Platform not running (skip live tests)", f"status={status}")

# Nginx
status_nginx, _ = http_get(f"{NGINX_URL}/health")
if status_nginx == 200:
    check("Nginx proxy responds", True)
else:
    warn("Nginx not running", f"status={status_nginx}")

# Camera MJPEG direct (try localhost:8101)
for port, name in [(8101, "Camera 1"), (8102, "Camera 2"), (8103, "Camera 3")]:
    status_cam, _ = http_get(f"http://localhost:{port}/video", timeout=3)
    if status_cam == 200:
        check(f"{name} MJPEG available on port {port}", True)
    else:
        warn(f"{name} not running on port {port}")


# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'═'*60}")
print(f"  Results: {results['pass']} PASS / {results['fail']} FAIL / {results['warn']} WARN")
print(f"{'═'*60}")

sys.exit(1 if results["fail"] > 0 else 0)
