#!/usr/bin/env python3
"""Live API test suite — tests all endpoints against running services."""
import json
import sys
import time
import urllib.request
import urllib.error

PLATFORM = "http://localhost:8000"
NGINX = "http://localhost:8009"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidXNlcm5hbWUiOiJhZG1pbiIsInJvbGUiOiJ2aWV3ZXIiLCJleHAiOjE3ODAxNTAyMTl9.vx30ZsNQEsYkkp8xf4s3SdyFZBFWh2I1bpmCdVCOUA0"

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


def get(url: str, timeout: int = 5):
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except:
            return e.code, body.decode()
    except Exception as e:
        return None, str(e)


def post(url: str, data: dict = None, timeout: int = 10):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except:
            return e.code, body.decode()
    except Exception as e:
        return None, str(e)


def delete(url: str, timeout: int = 5):
    try:
        req = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return None, str(e)


# ═══════════════════════════════════════════════════
print("\n═══ Phase A: Platform Health ═══")

s, d = get(f"{PLATFORM}/health")
check("GET /health", s == 200, f"status={s}")

s, d = get(f"{PLATFORM}/ready")
check("GET /ready", s == 200 and d.get("status") in ("ready", "degraded"), f"status={d.get('status') if d else 'N/A'}")
if d:
    svcs = d.get("services", {})
    check("  - database", svcs.get("database") == "healthy")
    check("  - kafka", svcs.get("kafka") == "healthy")
    check("  - timescaledb", svcs.get("timescaledb") == "healthy")

s, d = get(f"{PLATFORM}/")
check("GET / (root)", s == 200 and d.get("service") == "traffic-platform")

# ═══════════════════════════════════════════════════
print("\n═══ Phase B: Nginx Proxy ═══")

s, d = get(f"{NGINX}/health")
check("Nginx → /health proxy", s == 200, f"status={s}")

s, d = get(f"{NGINX}/ready")
check("Nginx → /ready proxy", s == 200, f"status={s}")

s, d = get(f"{NGINX}/api/v1/pipelines")
check("Nginx → /api/v1/pipelines proxy", s == 200, f"status={s}")

# ═══════════════════════════════════════════════════
print("\n═══ Phase C: Intersections API ═══")

s, d = get(f"{PLATFORM}/api/v1/intersections")
check("GET /intersections", s == 200)

s, d = get(f"{PLATFORM}/api/v1/intersections/summary")
check("GET /intersections/summary", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase D: Pipelines API ═══")

s, d = get(f"{PLATFORM}/api/v1/pipelines")
check("GET /pipelines (empty)", s == 200 and isinstance(d, list))

s, d = get(f"{PLATFORM}/api/v1/pipelines/summary")
check("GET /pipelines/summary", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase E: Video Streams API ═══")

s, d = get(f"{PLATFORM}/api/v1/video/streams")
check("GET /video/streams (empty)", s == 200)

# Start a stream (will fail without actual camera, but API should respond)
s, d = post(f"{PLATFORM}/api/v1/video/streams/1/start")
check("POST /video/streams/1/start", s == 200, f"status={d.get('status') if d else s}")

s, d = get(f"{PLATFORM}/api/v1/video/streams")
check("GET /video/streams (after start)", s == 200 and len(d) > 0)

# Stop
s, d = post(f"{PLATFORM}/api/v1/video/streams/1/stop")
check("POST /video/streams/1/stop", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase F: Alerts API ═══")

s, d = get(f"{PLATFORM}/api/v1/alerts")
check("GET /alerts", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase G: Drones API ═══")

s, d = get(f"{PLATFORM}/api/v1/drones")
check("GET /drones", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase H: System API ═══")

s, d = get(f"{PLATFORM}/api/v1/system/health")
check("GET /system/health", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase I: Calibration API ═══")

s, d = get(f"{PLATFORM}/api/v1/calibration/summary")
check("GET /calibration/summary", s == 200)

# ═══════════════════════════════════════════════════
print("\n═══ Phase J: WebSocket ═══")
try:
    import asyncio
    import websockets
    
    async def test_ws():
        async with websockets.connect(f"ws://localhost:8000/ws/realtime", open_timeout=5) as ws:
            # Subscribe
            await ws.send(json.dumps({"action": "subscribe", "channel": "uav_intersection:INT_camera_1"}))
            # Should get ack or just stay connected
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                return True, msg
            except asyncio.TimeoutError:
                return True, "connected (no message in 3s)"
    
    ok, msg = asyncio.run(test_ws())
    check("WebSocket connect + subscribe", ok, str(msg)[:60])
except ImportError:
    warn("websockets not installed, skip WS test")
except Exception as e:
    check("WebSocket connect + subscribe", False, str(e)[:80])

# ═══════════════════════════════════════════════════
print(f"\n{'═'*60}")
print(f"  Results: {results['pass']} PASS / {results['fail']} FAIL / {results['warn']} WARN")
print(f"{'═'*60}")
sys.exit(1 if results["fail"] > 0 else 0)
