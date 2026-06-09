# ARCHITECTURE.md — TrafficAnalyzer 系统架构

> 基于 commit `e69acee` 的真实代码分析。

## 系统总览

TrafficAnalyzer 是一个环形交叉路口交通分析系统。核心功能：从视频流（MP4 文件或 RTSP 实时流）中检测车辆、跟踪轨迹、计算每条道路的拥堵统计，并通过 Grafana 仪表盘可视化结果。

```
┌─────────────────────────────────────────────────────────┐
│                    视频源（MP4/RTSP/摄像头）                │
└─────────────────────┬───────────────────────────────────┘
                      │ cv2.VideoCapture
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   VideoReader (生成器)                    │
│  逐帧产出 FrameElement(source, frame, timestamp, roads)  │
│  注入遥测数据 + 车道多边形（如有配置）                      │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement
                      ▼
┌─────────────────────────────────────────────────────────┐
│             DetectionTrackingNodes                       │
│  YOLO11 检测 → detected_* + tracked_cls_ids              │
│  ByteTrack 跟踪 → tracked_* + id_list 字段               │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带检测结果）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             HomographyCalibrationNode                    │
│  遥测→H矩阵（Nadir/Oblique模式）或参考点→静态H            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             MotionCompensationNode                       │
│  GPS锚定世界坐标系、无人机位移/速度矢量、悬停检测          │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带运动补偿字段）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             TrackerInfoUpdateNode                        │
│  维护 buffer_tracks 字典（TrackElement）                  │
│  道路分配 + 出口道路检测 + motor/non_motor分类            │
│  轨迹点累积 + 完成轨迹发射（含世界坐标）                  │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             SpeedEstimationNode                          │
│  透视变换+帧间位移→车速(km/h)，减去无人机速度             │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             DirectionFlowNode                            │
│  世界坐标系航向→左转/直行/右转/掉头分类+排队检测          │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             LaneAnalysisNode（数据驱动）                  │
│  车道级流量/排队长度/车头时距（有标注时自动输出）          │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             TrajectoryNode                               │
│  轨迹转向分类 + 世界坐标轨迹输出                          │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ConflictDetectionNode（默认关闭）             │
│  机非冲突TTC检测 + 世界坐标位置输出                       │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             CalcStatisticsNode                           │
│  cars_amount + roads_activity                            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             KafkaProducerNode                            │
│  statistics_{n} + track_complete_{n} + conflicts_{n}     │
│  含方向流量/车道统计/车速/无人机位置/冲突计数             │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ShowNode (supervision 库)                    │
│  圆角边框+ID+道路多边形+车速标签+方向流量+轨迹尾迹+FPS    │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│  VideoSaverNode（可选）    │  │ FlaskServerVideoNode     │
│  写入 MP4 文件             │  │ MJPEG 流 → /video        │
└──────────────────────────┘  └──────────────────────────┘
```

## 进程模型（4 种入口）

### main.py — 单进程顺序模式

- **用途**：调试、理解管道逻辑
- **特点**：所有节点在同一进程内顺序执行
- **缺点**：YOLO 推理阻塞后续节点，吞吐量最低

### main_optimized.py — 三进程并行模式（唯一生产入口）

- **进程 1**：VideoReader + DetectionTrackingNodes（CPU 读取 + GPU 推理）
- **进程 2**：Homography + MotionCompensation + TrackerInfoUpdate + Speed + Direction + Lane + Trajectory + Conflict + CalcStatistics + KafkaProducer（CPU 密集）
- **进程 3**：ShowNode + VideoSaver + FlaskServer（渲染 + IO）
- **队列**：maxsize=50，进程间通过 `multiprocessing.Queue` 传递 FrameElement
- **健康检查**：下游进程通过 `get(timeout=10)` + `is_alive()` 检测上游崩溃并自动退出
- **为什么这样设计**：将 GPU 推理、CPU 计算、IO 操作分离到不同进程，利用多核并行
- **运动补偿位置**：MotionCompensationNode 在进程 2 中，位于 HomographyCalibrationNode 之后
- **历史**：整合了旧版 `main_stream_optimized.py`（2 进程 RTSP v1）和 `main_stream_optimized_v2.py`（2 进程 RTSP v2 + 健康检查）的特性

## 微服务数据路径

```
Backend (KafkaProducerNode)
  │ statistics_{n}:  {camera_id, cars, road_1..5, direction_flow, lane_stats, avg_speed_kmh, drone_position, ...}
  │ track_complete_{n}: {track_id, turn_behavior, vehicle_class, trajectory_px, trajectory_world_m, ...}
  │ conflicts_{n}:   {motor_id, non_motor_id, distance_m, ttc_sec, severity, motor_position_m, ...}
  ▼
Kafka topics (3 个 per camera)
  │
  ▼
Telegraf (kafka_consumer input, json data_format)
  │ name_override: camera_{n} (仅 statistics topic)
  ▼
InfluxDB 1.8 (database: "influx")
  │ measurement: camera_{n}
  │ fields: cars, road_1..5, avg_speed_kmh, direction_flow_*, ...
  ▼
Grafana (provisioned dashboards)
  ▼
Dashboard panels: 车辆数 + 道路拥堵 + 车速 + 方向流量

Platform Consumer (platform/app/kafka/consumer.py)
  │ 订阅 (statistics|track_complete|conflicts|telemetry)_.*
  │
  │ statistics_* → _handle_stats()
  │   ├── WebSocket → intersection:{id}
  │   ├── AlertEngine.check_stats()
  │   └── drone_store.update_drone_from_stats()
  │
  │ track_complete_* → _handle_track_complete()
  │   ├── WebSocket → intersection:{id}
  │   └── AlertEngine.on_anomaly_track() (if is_anomaly)
  │
  │ conflicts_* → _handle_conflict()
  │   ├── WebSocket → intersection:{id}
  │   └── AlertEngine._create_alert() (P1/P2)
  │
  │ telemetry_* → _handle_telemetry()
  │   ├── WebSocket → telemetry:{drone_id}
  │   └── drone_store.update_drone_telemetry()
  │
  ▼
Platform Web UI: 轨迹回放 + 冲突告警 + 路口热力图 + 实时遥测

PipelineManager (platform/app/services/pipeline_manager.py)
  │ 管理检测管道生命周期
  │ POST /api/v1/pipelines → 启动子进程(python main_optimized.py)
  │ DELETE /api/v1/pipelines/{id} → SIGTERM → 10s → SIGKILL
  │ 后台监控任务: 每5s检查进程存活状态
  ▼
检测管道子进程: GPU推理 + CPU计算 + Kafka输出
```

### Nginx 视频流聚合

```
http://localhost:8009/camera_{n}
  → proxy_pass http://traffic_analyzer_camera_{n}:8100/video
```

使用正则 `~ ^/camera_(\d+)$` 动态路由到对应摄像头容器的 Flask MJPEG 端点。

### WebSocket 频道模型

前端通过 `useWebSocket` hook 订阅频道，平台 Kafka consumer 按频道广播：

| 频道名 | 消息类型 | 来源 | 前端页面 |
|---|---|---|---|
| `intersection:{id}` | stats, track_complete, conflict | Kafka stats/track/conflict topics | Monitoring, Dashboard |
| `alerts` | alert_new | AlertEngine | Dashboard |
| `system` | system_metrics | Kafka system_metrics topic | Dashboard |
| `telemetry:{drone_id}` | telemetry | Kafka telemetry topic | Drones |

订阅协议：
```json
// 订阅
{"action": "subscribe", "channel": "intersection:INT_camera_1"}
// 推送
{"channel": "intersection:INT_camera_1", "type": "stats", "data": {...}, "ts": 1234567890}
```

### 遥测数据源

| 源 | 文件 | 格式 | 场景 |
|---|---|---|---|
| MQTT 实时 | `services/TelemetrySubscriber.py` | DJI Cloud API JSON | 生产（直播无人机） |
| JSON 文件 | `services/TelemetryFileReader.py` | DJI Cloud API JSON 导出 | 离线回放 |
| SRT 字幕 | `services/SrtTelemetryParser.py` | DJI 视频字幕 (.srt) | 离线回放（逐帧精确） |

三种源实现相同的 `get_nearest(timestamp) -> dict` 接口，VideoReader 通过 `telemetry.source` 配置切换。

## 配置系统

使用 **Hydra** 分层配置管理：

- 主配置：`configs/app_config.yaml`
- 日志配置：`configs/hydra/job_logging/custom.yaml`
- 环境变量覆盖：`${oc.env:VIDEO_SRC}`、`${oc.env:TOPIC_NAME}` 等
- CLI 覆盖：`python main_optimized.py pipeline.save_video=True`

**为什么选择 Hydra**：原始项目来自俄罗斯团队，Hydra 提供了灵活的配置组合能力，允许通过环境变量为不同摄像头容器复用同一配置文件。

## 关键设计决策

### 1. FrameElement 作为共享数据载体

**决策**：所有节点通过读写同一个 FrameElement 对象来协作，而不是返回值或事件驱动。
**原因**：视频处理管道是严格线性的，每个节点只需要在上一节点的输出上追加数据。共享对象避免了数据拷贝和复杂的消息路由。
**代价**：FrameElement 的字段随节点增多而膨胀，新节点需要理解所有上游字段。

### 2. VideoEndBreakElement 哨兵模式

**决策**：使用特殊的 VideoEndBreakElement 类（继承 FrameElement）作为流结束信号，每个节点通过 `isinstance()` 检查来传递它。
**原因**：在 multiprocessing.Queue 中，无法发送 Python 异常或关闭信号。哨兵对象可以被序列化通过队列，每个节点看到后执行清理并退出。
**代价**：每个节点的 process() 方法开头都需要 isinstance 检查。

### 3. ByteTrack 而非 DeepSORT

**决策**：使用 ByteTrack 作为多目标跟踪算法。
**原因**：ByteTrack 利用低置信度检测框进行第二轮关联，在车辆密集场景（环形路口）中跟踪精度更高。不需要外观特征提取网络，推理更快。
**代价**：跟踪完全基于 IOU，当车辆被遮挡超过 track_buffer 帧后会丢失 ID。

### 4. 硬编码 5 条道路

**决策**：CalcStatisticsNode 和 KafkaProducerNode 中硬编码了 5 条道路（road_1..5）。
**原因**：原始项目针对特定的环形交叉路口设计，恰好有 5 条道路。
**代价**：增加或减少道路数量需要修改多个文件和 Grafana 仪表盘。这是最大的技术债之一。

### 5. 无人机运动补偿（2026-05-30）

**决策**：采用混合方案——GPS锚定世界坐标系 + 帧间遥测速度积分 + 悬停自动跳过。
**原因**：
- 无人机巡飞速度可达 12 m/s（43 km/h），不减去无人机速度会导致车速估计误差 ±43 km/h
- 云台偏航旋转会污染像素空间方向分类
- GPS提供绝对参考，帧间速度积分平滑GPS噪声

**实现**：
- `MotionCompensationNode`：注入 world_anchor（首10帧GPS均值）、drone_displacement（GPS增量）、drone_velocity（遥测速度矢量）
- `SpeedEstimationNode`：减去无人机速度矢量 → 真实地面车速
- `DirectionFlowNode`：世界坐标系航向（无人机>5m/s回退像素空间）
- 事件输出补充世界坐标（东北偏移米）

**已知限制**：
- 轨迹世界坐标在快速巡飞时误差=无人机速度×轨迹时长（12m/s×8s=96m）
- 方向分类在无人机>5m/s时降级为像素空间heading

**代价**：
- 依赖MQTT遥测数据（需DJI SDK或类似遥测源）
- 首10帧需等待GPS锚点初始化
- GPS丢失时保持上次位移（非绝对准确）

---

## 平台 Web 服务架构（platform/）

> 2026-05-29 从微服务重构为单体架构。

### 系统总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端（traffic-fly-console）                │
│                    Vue.js SPA + Nginx (:8080)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ /api/*  /ws/*
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    平台单体应用（platform/app）                    │
│                      FastAPI + Uvicorn (:8000)                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    JWT 认证中间件                             ││
│  │           （公开端点：/health, /ready, /auth/*, /docs）       ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│
│  │ auth.py  │ │intersec- │ │ drones.py│ │ alerts.py│ │system. ││
│  │          │ │tions.py  │ │          │ │          │ │py      ││
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘│
│       │            │            │            │           │      │
│  ┌────┴────────────┴────────────┴────────────┴───────────┴────┐ │
│  │                    业务逻辑层（services/）                   │ │
│  │   auth_service.py  │  alert_engine.py                       │ │
│  └────────┬───────────┴──────────────┬─────────────────────────┘ │
│           │                          │                           │
│  ┌────────┴────────┐    ┌────────────┴────────────┐             │
│  │   PostgreSQL    │    │   Kafka Consumer        │             │
│  │  （SQLAlchemy） │    │  （aiokafka）           │             │
│  └─────────────────┘    └────────────┬────────────┘             │
│                                      │                          │
│                           ┌──────────┴──────────┐               │
│                           │  WebSocket Manager  │               │
│                           │   （ws_manager.py） │               │
│                           └─────────────────────┘               │
│                                                                 │
│                           ┌─────────────────────┐               │
│                           │   InfluxDB Query    │               │
│                           │ （influx_query.py） │               │
│                           └─────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流

```
1. 用户认证流程：
   POST /api/v1/auth/login
     → auth.py
     → auth_service.authenticate_user()
     → PostgreSQL (users 表)
     → auth_service.create_access_token() (PyJWT)
     → 返回 JWT token

2. 实时数据推送流程：
   视频分析管道 → Kafka topic (statistics_*, detections_*, etc.)
     → KafkaConsumerService.consume_loop()
     → 解析消息类型
     → ws_manager.broadcast(channel, data)
     → WebSocket 客户端

3. 时序数据查询流程：
   GET /api/v1/trajectories?intersection_id=X&start=T1&end=T2
     → trajectories.py
     → influx_query.query_track_events()
     → InfluxDB 1.8 (InfluxQL)
     → 返回轨迹列表
```

### 关键设计决策

#### 1. 单体架构（2026-05-29 迁移）

**决策**：将 4 个微服务（gateway、operations、vision、flight）合并为单一 FastAPI 应用。
**原因**：

- 微服务增加了网络延迟、服务发现、分布式追踪等复杂度
- 团队规模小，不需要独立部署和扩展
- API 端点之间共享大量状态（Kafka 消费者缓存、WebSocket 连接池）
  **代价**：单一故障点，但通过优雅降级模式缓解

#### 2. 优雅降级模式

**决策**：应用启动时不要求所有依赖（DB、Kafka、InfluxDB）可用，而是在 lifespan 中尝试连接并记录状态。
**原因**：开发环境可能没有完整的基础设施栈，应用应该能够部分工作。
**实现**：`/ready` 端点返回各依赖的健康状态，客户端根据可用功能调整 UI。

#### 3. PyJWT 替代 python-jose

**决策**：使用 PyJWT 而非 python-jose 作为 JWT 库。
**原因**：python-jose 的 cryptography 依赖在 ARM64 架构上触发 SIGILL（exit code 132）。
**代价**：API 略有不同，但功能等价。

### 配置系统

使用 **Pydantic Settings** 管理环境变量：

- 主配置类：`platform/app/core/config.py:Settings`
- 环境变量前缀：无（直接使用变量名）
- 默认值：适合本地开发（localhost）
- Docker 覆盖：通过 `docker-compose.platform.yml` 的 `environment` 字段

**关键环境变量**：

- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL
- `KAFKA_BOOTSTRAP` — Kafka broker
- `INFLUX_HOST`, `INFLUX_PORT`, `INFLUX_DATABASE` — InfluxDB
- `JWT_SECRET_KEY`, `JWT_ALGORITHM` — JWT 签名
