# ARCHITECTURE.md — TrafficAnalyzer 系统架构

> 2026-07-16 本机开发环境已按 ADR-019 完成纯净切换。本文中的旧链路段落仅是历史设计记录；
> 当前实现以根 `docker-compose.yaml`、Alembic `20260723_0019` 和 canonical `uav_*` 契约为准。

## 系统总览

TrafficAnalyzer 是智慧交通大项目下的无人机 AI 交通分析子系统。核心功能是从视频流
（MP4 文件或 RTSP 实时流）中检测车辆、跟踪轨迹、计算道路与车道指标、识别冲突和
形成可复核事件。目标态由无人机平台前端提供实时态势与历史查询，不再依赖 Grafana。

### 架构状态说明

- **本机已实施**：PostgreSQL 连接数据库固定为 `road9`，启用 TimescaleDB 扩展；
  无人机平台消息名和平台自建物理表名统一以 `uav_` 开头；废弃
  Kafka → Telegraf → InfluxDB → Grafana 链路。
- **数据边界**：不迁移任何旧 PostgreSQL、实验 TimescaleDB、InfluxDB 或 Kafka 历史数据；
  新 `road9` 仅由 migration 和管理员 seed 初始化，业务与时序事实从空数据开始。
- **生产边界**：本机实施不关闭生产镜像、秘密、TLS/SASL、HA、容量和 RPO/RTO 门禁。

```
┌─────────────────────────────────────────────────────────┐
│                    视频源（MP4/RTSP/摄像头）                │
└─────────────────────┬───────────────────────────────────┘
                      │ cv2.VideoCapture
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   VideoReader (生成器)                    │
│  逐帧产出 FrameElement(source, frame, timestamp)         │
│  注入遥测数据 + 可选的固定 Runtime Road Map Bundle        │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement
                      ▼
┌─────────────────────────────────────────────────────────┐
│                    DetectionNode                          │
│  YOLO11 检测 → detected_xyxy/conf/cls/model lineage      │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带检测结果）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ImageMotionEstimationNode                    │
│  排除目标框的背景 LK/RANSAC previous→current 图像 warp     │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             GroundTrajectoryTrackerNode                  │
│  纯图像 ByteTrack：视觉补偿后 IoU + 类别软约束 + 真实时间   │
│  此边界禁止读取 H / ENU / 遥测 / 地图覆盖                  │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│ HomographyCalibration + MotionCompensation               │
│  按 SourceProfile 配准与当前遥测生成逐帧 pixel→map ENU      │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│ FlightGeoReference + PostTrackingWorldProjection         │
│  ByteTrack 后世界投影、质量门禁、地图覆盖与正式业务分段       │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             TrackerInfoUpdateNode                        │
│  维护 buffer_tracks 字典（TrackElement）                  │
│  车辆底部接地点 + motor/non_motor 分类 + 逐帧轨迹累积      │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             SpeedEstimationNode                          │
│  带时间戳的 ENU 轨迹回归→车速(km/h)，不重复扣无人机速度    │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             DirectionFlowNode                            │
│  ENU 航向→左转/直行/右转/掉头分类+排队检测                │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             LaneDetectionNode（模型驱动，可选）           │
│  YOLO 分割模型检测车道标线/路面，仅产生候选几何           │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             LaneAnalysisNode（数据驱动）                  │
│  消费已验证匹配结果；候选几何不能覆盖发布地图              │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             TrajectoryNode                               │
│  输出 trajectory_enu_m + trajectory_gcj02               │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             RoadMapMatchingNode                         │
│  lane_verified 车道面 + 横距 + 航向 + 拓扑 + 历史连续性  │
│  有地图时输出正式匹配；无地图时透传检测/像素跟踪结果       │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             AutoLaneInferenceNode（轨迹驱动）             │
│  自动发现车道中心线和方向，仅输出质量辅助候选              │
│  不覆盖已发布地图，不生成正式 Lane ID                     │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ConflictDetectionNode（默认启用）             │
│  右转/左转机非 near-miss 证据漏斗 + 冲突点 ENU/GCJ-02 输出 │
│  同帧输出标定/轨迹/配对/预测/证据/去重/事件诊断漏斗         │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             CalcStatisticsNode                           │
│  cars_amount + roads_activity                            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             KafkaProducerNode                            │
│  uav_statistics_{n} / uav_track_complete_{n}              │
│  uav_conflicts_{n} / uav_telemetry_{n}                     │
│  含方向流量/车道统计/车速/无人机位置/正式冲突计数与 TCC 诊断│
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ShowNode (supervision 库)                    │
│  圆角边框+ID+已验证渠化几何+车速标签+方向流量+轨迹尾迹   │
│  +候选质量辅助叠层+FPS                                   │
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

- **进程 1**：VideoReader + DetectionNode（CPU 读取 + GPU/MPS YOLO 推理，仅输出检测）
- **进程 2**：ImageMotion + GroundTrajectoryTracker(ByteTrack image-only) + Homography + MotionCompensation + FlightGeoReference + PostTrackingWorldProjection + TrackerInfoUpdate + Speed + Direction + Lane/Map + Conflict + CalcStatistics + KafkaProducer（CPU 密集）
- **进程 3**：ShowNode + VideoSaver + FlaskServer（渲染 + IO）
- **队列**：`FRAME_QUEUE_MAXSIZE` 默认 8，进程间通过 `multiprocessing.Queue` 传递 FrameElement；可按目标环境容量显式调整
- **健康检查**：下游进程通过 `get(timeout=10)` + `is_alive()` 检测上游崩溃并自动退出
- **为什么这样设计**：将 GPU 推理、CPU 计算、IO 操作分离到不同进程，利用多核并行
- **运动补偿位置**：MotionCompensationNode 在进程 2 中，位于 HomographyCalibrationNode 之后
- **历史**：整合了旧版 `main_stream_optimized.py`（2 进程 RTSP v1）和 `main_stream_optimized_v2.py`（2 进程 RTSP v2 + 健康检查）的特性

## 数据路径（本机 canonical 实现）

```
Backend (KafkaProducerNode)
  │ uav_statistics_{n} / uav_stats
  │ uav_track_complete_{n} / uav_track_complete
  │ uav_conflicts_{n} / uav_conflict
  │ uav_telemetry_{n} / uav_telemetry
  ▼
Apache Kafka KRaft
  │
  ▼
Platform Consumer (platform/app/kafka/consumer.py)
  │ 校验 canonical envelope / msg_type / message_id
  │ uav_message_inbox + 事实表同事务写入
  │ 成功后手动提交 Kafka offset
  │
  ▼
road9 / TimescaleDB
  │
  ├── REST 历史查询
  └── WebSocket uav_* channel → Console2

PipelineManager (platform/app/services/pipeline_manager.py)
  │ 管理检测管道生命周期
  │ POST /api/v1/pipelines → 启动子进程(python main_optimized.py)
  │ DELETE /api/v1/pipelines/{id} → SIGTERM → 10s → SIGKILL
  │ 后台监控任务: 每5s检查进程存活状态，return_code=0 记为 stopped，非零记为 error
  ▼
检测管道子进程: GPU推理 + CPU计算 + Kafka输出
```

上述路径是仓库当前实现。`Telegraf → InfluxDB → Grafana` 已按 ADR-019 从本机运行态、
依赖和部署中删除；后文出现该链路时仅是历史快照，不允许临时恢复、迁移核验或新增兼容。

### canonical 当前态：Kafka + PostgreSQL/TimescaleDB + 无人机平台

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
- 历史态势读模型使用 `uav_traffic_metrics` 已类型化列做轻量投影，并按请求
  `granularity` 在应用层每桶保留最后一个观测；审计 `payload` 不进入批量查询，只允许为
  最后一个返回点补读 TCC 诊断。这样趋势轮询不会把活动轨迹、标注快照等大对象反序列化进
  Platform 进程。
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
- schema 或消息身份冲突属于永久错误：Consumer 先把原始 payload、hash、Topic、partition、
  offset 和原因耐久写入 `uav_message_dead_letters`，成功后才提交 offset；隔离写入失败仍 seek
  原 offset。该入站隔离表与 EventDelivery 的 `uav_dead_letters` 各自独立。
- `road9` 中既有的共享路网主数据、PostgreSQL 系统目录和 TimescaleDB 扩展内部对象不属于
  无人机平台自建表，不强制重命名；无人机平台只读引用时必须保存路网版本和权威 ID。
- 不再为 Grafana 或 InfluxDB 新增查询、面板、measurement 或兼容字段；可视化统一由
  `console2` 通过平台 REST/WebSocket 获取。
- 无人机档案、数据源、FlightPlan、Mission 和 Pipeline 期望状态必须持久化到 `road9`；
  当前内存 `DRONES/MISSIONS`、PID、进程句柄、打开的视频流和帧缓存只属于迁移/运行态，
  不得作为重启恢复真源。
- 规划统一事件总线使用 `uav_ai_events`，主平台回执使用 `uav_ai_event_feedback`；在其合同
  冻结前，现有分场景 Topic 继续承担检测管道内部传输，但迁移后的名称必须带 `uav_`。

#### 历史数据边界（不执行迁移）

下列内容只记录为什么旧数据不能安全回填。本机切换已决定不迁移、不备份、不核验旧内容，
因此运行时不提供转换器、兼容消费或迁移隔离表：

- `statistics` 类 point 的 `time` 可能是 Telegraf/InfluxDB 写入时刻，不必然等于视频帧
  观测时刻；`conflict` 类 point 也可能只保留 Consumer 写入时刻，而非冲突发生时刻。
- `track_complete` 历史数据存在把视频流相对秒误当 Unix 秒转换的风险，可能形成靠近
  Unix epoch（1970 年）的伪时间。此类值不得直接进入 `uav_track_events` 或
  `uav_track_points` 的业务时间列。
- 历史方案曾要求每条迁移记录保留 `source_time_raw`、`source_time_semantics` 和 `time_quality`；
  该方案已取消，本机不会生成此类迁移记录。
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

上述内容是已取消的历史迁移风险分析，不再形成回填任务、转换器或对账门禁；本机新库从
空数据开始，任何旧时间字段都不会进入 `road9`。

旧资产只保留 7 天且不再挂载。到期后通过
`scripts/purge_adr019_legacy_storage.py` 的固定 allowlist、到期校验和显式确认人工清理；
严禁把这些资产导入新 `road9`。

根 `Dockerfile` 是 Platform 与检测器的统一镜像：Platform 包、Alembic、
`main_optimized.py`、检测节点、配置和遥测实现一并写入 `/app`。镜像构建安装
`platform/pipeline-requirements.txt`，并通过 `platform/pipeline-constraints.txt` 锁定
`numpy<2`、`torch==2.2.2` 和 `torchvision==0.17.2`。权重与视频不进入镜像，Compose
只读挂载到 `/app/weights` 和 `/app/test_videos`；`PIPELINE_PROJECT_ROOT=/app`。镜像和根
Compose 只用于生产发布，不是 Mac 开发启动入口。
生产 Compose 固定 `DEPLOYMENT_MODE=production`，并要求显式提供数据库密码、JWT secret、
管理员初始密码与 CORS allowlist；开发默认凭据不能进入容器发布态。

Platform 启动只初始化 PipelineManager，不自动创建检测任务。Pipeline API 或 Mission 调度
只依赖 `start / inspect / stop` 执行 seam；`LocalPipelineExecutor` 在 Platform 所在操作系统
创建 `main_optimized.py` 进程组。Apple Silicon 开发态 Platform 与检测器都运行于原生
macOS arm64；生产发布态二者都运行于 Linux 容器，不跨主机委派。启动命令追加
`hydra/job_logging=disabled`；检测器 stdout/stderr 持续 drain 并保留尾部用于异常诊断。multiprocessing
子进程若发现 `FileHandler` 目标不可写，会移除 file handler 并降级到 console。

旧的独立检测器构建定义保存在 `Dockerfile.detector`，仅作为可构建备份，不属于 canonical
Compose。Docker Desktop 普通 Linux 容器不具备 macOS Metal/MPS 后端，不能通过
`platform: linux/arm64` 或 `device=mps` 获得 Apple GPU。生产通过构建系统选择目标架构和
CPU/CUDA 设备；NVIDIA GPU/CUDA 和生产镜像 pin 仍是外部门禁。

### Apple Silicon 原生 MPS 回放

Mac 开发机不得用 x86_64/Rosetta Python 承担 YOLO 推理。仓库通过
`scripts/bootstrap_native_mps.sh` 使用原生 arm64 `uv` 创建隔离的
`.venv-mps`，按 Platform 检测器约束安装 PyTorch，并强制验证
`platform.machine() == arm64`、`torch.backends.mps.is_built()` 和
`torch.backends.mps.is_available()`。环境检查未通过时，不允许静默降级到 CPU。

交互式开发使用 `scripts/mac_local_platform.sh up`。脚本先 fail closed 验证 Darwin、arm64、
`mps.is_built()` 与 `mps.is_available()`，然后以用户级 `launchd` 运行 `run_platform.py`，注入
原生 `.venv-mps`、`PIPELINE_DEVICE=mps`、默认 `PIPELINE_IMGSZ=960`、
`PYTORCH_ENABLE_MPS_FALLBACK=1`、持久证据目录 `.runtime/survey` 以及本机 road9/Kafka 地址。
本机证据目录不得回退到 `/tmp`；`uav_evidence_items.storage_key` 与内容寻址对象必须成对保留，
切换运行拓扑时先以非破坏方式导入既有证据卷，不能只复用 road9 元数据。Platform 创建的检测器是同一
macOS 环境中的进程组，因此 REST、Mission、MJPEG 与进程生命周期都保持本地回环，不需要
agent、token、路径翻译或 `host.docker.internal`。`status|logs|stop|restart` 由同一脚本管理。
`run_platform.py` 使用 `os.execvpe` 原位替换为 uvicorn，使 launchd/Docker 直接拥有服务进程；
不得恢复为 `subprocess.call` wrapper，否则 `launchctl remove` 只会终止外层进程并遗留多个连接
同一 `road9` 的 Mission 调度器，进而把另一实例的存活 Pipeline 误判为
`pipeline_runtime_missing`。本机脚本按 launchd owner PID 与精确 uvicorn 命令双重检查单实例；
发现重复实例时 `up/status` fail closed，不得继续提供误导性的 ready 状态。停止与重启必须等待
服务端口释放且同命令进程归零后再返回。

`scripts/run_native_mps_replays.py` 是本机批量验收入口：检测器在宿主机 MPS 上串行运行，
通过 `localhost:9092` 向开发 Kafka 发送 canonical 消息，并通过
`POST /api/v1/pipelines/register` 把外部进程登记到 Platform。运行器直接消费每次运行的
`uav_statistics_*`、`uav_track_complete_*`、`uav_conflicts_*`，按 `pipeline_id`
隔离并在 `output/native-mps/<run>/` 保存完整轨迹、TCC 事件、性能样本和汇总。
原生 Platform 继续独立消费同一 Topic 并写入 `road9`。
批处理显式关闭悬停车道标注快照，避免每秒把重复 JPEG 编入态势消息；真实 TCC 事件的
证据快照仍保留。交互式 Mission 默认继续开启悬停快照，车道标注流程不变。
批量入口默认 `frame_stride=10`（约 3Hz 视频时间采样），与既有连续轨迹验收口径一致；
需要逐帧精度评估时可显式降低，但不得把高 stride 结果作为模型精度证明。
批量入口默认 `imgsz=640`，用于 Apple Silicon 长时间回放的速度优先配置；生产检测配置
仍保持 `imgsz=960` 的小目标精度优先口径。两者结果不得直接作为同一精度基线比较。

默认目录包含 `inter_xqh` 1 源、`mp4new` 5 源和 `mp4new2` 3 源，共 9 个 SourceProfile；三组
`mp4new2` 复用既有海右路、礼士路、崇华路渠化地图，不创建假路口。TCC 验收只接受
`prediction_type=path_intersection` 且 `distance_m≈0` 的真实事件；0 事件是允许的业务结果，
不得通过放宽阈值制造正样本。

`finalize_demo_replay_batches.py` 与 `verify_gcj02_demo_replays.py` 支持重复传入 `--source`，用于
显式缩小技术演示回归范围；不传时仍按 9 源严格门禁。2026-07-22 用户将视频回归范围收敛为
2 条轨迹样本：已自然 EOF 的前 5 源保留并固化为 5 个 completed Mission（13,042 条轨迹），
第 6 源中止批次已按白名单清零，其余来源未运行。该抽样结果只证明演示链路，不替代生产全源回放。

批量验收的每个 SourceProfile 必须同时满足：检测进程返回码为 0、Stats 与完成轨迹均非空、
每条 Stats 都携带 TCC 漏斗诊断、且不存在不符合严格业务口径的 TCC 事件。若批量抽帧未产生
正样本，必须再通过正常 Mission 验证 `path_intersection + distance_m≈0` 及固定三图证据包，
不能把“0 事件”误报为链路未执行，也不能通过降低门槛制造事件。

Console2 Monitoring 在存在运行中 Pipeline 时只投放当前会话 active/completed 世界轨迹；离线时按
当前 SourceProfile 查询 24 小时内最多 500 条 `spatial_ready` 历史轨迹并标记为“BEV 历史轨迹回放”。
页面上限用于保护高德地图轨迹图层渲染，不替代 Road9 总量对账。

### 检测器 MJPEG 地址登记与浏览器直连

Platform 通过 PipelineManager 启动检测器子进程时，每条管道分配独立 `VIDEO_PORT`，并按
`PIPELINE_VIDEO_BASE` 生成浏览器可访问的 `video_stream_url`。本机默认模板为
`http://127.0.0.1:{video_port}/video`；由 Platform 外部启动的检测进程必须在
`POST /api/v1/pipelines/register` 时显式登记同一地址。Pipeline 列表、详情和 Mission 聚合响应
都返回该字段。

Console2 的实时监控屏和无人机回放屏直接把登记地址用作 `<img src>`，视频字节不再经过
Vite 或 Platform：

```
Browser <img src="http://127.0.0.1:8101/video">
  → detector Flask MJPEG :8101/video
```

`/api` 和 `/ws` 仍由 Vite 转发到 Platform；Vite 不再配置 `/camera_*` 视频代理。
`/api/v1/video/camera/{camera_id}` 暂保留为兼容诊断端点，不属于 Console2 运行时数据路径。

Console2 监测页除处理明确的 `<img onError>` 外，还对 MJPEG 首帧设置 8 秒看门狗。
本地检测器只有在 `VideoServer` 完成端口绑定并输出 `MJPEG_READY` 后，Platform 才会把
Pipeline/Mission 标记为 `running`；默认等待上限为 45 秒，超时或子进程提前退出均按启动失败
收敛，避免把尚不可访问的视频地址提前暴露给浏览器。Mission 调度器对刚启动 Pipeline 的一次
临时查询缺失保留 15 秒确认窗口，窗口内继续观察，避免并发轮询把实际存活的检测器误判为
`pipeline_runtime_missing`；超过窗口仍不存在才进入失败终态。运行中的连接若仍未产生可解码首帧，
页面前 5 次按 3 秒间隔重建流连接，此后每 10 秒持续自动恢复，不再永久锁死错误态；已有
1280×720 等有效自然尺寸的画面不会被看门狗打断。飞行任务页和监测页
共享 `video_stream_url` 登记合同。UAT/生产必须把 `PIPELINE_VIDEO_BASE` 配置为浏览器可达的
HTTPS 地址模板，并在发布门禁中验证端口暴露、TLS 和网络访问策略；不得把本机回环默认值
直接用于远端浏览器。

监测页以运行中 Pipeline 的 SourceProfile 归属为展示真源：当 URL 指向同一路口已停止的
视频源、但该路口存在运行中的其他视频源时，Console2 会同步替换 URL 与查询范围后再展示
该 Pipeline 的 MJPEG，避免将一个视频源的画面与另一个视频源的统计、轨迹或事件混用。

### Console2 GCJ-02 地图投放

Console2 城市地图、实时监测和渠化地图编辑预览统一使用高德 JS API 2.0。底图和所有
`trajectory_gcj02`、`geometry_gcj02`、`position_gcj02` 坐标均为 GCJ-02，GeoJSON 顺序固定为
`[longitude, latitude]`。`trajectory_enu_m` 只参与速度、距离、TTC、PET 和拟合计算，不由浏览器
近似换算经纬度。缺失已验证地图或 GCJ-02 轨迹时显示真实空态，不回退其他底图或坐标契约。
Console2 在配置了 `AMAP_SECURITY_JS_CODE` 时，于 Loader 执行前设置
`window._AMapSecurityConfig.securityJsCode`；未配置时仅使用 Web Key，仍尝试由浏览器直接连接
高德。Vite 与 Console Nginx 均不提供 `/_AMapService` 代理。安全密钥可选是 2026-07-22 用户明确
接受高德警告或拒绝风险后的部署取舍；配置安全密钥时它会暴露给浏览器，所有入口仍应使用高德
控制台域名白名单限制调用来源。
左侧实时态势主卡展示最近一条有效 `uav_stats.active_trajectories` 的数量；统计超过新鲜度
窗口时显示无实时数据，不再把拥堵指数作为该主卡的展示指标。
底部实时数据时间轴默认收缩为 12px 感应条，鼠标悬停或键盘聚焦时展开，移出或失焦后
自动收回；暂停与恢复实时数据的行为不受收缩状态影响。

需要地图匹配、世界坐标轨迹或车道级研判的正式 Pipeline，只接收启动时固定的
`RUNTIME_MAP_BUNDLE_JSON`。Bundle 必须引用不可变的 `lane_verified` 版本，包含 GCJ-02/ENU
几何、拓扑、视觉配准和本地稳定车道键；运行中禁止热切换。未绑定路网的仅检测 Pipeline
不设置该环境变量，以 `road_context_status=missing`、`quality_status=unverified` 运行
YOLO/ByteTrack 与 MJPEG，不得传入空对象伪装 Runtime Bundle。
`HomographyCalibrationNode` 必须按 `SOURCE_PROFILE_ID` 选择唯一 verified 配准，并在车道匹配、
速度和轨迹节点之前锁定地图锚点与单应矩阵。`MotionCompensationNode` 以配准时刻的
`registration_position_gcj02` 为位移零点；车辆底部接地点在每一帧使用该帧矩阵与位移累积为
ENU/GCJ-02，不允许在轨迹结束时用末帧矩阵重投整段历史。像素轨迹仅保留为检测证据，不能
进入地图或产生正式车道级统计。

### Nginx 视频流兼容入口

```
http://localhost:8009/camera_{n}
  → proxy_pass http://traffic_analyzer_camera_{n}:8100/video
```

该路由只为旧客户端兼容保留；Console2 不再引用 `/camera_{n}`。生产直连地址应通过
`PIPELINE_VIDEO_BASE` 登记为浏览器可达的受控入口。

### WebSocket 频道模型

前端通过 `useWebSocket` hook 订阅频道，平台 Kafka consumer 按 canonical 频道广播：

| channel | `msg_type` 示例 | 前端页面 |
|---|---|---|
| `uav_intersection:{intersection_id}` | `uav_stats`, `uav_track_complete`, `uav_conflict` | Monitoring, Dashboard |
| `uav_alerts` / `uav_alerts:{intersection_id}` | `uav_alert_new`, `uav_alert_updated` | Dashboard, Monitoring |
| `uav_system` | `uav_system_metrics` | Dashboard |
| `uav_telemetry:{drone_id}` | `uav_telemetry` | Drones |
| `uav_calibration` | `uav_lane_annotation_task` | Calibration |

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

### 无人机对接与飞行计划调度（S9 当前工程实现）

S9 在平台单体中增加持久化无人机配置与后台调度服务，不新增 flight 微服务。实时与本地源都复用现有 PipelineManager 和生产入口 `main_optimized.py`：

```text
管理员 / /drones 四页签
  │
  ├── Drone + SourceProfile
  │     ├── live: RTSP video + MQTT telemetry
  │     └── local_replay: server MP4 + DJI .srt 或 DJI Cloud JSON telemetry
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
MissionOrchestrator（FastAPI 后台服务）
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
- 路口渠化工作流允许“视频先发现”和“路口先建档”两条入口，但都必须汇聚到 `IntersectionProject + SourceProfile + SourceIntersectionBinding`。`IntersectionProject` 是稳定工作壳，不替代 RoadContext；视频归属必须先经 WGS84 证据留存和 GCJ-02 候选匹配，不能直接套用无人机默认路口。
- DJI Cloud JSON 回放源在 `uav_telemetry_sources.config` 保存 `time_offset_sec/sync_tolerance_sec`，PipelineManager 将其作为 Hydra override 传给 `TelemetryFileReader`；原始空洞返回无有效遥测，不做插值伪造。
- 根 `docker-compose.yaml` 为 Platform 启用 Docker init 进程，用于回收 EOF、人工停止或异常退出后的多进程检测 worker，避免反复切换摄像头积累僵尸进程。
- Console2 `/drones` 从持久化 Drone/Source/Mission 聚合生成路口控制卡，通过手动 Mission 独立启停，并与 `/monitoring` 共用 Pipeline 启动时登记的 `video_stream_url` 直连检测器 MJPEG。
- 本地路径经 realpath 规范化并限制在批准的 allowlist 根目录；RTSP/MQTT 凭据只保存 secret reference，API、日志和审计不得回显明文。
- 平台启动时从数据库恢复当前窗口和 Pipeline 期望状态；进程句柄无法恢复，只能核对现存进程或幂等拉起。
- 计划触发的是 AI 检测 Pipeline，不调用无人机航点、起降、返航或其他飞控接口。
- `RoadContext` 通过 `Road9RoadContextAdapter` 读取外部权威源，并可在本地使用显式 `FixtureRoadContextAdapter`；fixture 的质量始终为 `unverified`，不能模拟权威批准。
- `EventDelivery` 统一事件/outbox/attempt/dead-letter/receipt/feedback 接缝；主平台 Adapter 在合同未冻结时使用禁用实现并返回 blocked，不产生伪成功。
- 新 Pipeline 只生产 `uav_statistics_*` 等 canonical Topic；Kafka consumer 拒绝旧 Topic/msg_type。

### 主任首屏只读聚合（S8 I5 第一阶段）

```text
Console2 /
  → GET /api/v1/dashboard/{overview,intersections,intersections/{id},drones}
  → DashboardReadModel（无写操作、无独立真源）
     ├── RoadContextSnapshot / Mission / Pipeline / Drone
     ├── TimescaleDB traffic/conflict/telemetry facts
     └── AiEvent / SurveyTask / EventDelivery 状态
  → uav.dashboard/v1 + as_of/window/quality/reason
```

- DashboardReadModel 只在查询时聚合现有事实，不创建 Dashboard 业务表。后续缓存、物化视图或连续聚合必须以 `uav_` 命名、可重建且不得复制事件/任务状态机。
- S8 口径未批准时 KPI 值为 null，同时返回事实分子/分母和阻断原因；主任首屏不展示无值或未验证的 KPI 卡片，也不把缺失解释为 0。阻断详情只保留在 API 和口径治理材料中。
- 当前唯一活动底图是高德 JS API 2.0，Dashboard 路口、无人机、路网和轨迹坐标全部使用经服务端一次转换的 GCJ-02。只有 `lane_verified` 地图或可追溯的 GCJ-02 测试点位进入地图；缺坐标或未验证记录进入隔离计数/配置待办。
- 正式首页顶部范围、窗口和 `as_of` 来自聚合响应，不再使用 AppState 中的试点原型常量。I5-B 内部查询已支持风险/监测/质量、GCJ-02 bbox、搜索和 offset/limit，并将 road9 超时统一为 503；Console2 保留上一成功快照和有限重试，高德加载失败时降级为列表/KPI。项目范围/权限、点位聚合/zoom、全局增量/断线 REST 缺口回补和容量仍属后续或外部门禁。

### I6 本机纯净目标栈与恢复边界

- 根 `docker-compose.yaml` 是唯一完整拓扑，包含 `road9`/TimescaleDB、Apache Kafka KRaft、Platform、Console2、Nginx，以及可选 Kafka UI/GPU 检测器；隔离验证使用环境变量覆盖 project、端口和卷名。
- Platform 镜像复制 `alembic.ini` 与全部 forward migration，`/ready` 同时确认 database、Kafka、TimescaleDB 和 PipelineManager；`/health` 仅表示进程存活。
- 新 `road9` 最初由 `20260715_0010` 从空库创建并确认 5 张 hypertable，随后以前向迁移到
  `20260723_0019`；`0013` 增加 Kafka inbox 可恢复派发，`0014/0015` 增加轨迹研判维度与索引，
  `0016/0017` 建立 GCJ-02 渠化地图及按 SourceProfile 配准，`0018` 增加路口项目化接入，
  `0019` 增加飞行分段、跟踪 profile 与运行质量谱系。当前数据只来自清理后的本机重建，
  不得存在旧 `traffic_platform` database 或迁移隔离表。
- 正式本机切换执行 30 分钟 readiness/认证/Dashboard/System 连续探测；它只证明本机开发稳定性，不定义生产 SLO。
- 旧卷和绑定目录保留 7 天且不挂载，到期后仅允许 `scripts/purge_adr019_legacy_storage.py` 固定 allowlist 人工删除。
- `20260715_0009` 使用数据库触发器维护 `uav_conflict_reviews → uav_conflict_events` 的存在性和删除级联。原因是 PostgreSQL 普通表直接外键指向 Timescale Hypertable 会展开 chunk 约束，无法被 `pg_dump/pg_restore` 可靠重建。
- 恢复必须执行 `timescaledb_pre_restore()/post_restore()`，并核对 migration revision、扩展版本、Hypertable 数、`uav_*` 表计数和业务行计数。当前只证明本地工程可恢复，不代表生产 RPO/RTO、备份介质、加密、异地或 HA 已批准。
- `scripts/validate_i6_local_performance.py` 是受 guard 保护的 localhost 只读烟测，只记录已认证 GET 的成功率和 p50/p95/max，不内置合同阈值。当前 80 请求/并发 8 全部返回 200，但证据固定标记 `local_non_contract` 与 `threshold_status=unverified`；生产硬件、负载模型、持续时长、阈值和签署仍由 S7-TBD-004 冻结。
- `scripts/validate_i6_database_outage.py` 使用独立 Compose project、数据库端口和 Platform 端口执行断库恢复，不影响当前开发库。Dashboard 聚合边界将 `TimeoutError/OSError/SQLAlchemyError` 统一映射为 `503 dashboard_dependency_unavailable`；隔离演练已验证断库前 200、断库 503、恢复后 200，并自动清理临时资源。该行为只证明单实例依赖降级/恢复，不定义生产 RTO/RPO 或 HA。

### 事故测绘深模块（S3 当前实现）

S3 已在 Platform 单体和 Console2 中形成可运行闭环，开发与回归使用本地 PostgreSQL
`database=road9`，不经过 InfluxDB：

```text
Console2 /survey/**
  → JWT + 幂等 REST /api/v1/survey-*
  → SurveyService（任务状态机、服务端量算、复核、报告、投递门禁）
  → PostgreSQL road9 / uav_* 普通表
  → ContentAddressedStore（派生成果 SHA-256 不可变对象）
  → ServerAssetReference（allowlist 相对键 + SHA-256 + 大小，原文件零复制）
  → SurveyWorker（MP4+DJI SRT / DJI Cloud JSON 关键帧处理、outbox 重试/死信）
```

- 已登记 `source_profile_id` 的服务器 MP4、DJI `.srt` 和 DJI Cloud JSON `.json/.txt` 使用 `storage_backend=server_asset`：数据库只保存 allowlist 相对键、SHA-256、大小和本机快速指纹（size/mtime/ctime），绝不复制原文件；显式资产键和 multipart 上传仍保留给其他场景。指纹未变化时目录查询为 O(1)，指纹变化或旧记录缺少指纹时重新计算完整 SHA-256；原文件缺失或内容变化时读取及派生处理返回 `missing/hash_mismatch`，不能继续生成可信成果。
- 后台提取 6 个关键帧，保存原始帧、BEV 图、遥测、质量观测和像素到 ENU 的变换；未冻结的 RTK、覆盖和精度阈值始终标记 `unverified`。
- 关键帧、BEV、场景标注、车道标注底图和报告仍写入持久内容寻址卷。场景标注按关键帧保留 revision/audit；车道标注保留悬停触发，并可从已持久化真实关键帧恢复任务，确认后同步 `uav_lane_annotation_tasks` 与 `uav_visual_lane_bindings`。
- 检测器仅在真实冲突发生时把对应 JPEG 写入事件证据包；无事件素材只记录零检出，不生成测试事件。
- 点、线、折线、面积和对象几何都由服务端基于帧变换计算并版本化，浏览器只提交图像坐标，不能自报米制结果。帧读接口额外返回 BEV→ENU `metric_transform`，仅用于画布鼠标跟随预览边长；保存后显示以服务端 `metric_geometry` 为准。
- 报告生成前重新校验证据对象的 SHA-256 与大小，按关联 BEV 固化带逐边长度的 `survey_report_annotated_image`，嵌入 PDF，并输出 canonical JSON 和 GeoJSON。Console2 报告/历史任务优先读取该内容寻址图，旧版本则从 BEV+量算版本链只读重绘；质量规则未批准或投递 URL 未配置时禁止外发。
- 对外投递使用 `uav_ai_events(event_type=survey_result)`、`uav_event_outbox`、attempt 和 dead-letter 形成可靠投递链；批准阈值和主平台合同仍属外部验收阻断项。

### 执法候选深模块（S4 当前实现）

I4 将正式 `/enforcement/**` 从 React 内存 Mock 切换为 API 驱动的本地候选闭环：

```text
Console2 /enforcement/**
  → JWT + revision REST /api/v1/enforcement/**
  → EnforcementService
     ├── candidate zone/rule + AuditLog
     ├── uav_ai_events(event_type=enforcement_clue)
     ├── uav_enforcement_clues + uav_evidence_*
     └── append-only uav_enforcement_review_audits
  → PostgreSQL road9
  → disabled authority/main-platform adapters (503, no fake success)
```

- `EnforcementService` 是本地事务、幂等、质量门禁和状态转换的深模块；API 与 Console2 不直接拼接事件、证据、规则版本或审计表。
- 本地围栏和规则只能是 `candidate/retired`，通过 `revision` 乐观并发更新；权威发布 Adapter 未冻结时返回 503，不能把本地保存解释为权威生效。
- 执法线索事件真源仍是统一 `uav_ai_events`；执法表只保存车辆、围栏/规则快照和视频/雷达/融合等专属事实，证据和投递不复制状态机。
- 技术复核只改变 review 摘要并追加审计，不改写原始线索事实，也不产生违法、案件、处罚或主平台成功状态。
- 雷达与融合字段实行来源门禁：无真实设备、有效检定或独立测量时保持空值；本地验证样本明确标记 `validation_fixture/unverified`。

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

三进程入口同样必须把 sentinel 判断放在任何普通帧字段和共享内存访问之前。2026-07-15 的真实 5GB EOF 验证发现检测进程先读取 `.frame` 会使 sentinel 以 `AttributeError` 退出；当前 `proc_frame_reader_and_detection` 已先把 `VideoEndBreakElement` 级联入队并退出，tracker/show 继续按既有节点契约完成清理。`test/test_main_optimized_eof.py` 是该顺序的最小回归，`docs/test_report_s9_inter_xqh_eof.json` 是重启恢复后自然 EOF 的原始链路证据。

### 3. ByteTrack 而非 DeepSORT

> 历史基线：以下是原始 `hover_only_legacy` 取舍。`hover_cruise_v1` 已由 ADR-023 改为背景视觉运动补偿后的纯图像 ByteTrack，并把世界投影放到 ID 之后；当前定义见本文“2026-07-23 巡航与悬停正拍融合架构”。

**决策**：使用 ByteTrack 作为多目标跟踪算法。
**原因**：ByteTrack 利用低置信度检测框进行第二轮关联，在车辆密集场景（环形路口）中跟踪精度更高。不需要外观特征提取网络，推理更快。
**代价**：跟踪完全基于 IOU，当车辆被遮挡超过 track_buffer 帧后会丢失 ID。

### 4. 硬编码 5 条道路

**决策**：CalcStatisticsNode 和 KafkaProducerNode 中硬编码了 5 条道路（road_1..5）。
**原因**：原始项目针对特定的环形交叉路口设计，恰好有 5 条道路。
**代价**：增加或减少道路数量需要修改多个文件和 Grafana 仪表盘。这是最大的技术债之一。

### 5. 无人机运动补偿（2026-05-30）

> 历史基线：当前 H 重投影历史像素和无人机速度矢量减法只保留给 `hover_only_legacy`。`hover_cruise_v1` 使用每个点所属源帧的绝对 ENU 事实，当前实现见 ADR-023。

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
> 下图是当前 Platform 单体；旧查询实现和旧 Compose 服务已删除。

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

3. 时序数据查询流程（I3 当前实现）：
   GET /api/v1/trajectories?intersection_id=X&start=T1&end=T2
     → trajectories.py
     → PostgreSQL/Timescale repository
     → database `road9` 内的 `uav_track_events`，关联 `uav_track_points`
     → 返回轨迹列表

4. 飞行计划执行流程（S9 当前实现）：
   POST /api/v1/flight-plans/{id}/enable
     → 校验 Drone、成对 Source、inter_id + road_data_version、权限和重叠窗口
     → PostgreSQL database=road9 持久化 uav_flight_plans
     → Scheduler 竞争 advisory lock 并扫描 due occurrence
     → 事务创建唯一 uav_missions 记录，状态 pending → starting
     → PipelineManager.start_pipeline()，保存 uav_pipelines 与 actual_started_at
     → 状态 running；Scheduler 每个 tick 同步 Pipeline 运行时
     → 本地零退出 EOF 写 completed/source_eof；异常退出或运行时丢失写 failed/pipeline_error
     → 到达计划窗口写 completed/window_ended
     → 重启窗口内幂等恢复，已错过窗口写 skipped/window_missed
```

Platform 的历史 API 直接查询 PostgreSQL/TimescaleDB；仓库不保留旧查询客户端、依赖或运行时配置。

I3 的 `MetricStore` 是 Kafka 与存储之间的深模块边界：消费者只提交 canonical 信封，模块内部完成 schema/业务时间校验、payload hash、`uav_message_inbox` 判重、事实展开和同事务提交。旧信封直接拒绝并进入 dead letter。数据库成功后才手动提交 Kafka offset；瞬态失败 seek 回原 offset，成功重放由 inbox 返回既有事实引用且不重复广播。可变冲突复核单独进入 `uav_conflict_reviews`，不修改 `uav_conflict_events` 追加事实。

冲突视觉证据的生成 seam 位于 `KafkaProducerNode → utils_local.event_evidence`，早于 `ShowNode` 且不改变三进程拓扑。每个冲突用同一帧生成“原图 / 检测器输出 / 同期轨迹还原”三项有序证据；`MetricStore` 将三项作为一个 `EvidencePackage` 在冲突事实事务内登记，两个派生项回指原图。Console2 只消费 `evidence_refs` 并通过鉴权证据接口读取，不在浏览器重新推断检测或轨迹画面。

### 关键设计决策

#### 1. 单体架构（2026-05-29 迁移）

**决策**：将 4 个微服务（gateway、operations、vision、flight）合并为单一 FastAPI 应用。
**原因**：

- 微服务增加了网络延迟、服务发现、分布式追踪等复杂度
- 团队规模小，不需要独立部署和扩展
- API 端点之间共享大量状态（Kafka 消费者缓存、WebSocket 连接池）
  **代价**：单一故障点，但通过优雅降级模式缓解

#### 2. 优雅降级模式

**决策（当前态）**：应用启动时不要求所有依赖（PostgreSQL/TimescaleDB、Kafka）可用，
而是在 lifespan 中尝试连接并记录状态；readiness 只报告当前 canonical 依赖，不包含 InfluxDB。
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
- Docker 覆盖：通过根 `docker-compose.yaml` 的 `environment` 字段

**关键环境变量**：

- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL；目标态
  `DB_NAME=road9`，不得把 `road9` 当作 schema 名替代数据库名
- `KAFKA_BOOTSTRAP` — Kafka broker
- `JWT_SECRET_KEY`, `JWT_ALGORITHM` — JWT 签名

### 2026-07-16 MP4 + SRT 展示链路收敛

- 检测器不写 SQLite，也不直写 `road9`；唯一业务路径为检测器 -> Kafka -> Platform 事务 -> `road9`/TimescaleDB。
- `ReliableKafkaPublisher` 将完成轨迹与真实冲突在 Kafka 确认前保留为 fsync + atomic rename 文件；它是故障 spool，不是可查询业务库。
- canonical envelope 携带 Mission/Pipeline/Run/Source/Inter/Road/Quality lineage，`MetricStore` 以原始业务时间写入轨迹点。
- Console2 的事件中心、轨迹研判和事故测绘均只从 REST/WebSocket 读取 `road9` 事实；详细验收见 `docs/test_report_mp4_srt_product_deep_demo.md`。

### 2026-07-21 轨迹研判读模型

`/gis` 不再直接把一个历史窗口内最多 500 条完整轨迹一次性铺到地图。Platform 通过
`PostgresMetricStoreAdapter.query_trajectory_analysis()` 先在 `road9.uav_track_events` 和
`uav_conflict_events` 按路口、业务时间、Mission/SourceProfile 缩小候选；纯函数
`build_trajectory_analysis()` 先选出每个 lineage 的 canonical 完成事实，再应用业务车型、YOLO
原始类别、转向和质量筛选，生成同一份研判读模型：

```text
road9 完成轨迹/冲突
  → SQL 来源与时间窗口过滤
  → lineage canonical 去重
  → 业务车型 / YOLO / 转向 / 质量过滤
  → lineage-safe 冲突归因
  → 流向排名 + 时间桶 + 双分类摘要
  → 当前时间片可回放轨迹片段（服务端限量）
  → Console2 地图、排名、分类与代表轨迹联动
```

地图只消费至少两个 `trajectory_gcj02` 点且具有 `anchor_gcj02` 的完成轨迹；分析计算消费
对应的 `trajectory_enu_m`。
默认 30 分钟数据段和时间片均锚定最新一条可回放轨迹，而不是当前墙钟或最新但空间信息不完整的记录；因此不会出现总量有值、
首屏地图却因最新降级记录而全空。全窗口总量、可回放量、时间片省略量和空间覆盖率分列返回，
避免渲染上限被误读成业务总量。时间桶最多 720 个，单条轨迹最多返回 60 点，地图时间片最多
返回受 `track_limit` 控制的证据轨迹。轨迹按 SourceProfile、Mission、Pipeline 与 Track ID 的
可用组合去重，抽样优先保留端点、转折点和安全归因冲突附近点；这些边界只控制读模型和渲染，
不修改 canonical 事实。

## 2026-07-23 巡航与悬停正拍融合架构

`hover_cruise_v1` 将同一 Mission 的进场巡航、路口悬停和离场巡航放入同一条三进程管道；`hover_only_legacy` 是只恢复既有悬停能力的回滚 profile。既有 FlightPlan 在 migration `20260723_0019` 中回填为 `hover_only_legacy`，新 FlightPlan 默认使用 `hover_cruise_v1`。

```text
进程 1：VideoReader/MQTT/SRT/JSON → DetectionNode(YOLO only)
进程 2：ImageMotionEstimation → GroundTrajectoryTracker(ByteTrack image association)
       → HomographyCalibration → MotionCompensation → FlightGeoReference
       → PostTrackingWorldProjection
       → TrackerInfoUpdate → Speed/Direction/Map/Lane/TCC/Statistics/Kafka
进程 3：ShowNode → VideoSaver/MJPEG
```

ByteTrack 的明确节点位置是进程 2 的 `GroundTrajectoryTrackerNode`，位于所有 H/ENU/地图处理之前。`ImageMotionEstimationNode` 只从排除目标框的背景图像估计 `camera_motion_warp`；ByteTrack 保留高/低置信度两轮关联，以该视觉 warp 补偿旧框，并使用补偿后 IoU、类别软约束、置信度和真实源时间。其公共 `update` 接口不接受世界位置或 H。同业务组原始类别可即时修正，机动车/非机动车跨组变化默认需连续 3 帧确认。旧 `DetectionTrackingNodes` 只在 `hover_only_legacy` 回滚路径中保留，待巡航生产门禁通过和稳定观察后删除。

迁移验证可设置 `TRACKING_SHADOW_ENABLED=true`，在离线源旁路运行不使用视觉 warp 的 legacy ByteTrack，并把逐帧双方轨迹数、bbox IoU 对应和未匹配 ID 写入 `uav.tracking-shadow/v2` JSONL。主/影子跟踪器使用隔离的 ID 分配器；shadow 结果不写入 `FrameElement` 业务字段、不进入 Kafka/road9/统计/TCC，并在 `offline_only` 下拒绝 RTSP/HTTP/摄像头源。

`DetectionNode` 与 legacy `DetectionTrackingNodes` 共用 `utils_local/detection_geometry.py`。Apple MPS 在推理前强制 Ultralytics 选择非原地 bbox 裁剪，避免旧 PyTorch MPS 的 sliced `clamp_` 静默破坏边界框；输出再按同一行同时校验 bbox、置信度和类别，非有限值、零/负宽高或数组错位均被丢弃并写入 `detection_diagnostics`。任何 `invalid_geometry_count>0` 都由 `FlightGeoReferenceNode` 以 `invalid_detector_geometry` 阻断当帧正式研判，剩余合法框仅可预览。

`FlightGeoReferenceNode` 与 `PostTrackingWorldProjectionNode` 共同构成图像 ID 之后的正式业务边界：前者逐帧生成 `pixel_to_map_enu`，并用已经独立计算的背景视觉变换校验遥测位姿；后者投影已分配 ID 的目标接地点、检查目标地图覆盖并分配正式业务 ID。只有 `hover_verified` 或 `cruise_nadir`、`lane_verified` Runtime Bundle、配准位姿谱系、地图覆盖、遥测、视觉变换和检测几何全部通过时，轨迹才进入 `buffer_tracks`。质量失败只能结束正式业务分段，不能重置图像关联 ID。

`PostTrackingWorldProjectionNode` 是 `hover_cruise_v1` 唯一的像素→ENU→GCJ-02 事实所有者：镜头去畸变、目标接地点投影和地图覆盖判断复用同一个逐帧计算结果。`TrackerInfoUpdateNode` 只能消费已经生成的当前点，禁止再次读取 H 投影；后续 H 或锚点变化不能改写该帧事实。`SpeedEstimationNode` 在该 profile 下只对至少3个逐帧 `position_history_enu_m` 点做真实时间回归，世界历史不足时不产生正式速度；“用当前 H 重投影全部历史像素”的逻辑仅保留给 `hover_only_legacy` 回滚。

轨迹坐标分为三层且不得混用：`trajectory_px` 是每个源帧中的车辆地面接触点；`trajectory_display_px` 是用相邻背景视觉 `camera_motion_warp` 逐帧递推到当前画面的显示缓存；`trajectory_enu_m/trajectory_gcj02` 是 ByteTrack 分配 ID 后，用每个点所属源帧的绝对矩阵生成的世界事实。源像素、世界坐标、`trajectory_timestamps_sec/trajectory_frame_nums/point_quality_lineage` 按同一索引保留；旧 bbox 中心显式保留为 `trajectory_bbox_center_px`。ShowNode 禁止用当前 H 反投影整段历史，世界坐标也禁止反馈关联或修正显示 ID。

进程 3 的 `ShowNode` 不再使用 `sv.TraceAnnotator` 的隐式跨帧 bbox-center 缓存。正式和候选尾迹都消费显式的当前帧图像坐标并使用同一个接地点锚点：正式轨迹绘制类别色实线，候选轨迹绘制最多30点的琥珀虚线；亚像素 bbox 往返抖动只在绘制副本中简化，不改写图像或世界轨迹事实。每车使用紧凑 `#ID class C` 标签，右上角只绘制一次 `AMBER DASHED = CANDIDATE / NO STATS-TCC` 图例。候选框、标签、尾迹的字号、线宽和虚线节距按源画面到1280×720交付视口的比例缩放，同时截断不连续跳变和过长尾迹。`trajectory_display_px` 在 Kafka 发布前剔除，不创建或补写 `buffer_tracks`，也不改变任何正式质量门禁。

Runtime Bundle 中 verified visual registration 新增 `registration_pose`、`camera_calibration` 与 `map_coverage_enu_m`。悬停矩阵在稳定姿态下退化为既有固定配准；巡航帧在同一不可变地图上动态投影。巡航帧不能创建、修改或发布地图。

RTSP 由单后台解码线程持续排空到一个“最新帧”槽位，记录 `source_drop_count/source_drop_reason/source_capture_time`；MP4 仍采用完整帧反压。自然 EOF 到达进程 2 时，`GroundTrajectoryTracker.flush(natural_eof)` 先终止关联，`TrackerInfoUpdateNode.flush()` 再把剩余正式轨迹序列化并在 publisher 关闭前发送；随后继续透传唯一 EOF sentinel。三段队列和共享内存责任不变。

Mission 取得 Runtime Bundle 时，`Road9RoadContextAdapter` 与校准 API 共用同一 registration 输出边界，必须携带位姿、相机和地图覆盖三类谱系。衍生 V2 地图缺少直接 checksum 时只沿显式 `quality.source_map_version_id` 追溯父地图的上游 snapshot；不存在谱系就拒绝解析，不能选“最新”快照。

手动 Mission 的地图解析以 `inter_id + source_profile_id` 为边界：显式 `map_version_id` 是严格约束，未显式指定时优先已就绪的请求道路版本，再按不可变地图版本倒序选择最新的完整 SourceProfile 配准。解析结果把精确 map/version/registration/checksum 和选择策略冻结到 Mission 快照，`_runtime_params` 再按该 map id 取同一 Bundle，避免无人机档案中的原始道路版本误选无配准快照。没有合格地图时仍保留检测器降级启动，但世界投影及正式业务消费者保持关闭。

Console2 监控态分为历史 REST 与实时 WebSocket 两个状态层，展示标量时实时层覆盖历史层；只有 WebSocket 层可更新实时活动/候选轨迹和新鲜度时钟。实时业务消息必须同时匹配当前 SourceProfile 与运行 `pipeline_id`，Pipeline id 变化会重置旧会话的统计、轨迹与冲突，避免 Kafka backlog 或同源旧任务覆盖当前 Runtime 质量。BEV 地图只消费服务端提供的 GCJ-02 点列，降级候选以虚线投放；仅有像素轨迹时展示明确空态，不在浏览器中重建坐标。

ADR-023 已废止世界 Mahalanobis 关联：H 抖动不再能改变匹配结果，`pose_motion_warp` 只用于视觉/遥测一致性诊断。2026-07-24 同一真实 xqh 840s–EOF 原生 MPS 的 image-v2 复验结果记录在 `docs/generated/xqh-hover-departure-acceptance.json`；该证据只证明本机吞吐、双坐标对齐、显示和业务隔离，不替代 IDF1/HOTA/位置与速度真值验收。

本项目不包含人工轨迹标注、AI预标注、标注任务分派或复核工作包。自动化验收只验证运行链、图像关联代理、坐标对齐、质量隔离、性能和EOF；没有外部已批准真值时，IDF1/HOTA、正式ID switch、位置RMSE和速度MAE不评估、不宣称。该边界不影响悬停关键帧上的车道/地图人工复核流程。
