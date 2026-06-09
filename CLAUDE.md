# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
**模型不支持图片**

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
| `docs/2026-05-29-srt-traffic-situation-design.md` | 交通态势感知系统设计（方向/车道/轨迹/冲突） |
| `docs/2026-05-30-drone-motion-compensation-design.md` | 无人机运动补偿 + 事件世界坐标设计 |
| `docs/2026-05-30-pipeline-platform-integration.md` | **视频检测流×平台整合方案**（Kafka对齐、PipelineManager、docker-compose统一） |
| `docs/2026-05-31-uav-traffic-perception-system-design.md` | **总体技术设计方案**（背景/架构/模型/数据/平台/实施路径/风险/演进，完整版） |
| `docs/test_report_inter_xqh.md` | 端到端测试报告（inter_xqh视频+SRT遥测，49/49 PASS） |
| `docs/superpowers/specs/` | 设计规格文档目录 |

## 文档维护规则
每次完成任务后，必须同步更新相关文档。

## 快速验证
### 管道端到端测试
```bash
# 使用 inter_xqh 视频 + SRT 遥测（需 YOLO 权重 weights/uav_best.pt）
python test_pipeline_inter_xqh.py
# 预期: 49 PASS / 0 FAIL（CPU上约3分钟，GPU约1分钟）
```

### 平台启动
```bash
cd platform
pip install -e .
python scripts/run_local.py
# 访问 http://localhost:8000 — 43 条 API 路由
# /api/v1/pipelines — 管道管理
# /api/v1/drones — 无人机管理
# /api/v1/intersections — 路口管理
```

### Docker 全栈
```bash
docker compose -f ./docker-compose.yaml -f ./docker-compose.test.yaml -p traffic_analyzer up -d --build
# Kafka:9092, InfluxDB:8087, Platform:8000, Grafana:3111
```


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
VideoReader → DetectionTrackingNodes → HomographyCalibrationNode → MotionCompensationNode
  → TrackerInfoUpdateNode → SpeedEstimationNode → DirectionFlowNode → LaneAnalysisNode
  → TrajectoryNode → ConflictDetectionNode → CalcStatisticsNode
  → [KafkaProducerNode] → ShowNode → [VideoSaverNode | FlaskServerVideoNode]
```

- **`elements/FrameElement.py`** — the shared data carrier. Starts with raw `frame`, `timestamp`, `roads_info`. Nodes progressively populate `detected_*`, `tracked_*`, `id_list`, `buffer_tracks`, `info`, `homography_matrix`, `drone_displacement_m`, `direction_stats`, `completed_tracks`, `conflict_events`, and `frame_result`.
- **`elements/TrackElement.py`** — per-vehicle tracking state (ID, first/last seen timestamp, originating road, speed, trajectory, vehicle_class, direction_class).
- **`elements/VideoEndBreakElement.py`** — sentinel that signals end-of-stream; all nodes must pass it through.

### Node responsibilities

| Node                        | File                                   | Purpose                                                                                                                                                                                              |
| --------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VideoReader`               | `nodes/VideoReader.py`                 | Generator yielding `FrameElement` per frame. Loads road polygon JSON. Injects telemetry + lane polygons.                                                                                             |
| `DetectionTrackingNodes`    | `nodes/DetectionTrackingNodes.py`      | YOLO11 inference + ByteTrack tracking. Preserves YOLO class IDs in `tracked_cls_ids`.                                                                                                                |
| `HomographyCalibrationNode` | `nodes/HomographyCalibrationNode.py`   | Computes per-frame H matrix from telemetry (Nadir/Oblique) or static reference points.                                                                                                               |
| `MotionCompensationNode`    | `nodes/MotionCompensationNode.py`      | GPS-anchored world frame. Injects `drone_displacement_m`, `drone_velocity_ms`, `is_hovering`, `gimbal_yaw_delta`.                                                                                    |
| `TrackerInfoUpdateNode`     | `nodes/TrackerInfoUpdateNode.py`       | Maintains `buffer_tracks`. Road assignment, exit_road detection, motor/non_motor classification, trajectory accumulation, completed_tracks emission (with world coordinates).                        |
| `SpeedEstimationNode`       | `nodes/SpeedEstimationNode.py`         | Speed in km/h via homography + frame displacement. Subtracts drone velocity vector. EMA smoothing.                                                                                                    |
| `DirectionFlowNode`         | `nodes/DirectionFlowNode.py`           | Left/straight/right/U-turn classification via world-coordinate heading. Queue detection. Headway tracking.                                                                                            |
| `LaneAnalysisNode`          | `nodes/LaneAnalysisNode.py`            | Lane-level flow, queue length, headway. Data-driven (auto-skips when no lane polygons).                                                                                                              |
| `TrajectoryNode`            | `nodes/TrajectoryNode.py`              | Turn behavior classification + world-coordinate trajectory output (`trajectory_world_m`).                                                                                                            |
| `ConflictDetectionNode`     | `nodes/ConflictDetectionNode.py`       | Motor/non-motor conflict via TTC + proximity. World-coordinate positions. `enabled: false` by default.                                                                                                |
| `CalcStatisticsNode`        | `nodes/CalcStatisticsNode.py`          | Computes `cars_amount` (smoothed) and `roads_activity` (vehicles/minute per road).                                                                                                                    |
| `KafkaProducerNode`         | `nodes/KafkaProducerNode.py`           | Multi-topic: `statistics_{n}`, `track_complete_{n}`, `conflicts_{n}`. Sends every `how_often_sec` seconds. Includes direction_flow, drone_position, is_hovering.                                     |
| `ShowNode`                  | `nodes/ShowNode.py`                    | Renders bounding boxes, road polygons, speed labels, direction overlay (S:/L:/R:), lane polygons, FPS, statistics. Uses **supervision** library (`RoundBoxAnnotator`, `LabelAnnotator`, `TraceAnnotator`, `MaskAnnotator`) for polished visualization. |
| `VideoSaverNode`            | `nodes/VideoSaverNode.py`              | Writes `frame_result` to MP4 file.                                                                                                                                                                   |
| `FlaskServerVideoNode`      | `nodes/FlaskServerVideoNode.py`        | Streams `frame_result` via Flask MJPEG endpoint at `/video`.                                                                                                                                         |

### Entry points

- **`main.py`** — single-process sequential loop. Debug only.
- **`main_optimized.py`** — 3-process multiprocessing pipeline (reader+detection | tracker+stats+kafka | show+save+flask). The **only** production entry point. Includes process health checks (is_alive + queue timeout) from the old stream variants. Queues have `maxsize=50`.

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

### Telemetry sources

| Source | File | Format | Usage |
|---|---|---|---|
| MQTT real-time | `services/TelemetrySubscriber.py` | DJI Cloud API JSON | Production (live drone) |
| JSON file | `services/TelemetryFileReader.py` | DJI Cloud API JSON export | Offline replay |
| SRT subtitle | `services/SrtTelemetryParser.py` | DJI video subtitle (.srt) | Offline replay (frame-accurate) |

All implement the same `get_nearest(timestamp) -> dict` interface, so VideoReader can switch between them transparently via `telemetry.source` config.

### Test scripts

| Script | Purpose |
|---|---|
| `test_pipeline_inter_xqh.py` | Full pipeline E2E test with 4K drone video + SRT telemetry (49 checks) |
| `test_pipeline_no_yolo.py` | Pipeline test without YOLO (for CI without GPU) |

### Test data

- `test_videos/inter_xqh/` — DJI M300 drone video (4K@30fps, 16.5min) + SRT telemetry (29,741 records) + flight plan

### Key libraries

- **ultralytics** (YOLO11) — object detection; weights in `weights/` (default: `uav_best.pt`, a custom UAV-trained model detecting COCO classes 2–9)
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
│   ├── api/v1/                   # REST endpoints (43 routes)
│   │   ├── auth.py               # JWT authentication
│   │   ├── intersections.py      # Intersection management + drone enrichment
│   │   ├── drones.py             # Drone fleet management
│   │   ├── pipelines.py          # Pipeline lifecycle API (start/stop/monitor)
│   │   ├── trajectories.py       # Vehicle trajectories
│   │   ├── alerts.py             # Alert rules & history
│   │   ├── video.py              # Video streams (HLS)
│   │   ├── calibration.py        # Camera calibration
│   │   └── system.py             # System health + pipeline status
│   ├── kafka/
│   │   ├── consumer.py           # Kafka consumer (aiokafka)
│   │   └── ws_manager.py         # WebSocket pub/sub manager
│   ├── middleware/
│   │   └── auth.py               # JWT middleware
│   ├── services/
│   │   ├── auth_service.py       # User auth (PyJWT + bcrypt)
│   │   ├── alert_engine.py       # Alert rule evaluation
│   │   └── pipeline_manager.py   # Pipeline lifecycle (subprocess管理)
│   ├── models/
│   │   └── drone_store.py        # In-memory drone state (Kafka实时更新)
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

### Platform Kafka Consumer

The platform subscribes to all pipeline topics via regex pattern `(statistics|track_complete|conflicts|telemetry)_.*` and routes messages to WebSocket channels:

| Topic pattern | msg_type | Handler | WebSocket channel |
|---|---|---|---|
| `statistics_*` | `stats` | `_handle_stats()` | `intersection:{id}` |
| `track_complete_*` | `track_complete` | `_handle_track_complete()` | `intersection:{id}` |
| `conflicts_*` | `conflict` | `_handle_conflict()` | `intersection:{id}` + `alerts` |
| `telemetry_*` | `telemetry` | `_handle_telemetry()` | `telemetry:{drone_id}` |

Stats messages also update `drone_store` via `update_drone_from_stats()` (extracts `drone_position` field). Telemetry messages update via `update_drone_telemetry()`.

### PipelineManager

`PipelineManager` manages detection pipeline lifecycle as child subprocesses. It spawns `python main_optimized.py` with env vars (`VIDEO_SRC`, `ROADS_JSON`, `TOPIC_NAME`, `CAMERA_ID`), monitors health via background task, and supports graceful shutdown (SIGTERM → 10s → SIGKILL).

### Frontend (traffic-fly-console/)

The frontend is a **React** SPA (Vite + TypeScript + Tailwind CSS). It uses:
- `useWebSocket` hook for real-time channel subscriptions (`intersection:{id}`, `alerts`, `system`, `telemetry:{drone_id}`)
- `trafficApi` service for REST calls to the platform
- React Query for data fetching and caching
- login user: `admin` , password:`admin123`
**Important:** `traffic-fly-console/nginx.conf` must proxy to `platform:8000` (not `gateway:8000`).

### Legacy microservices directories

The following directories are **deprecated** and should be removed after verification:
- `platform/gateway/` — former API gateway
- `platform/services/` — former microservices (flight, vision, operations)
- `platform/shared/` — former shared library
- `platform/frontend/` — former frontend (now at `traffic-fly-console/`)
