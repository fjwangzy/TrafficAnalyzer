# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目文档索引

**所有开发工作前必须先阅读相关文档。**

| 文档 | 说明 |
|------|------|
| `docs/CLAUDE.md` | **Claude 长期协作规则**（开发规则、架构原则、禁止事项、模块边界） |
| `docs/ARCHITECTURE.md` | 系统架构（进程模型、管道设计、微服务数据路径） |
| `docs/BUSINESS_LOGIC.md` | 核心业务逻辑（检测、跟踪、道路分配、统计计算） |
| `docs/PROJECT_STRUCTURE.md` | 项目结构和文件说明 |
| `docs/API_CONTRACTS.md` | API 契约（Kafka 消息格式、Flask 端点、InfluxDB 查询） |
| `docs/DATABASE_SCHEMA.md` | 数据库结构（InfluxDB measurement、Kafka topic） |
| `docs/DECISIONS.md` | 架构决策记录（ADR） |
| `docs/TASKS.md` | 技术债清单和待办事项 |

## Project Overview

TrafficAnalyzer is a roundabout traffic analysis system that processes video (MP4 or RTSP streams) to detect vehicles, track them, compute per-road congestion statistics, and visualize results via Grafana dashboards. This is the `feature/influx` branch — a multi-camera production version using InfluxDB as the time-series database.

Code comments and README are primarily in Chinese/Russian. All user-facing logs, config comments, and variable names are a mix of Chinese and English.

## Build and Run

### Docker Compose (full stack)

```bash
# Create .env file with credentials first (see README for template)
docker compose -p traffic_analyzer up -d --build
```

This starts: Zookeeper, Kafka, Kafka-UI, InfluxDB, Telegraf, Grafana, Nginx, and one or more `traffic_analyzer_camera_{n}` backend containers.

### Local Python (no microservices)

```bash
python -m pip install --upgrade pip
pip install "numpy<2"
pip install cython_bbox==0.1.5 lap==0.4.0
pip install torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

# Run without Kafka (results shown via Flask at http://127.0.0.1:8100/)
python main_optimized.py pipeline.send_info_kafka=False
```

### Generate road lane polygons for a new video

```bash
python generate_lanes.py <video_path> <output_json_path>
# Click 4 points per lane polygon; output is a JSON file compatible with configs/ roads format
```

### Export / update Grafana dashboards

`export_dashboards.py`, `fetch_dashboard.py`, `update_dashboards.py` are helper scripts at the repo root for Grafana dashboard management.

## Configuration

Uses **Hydra** (`hydra-core`). Main config: `configs/app_config.yaml`. Config values can be overridden via CLI (e.g., `python main_optimized.py pipeline.save_video=True`) or environment variables (via `${oc.env:VAR_NAME}`).

**Required env vars** (set in `docker-compose.yaml` per camera container, or defaulted in `main*.py`):

- `VIDEO_SRC` — path to MP4 file, RTSP URL, or camera index (int)
- `ROADS_JSON` — path to JSON file with road polygon coordinates (4 vertices per road, flat list of 8 floats)
- `TOPIC_NAME` — Kafka topic for this camera's statistics (e.g., `statistics_1`)
- `CAMERA_ID` — integer camera ID used in Kafka payloads

## Architecture

### Node-based pipeline

Frames flow through a chain of **nodes**, each enriching a shared `FrameElement` object with more data:

```
VideoReader → DetectionTrackingNodes → TrackerInfoUpdateNode → CalcStatisticsNode
  → [KafkaProducerNode] → ShowNode → [VideoSaverNode | FlaskServerVideoNode]
```

- **`elements/FrameElement.py`** — the shared data carrier. Starts with raw `frame`, `timestamp`, `roads_info`. Nodes progressively populate `detected_*`, `tracked_*`, `id_list`, `buffer_tracks`, `info`, and `frame_result`.
- **`elements/TrackElement.py`** — per-vehicle tracking state (ID, first/last seen timestamp, originating road).
- **`elements/VideoEndBreakElement.py`** — sentinel that signals end-of-stream; all nodes must pass it through.

### Node responsibilities

| Node                     | File                              | Purpose                                                                                                                                                                                           |
| ------------------------ | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VideoReader`            | `nodes/VideoReader.py`            | Generator yielding `FrameElement` per frame from MP4/RTSP/webcam. Loads road polygon JSON.                                                                                                        |
| `DetectionTrackingNodes` | `nodes/DetectionTrackingNodes.py` | YOLOv8 inference + ByteTrack tracking. Populates `detected_*` and `tracked_*` fields.                                                                                                             |
| `TrackerInfoUpdateNode`  | `nodes/TrackerInfoUpdateNode.py`  | Maintains `buffer_tracks` dict of active `TrackElement`s. Assigns each track a `start_road` when its bbox center first enters a road polygon. Prunes tracks older than `buffer_analytics` window. |
| `CalcStatisticsNode`     | `nodes/CalcStatisticsNode.py`     | Computes `cars_amount` (smoothed via sliding window) and `roads_activity` (vehicles/minute per road). Writes to `frame_element.info`.                                                             |
| `KafkaProducerNode`      | `nodes/KafkaProducerNode.py`      | Sends `info` dict to Kafka every `how_often_sec` seconds.                                                                                                                                         |
| `ShowNode`               | `nodes/ShowNode.py`               | Renders bounding boxes, road polygons, FPS, and statistics overlay onto `frame_result`.                                                                                                           |
| `VideoSaverNode`         | `nodes/VideoSaverNode.py`         | Writes `frame_result` to MP4 file.                                                                                                                                                                |
| `FlaskServerVideoNode`   | `nodes/FlaskServerVideoNode.py`   | Streams `frame_result` via Flask MJPEG endpoint at `/video`.                                                                                                                                      |

### Entry points

- **`main.py`** — single-process sequential loop. Simple but slow.
- **`main_optimized.py`** — 3-process multiprocessing pipeline (reader+detection | tracker+stats+kafka | show+save+flask). The recommended default for MP4 files. Queues have `maxsize=50`.
- **`main_stream_optimized.py`** — 2-process variant for live RTSP. Reader process drops frames when queue is full (`maxsize=2`) to always process the latest frame.
- **`main_stream_optimized_v2.py`** — same as above but adds `process.is_alive()` cross-checks so if one process dies, the other exits too.

### Microservices data path

```
Backend (KafkaProducerNode) → Kafka topic statistics_{n}
  → Telegraf (kafka_consumer input) → InfluxDB (database: "influx")
  → Grafana (dashboard per camera)
```

- **Telegraf config**: `services/telegraf/telegraf.conf` — one `[[inputs.kafka_consumer]]` block per camera topic, each with a unique `name_override`.
- **Adding a new camera**: add a `traffic_analyzer_camera_{n}` service in `docker-compose.yaml` with distinct `VIDEO_SRC`, `ROADS_JSON`, `TOPIC_NAME`, `CAMERA_ID`; add a matching `[[inputs.kafka_consumer]]` in `telegraf.conf`; create a Grafana dashboard.
- **Nginx** (`services/nginx/nginx.conf`): reverse proxy aggregating all Flask video streams on port 8009.
- **Grafana**: provisioned via `services/grafana/provisioning/`; dashboards stored in `services/grafana/provisioning/dashboards/`.

### Key libraries

- **ultralytics** (YOLOv8) — object detection; weights in `weights/` (default: `uav_best.pt`, a custom UAV-trained model detecting COCO classes 2–9)
- **ByteTrack** — multi-object tracking (`byte_tracker/byte_tracker_model.py` + `byte_tracker/utils/`)
- **shapely** — point-in-polygon tests for road assignment (`utils_local/utils.py:intersects_central_point`)
- **kafka-python** — Kafka producer
- **Flask** — MJPEG video streaming server
- **Hydra** — hierarchical config management
- **OpenCV** — frame I/O, drawing, video encoding

### Road polygon format

JSON files in `configs/` (e.g., `entry_exit_lanes.json`). Keys are road IDs (strings "1"–"5"). Values are flat lists of 8 floats representing 4 (x, y) vertices of a quadrilateral polygon:

```json
{"1": [x1, y1, x2, y2, x3, y3, x4, y4], ...}
```

A vehicle is assigned to a road when the center of its bounding box falls inside the polygon (via `shapely.geometry.Polygon.contains`).

## Platform (Web Management Console)

The `platform/` directory contains a FastAPI-based web management console for monitoring intersections, managing drones, viewing trajectories, and configuring alerts. It was refactored from microservices to a **monolith** in 2026-05-29.

### Platform architecture

```
platform/
├── app/                          # Monolith application
│   ├── main.py                   # FastAPI app with lifespan management
│   ├── core/
│   │   ├── config.py             # Unified Settings (Pydantic)
│   │   └── database.py           # SQLAlchemy async engine
│   ├── api/v1/                   # REST endpoints
│   │   ├── auth.py               # JWT authentication
│   │   ├── intersections.py      # Intersection management
│   │   ├── drones.py             # Drone fleet management
│   │   ├── trajectories.py       # Vehicle trajectories
│   │   ├── alerts.py             # Alert rules & history
│   │   ├── video.py              # Video streams
│   │   ├── calibration.py        # Camera calibration
│   │   └── system.py             # System health
│   ├── kafka/
│   │   ├── consumer.py           # Kafka consumer (aiokafka)
│   │   └── ws_manager.py         # WebSocket pub/sub manager
│   ├── middleware/
│   │   └── auth.py               # JWT middleware
│   ├── services/
│   │   ├── auth_service.py       # User auth (PyJWT + bcrypt)
│   │   └── alert_engine.py       # Alert rule evaluation
│   ├── models/                   # SQLAlchemy models
│   ├── schemas/                  # Pydantic schemas
│   └── utils/
│       └── influx_query.py       # InfluxDB query helper
├── docker/
│   └── docker-compose.platform.yml  # Docker Compose for platform stack
├── scripts/
│   └── run_local.py              # Local development launcher
├── Dockerfile                    # Platform container image
└── pyproject.toml                # Dependencies (hatchling build)
```

### Platform dependencies

- **FastAPI** + **uvicorn** — web framework
- **SQLAlchemy** (async) + **asyncpg** — PostgreSQL ORM
- **PyJWT** + **bcrypt** — authentication (NOT python-jose, which has ARM64 issues)
- **aiokafka** — Kafka consumer for real-time data
- **influxdb** — time-series queries (InfluxQL, not Flux)
- **websockets** — real-time updates to frontend

### Running the platform

**Docker Compose (full stack):**
```bash
cd platform/docker
docker compose -f docker-compose.platform.yml up -d --build
# Platform: http://localhost:8000
# Frontend: http://localhost:8080
```

**Local development:**
```bash
cd platform
pip install -e .
python scripts/run_local.py
# Platform: http://localhost:8000
```

### Frontend (traffic-fly-console/)

The frontend is a Vue.js SPA served via nginx. It proxies `/api/` and `/ws/` to the platform service.

**Important:** `traffic-fly-console/nginx.conf` must proxy to `platform:8000` (not `gateway:8000`).

### Legacy microservices directories

The following directories are **deprecated** and should be removed after verification:
- `platform/gateway/` — former API gateway
- `platform/services/` — former microservices (flight, vision, operations)
- `platform/shared/` — former shared library
- `platform/frontend/` — former frontend (now at `traffic-fly-console/`)
