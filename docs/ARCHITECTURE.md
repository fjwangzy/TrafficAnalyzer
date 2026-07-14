# ARCHITECTURE.md — TrafficAnalyzer 系统架构

> 当前实现说明基于 commit `84c6bd6` 的真实代码分析；标记为“目标态”的内容依据
> ADR-019（2026-07-13）编制，尚需代码、数据库迁移和 Compose 改造后才视为已实施。

## 系统总览

TrafficAnalyzer 是智慧交通大项目下的无人机 AI 交通分析子系统。核心功能是从视频流
（MP4 文件或 RTSP 实时流）中检测车辆、跟踪轨迹、计算道路与车道指标、识别冲突和
形成可复核事件。目标态由无人机平台前端提供实时态势与历史查询，不再依赖 Grafana。

### 架构状态说明

- **当前实现**：代码和 Compose 中仍存在 `statistics_*` 等旧 Topic、Telegraf、InfluxDB、
  Grafana 和 `InfluxQuery`；以下保留这些描述用于迁移核对，不能据此认定为目标架构。
- **目标态（Accepted）**：PostgreSQL 连接数据库固定为 `road9`，启用 TimescaleDB 扩展；
  无人机平台消息名和平台自建物理表名统一以 `uav_` 开头；废弃
  Kafka → Telegraf → InfluxDB → Grafana 链路。
- **实施判定**：只有代码、数据库迁移、配置、Compose、回归测试和数据核验全部完成，
  目标态才可从“规划”改为“已实施”。

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
│             LaneDetectionNode（模型驱动，可选）           │
│  YOLO 分割模型检测车道标线/路面→稳定车道多边形           │
│  优先级：人工标注 > 模型检测 > 轨迹推断                  │
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
│             AutoLaneInferenceNode（轨迹驱动）             │
│  自动发现车道中心线 + 各方向流量/排队/车头时距            │
│  无需人工标注 — 从轨迹空间聚类自动推断                    │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ConflictDetectionNode（默认启用）             │
│  右转/左转机非 near-miss 证据漏斗 + 冲突点世界坐标输出      │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             CalcStatisticsNode                           │
│  cars_amount + roads_activity                            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             KafkaProducerNode                            │
│  当前：statistics_{n} / track_complete_{n} / conflicts_{n}│
│  目标：对应名称统一增加 uav_ 前缀                         │
│  含方向流量/车道统计/自动车道/车速/无人机位置/冲突计数   │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ShowNode (supervision 库)                    │
│  圆角边框+ID+道路多边形+车速标签+方向流量+轨迹尾迹       │
│  +自动车道中心线+FPS                                     │
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
- **进程 2**：Homography + MotionCompensation + TrackerInfoUpdate + Speed + Direction + LaneDetection + LaneAnalysis + Trajectory + AutoLaneInference + Conflict + CalcStatistics + KafkaProducer（CPU 密集）
- **进程 3**：ShowNode + VideoSaver + FlaskServer（渲染 + IO）
- **队列**：maxsize=50，进程间通过 `multiprocessing.Queue` 传递 FrameElement
- **健康检查**：下游进程通过 `get(timeout=10)` + `is_alive()` 检测上游崩溃并自动退出
- **为什么这样设计**：将 GPU 推理、CPU 计算、IO 操作分离到不同进程，利用多核并行
- **运动补偿位置**：MotionCompensationNode 在进程 2 中，位于 HomographyCalibrationNode 之后
- **历史**：整合了旧版 `main_stream_optimized.py`（2 进程 RTSP v1）和 `main_stream_optimized_v2.py`（2 进程 RTSP v2 + 健康检查）的特性

## 数据路径（当前实现与目标态）

### 当前实现：待迁移旧链路

```
Backend (KafkaProducerNode)
  │ statistics_{n}:  {camera_id, cars, road_1..5, direction_flow, lane_source, lanes[], avg_speed_kmh, drone_position, ...}
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
  │ 订阅 ((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)
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
  │ 后台监控任务: 每5s检查进程存活状态，return_code=0 记为 stopped，非零记为 error
  ▼
检测管道子进程: GPU推理 + CPU计算 + Kafka输出
```

上述路径是仓库当前实现。`Telegraf → InfluxDB → Grafana` 已被 ADR-019 标记为废弃，
仅在迁移核验窗口内允许临时保留，不得继续作为新功能的依赖。

### 目标态：Kafka + PostgreSQL/TimescaleDB + 无人机平台

```text
无人机 AI 检测管道
  │
  ├── uav_statistics_{camera_id}       （周期态势指标）
  ├── uav_track_complete_{camera_id}   （完成轨迹）
  ├── uav_conflicts_{camera_id}        （冲突事件）
  └── uav_telemetry_{camera_id}        （无人机遥测）
          │
          ▼
Kafka（异步传输与削峰；Topic / msg_type 均以 uav_ 开头）
          │
          ▼
Platform Consumer（校验、幂等、路网 ID 关联、持久化）
          │
          ├── PostgreSQL database: road9
          │     ├── TimescaleDB hypertables
          │     │     ├── uav_traffic_metrics
          │     │     ├── uav_system_metrics
          │     │     ├── uav_telemetry_metrics
          │     │     ├── uav_track_points
          │     │     └── uav_conflict_events
          │     └── 事件与业务表
          │           ├── uav_message_inbox（消费幂等基线）
          │           ├── uav_drones / uav_video_sources / uav_telemetry_sources
          │           ├── uav_flight_plans / uav_missions / uav_pipelines
          │           ├── uav_track_events / uav_ai_events
          │           ├── uav_event_outbox / uav_event_delivery_attempts
          │           ├── uav_event_feedback / uav_dead_letters
          │           └── uav_evidence_packages / uav_evidence_items
          │
          ├── REST 历史查询 / 聚合查询
          └── WebSocket 实时广播
                ├── uav_intersection:{intersection_id}
                ├── uav_alerts
                ├── uav_alerts:{intersection_id}
                ├── uav_system
                ├── uav_telemetry:{drone_id}
                └── uav_calibration
                         │
                         ▼
                       console2
```

目标态约束：

- PostgreSQL 连接参数中的 `DB_NAME` 固定选择 `road9`；`road9` 是 database，不能自动解释成
  schema。旧 `ycx`/`road10` 调查结果只作为历史调查证据，不能覆盖本决策。
- TimescaleDB 与普通 PostgreSQL 表位于同一 `road9` 数据库，统一事务、权限、备份与审计；
  指标、遥测、轨迹点和冲突事件进入 canonical hypertable，轨迹摘要、AI 事件、可靠投递、
  反馈、死信和证据元数据进入 canonical 普通业务表。
- `uav_traffic_metrics` 统一通过 `grain_type`、`grain_key` 表达指标粒度：
  `grain_type` 取 `intersection`、`link`、`lane`，`grain_key` 分别保存对应的权威
  `inter_id`、`link_id`、`lane_id`。
- `uav_message_inbox` 是长期 canonical 消费幂等表，不是迁移期临时表。Consumer 必须在
  同一 PostgreSQL 事务内先登记 `(source_system, message_id)` 唯一记录、校验 payload hash，
  再写事实数据并回填 fact references/status；同时保留 Topic、partition、offset。其保留期
  必须覆盖系统允许的最大消息重放窗口。
- TimescaleDB hypertable 的唯一键因分区约束需要包含时间列，只能作为第二层防重；不得用它
  代替 `uav_message_inbox` 的跨时间消息幂等判断。
- 所有无人机平台拥有的 Kafka Topic、`msg_type`、WebSocket channel 和物理表名必须以
  `uav_` 开头。示例中的复数形式是目标契约，落库与接口文档必须保持一致。
- camera-scoped Topic 必须由统一 builder 使用“消息类别 + 显式 `camera_id`”生成；builder
  负责校验 `camera_id` 并选择 canonical 模板。禁止从一个 Topic 名通过字符串替换推导
  另一个 Topic，避免相似词、前后缀或自定义配置导致误路由。
- `track_complete`、`conflict`、AI event 和证据引用属于不可静默丢失数据。生产侧必须先写
  持久化 spool/outbox 再进入内存发送队列，只有收到 Kafka/下游确认后才清理；队列满、
  进程崩溃或 send 失败必须可重试和可告警。周期指标仅在契约明确允许有损时才可丢弃，且
  必须通过 `uav_system_metrics` 上报预期、已发/已收、丢弃量和 coverage。
- Kafka Consumer 必须关闭 auto commit。只有 `uav_message_inbox` 与全部事实数据在同一
  PostgreSQL 事务成功提交后，才可手动提交对应 offset；数据库失败时不提交，使消息能够
  重放。数据库已提交但 offset 尚未提交时的重复消费由 inbox 幂等吸收。
- `road9` 中既有的共享路网主数据、PostgreSQL 系统目录和 TimescaleDB 扩展内部对象不属于
  无人机平台自建表，不强制重命名；无人机平台只读引用时必须保存路网版本和权威 ID。
- 不再为 Grafana 或 InfluxDB 新增查询、面板、measurement 或兼容字段；可视化统一由
  `console2` 通过平台 REST/WebSocket 获取。
- 无人机档案、数据源、FlightPlan、Mission 和 Pipeline 期望状态必须持久化到 `road9`；
  当前内存 `DRONES/MISSIONS`、PID、进程句柄、打开的视频流和帧缓存只属于迁移/运行态，
  不得作为重启恢复真源。
- 规划统一事件总线使用 `uav_ai_events`，主平台回执使用 `uav_ai_event_feedback`；在其合同
  冻结前，现有分场景 Topic 继续承担检测管道内部传输，但迁移后的名称必须带 `uav_`。

#### 历史 InfluxDB 时间迁移边界

旧 InfluxDB point 的 `time` 不能统一映射为 TimescaleDB 的 `observed_at` 或
`occurred_at`。不同 measurement 的写入路径和原始 payload 不同，必须由独立转换器按
measurement 判断时间语义：

- `statistics` 类 point 的 `time` 可能是 Telegraf/InfluxDB 写入时刻，不必然等于视频帧
  观测时刻；`conflict` 类 point 也可能只保留 Consumer 写入时刻，而非冲突发生时刻。
- `track_complete` 历史数据存在把视频流相对秒误当 Unix 秒转换的风险，可能形成靠近
  Unix epoch（1970 年）的伪时间。此类值不得直接进入 `uav_track_events` 或
  `uav_track_points` 的业务时间列。
- 每条迁移记录必须保留 `source_time_raw`、`source_time_semantics` 和 `time_quality`。
  `source_time_semantics` 至少区分 `event_time`、`write_time`、`stream_relative`、
  `unknown`；`time_quality` 至少区分 `verified`、`inferred`、`invalid`、`unknown`。
- 只有能由原消息字段、任务起始时间、视频时间轴或其他可审计证据证明的时间，才可写入
  `observed_at`/`occurred_at`。无法证明时，旧 `time` 只作为 `ingested_at`/原始审计信息，
  不得冒充业务发生时间。
- 异常轨迹先进入隔离区；仅当任务开始时间与流相对秒的组合关系可证明时才允许重建，且
  必须记录重建方法和 `time_quality=inferred`。无法重建的记录保留隔离，不参与业务时序
  聚合、轨迹排序或事件 SLA 计算。
- 历史 `statistics` 可能同时经 Telegraf 和 Platform Consumer 写入。两条路径不是两份独立
  观测，迁移时必须按 source writer、原 Topic/partition/offset、message ID 或可审计指纹
  识别重复；不能把两边记录简单相加。缺少可靠关联键时，应选择并记录权威来源，将另一侧
  仅用于对账，并降低迁移质量标记。

因此，历史回填需要“measurement 分支 + 时间质量门禁”，不能使用一条
`Influx time → occurred_at` 的通用 SQL 完成。

平台容器会把项目根目录以 `/project` 只读挂载，并在镜像构建时安装
`platform/pipeline-requirements.txt` 中的检测器依赖，并通过
`platform/pipeline-constraints.txt` 锁定 `numpy<2`、`torch==2.2.2` 和
`torchvision==0.17.2`，避免 `ultralytics` 自由解析到不兼容或过重的新版
Torch/CUDA 包。依赖文件应覆盖根 `requirements.txt`，否则通过 `POST /api/v1/pipelines`
启动 `main_optimized.py` 时会出现缺少 `hydra`、YOLO、OpenCV 等模块的错误。
Platform 拉起的检测器命令会追加 `hydra/job_logging=disabled`，避免 Hydra 默认
`logs/app.log` 文件 handler 在只读 `/project` 下创建日志失败；检测器 stdout/stderr
由 PipelineManager 持续 drain 并保留尾部用于异常诊断。`main_optimized.py`
的 multiprocessing 子进程会重新加载日志配置；若 `FileHandler` 目标不可写，会自动
移除 file handler 并降级到 console，避免 reader/tracker/show worker 因日志文件不可写退出。

### Platform/Vite MJPEG 代理

Platform 通过 PipelineManager 启动检测器子进程时，每条管道分配独立 `VIDEO_PORT`。
检测器 Flask MJPEG 服务绑定在 Platform 容器内部 `127.0.0.1:{video_port}`；
宿主机 Vite dev server 不能直接访问该容器本地端口。实时页面的
`/camera_N` 因此走两跳代理：

```
Browser <img src="/camera_10">
  → Vite /camera_10
  → Platform /api/v1/video/camera/10
  → Platform container localhost:8101/video
```

`/api/v1/video/camera/{camera_id}` 是公开只读 MJPEG 端点，未运行对应管道时返回
`camera_not_running`。这保证前端 `<img>` 不需要 Bearer token 也能显示检测画面。

### Nginx 视频流聚合

```
http://localhost:8009/camera_{n}
  → proxy_pass http://traffic_analyzer_camera_{n}:8100/video
```

生产多 camera 容器模式使用正则 `~ ^/camera_(\d+)$` 动态路由到对应摄像头容器的
Flask MJPEG 端点。

### WebSocket 频道模型

前端通过 `useWebSocket` hook 订阅频道，平台 Kafka consumer 按频道广播。当前代码仍使用
无前缀频道，目标态必须迁移为下表中的 `uav_` 名称：

| 当前频道（待迁移） | 目标频道 | 目标 `msg_type` 示例 | 前端页面 |
|---|---|---|---|
| `intersection:{id}` | `uav_intersection:{intersection_id}` | `uav_stats`, `uav_track_complete`, `uav_conflict` | Monitoring, Dashboard |
| `alerts` | `uav_alerts` | `uav_alert_new`, `uav_alert_updated` | Dashboard |
| — | `uav_alerts:{intersection_id}` | `uav_alert_new`, `uav_alert_updated` | Monitoring |
| `system` | `uav_system` | `uav_system_metrics` | Dashboard |
| `telemetry:{drone_id}` | `uav_telemetry:{drone_id}` | `uav_telemetry` | Drones |
| — | `uav_calibration` | `uav_lane_annotation_task` | Calibration |

订阅协议：
```json
// 订阅
{"action": "subscribe", "channel": "uav_intersection:INT_camera_1"}
// 推送
{"channel": "uav_intersection:INT_camera_1", "type": "uav_stats", "data": {...}, "ts": 1234567890}
```

### 遥测数据源

| 源 | 文件 | 格式 | 场景 |
|---|---|---|---|
| MQTT 实时 | `services/TelemetrySubscriber.py` | DJI Cloud API JSON | 生产（直播无人机） |
| JSON 文件 | `services/TelemetryFileReader.py` | DJI Cloud API JSON 导出 | 离线回放 |
| SRT 字幕 | `services/SrtTelemetryParser.py` | DJI 视频字幕 (`.srt`) | 离线回放（逐帧精确）；不是 Secure Reliable Transport 视频协议 |

三种源实现相同的 `get_nearest(timestamp) -> dict` 接口，VideoReader 通过 `telemetry.source` 配置切换。

### 无人机对接与飞行计划调度（S9 目标态）

S9 在平台单体中增加持久化无人机配置与后台调度服务，不新增 flight 微服务。实时与本地源都复用现有 PipelineManager 和生产入口 `main_optimized.py`：

```text
管理员 / /drones 四页签
  │
  ├── Drone + SourceProfile
  │     ├── live: RTSP video + MQTT telemetry
  │     └── local_replay: server MP4 + DJI .srt telemetry
  │
  └── FlightPlan (once / weekly / timezone / exception dates)
          │
          ▼
PostgreSQL road9
  ├── uav_drones
  ├── uav_video_sources / uav_telemetry_sources
  ├── uav_flight_plans
  ├── uav_missions
  └── uav_pipelines
          │
          ▼
FlightPlanScheduler（FastAPI 后台服务）
  ├── 每 ≤5s 扫描到期窗口
  ├── PostgreSQL advisory lock / 租约竞争单调度资格
  ├── (flight_plan_id, scheduled_start_at) 唯一约束防重
  ├── 窗口内重启恢复；错过完整窗口标记 skipped/window_missed
  └── 到点创建 Mission、调用 PipelineManager；到时停止 Pipeline
          │
          ▼
PipelineManager → main_optimized.py → Kafka uav_* → road9/TimescaleDB + WebSocket
```

架构边界：

- FlightPlan 是排期定义，Mission 是一次业务执行，Pipeline 是分析进程；三类 ID 和状态机不得混用。
- 同一无人机 enabled 计划不能重叠；不同无人机可以同时监测同一路口。
- 编辑/暂停计划只影响未来执行，不改写运行中 Mission 的设备、源、路网和计划快照。
- SourceProfile 是 API 聚合，物理数据由 `uav_video_sources` 与 `uav_telemetry_sources` 承载；配对关系只能有一套状态真源。
- 本地路径经 realpath 规范化并限制在批准的 allowlist 根目录；RTSP/MQTT 凭据只保存 secret reference，API、日志和审计不得回显明文。
- 平台启动时从数据库恢复当前窗口和 Pipeline 期望状态；进程句柄无法恢复，只能核对现存进程或幂等拉起。
- 计划触发的是 AI 检测 Pipeline，不调用无人机航点、起降、返航或其他飞控接口。

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
> 下图为 ADR-019 的平台目标态；仓库当前仍包含 `InfluxQuery` 和旧 Compose 服务，属于待迁移项。

### 系统总览

```
┌─────────────────────────────────────────────────────────────────┐
│                           前端（console2）                       │
│                    React SPA + Nginx (:8080)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ /api/*  /ws/*
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    平台单体应用（platform/app）                    │
│                      FastAPI + Uvicorn (:8000)                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    JWT 认证中间件                             ││
│  │       （登录公开；REST Bearer JWT；WebSocket query JWT）      ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│
│  │ auth.py  │ │intersec- │ │ drones.py│ │ alerts.py│ │system. ││
│  │          │ │tions.py  │ │          │ │          │ │py      ││
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘│
│       │            │            │            │           │      │
│  ┌────┴────────────┴────────────┴────────────┴───────────┴────┐ │
│  │                    业务逻辑层（services/）                   │ │
│  │ auth_service │ alert_engine │ PipelineManager │ Scheduler   │ │
│  └────────┬───────────┴──────────────┬─────────────────────────┘ │
│           │                          │                           │
│  ┌────────┴────────┐    ┌────────────┴────────────┐             │
│  │ PostgreSQL      │    │   Kafka Consumer        │             │
│  │ database=road9  │    │  （aiokafka）           │             │
│  │ + TimescaleDB   │    └────────────┬────────────┘             │
│  └────────┬────────┘                 │                          │
│                                      │                          │
│                           ┌──────────┴──────────┐               │
│                           │  WebSocket Manager  │               │
│                           │   （ws_manager.py） │               │
│                           └─────────────────────┘               │
│                                                                 │
│                           ┌─────────────────────┐               │
│                           │ PostgreSQL/Timescale│               │
│                           │ Repository（目标）  │               │
│                           └─────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流

```
1. 用户认证流程（目标）：
   POST /api/v1/auth/login
     → auth.py
     → auth_service.authenticate_user()
     → PostgreSQL database=road9（平台自建认证表名以 uav_ 开头）
     → auth_service.create_access_token() (PyJWT)
     → 返回 JWT token

2. 实时数据推送与持久化流程（目标）：
   视频分析管道 → Kafka topic (uav_statistics_*, uav_track_complete_*,
                              uav_conflicts_*, uav_telemetry_*)
     → KafkaConsumerService.consume_loop()
     → 校验 uav_* msg_type、幂等键和路网关联字段
     → PostgreSQL/TimescaleDB 持久化成功
     → ws_manager.broadcast(uav_* channel, data)
     → WebSocket 客户端

3. 时序数据查询流程（目标）：
   GET /api/v1/trajectories?intersection_id=X&start=T1&end=T2
     → trajectories.py
     → PostgreSQL/Timescale repository
     → database `road9` 内的 `uav_track_events`，关联 `uav_track_points`
     → 返回轨迹列表

4. 飞行计划执行流程（S9 目标）：
   POST /api/v1/flight-plans/{id}/enable
     → 校验 Drone、成对 Source、inter_id + road_data_version、权限和重叠窗口
     → PostgreSQL database=road9 持久化 uav_flight_plans
     → Scheduler 竞争 advisory lock 并扫描 due occurrence
     → 事务创建唯一 uav_missions 记录，状态 pending → starting
     → PipelineManager.start_pipeline()，保存 uav_pipelines 与 actual_started_at
     → 状态 running；到时/本地 EOF 后停止并完成
     → 重启窗口内幂等恢复，已错过窗口写 skipped/window_missed
```

目标态不包含 Telegraf、InfluxDB 或 Grafana。迁移完成前，当前实现仍可能从
`influx_query.py` 查询旧数据；这只是过渡兼容，不得作为新增 API 的数据源。

### 关键设计决策

#### 1. 单体架构（2026-05-29 迁移）

**决策**：将 4 个微服务（gateway、operations、vision、flight）合并为单一 FastAPI 应用。
**原因**：

- 微服务增加了网络延迟、服务发现、分布式追踪等复杂度
- 团队规模小，不需要独立部署和扩展
- API 端点之间共享大量状态（Kafka 消费者缓存、WebSocket 连接池）
  **代价**：单一故障点，但通过优雅降级模式缓解

#### 2. 优雅降级模式

**决策（目标态）**：应用启动时不要求所有依赖（PostgreSQL/TimescaleDB、Kafka）可用，
而是在 lifespan 中尝试连接并记录状态。当前代码中的 InfluxDB 健康项须随迁移删除。
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

- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL；目标态
  `DB_NAME=road9`，不得把 `road9` 当作 schema 名替代数据库名
- `KAFKA_BOOTSTRAP` — Kafka broker
- `INFLUX_HOST`, `INFLUX_PORT`, `INFLUX_DATABASE` — 仅为当前旧实现兼容配置，完成
  PostgreSQL/TimescaleDB 迁移后删除
- `JWT_SECRET_KEY`, `JWT_ALGORITHM` — JWT 签名
