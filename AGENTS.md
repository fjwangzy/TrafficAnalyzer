# AGENTS.md

## 2026-10-19 用户确认消费异常时优先最新数据

历史Kafka offset仅作运输审计，不作为消息身份门禁。正式与Replay V2均使用稳定消息ID及内容哈希去重。
异常处理/提交失败时跳受影响分区最新位置；无法定位记录的消费/解码错误按当前分配分区降级，
断线恢复后从最新数据继续，避免历史积压阻塞功能。必须记录异常及恢复offset，不自动补回跳过区间；
身份冲突、契约校验、认证和质量门禁保持。canonical迁移20261019_0021、Replay V2迁移20261019_rv2_0005。
生产需显式init-db，不能绕过ADR-041依赖/迁移基线门禁。

本文件是 TrafficAnalyzer 仓库的协作与实现约束。

## 数据架构优先级（ADR-019）

自 2026-07-16 起，本机开发环境已完成纯净切换：唯一数据库为 PostgreSQL connection database=`road9` + TimescaleDB；UAV Topic、`msg_type`、WebSocket channel 和本项目自建表统一使用 `uav_` 前缀。旧数据库和旧观测链路不迁移历史数据，已从当前 Compose、运行时代码、依赖和测试中退役。历史 ADR/报告可保留旧链路说明，但必须明确标记为历史，不能恢复为运行时兼容。

2026-10-15 经项目方确认，本次内网生产使用外部瀚高 database=`xinchan`、schema=`ycx_drone`，
本机 `road9.public` 约束保持；生产使用根 Compose 加 `deploy/intranet/compose.yaml`，
生产主机为 Linux x86_64/amd64 + Ascend 310P3 + CANN 9.0.0（以项目方最终更正为准），
详见 ADR-033 与 `docs/DEPLOYMENT_INTRANET.md`。该生产例外不得反向改动 Mac 原生/MPS 默认值。

本次切换只证明本机开发闭环，不代表生产验收。生产镜像 pin、秘密管理、TLS/SASL、HA、容量、保留策略和 RPO/RTO 仍需外部门禁。

## 开发前必读

| 文档 | 说明 |
|---|---|
| `docs/AGENTS.md` | 长期协作规则、架构原则、禁止事项和模块边界 |
| `docs/ARCHITECTURE.md` | 系统架构和 canonical 数据路径 |
| `docs/BUSINESS_LOGIC.md` | 检测、跟踪、道路分配和统计逻辑 |
| `docs/PROJECT_STRUCTURE.md` | 项目结构 |
| `docs/API_CONTRACTS.md` | Kafka、REST、WebSocket 和持久化契约 |
| `docs/DATABASE_SCHEMA.md` | `road9`、TimescaleDB 与 `uav_*` 表 |
| `docs/DECISIONS.md` | 架构决策记录，尤其 ADR-019 |
| `docs/TASKS.md` | 技术债和交付状态 |
| `docs/test_report_inter_xqh.md` | 真实视频/SRT 管道回归基线 |

每次完成任务必须同步更新相关文档。若仓库存在 `.codegraph/`，理解或定位代码时先使用 CodeGraph。

## 本机开发与生产发布拓扑

Apple Silicon 开发态的 Platform 必须使用原生 macOS arm64 Python 启动，检测器作为其
本地子进程直接使用 Metal/MPS；不得在 Docker Desktop Linux 容器内运行开发态 Platform。

- `scripts/mac_local_platform.sh up`：启动原生 Platform（端口 `8000`）并强制 MPS；
- `cd console2 && npm run dev`：开发态 Console；
- `road9` 与 Kafka 使用各自可访问的本机/开发基础设施端口 `5432`、`9092`。

根 `docker-compose.yaml` 仅用于生产发布拓扑：

- `road9`：TimescaleDB，正式端口 `5432`，稳定卷 `traffic_road9_data`；
- `kafka`：Apache Kafka KRaft，正式端口 `9092`；
- `platform`：FastAPI，正式端口 `8000`；
- `console2`：React SPA及API/WebSocket/MJPEG/HLS统一代理，正式端口 `8009`；
- `kafka-ui`：可选 `ops` profile；
- NVIDIA CUDA MPS 与检测器：可选 `gpu-only` profile，与 Apple Metal/MPS 无关。

```bash
scripts/mac_local_platform.sh up
cd console2 && npm run dev

# 仅生产发布
docker compose -p traffic_analyzer up -d --build
docker compose -p traffic_analyzer --profile ops up -d kafka-ui
docker compose -p traffic_analyzer --profile gpu-only up -d --build
```

生产 Compose 固定 `DEPLOYMENT_MODE=production`，未提供 `ROAD9_PASSWORD`、`JWT_SECRET_KEY`、
`BOOTSTRAP_ADMIN_PASSWORD` 和 JSON `CORS_ORIGINS` 时必须拒绝解析/启动，不得用本地默认密码发布。

禁止重新加入旧 PostgreSQL、旧/实验 TimescaleDB、旧 Topic fallback 或退役观测服务。生产
隔离验证必须复用根 Compose，使用独立 project、临时端口和独立卷名。

## 快速验证

```bash
python -m pytest platform/tests -q
python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py -q
cd console2 && npm test && npm run build
python test/test_pipeline_inter_xqh.py
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

`test/test_pipeline_inter_xqh.py` 预期 `56 PASS / 0 FAIL / 0 WARN`，需要 `weights/uav_best.pt`。生产范围审计继续保留外部阻断。

## 检测管道

生产入口只有 `main_optimized.py`，三进程结构为 reader+detection、tracker+stats+kafka、show+save+flask，队列默认 `maxsize=8`（可用 `FRAME_QUEUE_MAXSIZE` 显式调整）并带进程健康检查。

```text
VideoReader → DetectionNode → ImageMotionEstimationNode → GroundTrajectoryTrackerNode
  → HomographyCalibrationNode → MotionCompensationNode → FlightGeoReferenceNode
  → PostTrackingWorldProjectionNode → TrackerInfoUpdateNode
  → SpeedEstimationNode → DirectionFlowNode → LaneDetectionNode
  → LaneAnalysisNode → TrajectoryNode → RoadMapMatchingNode → AutoLaneInferenceNode → ConflictDetectionNode
  → CalcStatisticsNode → KafkaProducerNode → ShowNode → VideoSaverNode/FlaskServerVideoNode
```

`FrameElement` 是逐节点富化的数据载体，`TrackElement` 保存单车状态，`VideoEndBreakElement` 是 EOF sentinel；所有节点都必须透传 EOF。

巡航跟踪只执行自动化工程验收，不建设人工轨迹标注、AI 预标注或标注复核工作包。无外部批准
真值时，IDF1/HOTA、正式 ID switch、位置 RMSE 和速度 MAE 必须记录为 `not_evaluated`，不能用
观测 ID、寿命、IoU 或尾迹观感替代。该边界不改变悬停关键帧上的车道/地图人工复核。

关键实现：

| 模块 | 文件 | 责任 |
|---|---|---|
| 视频读取 | `nodes/VideoReader.py` | MP4/RTSP、SRT/MQTT/JSON 遥测与可选 Runtime Road Map Bundle 注入 |
| 检测 | `nodes/DetectionNode.py` | `hover_cruise_v1` 的 YOLO11-only 检测；输出 `detected_*` |
| 图像跟踪 | `nodes/ImageMotionEstimationNode.py`、`nodes/GroundTrajectoryTrackerNode.py` | 背景视觉运动估计及纯图像 ByteTrack；禁止读取 H/ENU/地图质量 |
| 地理参考/世界投影 | `nodes/FlightGeoReferenceNode.py`、`nodes/PostTrackingWorldProjectionNode.py` | 为成熟图像关联分配稳定 track_id，并生成可空的逐帧 ENU/GCJ-02；不得因地理或路网质量拆分轨迹 |
| 旧回滚 | `nodes/DetectionTrackingNodes.py` | 仅 `hover_only_legacy` 使用的 YOLO11 + ByteTrack 组合路径 |
| 世界坐标 | `nodes/HomographyCalibrationNode.py`、`nodes/MotionCompensationNode.py` | pixel→ENU 矩阵、GCJ-02 展示坐标和无人机运动补偿 |
| 轨迹/速度/方向 | `TrackerInfoUpdateNode.py`、`SpeedEstimationNode.py`、`DirectionFlowNode.py`、`TrajectoryNode.py` | 车辆状态、世界轨迹和转向分类 |
| 车道 | `RoadMapMatchingNode.py`、`LaneDetectionNode.py`、`LaneAnalysisNode.py`、`AutoLaneInferenceNode.py` | `lane_verified` 地图正式匹配；模型/自动结果仅作候选 |
| 冲突 | `nodes/ConflictDetectionNode.py` | 未来路径交点 TTC/PET、证据和风险分 |
| Kafka | `nodes/KafkaProducerNode.py` | canonical 多 Topic 消息信封 |

本地无 Kafka 运行：

```bash
python main_optimized.py pipeline.send_info_kafka=False
```

关键环境变量为 `VIDEO_SRC`、可选 `RUNTIME_MAP_BUNDLE_JSON`、`TOPIC_NAME`、`CAMERA_ID`、`KAFKA_BOOTSTRAP`。图像轨迹与世界坐标均不依赖地图；世界坐标由当前帧视频尺寸、相机参数及同步遥测计算。Runtime Road Map Bundle 只填充 Lane/Link 及其匹配质量，通用车辆计数、速度、方向和 TCC 不受路网影响。`TOPIC_NAME` 示例必须使用 `uav_statistics_1`。

## canonical 消息契约

Platform 只订阅：

| Topic | `msg_type` | WebSocket channel |
|---|---|---|
| `uav_statistics_*` | `uav_stats` | `uav_intersection:{id}` |
| `uav_track_complete_*` | `uav_track_complete` | `uav_intersection:{id}` |
| `uav_conflicts_*` | `uav_conflict` | `uav_intersection:{id}`、`uav_alerts*` |
| `uav_telemetry_*` | `uav_telemetry` | `uav_telemetry:{drone_id}` |
| `uav_system_metrics` | `uav_system_metrics` | `uav_system` |

车道标注使用 `uav_calibration`。Runtime 不接受无前缀 Topic、旧 `msg_type` 或旧 WebSocket channel；不要添加适配器、fallback 或双订阅。

## Platform 与 Console2

`platform/app/` 是 FastAPI 单体。数据库初始化只执行 Alembic 并在空库创建本机管理员，不复制任何旧用户、告警、业务或时序数据。Kafka 记录由 `PostgresMetricStoreAdapter` 在事务内写 inbox 与 TimescaleDB/普通表；认证使用 PyJWT+bcrypt。

```bash
cd platform
pip install -e .
python scripts/run_local.py
```

Console2 位于 `console2/`，Docker 入口 `http://localhost:8009`，账号 `admin / admin123`。Nginx 必须通过 Compose service DNS `platform:8000` 访问 Platform。

## 遥测源

| Source | File | Usage |
|---|---|---|
| MQTT | `services/TelemetrySubscriber.py` | 实时 DJI Cloud API |
| JSON/TXT | `services/TelemetryFileReader.py` | 离线回放 |
| SRT | `services/SrtTelemetryParser.py` | 帧级离线回放 |

三者实现统一 `get_nearest(timestamp) -> dict` 接口。

## 旧存储保留

旧卷和 `services/influxdb_data` 只允许按 `scripts/purge_adr019_legacy_storage.py` 生成的 manifest 保留 7 天，期间不得挂载、导入或校验内容。清理脚本必须保持固定 allowlist、到期拒删和双重显式确认；不得绕过脚本人工扩大删除范围。

## 内网私有发布（2026-10-16）

内网版本复用根Compose加`deploy/intranet/compose.yaml`生成仅含`init-db`、`platform`、`console2`的发布Compose，去掉独立Nginx服务。私有包根`.env`保存用户授权填入的生产连接，600权限；禁止进入Git、镜像或源码包。首次`./docker-compose up -d`负责离线镜像/模型导入和预检，再由一次性init-db迁移后启动两服务。瀚高应用为xinchan.ycx_drone，YCX同库road11只读；macOS原生MPS和开发.env不变。详见`docs/DEPLOYMENT_INTRANET.md`。

## 2026-10-16 生产CPU最终更正为aarch64

用户以生产机Architecture=aarch64更正此前amd64结论；内网构建、ELF检查、镜像/主机启动检查和回滚检查统一为ARM64。计划版本2026.10.16-intranet.3，旧amd64归档保留历史但不能直接部署。CANN9.0.0/310P ARM64官方digest已重新核实；参考项目19个国密动态库仍是x86_64，禁止混装，补齐aarch64国密libpq及依赖并完成实际加载前，不发布完整ARM64包。16个源/7台无人机及29个视频遥测保留，模型兼容单独核验；macOS原生MPS和本地.env不变。

ARM64驱动补充：用户提供`deploy/highgo-reference/libpq.so.5`，已核实ELF183/aarch64及SM3符号；OpenSSL1.1兼容依赖取自Ubuntu官方ARM64包并核对SHA，原始来源/逐库SHA记于`deploy/highgo-reference/ARM64_SOURCE.json`。正式ARM64版本改为2026.10.16-intranet.4；intranet.3保留源码准备快照，不作为完整包。

## 2026-10-17 用户授权的生产降级与路网暂关闭（ADR-037）

生产.env设ROAD_FEATURES_ENABLED=false、DB_TIMESCALE_REQUIRED=false、YCX_METRICS_BACKEND=doris。
暂停标注/导入API、自动标注任务、路网包匹配及车道推断，隐藏平台治理一级/标定入口；系统设置图标保留。
PostGIS/版本表及Doris为可选依赖；两张外部指标表在Doris，不属于瀚高。未启用Timescale可使用相同普通PG表，
没有压缩/自动保留；DBA启用后由显式init-db做幂等超表转换，不改版本表、不删数据。
本机road9/MPS和前端开发默认true/原PostgreSQL态势读取不变。本例外不放宽DB/Kafka认证或昇腾模型门禁。

## 2026-10-17 路网与路况统一 Doris（ADR-038）

用户确认路网、路口/路段路况均从 Doris `ycx_xc` 只读取得，确认指标表为
`dws_tfc_inter_index_m_5mi`、`dws_tfc_link_index_m_5mi`；瀚高仅承载 UAV 应用数据，
不再读取其 road11/xianchang。运行时无 PostgreSQL/瀚高外部读库 fallback。
本机连接存于 Git 忽略的 `platform/.env`（600），本地 road9.public/MPS 写链路不变。
路网版本字段是 `dim_data_version.is_enabled`；WKT 使用已有 Shapely 解码，附近路口使用 Doris 球面距离。
路口以各方向月均延误指数的最大值分级，不得伪装成饱和度；两表共同最新月份写入 source.stat_month。
ADR-037 的生产路网关闭开关仍保留，不因本机接入自动恢复生产标注/匹配/车道推断。
详见 `docs/DORIS_INTEGRATION_VALIDATION_20261017.md`。

## 2026.10.17-intranet.1 完整离线发布

本机复验后已生成新的Linux ARM64完整包（非补丁），默认生产Doris为37.12.11.127:9030/ycx_xc，
本机仍用8.149.139.113:9030；内网既有账号与公网账号分开，密码只在私有包根.env（600）。
完整累计此前瀚高/schema/可选依赖/路网暂停/统一Doris修复；启动仍是./docker-compose up -d。
复用原独立模型和视频包，保留旧归档与现场数据路径；生产ROAD_FEATURES_ENABLED=false、DB_TIMESCALE_REQUIRED=false。
本机及镜像/包校验不代表现场SM3/Kafka ACL/内网网络/NPU数值或性能验收；交付证据见dist/DELIVERY-2026.10.17-intranet.1.json。

## 2026-10-17 生产瀚高新目标（intranet.2）

用户最新确认生产瀚高账号sysdba、database=ycx_prod、schema=drone；连接地址37.12.14.133:5866不变。
密码仅存Git忽略的600权限生产.env。本机road9/MPS与公网Doris不改，生产Doris/Kafka/MineMap配置保留。
本次提供完整2026.10.17-intranet.2离线包及检查工具，不要求用户操作intranet.1或打旧补丁。
预检/初始化/权限/版本表查询必须遵循Settings中的DB_NAME/DB_SCHEMA核对实际目标，禁止再写死xinchan.ycx_drone。
生产不得指向本机road9或公共/系统schema；不创建生产库、不复制旧数据，DBA预建ycx_prod.drone。

## 2026-10-17 用户授权临时同机PostgreSQL（ADR-039）

生产HG扩展问题待解，intranet.3临时加入同机ARM64 PostgreSQL17.10/PostGIS3.6.4/TimescaleDB2.28.2。
复用根Compose+intranet覆盖+compose.postgres.yaml；主.env指向road9:5432/ycx_prod.drone，DB_TIMESCALE_REQUIRED=true，路网开关仍false。
DATA_ROOT/postgres独立持久化，无宿主数据库端口；空目录自动初始化扩展/schema，之后init-db迁移再启动应用。
原HG私有连接保留.env.hg及三服务compose，禁止将配置切换当作数据迁移；切回须停写/备份/目标兼容性和数据对账。
不导入HG旧数据，不改本机road9/MPS，不放宽内网认证/NPU门禁。单机数据库不等于生产HA或恢复目标验收。

## 2026-10-18 日志与宿主源码发布（ADR-041）

生产运行日志统一使用Python标准logging，包含时间/级别/PID/Pipeline/logger及异常栈；检测器输出由Platform单点采集并轮转，保持docker logs可见，宿主日志根为DATA_ROOT/logs。初始化与慢阶段必须有完成前的BEGIN/WAIT证据，禁止只用print或进度条承担运行诊断。
内网兼容升级使用app-package源码包及app-compose入口，完整应用源码与Console构建资源按版本只读挂宿主，生成配置另放可写目录。保留原私有env、模型、视频、数据库和数据路径；迁移/依赖基线变化必须拒绝源码升级，另行发布。macOS原生MPS默认不变。
